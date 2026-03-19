"""日志配置 - 使用 loguru"""

import sys
from pathlib import Path

from loguru import logger


def setup_logging():
    """配置完整的日志记录系统"""
    from class_copilot.config import settings

    log_dir = Path(settings.data_dir) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    # 移除默认处理器
    logger.remove()

    # 控制台输出 - INFO 级别
    logger.add(
        sys.stderr,
        level="INFO",
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
            "<level>{message}</level>"
        ),
        colorize=True,
        enqueue=True,  # 异步写入，线程安全
    )

    # 主日志文件 - DEBUG 级别，按天轮转
    logger.add(
        str(log_dir / "app_{time:YYYY-MM-DD}.log"),
        level="DEBUG",
        format=(
            "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | "
            "{name}:{function}:{line} | {message}"
        ),
        rotation="00:00",  # 每天午夜轮转
        retention="30 days",  # 保留30天
        compression="zip",  # 压缩旧日志
        encoding="utf-8",
        enqueue=True,
    )

    # 错误日志 - ERROR 级别，单独文件
    logger.add(
        str(log_dir / "error_{time:YYYY-MM-DD}.log"),
        level="ERROR",
        format=(
            "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | "
            "{name}:{function}:{line} | {message}\n{exception}"
        ),
        rotation="00:00",
        retention="90 days",
        compression="zip",
        encoding="utf-8",
        enqueue=True,
        backtrace=True,
        diagnose=True,
    )

    # ASR 专用日志 - 记录转写详情
    logger.add(
        str(log_dir / "asr_{time:YYYY-MM-DD}.log"),
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {message}",
        rotation="00:00",
        retention="14 days",
        compression="zip",
        encoding="utf-8",
        enqueue=True,
        filter=lambda record: record["extra"].get("module") == "asr",
    )

    # LLM 专用日志 - 记录问题检测和答案生成
    logger.add(
        str(log_dir / "llm_{time:YYYY-MM-DD}.log"),
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {message}",
        rotation="00:00",
        retention="14 days",
        compression="zip",
        encoding="utf-8",
        enqueue=True,
        filter=lambda record: record["extra"].get("module") == "llm",
    )

    # WebSocket 专用日志
    logger.add(
        str(log_dir / "websocket_{time:YYYY-MM-DD}.log"),
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {message}",
        rotation="00:00",
        retention="7 days",
        compression="zip",
        encoding="utf-8",
        enqueue=True,
        filter=lambda record: record["extra"].get("module") == "websocket",
    )

    # 精修 ASR 任务日志
    logger.add(
        str(log_dir / "refinement_{time:YYYY-MM-DD}.log"),
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {message}",
        rotation="00:00",
        retention="14 days",
        compression="zip",
        encoding="utf-8",
        enqueue=True,
        filter=lambda record: record["extra"].get("module") == "refinement",
    )

    logger.info("日志系统初始化完成，日志目录: {}", log_dir)


# 预定义模块级 logger
asr_logger = logger.bind(module="asr")
llm_logger = logger.bind(module="llm")
ws_logger = logger.bind(module="websocket")
refinement_logger = logger.bind(module="refinement")
