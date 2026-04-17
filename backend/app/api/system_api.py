"""
QuantWeave - 系统配置 API
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from loguru import logger

from ..core.database import get_db
from ..models.models import (
    Strategy, Trade, BacktestResult, Watchlist,
    DailySignal, RiskAlert, Stock, Account,
)
from ..services.strategy.strategy_service import STRATEGY_REGISTRY

router = APIRouter(prefix="/system", tags=["系统"])


@router.get("/info", summary="系统信息")
def system_info():
    return {
        "name": "QuantWeave",
        "version": "1.0.0",
        "description": "个人量化交易平台",
        "features": [
            "多数据源行情（Tushare + AKShare）",
            f"{len(STRATEGY_REGISTRY)}种内置策略",
            "完整回测引擎",
            "风控告警系统",
            "多渠道通知（钉钉/企微/邮件）",
            "定时任务调度",
        ],
        "strategies": list(STRATEGY_REGISTRY.keys()),
    }


@router.get("/health", summary="健康检查")
def health_check():
    return {"status": "ok", "message": "QuantWeave 服务运行中"}


@router.get("/dashboard", summary="仪表盘聚合数据")
def get_dashboard(db: Session = Depends(get_db)):
    """
    聚合仪表盘所需的全部数据：
    资产概览、策略统计、回测成绩、关注列表、风控告警
    """

    # 1. 账户资产 — 尝试从 NAS MySQL 读取，失败则用本地默认值
    total_assets = 1000000.0
    cash_balance = 1000000.0
    market_value = 0.0
    profit = 0.0
    profit_pct = 0.0

    try:
        account = db.query(Account).filter(Account.name == "main").first()
        if account and account.total_assets > 0:
            total_assets = account.total_assets
            cash_balance = account.cash_balance
            market_value = account.market_value
            profit = account.profit
            profit_pct = account.profit_pct
    except Exception as e:
        logger.debug(f"Dashboard: NAS账户读取失败，使用默认值: {e}")
        pass

    # 2. 策略统计
    active_strategies = db.query(Strategy).filter(
        Strategy.status == "running"
    ).count()
    total_strategies = db.query(Strategy).count()
    # 内置策略也算
    if total_strategies == 0:
        active_strategies = len(STRATEGY_REGISTRY)
        total_strategies = len(STRATEGY_REGISTRY)

    # 3. 回测统计 — 取最近一次回测结果
    latest_backtest = db.query(BacktestResult).order_by(
        BacktestResult.created_at.desc()
    ).first()
    total_return = latest_backtest.total_return if latest_backtest else 0.0
    win_rate = latest_backtest.win_rate if latest_backtest else 0.0
    sharpe_ratio = latest_backtest.sharpe_ratio if latest_backtest else 0.0
    max_drawdown = latest_backtest.max_drawdown if latest_backtest else 0.0

    # 4. 交易统计
    trade_count = db.query(Trade).filter(Trade.is_backtest == False).count()
    backtest_trade_count = db.query(Trade).filter(Trade.is_backtest == True).count()

    # 今日收益 — 最近一笔交易的盈亏
    latest_trade = db.query(Trade).order_by(Trade.created_at.desc()).first()
    today_pnl = latest_trade.profit if latest_trade and latest_trade.profit else 0.0

    # 5. 关注列表
    watchlist_count = db.query(Watchlist).filter(Watchlist.is_active == True).count()

    # 6. 风控告警
    unresolved_alerts = db.query(RiskAlert).filter(
        RiskAlert.is_resolved == False
    ).count()
    critical_alerts = db.query(RiskAlert).filter(
        RiskAlert.is_resolved == False,
        RiskAlert.level == "critical",
    ).count()

    # 7. 股票数据量
    stock_count = db.query(Stock).filter(Stock.is_active == True).count()

    # 8. 最近5条信号
    recent_signals = db.query(DailySignal).order_by(
        DailySignal.created_at.desc()
    ).limit(5).all()
    signals_data = []
    for s in recent_signals:
        signals_data.append({
            "date": s.signal_date,
            "ts_code": s.ts_code,
            "action": s.action,
            "price": s.price,
            "strategies": s.strategies,
            "score": s.score,
        })

    # 9. 回测历史概要（用于净值曲线）
    backtest_history = db.query(BacktestResult).order_by(
        BacktestResult.created_at.desc()
    ).limit(10).all()
    equity_curve = []
    strategy_returns = []
    if latest_backtest and latest_backtest.equity_curve:
        equity_curve = latest_backtest.equity_curve
    if latest_backtest and latest_backtest.daily_returns:
        # daily_returns 可能是纯数字列表或 dict 列表
        raw_returns = latest_backtest.daily_returns[:30] if isinstance(latest_backtest.daily_returns, list) else []
        strategy_returns = []
        for i, r in enumerate(raw_returns):
            if isinstance(r, dict):
                strategy_returns.append({"date": r.get("date", ""), "return": r.get("return", 0)})
            else:
                strategy_returns.append({"date": f"day_{i+1}", "return": float(r) if r else 0})

    return {
        # 资产概览
        "total_assets": total_assets,
        "cash_balance": cash_balance,
        "market_value": market_value,
        "profit": profit,
        "profit_pct": profit_pct,
        "total_return": total_return,
        "today_pnl": today_pnl,

        # 策略
        "active_strategies": active_strategies,
        "total_strategies": total_strategies,
        "win_rate": win_rate,
        "sharpe_ratio": sharpe_ratio,
        "max_drawdown": max_drawdown,

        # 数据
        "trade_count": trade_count,
        "backtest_trade_count": backtest_trade_count,
        "watchlist_count": watchlist_count,
        "stock_count": stock_count,

        # 风控
        "unresolved_alerts": unresolved_alerts,
        "critical_alerts": critical_alerts,

        # 图表数据
        "equity_curve": equity_curve,
        "strategy_returns": strategy_returns,

        # 最近信号
        "recent_signals": signals_data,

        # 回测历史
        "backtest_history": [
            {
                "id": b.id,
                "strategy_id": b.strategy_id,
                "total_return": b.total_return,
                "sharpe_ratio": b.sharpe_ratio,
                "max_drawdown": b.max_drawdown,
                "win_rate": b.win_rate,
                "created_at": b.created_at.isoformat() if b.created_at else None,
            }
            for b in backtest_history
        ],

        # 系统状态
        "system_status": "online",
    }
