"""
QuantWeave - 数据相关 API
"""
from fastapi import APIRouter, Depends, Query, BackgroundTasks
from sqlalchemy.orm import Session
from typing import Optional, List
from pydantic import BaseModel, Field
import time
from loguru import logger

from ..core.database import get_db
from ..core.config import get_settings
from ..models.models import Stock, StockDaily
from ..services.data.data_service import DataService

router = APIRouter(prefix="/data", tags=["数据管理"])
settings = get_settings()


class BatchSyncRequest(BaseModel):
    ts_codes: List[str] = Field(..., max_length=100, description="最多100只股票")
    start_date: str
    end_date: str


@router.get("/stocks", summary="获取股票列表")
def get_stocks(
    keyword: Optional[str] = Query(None, description="搜索关键词（代码或名称）"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    query = db.query(Stock).filter(Stock.is_active == True)
    if keyword:
        query = query.filter(
            (Stock.ts_code.contains(keyword)) |
            (Stock.name.contains(keyword)) |
            (Stock.symbol.contains(keyword))
        )
    total = query.count()
    items = query.offset((page - 1) * size).limit(size).all()
    return {
        "total": total,
        "page": page,
        "size": size,
        "items": [
            {
                "ts_code": s.ts_code,
                "symbol": s.symbol,
                "name": s.name,
                "industry": s.industry,
                "market": s.market,
            }
            for s in items
        ],
    }


@router.post("/stocks/sync", summary="同步股票列表")
def sync_stocks(db: Session = Depends(get_db)):
    service = DataService(db, tushare_token=settings.TUSHARE_TOKEN)
    count = service.sync_stock_list()
    return {"message": f"同步完成，新增 {count} 只", "count": count}


@router.get("/status", summary="获取数据状态")
def get_data_status(db: Session = Depends(get_db)):
    """获取数据库中最新数据的日期"""
    latest = db.query(StockDaily.trade_date).order_by(StockDaily.trade_date.desc()).first()
    stock_count = db.query(Stock).filter(Stock.is_active == True).count()
    daily_count = db.query(StockDaily).count()
    
    return {
        "latest_date": latest[0] if latest else None,
        "stock_count": stock_count,
        "daily_records": daily_count,
    }


@router.get("/daily/{ts_code}", summary="获取日线行情")
def get_daily(
    ts_code: str,
    start_date: str = Query(..., description="开始日期 20250101"),
    end_date: str = Query(..., description="结束日期 20250410"),
    db: Session = Depends(get_db),
):
    service = DataService(db, tushare_token=settings.TUSHARE_TOKEN)
    df = service.fetch_daily(ts_code, start_date, end_date)
    if df.empty:
        return {"items": [], "total": 0}
    df = service.calculate_ma(df)
    return {
        "total": len(df),
        "items": df.to_dict(orient="records"),
    }


@router.get("/realtime", summary="获取实时行情")
def get_realtime(
    codes: str = Query(..., description="股票代码，逗号分隔 000001.SZ,600519.SH"),
    db: Session = Depends(get_db),
):
    service = DataService(db, tushare_token=settings.TUSHARE_TOKEN)
    ts_codes = [c.strip() for c in codes.split(",")]
    data = service.get_realtime_quote(ts_codes)
    return {"items": data, "total": len(data)}


@router.post("/batch-sync", summary="批量同步历史数据")
def batch_sync_daily(
    request: BatchSyncRequest,
    db: Session = Depends(get_db),
):
    """批量同步多只股票的历史日线数据"""
    service = DataService(db, tushare_token=settings.TUSHARE_TOKEN)
    results = []
    total_saved = 0
    
    for ts_code in request.ts_codes:
        try:
            df = service.fetch_daily(ts_code, request.start_date, request.end_date)
            if not df.empty:
                saved = service.save_daily_data(df)
                results.append({"ts_code": ts_code, "status": "success", "rows": saved})
                total_saved += saved
            else:
                results.append({"ts_code": ts_code, "status": "no_data", "rows": 0})
        except Exception as e:
            results.append({"ts_code": ts_code, "status": "error", "error": str(e), "rows": 0})
    
    return {
        "message": f"批量同步完成，共保存 {total_saved} 条数据",
        "total": len(request.ts_codes),
        "saved": total_saved,
        "results": results,
    }


@router.post("/sync-all-daily", summary="同步全部股票历史数据（耗时）")
def sync_all_daily(
    start_date: str = Query(..., description="开始日期 20250101"),
    end_date: str = Query(..., description="结束日期 20250410"),
    limit: int = Query(50, ge=1, le=500, description="每次同步数量"),
    db: Session = Depends(get_db),
):
    """同步全部股票的历史数据（需要较长时间，内置限速）"""
    # 获取股票列表
    stocks = db.query(Stock).filter(Stock.is_active == True).limit(limit).all()
    ts_codes = [s.ts_code for s in stocks]
    
    service = DataService(db, tushare_token=settings.TUSHARE_TOKEN)
    results = []
    total_saved = 0
    
    for i, ts_code in enumerate(ts_codes):
        try:
            df = service.fetch_daily(ts_code, start_date, end_date)
            if not df.empty:
                saved = service.save_daily_data(df)
                results.append({"ts_code": ts_code, "status": "success", "rows": saved})
                total_saved += saved
            else:
                results.append({"ts_code": ts_code, "status": "no_data", "rows": 0})
            # 每5只暂停0.5秒，避免触发API限速
            if (i + 1) % 5 == 0:
                time.sleep(0.5)
        except Exception as e:
            logger.warning(f"同步失败 {ts_code}: {e}")
            results.append({"ts_code": ts_code, "status": "error", "error": str(e)})
    
    return {
        "message": f"已同步 {len(ts_codes)} 只股票的历史数据",
        "total": len(ts_codes),
        "saved": total_saved,
        "start_date": start_date,
        "end_date": end_date,
    }
