"""
QuantWeave 量化交易平台 - 主程序入口
"""
from pathlib import Path
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager
from loguru import logger
from sqlalchemy.orm import Session

from .core.config import get_settings
from .core.database import init_db, SessionLocal
from .api import all_routers
from .services.scheduler.scheduler_service import SchedulerService
from .services.notify.notify_service import NotifyService
from .services.data.data_service import DataService
from .services.signal.signal_service import SignalService
from .services.strategy.strategy_service import STRATEGY_REGISTRY

# 前端静态文件目录
FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"

settings = get_settings()

# 全局调度器实例
scheduler = None


def get_db():
    """数据库会话依赖"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def morning_brief_task():
    """9:30早盘提醒任务"""
    logger.info("🕘 开始执行早盘提醒任务...")
    try:
        db = SessionLocal()
        try:
            data_service = DataService(db)
            signal_service = SignalService(db, data_service)
            # 生成早盘提醒文本
            brief_text = signal_service.generate_morning_brief()
            logger.info(f"早盘提醒生成完成，内容长度: {len(brief_text)}")
            
            # 发送通知
            notify_service = NotifyService(
                serverchan_key=settings.SERVERCHAN_KEY,
                wechat_webhook=settings.WECHAT_WEBHOOK,
                dingtalk_webhook=settings.DINGTALK_WEBHOOK,
                email_smtp=settings.EMAIL_SMTP,
                email_sender=settings.EMAIL_SENDER,
                email_password=settings.EMAIL_PASSWORD,
                email_receiver=settings.EMAIL_RECEIVER,
            )
            notify_service.send("QuantWeave 早盘提醒", brief_text, level="info")
            logger.info("✅ 早盘提醒通知发送成功")
        finally:
            db.close()
    except Exception as e:
        logger.error(f"早盘提醒任务执行失败: {e}")


def data_sync_task():
    """数据同步任务"""
    logger.info("📊 数据同步任务执行...")
    try:
        db = SessionLocal()
        try:
            data_service = DataService(db, tushare_token=settings.TUSHARE_TOKEN)
            # 同步股票列表
            stock_count = data_service.sync_stock_list()
            # 同步ETF列表
            etf_count = data_service.sync_etf_list()
            logger.info(f"数据同步完成: 股票{stock_count}只, ETF{etf_count}只")
        finally:
            db.close()
    except Exception as e:
        logger.error(f"数据同步任务执行失败: {e}")


def signal_scan_task():
    """策略信号扫描任务"""
    logger.info("📈 策略信号扫描任务执行...")
    try:
        db = SessionLocal()
        try:
            data_service = DataService(db, tushare_token=settings.TUSHARE_TOKEN)
            signal_service = SignalService(db, data_service)
            # 获取关注列表
            watchlist = data_service.get_watchlist()
            if not watchlist:
                logger.info("关注列表为空，跳过信号扫描")
                return
            # 生成信号
            result = signal_service.generate_daily_signals(
                stock_codes=[w["ts_code"] for w in watchlist],
                strategy_keys=list(STRATEGY_REGISTRY.keys()),  # 使用所有策略
                watchlist_only=True,
            )
            logger.info(f"信号扫描完成: 共{len(result.get('signals', []))}条信号")
        finally:
            db.close()
    except Exception as e:
        logger.error(f"策略信号扫描任务执行失败: {e}")


def risk_check_task():
    """风控巡检任务"""
    logger.info("🛡️ 风控巡检任务执行...")
    # 暂不实现，后续补充
    pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期"""
    logger.info(f"🚀 {settings.APP_NAME} v{settings.APP_VERSION} 启动中...")
    init_db()
    logger.info("✅ 数据库初始化完成")
    
    # 初始化调度器
    global scheduler
    scheduler = SchedulerService()
    scheduler.register_default_jobs(
        data_sync_func=data_sync_task,
        signal_scan_func=signal_scan_task,
        risk_check_func=risk_check_task,
        morning_brief_func=morning_brief_task,
    )
    scheduler.start()
    logger.info("✅ 定时任务调度器启动完成")
    
    yield
    
    # 停止调度器
    if scheduler:
        scheduler.stop()
    logger.info("👋 服务停止")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="个人量化交易平台 API",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
for router in all_routers:
    app.include_router(router, prefix=settings.API_PREFIX)


# 挂载前端静态文件
@app.get("/")
async def serve_index():
    """首页"""
    index_file = FRONTEND_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"message": f"QuantWeave v{settings.APP_VERSION} API 运行中", "docs": "/docs"}


@app.get("/portfolio")
async def serve_portfolio():
    """持仓管理页面"""
    portfolio_file = FRONTEND_DIR / "portfolio.html"
    if portfolio_file.exists():
        return FileResponse(portfolio_file)
    return {"error": "portfolio.html not found"}


# 静态资源（JS/CSS/图片等）—— 挂载在根路径，放在路由之后作为 fallback
# API 路由（/api/v1/*）优先匹配，未匹配的走静态文件
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="static")
