"""
家庭NAS数据库配置
包含MySQL和Redis连接配置
"""

import os
from pathlib import Path
from typing import Dict, Any
from dotenv import load_dotenv
import redis
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool

# 确保 .env 被加载（Pydantic Settings 只在自己的类中加载，os.getenv 读不到）
_env_file = Path(__file__).resolve().parent.parent.parent / ".env"
if _env_file.exists():
    load_dotenv(_env_file, override=False)

# NAS服务器配置 — 从环境变量读取（不再硬编码）
NAS_MYSQL_HOST = os.getenv("NAS_MYSQL_HOST", "192.168.0.222")
NAS_MYSQL_PORT = int(os.getenv("NAS_MYSQL_PORT", "3306"))
NAS_MYSQL_USER = os.getenv("NAS_MYSQL_USER", "root")
NAS_MYSQL_PASSWORD = os.getenv("NAS_MYSQL_PASSWORD", "")
NAS_MYSQL_DATABASE = os.getenv("NAS_MYSQL_DATABASE", "quantweave")

# NAS Redis配置 — 从环境变量读取（不再硬编码）
NAS_REDIS_HOST = os.getenv("NAS_REDIS_HOST", "192.168.0.222")
NAS_REDIS_PORT = int(os.getenv("NAS_REDIS_PORT", "6379"))
NAS_REDIS_DB = int(os.getenv("NAS_REDIS_DB", "0"))

# MySQL连接URL
NAS_DATABASE_URL = f"mysql+pymysql://{NAS_MYSQL_USER}:{NAS_MYSQL_PASSWORD}@{NAS_MYSQL_HOST}:{NAS_MYSQL_PORT}/{NAS_MYSQL_DATABASE}"

# 创建NAS MySQL引擎
nas_engine = create_engine(
    NAS_DATABASE_URL,
    poolclass=QueuePool,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    echo=False,
    connect_args={
        "charset": "utf8mb4",
        "connect_timeout": 10
    }
)

# NAS数据库会话
NASSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=nas_engine)

def get_nas_db():
    """获取NAS数据库会话"""
    db = NASSessionLocal()
    try:
        yield db
    finally:
        db.close()

# Redis连接池
nas_redis_pool = None

def get_nas_redis():
    """获取NAS Redis连接"""
    global nas_redis_pool
    if nas_redis_pool is None:
        nas_redis_pool = redis.ConnectionPool(
            host=NAS_REDIS_HOST,
            port=NAS_REDIS_PORT,
            db=NAS_REDIS_DB,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5
        )
    return redis.Redis(connection_pool=nas_redis_pool)

def init_nas_database():
    """初始化NAS数据库表"""
    from ..models.models import Base
    Base.metadata.create_all(bind=nas_engine)
    print(f"NAS数据库表已创建（MySQL: {NAS_MYSQL_HOST}:{NAS_MYSQL_PORT}）")

def check_nas_connection() -> Dict[str, Any]:
    """检查NAS服务连接状态"""
    import mysql.connector
    from mysql.connector import Error as MySQLError
    
    status = {
        "mysql": {"host": NAS_MYSQL_HOST, "port": NAS_MYSQL_PORT, "connected": False, "error": None},
        "redis": {"host": NAS_REDIS_HOST, "port": NAS_REDIS_PORT, "connected": False, "error": None}
    }
    
    # 检查MySQL连接
    try:
        conn = mysql.connector.connect(
            host=NAS_MYSQL_HOST,
            port=NAS_MYSQL_PORT,
            user=NAS_MYSQL_USER,
            password=NAS_MYSQL_PASSWORD,
            database=NAS_MYSQL_DATABASE,
            connection_timeout=5
        )
        if conn.is_connected():
            status["mysql"]["connected"] = True
            cursor = conn.cursor()
            cursor.execute("SELECT VERSION()")
            version = cursor.fetchone()[0]
            status["mysql"]["version"] = version
            cursor.close()
            conn.close()
        else:
            status["mysql"]["error"] = "连接失败"
    except MySQLError as e:
        status["mysql"]["error"] = str(e)
    except Exception as e:
        status["mysql"]["error"] = f"未知错误: {str(e)}"
    
    # 检查Redis连接
    try:
        r = get_nas_redis()
        if r.ping():
            status["redis"]["connected"] = True
            info = r.info()
            status["redis"]["version"] = info.get("redis_version", "unknown")
        else:
            status["redis"]["error"] = "PING失败"
    except Exception as e:
        status["redis"]["error"] = str(e)
    
    return status