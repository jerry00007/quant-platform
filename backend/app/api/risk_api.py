"""
QuantWeave - 风控 API
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..core.database import get_db
from ..models.models import RiskAlert

router = APIRouter(prefix="/risk", tags=["风控管理"])


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
