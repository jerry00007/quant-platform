"""
Paper Trading API - 超短线模拟盘接口

完全独立于核心策略的持仓/交易API，只操作 paper_ 前缀的表。
"""
import sqlite3
from typing import Optional
from fastapi import APIRouter, Query
from pydantic import BaseModel
from loguru import logger

from app.services.paper_trading.paper_engine import PaperEngine, DB_PATH

router = APIRouter(prefix="/paper", tags=["paper_trading"])


@router.get("/status")
async def get_paper_status():
    """获取模拟盘完整状态（账户+持仓+最近交易）"""
    engine = PaperEngine(str(DB_PATH))
    return engine.get_status_data()


@router.post("/scan")
async def trigger_scan():
    """手动触发扫描+买入"""
    engine = PaperEngine(str(DB_PATH))
    text = engine.scan_and_buy()
    return {"success": True, "message": text}


@router.post("/sell-check")
async def trigger_sell_check():
    """手动触发卖出检测"""
    engine = PaperEngine(str(DB_PATH))
    text = engine.check_and_sell()
    return {"success": True, "message": text}


@router.post("/init")
async def reset_account():
    """重置模拟盘账户"""
    conn = sqlite3.connect(str(DB_PATH))
    try:
        conn.execute("DELETE FROM paper_trades")
        conn.execute("DELETE FROM paper_positions")
        conn.execute("""
            UPDATE paper_account SET
                total_assets = 700000.0,
                cash_balance = 700000.0,
                total_profit = 0.0,
                total_profit_pct = 0.0,
                max_drawdown = 0.0,
                peak_assets = 700000.0,
                total_trades = 0,
                win_trades = 0,
                updated_at = datetime('now')
            WHERE name = 'ultra_short'
        """)
        conn.commit()
        return {"success": True, "message": "模拟盘已重置: 初始资金70万"}
    finally:
        conn.close()


@router.get("/trades")
async def get_recent_trades(limit: int = Query(50, ge=1, le=200)):
    """获取最近交易记录"""
    conn = sqlite3.connect(str(DB_PATH))
    try:
        rows = conn.execute(
            "SELECT id, ts_code, name, direction, price, volume, amount, "
            "commission, tax, net_amount, profit, profit_pct, mode, mode_name, "
            "score, reason, trade_date, created_at "
            "FROM paper_trades ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        cols = ["id", "ts_code", "name", "direction", "price", "volume", "amount",
                "commission", "tax", "net_amount", "profit", "profit_pct", "mode",
                "mode_name", "score", "reason", "trade_date", "created_at"]
        return {"trades": [dict(zip(cols, r)) for r in rows]}
    finally:
        conn.close()
