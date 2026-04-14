"""
QuantWeave - 日志配置（持久化 + 轮转）
"""
import os
from loguru import logger
from .config import get_settings


def setup_logging():
    """配置日志持久化和轮转"""
    settings = get_settings()
    log_dir = settings.LOG_DIR
    os.makedirs(log_dir, exist_ok=True)

    # 移除默认 handler
    logger.remove()

    # 控制台输出
    logger.add(
        sink=lambda msg: print(msg, end=""),
        level=settings.LOG_LEVEL,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level:<7} | {name}:{line} - {message}",
    )

    # 文件输出（轮转 + 保留期）
    logger.add(
        os.path.join(log_dir, "quantweave_{time:YYYY-MM-DD}.log"),
        level=settings.LOG_LEVEL,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level:<7} | {name}:{line} - {message}",
        rotation=settings.LOG_ROTATION,
        retention=settings.LOG_RETENTION,
        encoding="utf-8",
    )

    # 错误日志单独文件
    logger.add(
        os.path.join(log_dir, "error_{time:YYYY-MM-DD}.log"),
        level="ERROR",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level:<7} | {name}:{line} - {message}",
        rotation=settings.LOG_ROTATION,
        retention=settings.LOG_RETENTION,
        encoding="utf-8",
    )

    logger.info("日志系统初始化完成")
    return logger
