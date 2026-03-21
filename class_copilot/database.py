"""数据库引擎和会话管理"""

from pathlib import Path

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase

from class_copilot.config import settings


class Base(DeclarativeBase):
    pass


db_path = Path(settings.data_dir) / "class_copilot.db"
engine = create_async_engine(
    f"sqlite+aiosqlite:///{db_path}",
    echo=False,
    connect_args={"check_same_thread": False, "timeout": 30},
    pool_size=1,
    max_overflow=0,
    pool_timeout=30,
)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db():
    """初始化数据库，创建所有表"""
    async with engine.begin() as conn:
        # 启用 WAL 模式
        await conn.exec_driver_sql("PRAGMA journal_mode=WAL")
        await conn.exec_driver_sql("PRAGMA foreign_keys=ON")

        from class_copilot.models import models  # noqa: F401

        await conn.run_sync(Base.metadata.create_all)


async def get_db() -> AsyncSession:
    """获取数据库会话"""
    async with async_session() as session:
        yield session
