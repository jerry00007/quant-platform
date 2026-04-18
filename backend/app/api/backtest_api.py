"""
QuantWeave - 回测 API
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..core.database import get_db
from ..core.config import get_settings
from ..models.models import BacktestResult
from ..schemas import BacktestRequest
from ..services.backtest.backtest_service import BacktestEngine
from ..services.backtest.market_backtest import MarketBacktestEngine
from ..services.backtest.quick_picks_backtest import QuickPicksBacktestEngine
from ..services.data.data_service import DataService

router = APIRouter(prefix="/backtest", tags=["回测管理"])
settings = get_settings()


@router.post("/run", summary="执行回测")
def run_backtest(data: BacktestRequest, db: Session = Depends(get_db)):
    """
    执行策略回测
    
    单股票模式:
    {
        "mode": "single",
        "strategy": "dual_ma",
        "ts_code": "000001.SZ",
        "start_date": "20240101",
        "end_date": "20260401",
        "initial_cash": 1000000
    }
    
    全市场模式:
    {
        "mode": "market",
        "strategies": ["dual_ma", "macd"],
        "start_date": "20240101",
        "end_date": "20260401",
        "initial_cash": 1000000,
        "max_positions": 10,
        "position_per_stock": 0.2,
        "stop_loss_pct": -0.08,
        "take_profit_pct": 0.15
    }
    """
    data_service = DataService(db, tushare_token=settings.TUSHARE_TOKEN)

    # 类型转换：前端传 stop_loss/take_profit 为字符串，需转为 float
    stop_loss_val = None
    if data.stop_loss:
        try:
            stop_loss_val = float(data.stop_loss)
        except (ValueError, TypeError):
            pass
    take_profit_val = None
    if data.take_profit:
        try:
            take_profit_val = float(data.take_profit)
        except (ValueError, TypeError):
            pass

    if data.mode == "market":
        engine = MarketBacktestEngine(
            data_service=data_service,
            initial_cash=data.initial_cash,
            commission=data.commission,
            slippage=data.slippage,
            max_positions=data.max_positions,
            position_per_stock=data.position_per_stock,
            rebalance_interval=data.rebalance_interval,
            stop_loss_pct=data.stop_loss_pct,
            take_profit_pct=data.take_profit_pct,
        )
        strategies = data.strategies or ["dual_ma"]
        result = engine.run(
            strategy_types=strategies,
            start_date=data.start_date,
            end_date=data.end_date,
            stock_limit=data.stock_limit,
        )
    elif data.mode == "quick_picks":
        engine = QuickPicksBacktestEngine(
            initial_cash=data.initial_cash,
            max_positions=data.max_positions,
            top_n=data.stock_limit if data.stock_limit and data.stock_limit <= 20 else 5,
            commission=data.commission,
            slippage=data.slippage,
            scan_interval=data.rebalance_interval,
            stop_loss=data.stop_loss_pct if data.stop_loss_pct else None,
            max_hold_days=getattr(data, 'max_hold_days', None),
        )
        result = engine.run(
            start_date=data.start_date,
            end_date=data.end_date,
        )
    else:
        engine = BacktestEngine(
            data_service=data_service,
            initial_cash=data.initial_cash,
            commission=data.commission,
            slippage=data.slippage,
            position_ratio=data.position_ratio,
            stop_loss_pct=stop_loss_val,
            take_profit_pct=take_profit_val,
        )
        strategy_type = data.strategy_type or data.strategy
        result = engine.run(
            strategy_type=strategy_type,
            ts_code=data.ts_code,
            start_date=data.start_date,
            end_date=data.end_date,
            strategy_params=data.strategy_params,
        )

    if "error" not in result:
        bt = BacktestResult(
            strategy_id=data.strategy_id,
            start_date=data.start_date,
            end_date=data.end_date,
            initial_cash=result.get("initial_cash", data.initial_cash),
            final_value=result.get("final_value", 0),
            total_return=result.get("total_return", 0),
            annual_return=result.get("annual_return", 0),
            max_drawdown=result.get("max_drawdown", 0),
            sharpe_ratio=result.get("sharpe_ratio", 0),
            win_rate=result.get("win_rate", 0),
            profit_loss_ratio=result.get("profit_loss_ratio", 0),
            total_trades=result.get("total_trades", 0),
            daily_returns=[d["return"] for d in result.get("daily_returns", [])],
            equity_curve=[e["value"] for e in result.get("equity_curve", [])],
        )
        db.add(bt)
        db.commit()

    result["mode"] = data.mode
    return result


@router.get("/results", summary="获取回测历史")
def get_backtest_results(
    strategy_id: int = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
):
    query = db.query(BacktestResult)
    if strategy_id:
        query = query.filter(BacktestResult.strategy_id == strategy_id)
    total = query.count()
    items = query.order_by(BacktestResult.created_at.desc()).offset((page - 1) * size).limit(size).all()
    return {
        "total": total,
        "page": page,
        "size": size,
        "items": [
            {
                "id": r.id,
                "strategy_id": r.strategy_id,
                "start_date": r.start_date,
                "end_date": r.end_date,
                "initial_cash": r.initial_cash,
                "final_value": r.final_value,
                "total_return": r.total_return,
                "annual_return": r.annual_return,
                "max_drawdown": r.max_drawdown,
                "sharpe_ratio": r.sharpe_ratio,
                "win_rate": r.win_rate,
                "profit_loss_ratio": r.profit_loss_ratio,
                "total_trades": r.total_trades,
                "created_at": str(r.created_at),
            }
            for r in items
        ],
    }