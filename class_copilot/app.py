"""FastAPI 应用工厂"""

import asyncio

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from loguru import logger

from class_copilot.config import settings
from class_copilot.database import init_db, async_session
from class_copilot.routes.ws_routes import router as ws_router, broadcast_worker
from class_copilot.routes.api_routes import router as api_router
from class_copilot.services.session_manager import session_manager


def create_app() -> FastAPI:
    app = FastAPI(
        title="听课助手",
        version="2.0.0",
        docs_url="/docs",
    )

    # 注册路由
    app.include_router(ws_router)

    # 禁用前端静态文件缓存（开发模式，确保浏览器始终加载最新内容）
    class NoCacheMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            response = await call_next(request)
            if request.url.path.startswith("/assets") or request.url.path == "/":
                response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
                response.headers["Pragma"] = "no-cache"
                response.headers["Expires"] = "0"
            return response

    app.add_middleware(NoCacheMiddleware)
    app.include_router(api_router)

    @app.on_event("startup")
    async def startup():
        logger.info("应用启动中...")
        await init_db()
        await _fix_stale_sessions()
        await _load_saved_settings()
        await session_manager.initialize()

        # 启动 WebSocket 广播工作者
        asyncio.create_task(broadcast_worker())

        logger.info("应用启动完成")

    @app.on_event("shutdown")
    async def shutdown():
        logger.info("应用关闭中...")
        if session_manager.is_listening:
            await session_manager.stop_listening()
        session_manager.hotkey_service.unregister_all()
        logger.info("应用已关闭")

    # 前端静态文件
    import os

    frontend_dir = os.path.join(os.path.dirname(__file__), "frontend")
    if os.path.exists(frontend_dir):
        app.mount("/assets", StaticFiles(directory=os.path.join(frontend_dir, "assets")), name="assets")

        @app.get("/")
        async def serve_index():
            return FileResponse(os.path.join(frontend_dir, "index.html"))

        @app.get("/{path:path}")
        async def serve_spa(path: str):
            """SPA fallback"""
            file_path = os.path.join(frontend_dir, path)
            if os.path.isfile(file_path):
                return FileResponse(file_path)
            return FileResponse(os.path.join(frontend_dir, "index.html"))

    return app


async def _fix_stale_sessions():
    """启动时将所有残留的 active 会话标记为 interrupted"""
    from sqlalchemy import update as sql_update
    from class_copilot.models.models import Session
    from datetime import datetime

    try:
        async with async_session() as db:
            result = await db.execute(
                sql_update(Session)
                .where(Session.status == "active")
                .values(status="interrupted", ended_at=datetime.utcnow())
            )
            await db.commit()
            if result.rowcount:
                logger.info("已修复 {} 个残留的活跃会话", result.rowcount)
    except Exception as e:
        logger.warning("修复残留会话失败: {}", e)


async def _load_saved_settings():
    """从数据库加载已保存的设置（如 API Key）"""
    from sqlalchemy import select
    from class_copilot.models.models import SettingItem
    from class_copilot.services.encryption_service import decrypt_value

    import json

    try:
        async with async_session() as db:
            result = await db.execute(select(SettingItem))
            items = result.scalars().all()
            for item in items:
                key = item.key
                # 兼容旧字段名
                if key == "doubao_api_key":
                    key = "doubao_access_token"
                if hasattr(settings, key):
                    if item.is_encrypted:
                        value = decrypt_value(item.value)
                    else:
                        # 尝试 JSON 解码以还原 bool/int/float 等类型
                        try:
                            value = json.loads(item.value)
                        except (json.JSONDecodeError, ValueError):
                            value = item.value
                    setattr(settings, key, value)
                    label = "***" if item.is_encrypted else value
                    logger.info("已加载设置: {} = {}", key, label)
    except Exception as e:
        logger.warning("加载设置失败: {}", e)
