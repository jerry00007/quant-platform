"""
QuantWeave - 数据库连接管理

SQLite 并发保护策略：
  - WAL 模式：读写不互相阻塞，适合多 Automation 并发场景
  - busy_timeout：写锁等待5秒，避免 "database is locked" 错误
  - check_same_thread=False：允许跨线程使用连接
"""
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base
from .config import get_settings

settings = get_settings()

engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False},  # SQLite 需要
    echo=settings.DEBUG,
    pool_pre_ping=True,
)


# ── SQLite 并发保护 ──
@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    """设置 SQLite WAL 模式和 busy_timeout"""
    cursor = dbapi_connection.cursor()
    # WAL 模式：读写不互斥，大幅提升并发性能
    cursor.execute("PRAGMA journal_mode=WAL")
    # busy_timeout：写锁等待5秒（5000ms），避免 "database is locked"
    cursor.execute("PRAGMA busy_timeout=5000")
    # 同步模式：NORMAL（WAL模式下安全且快速）
    cursor.execute("PRAGMA synchronous=NORMAL")
    # 缓存大小：20MB（默认2MB太小）
    cursor.execute("PRAGMA cache_size=-20000")
    cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """数据库会话依赖"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """初始化数据库表"""
    Base.metadata.create_all(bind=engine)
