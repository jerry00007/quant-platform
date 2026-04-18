"""
QuantWeave - 风控 API
"""
from fastapi import APIRouter, Depends, Query, BackgroundTasks
from sqlalchemy.orm import Session
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel
from datetime import datetime
from ..core.database import get_db
from ..models.models import RiskAlert
from ..services.risk.risk_filter_service import RiskFilterService

router = APIRouter(prefix="/risk", tags=["风控管理"])


class RiskScanRequest(BaseModel):
    ts_codes: List[str]
    force: bool = False


def _get_db_path() -> Path:
    """获取 SQLite 数据库路径"""
    return Path(__file__).resolve().parent.parent.parent / "quantweave.db"


# ==================== 风控排雷扫描 ====================

@router.post("/scan", summary="风控排雷扫描（指定股票列表）")
def scan_risks(req: RiskScanRequest):
    """对指定股票列表执行6维度风控排雷扫描"""
    ts_codes = req.ts_codes
    if not ts_codes:
        return {"error": "请提供股票代码列表"}
    if len(ts_codes) > 100:
        return {"error": "单次最多扫描100只股票"}

    svc = RiskFilterService(_get_db_path())
    risk_data = svc.scan_risks(ts_codes, force=req.force)

    # 统计
    blocked = sum(1 for v in risk_data.values() if v.get("risk_level") in ("blocked", "block"))
    warning = sum(1 for v in risk_data.values() if v.get("risk_level") == "warning")
    safe = sum(1 for v in risk_data.values() if v.get("risk_level") == "safe")

    return {
        "total": len(ts_codes),
        "blocked_count": blocked,
        "warning_count": warning,
        "safe_count": safe,
        "data": risk_data,
    }


@router.get("/scan/portfolio", summary="持仓风控排雷")
def scan_portfolio_risks(
    force: bool = Query(False, description="强制刷新缓存"),
):
    """对当前全部持仓执行6维度风控排雷扫描"""
    import sqlite3
    db_path = _get_db_path()
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT ts_code, name FROM positions WHERE is_active = 1"
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        return {"total": 0, "message": "当前无活跃持仓", "data": {}}

    ts_codes = [r["ts_code"] for r in rows]
    name_map = {r["ts_code"]: r["name"] for r in rows}

    svc = RiskFilterService(db_path)
    risk_data = svc.scan_risks(ts_codes, force=force)

    # 给结果附加股票名称
    enriched = {}
    for code, info in risk_data.items():
        enriched[code] = {**info, "name": name_map.get(code, "")}

    blocked = sum(1 for v in risk_data.values() if v.get("risk_level") in ("blocked", "block"))
    warning = sum(1 for v in risk_data.values() if v.get("risk_level") == "warning")
    safe = sum(1 for v in risk_data.values() if v.get("risk_level") == "safe")

    return {
        "total": len(ts_codes),
        "blocked_count": blocked,
        "warning_count": warning,
        "safe_count": safe,
        "data": enriched,
    }


# ==================== 全市场风控快照 ====================

@router.post("/snapshot", summary="全市场风控快照（夜间批量扫描）")
def run_risk_snapshot(force: bool = Query(False, description="强制重扫")):
    """对全市场活跃股票执行6维度风控扫描，结果缓存到 stock_risk_flags 表"""
    from fastapi.responses import JSONResponse
    import threading

    db_path = _get_db_path()
    svc = RiskFilterService(db_path)

    # 检查今天是否已扫描过
    if not force:
        stats = svc._summarize_cache(datetime.now().strftime("%Y%m%d"))
        if stats.get("total", 0) > 0:
            return {
                "status": "already_done",
                "message": f"今日已扫描{stats['total']}只股票",
                **stats,
            }

    # 全量扫描（同步执行，可能需要5-10分钟）
    result = svc.scan_full_market(force=force)
    return {"status": "ok", **result}


# ==================== 原有告警接口 ====================


@router.get("/alerts", summary="获取风控告警列表")
def get_alerts(
    level: str = Query(None, description="级别: info/warning/critical"),
    is_resolved: bool = Query(None, description="是否已处理"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    query = db.query(RiskAlert)
    if level:
        query = query.filter(RiskAlert.level == level)
    if is_resolved is not None:
        query = query.filter(RiskAlert.is_resolved == is_resolved)
    total = query.count()
    items = query.order_by(RiskAlert.created_at.desc()).offset((page - 1) * size).limit(size).all()
    return {
        "total": total,
        "page": page,
        "size": size,
        "items": [
            {
                "id": a.id,
                "alert_type": a.alert_type,
                "level": a.level,
                "title": a.title,
                "detail": a.detail,
                "ts_code": a.ts_code,
                "strategy_id": a.strategy_id,
                "is_read": a.is_read,
                "is_resolved": a.is_resolved,
                "created_at": str(a.created_at),
            }
            for a in items
        ],
    }


@router.put("/alerts/{alert_id}/resolve", summary="处理告警")
def resolve_alert(alert_id: int, db: Session = Depends(get_db)):
    alert = db.query(RiskAlert).filter(RiskAlert.id == alert_id).first()
    if not alert:
        return {"error": "告警不存在"}
    alert.is_resolved = True
    alert.is_read = True
    db.commit()
    return {"message": "告警已处理"}


@router.get("/dashboard", summary="风控仪表盘数据")
def risk_dashboard(db: Session = Depends(get_db)):
    total = db.query(RiskAlert).count()
    unresolved = db.query(RiskAlert).filter(RiskAlert.is_resolved == False).count()
    critical = db.query(RiskAlert).filter(
        RiskAlert.level == "critical", RiskAlert.is_resolved == False
    ).count()
    warning = db.query(RiskAlert).filter(
        RiskAlert.level == "warning", RiskAlert.is_resolved == False
    ).count()

    return {
        "total_alerts": total,
        "unresolved": unresolved,
        "critical_count": critical,
        "warning_count": warning,
        "recent_alerts": [
            {
                "id": a.id,
                "alert_type": a.alert_type,
                "level": a.level,
                "title": a.title,
                "created_at": str(a.created_at),
            }
            for a in db.query(RiskAlert)
            .order_by(RiskAlert.created_at.desc())
            .limit(5)
            .all()
        ],
    }
