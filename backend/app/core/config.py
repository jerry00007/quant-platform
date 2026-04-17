"""
QuantWeave 量化交易平台 - 核心配置
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional
from functools import lru_cache


class Settings(BaseSettings):
    """应用配置"""
    
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")
    
    # 应用基础
    APP_NAME: str = "QuantWeave"
    APP_VERSION: str = "2.0.0"
    DEBUG: bool = True
    
    # 数据库
    DATABASE_URL: str = "sqlite:///./quantweave.db"
    
    # Tushare（从 .env 读取，不在源码硬编码）
    TUSHARE_TOKEN: str = ""
    
    # AKShare（无需token）
    
    # 风控参数
    MAX_POSITION_RATIO: float = 0.3  # 单只股票最大仓位比例
    MAX_LOSS_RATIO: float = 0.05     # 单日最大亏损比例
    STOP_LOSS_RATIO: float = 0.08    # 止损线
    TAKE_PROFIT_RATIO: float = 0.15  # 止盈线
    
    # 回测参数
    BACKTEST_INITIAL_CASH: float = 1000000.0  # 初始资金100万
    BACKTEST_COMMISSION: float = 0.0003       # 佣金费率万三
    BACKTEST_SLIPPAGE: float = 0.001          # 滑点千一
    
    # 通知配置
    DINGTALK_WEBHOOK: str = ""
    WECHAT_WEBHOOK: str = ""
    EMAIL_SMTP: str = ""
    EMAIL_SENDER: str = ""
    EMAIL_PASSWORD: str = ""
    EMAIL_RECEIVER: str = ""
    SERVERCHAN_KEY: str = ""  # Server酱 SendKey，用于推送到个人微信
    
    # 定时任务
    SCHEDULER_ENABLED: bool = True
    MARKET_OPEN_HOUR: int = 9
    MARKET_CLOSE_HOUR: int = 15
    
    # 日志配置
    LOG_LEVEL: str = "INFO"
    LOG_DIR: str = "./logs"
    LOG_ROTATION: str = "10 MB"       # 日志轮转大小
    LOG_RETENTION: str = "30 days"    # 日志保留天数

    # API
    API_PREFIX: str = "/api/v1"
    CORS_ORIGINS: list = ["http://localhost:3000", "http://localhost:5173", "http://127.0.0.1:3000", "http://localhost:8000", "null"]

    # NAS MySQL 配置（nas_config.py 通过 os.getenv 直接读取，此处声明避免 Pydantic 报错）
    NAS_MYSQL_HOST: str = "192.168.0.222"
    NAS_MYSQL_PORT: str = "3306"
    NAS_MYSQL_USER: str = "root"
    NAS_MYSQL_PASSWORD: str = ""
    NAS_MYSQL_DATABASE: str = "quantweave"

    # NAS Redis 配置
    NAS_REDIS_HOST: str = "192.168.0.222"
    NAS_REDIS_PORT: str = "6379"
    NAS_REDIS_DB: str = "0"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
