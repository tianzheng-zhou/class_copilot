"""FastAPI 应用工厂"""

import asyncio

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from loguru import logger

from class_copilot.database import init_db
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
