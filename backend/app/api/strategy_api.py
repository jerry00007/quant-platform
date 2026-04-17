"""
QuantWeave - 策略管理 API
"""
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from typing import Optional

from ..core.database import get_db
from ..models.models import Strategy
from ..services.strategy.strategy_service import STRATEGY_REGISTRY
from ..schemas import StrategyCreate, StrategyUpdate, StrategyStatusUpdate

router = APIRouter(prefix="/strategies", tags=["策略管理"])


@router.get("/types", summary="获取可用策略类型")
def get_strategy_types():
    types = []
    for key, cls in STRATEGY_REGISTRY.items():
        types.append({
            "key": key,
            "name": cls.name,
            "description": cls.description,
            "default_params": cls.params,
        })
    return {"items": types}


@router.get("", summary="获取策略列表")
def get_strategies(
    status: Optional[str] = Query(None, description="状态筛选: draft/running/paused/stopped"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    query = db.query(Strategy)
    if status:
        query = query.filter(Strategy.status == status)
    total = query.count()
    items = query.order_by(Strategy.updated_at.desc()).offset((page - 1) * size).limit(size).all()
    return {
        "total": total,
        "page": page,
        "size": size,
        "items": [
            {
                "id": s.id,
                "name": s.name,
                "description": s.description,
                "strategy_type": s.strategy_type,
                "params": s.params,
                "status": s.status,
                "stock_pool": s.stock_pool,
                "total_return": s.total_return,
                "max_drawdown": s.max_drawdown,
                "win_rate": s.win_rate,
                "sharpe_ratio": s.sharpe_ratio,
                "created_at": str(s.created_at),
                "updated_at": str(s.updated_at),
            }
            for s in items
        ],
    }


@router.post("", summary="创建策略")
def create_strategy(data: StrategyCreate, db: Session = Depends(get_db)):
    strategy = Strategy(
        name=data.name,
        description=data.description or "",
        strategy_type=data.strategy_type,
        params=data.params or {},
        stock_pool=data.stock_pool or [],
        status="draft",
    )
    db.add(strategy)
    db.commit()
    db.refresh(strategy)
    return {"id": strategy.id, "message": "策略创建成功"}


@router.put("/{strategy_id}", summary="更新策略")
def update_strategy(strategy_id: int, data: StrategyUpdate, db: Session = Depends(get_db)):
    strategy = db.query(Strategy).filter(Strategy.id == strategy_id).first()
    if not strategy:
        raise HTTPException(status_code=404, detail="策略不存在")
    update_data = data.model_dump(exclude_none=True)
    for key, value in update_data.items():
        if hasattr(strategy, key):
            setattr(strategy, key, value)
    db.commit()
    return {"message": "策略更新成功"}


@router.put("/{strategy_id}/status", summary="切换策略状态")
def toggle_strategy(strategy_id: int, data: StrategyStatusUpdate, db: Session = Depends(get_db)):
    strategy = db.query(Strategy).filter(Strategy.id == strategy_id).first()
    if not strategy:
        raise HTTPException(status_code=404, detail="策略不存在")
    strategy.status = data.status
    db.commit()
    return {"message": f"策略状态已切换为 {data.status}"}


@router.delete("/{strategy_id}", summary="删除策略")
def delete_strategy(strategy_id: int, db: Session = Depends(get_db)):
    strategy = db.query(Strategy).filter(Strategy.id == strategy_id).first()
    if not strategy:
        raise HTTPException(status_code=404, detail="策略不存在")
    db.delete(strategy)
    db.commit()
    return {"message": "策略已删除"}
