"""
QuantWeave - 回测 API
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..core.database import get_db
from ..core.config import get_settings
from ..models.models import BacktestResult
from ..services.backtest.backtest_service import BacktestEngine
from ..services.backtest.market_backtest import MarketBacktestEngine
from ..services.data.data_service import DataService

router = APIRouter(prefix="/backtest", tags=["回测管理"])
settings = get_settings()


@router.post("/run", summary="执行回测")
def run_backtest(data: dict, db: Session = Depends(get_db)):
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
    mode = data.get("mode", "single")
    data_service = DataService(db, tushare_token=settings.TUSHARE_TOKEN)
    
    if mode == "market":
        engine = MarketBacktestEngine(
            data_service=data_service,
            initial_cash=data.get("initial_cash", 1000000),
            commission=data.get("commission", 0.0003),
            slippage=data.get("slippage", 0.001),
            max_positions=data.get("max_positions", 10),
            position_per_stock=data.get("position_per_stock", 0.2),
            rebalance_interval=data.get("rebalance_interval", 1),
            stop_loss_pct=data.get("stop_loss_pct", -0.08),
            take_profit_pct=data.get("take_profit_pct", 0.15),
        )
        strategies = data.get("strategies", ["dual_ma"])
        result = engine.run(
            strategy_types=strategies,
            start_date=data.get("start_date"),
            end_date=data.get("end_date"),
            stock_limit=data.get("stock_limit", 200),
        )
    else:
        engine = BacktestEngine(
            data_service=data_service,
            initial_cash=data.get("initial_cash", 1000000),
            commission=data.get("commission", 0.0003),
            slippage=data.get("slippage", 0.001),
            position_ratio=data.get("position_ratio", 1.0),
            stop_loss_pct=data.get("stop_loss"),
            take_profit_pct=data.get("take_profit"),
        )
        strategy_type = data.get("strategy_type") or data.get("strategy")
        result = engine.run(
            strategy_type=strategy_type,
            ts_code=data.get("ts_code"),
            start_date=data.get("start_date"),
            end_date=data.get("end_date"),
            strategy_params=data.get("strategy_params"),
        )

    if "error" not in result:
        bt = BacktestResult(
            strategy_id=data.get("strategy_id", 0),
            start_date=data.get("start_date"),
            end_date=data.get("end_date"),
            initial_cash=result.get("initial_cash", data.get("initial_cash", 1000000)),
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

    result["mode"] = mode
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