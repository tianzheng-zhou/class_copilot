"""FastAPI 应用工厂"""

import asyncio

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
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
    app.include_router(api_router)

    @app.on_event("startup")
    async def startup():
        logger.info("应用启动中...")
        await init_db()
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


async def _load_saved_settings():
    """从数据库加载已保存的设置（如 API Key）"""
    from sqlalchemy import select
    from class_copilot.models.models import SettingItem
    from class_copilot.services.encryption_service import decrypt_value

    try:
        async with async_session() as db:
            result = await db.execute(select(SettingItem))
            items = result.scalars().all()
            for item in items:
                if hasattr(settings, item.key):
                    value = decrypt_value(item.value) if item.is_encrypted else item.value
                    setattr(settings, item.key, value)
                    label = "***" if item.is_encrypted else value
                    logger.info("已加载设置: {} = {}", item.key, label)
    except Exception as e:
        logger.warning("加载设置失败: {}", e)
