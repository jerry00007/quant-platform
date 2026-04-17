"""
QuantWeave — 实时行情 API

提供市场总览数据：
  - GET /market/indices     实时指数行情（雪球）
  - GET /market/breadth     市场宽度（涨跌分布）
  - GET /market/sectors     板块动量 TOP15
  - GET /market/overview    市场总览（聚合以上全部 + 持仓实时盈亏）
"""
import os
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import Optional
from loguru import logger

from ..core.database import get_db
from ..services.data.xueqiu_data import (
    get_index_quotes, batch_realtime_quotes, INDEX_MAP
)
from ..services.analysis.market_context import (
    evaluate_market_breadth, evaluate_sector_momentum
)

router = APIRouter(prefix="/market", tags=["实时行情"])

# 数据库路径
_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "quantweave.db"
)


@router.get("/indices", summary="实时指数行情")
def get_market_indices():
    """获取主要指数实时行情（雪球数据源，30秒缓存）

    返回上证指数、深证成指、创业板指、沪深300、上证50、中小板指
    """
    try:
        quotes = get_index_quotes()
        items = []
        for code, q in quotes.items():
            items.append({
                "ts_code": code,
                "name": INDEX_MAP.get(code, ""),
                "current": q.get("current"),
                "percent": q.get("percent", 0),
                "chg": q.get("chg", 0),
                "open": q.get("open"),
                "high": q.get("high"),
                "low": q.get("low"),
                "volume": q.get("volume", 0),
                "amount": q.get("amount", 0),
                "turnover_rate": q.get("turnover_rate"),
                "amplitude": q.get("amplitude"),
                "is_trade": q.get("is_trade", False),
            })
        return {"success": True, "data": items}
    except Exception as e:
        logger.warning(f"获取指数行情失败: {e}")
        return {"success": False, "data": [], "message": str(e)}


@router.get("/breadth", summary="市场宽度（涨跌分布）")
def get_market_breadth():
    """获取最新交易日的市场宽度数据

    返回上涨/下跌/平盘家数、涨停/跌停家数、市场情绪判断
    数据来自本地 SQLite 的 stock_daily 表
    """
    try:
        db_path = _DB_PATH if os.path.exists(_DB_PATH) else "quantweave.db"
        data = evaluate_market_breadth(db_path)
        return {"success": True, "data": data}
    except Exception as e:
        logger.warning(f"获取市场宽度失败: {e}")
        return {"success": False, "data": {}, "message": str(e)}


@router.get("/sectors", summary="板块动量排名")
def get_market_sectors(top_n: int = Query(15, ge=5, le=50)):
    """获取行业板块动量排名

    基于最新交易日各行业平均涨跌幅排名
    """
    try:
        db_path = _DB_PATH if os.path.exists(_DB_PATH) else "quantweave.db"
        data = evaluate_sector_momentum(db_path)
        return {"success": True, "data": data[:top_n]}
    except Exception as e:
        logger.warning(f"获取板块动量失败: {e}")
        return {"success": False, "data": [], "message": str(e)}


@router.get("/overview", summary="市场总览（聚合数据）")
def get_market_overview(db: Session = Depends(get_db)):
    """市场总览 — 聚合指数、宽度、板块 + 持仓实时盈亏

    一次性返回前端行情页需要的所有数据，减少请求次数
    """
    result = {
        "indices": [],
        "breadth": {},
        "sectors": [],
        "portfolio_realtime": [],
    }

    # 1. 实时指数
    try:
        quotes = get_index_quotes()
        result["indices"] = [
            {
                "ts_code": code,
                "name": INDEX_MAP.get(code, ""),
                "current": q.get("current"),
                "percent": q.get("percent", 0),
                "chg": q.get("chg", 0),
                "high": q.get("high"),
                "low": q.get("low"),
                "volume": q.get("volume", 0),
                "amount": q.get("amount", 0),
                "amplitude": q.get("amplitude"),
                "is_trade": q.get("is_trade", False),
            }
            for code, q in quotes.items()
        ]
    except Exception as e:
        logger.warning(f"overview 指数失败: {e}")

    # 2. 市场宽度
    try:
        db_path = _DB_PATH if os.path.exists(_DB_PATH) else "quantweave.db"
        result["breadth"] = evaluate_market_breadth(db_path)
    except Exception as e:
        logger.warning(f"overview 宽度失败: {e}")

    # 3. 板块动量
    try:
        db_path = _DB_PATH if os.path.exists(_DB_PATH) else "quantweave.db"
        result["sectors"] = evaluate_sector_momentum(db_path)
    except Exception as e:
        logger.warning(f"overview 板块失败: {e}")

    # 4. 持仓实时盈亏
    try:
        from ..services.portfolio.portfolio_service import PortfolioService
        svc = PortfolioService()
        summary = svc.get_position_summary(db, "main")
        positions = summary.get("positions", [])

        if positions:
            # 批量获取实时价格
            codes = [p["ts_code"] for p in positions]
            realtime = batch_realtime_quotes(codes)

            for p in positions:
                q = realtime.get(p["ts_code"], {})
                current_price = q.get("current", p.get("current_price", 0))
                avg_cost = float(p.get("avg_cost", 0))
                volume = int(p.get("volume", 0))
                market_value = current_price * volume
                cost_value = avg_cost * volume
                profit = market_value - cost_value
                profit_pct = (profit / cost_value * 100) if cost_value > 0 else 0

                p["current_price"] = current_price
                p["market_value"] = round(market_value, 2)
                p["profit"] = round(profit, 2)
                p["profit_pct"] = round(profit_pct, 2)
                p["change_pct"] = q.get("percent", 0)
                p["high"] = q.get("high")
                p["low"] = q.get("low")
                p["open"] = q.get("open")
                p["turnover_rate"] = q.get("turnover_rate")
                p["amplitude"] = q.get("amplitude")
                p["volume"] = volume  # 持仓股数
                p["quote_volume"] = q.get("volume", 0)  # 成交量
                p["amount"] = q.get("amount", 0)

        result["portfolio_realtime"] = positions
    except Exception as e:
        logger.warning(f"overview 持仓实时失败: {e}")

    return {"success": True, "data": result}
