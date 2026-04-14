"""
QuantWeave - 选股 & 信号 API
"""
from fastapi import APIRouter, Depends, Query, BackgroundTasks
from sqlalchemy.orm import Session
from typing import Optional, List

from ..core.database import get_db
from ..core.config import get_settings
from ..services.data.data_service import DataService
from ..services.screening.screening_service import ScreeningService
from ..services.signal.signal_service import SignalService

router = APIRouter(prefix="/screening", tags=["选股与信号"])

settings = get_settings()


def _get_data_service(db: Session) -> DataService:
    return DataService(db, tushare_token=settings.TUSHARE_TOKEN)


# ==================== 选股扫描 ====================

@router.get("/scan", summary="全市场选股扫描")
def scan_market(
    preset: str = Query("all", description="预设模板: aggressive/moderate/conservative/all"),
    strategies: Optional[str] = Query(None, description="指定策略，逗号分隔"),
    stocks: Optional[str] = Query(None, description="指定股票，逗号分隔"),
    days: int = Query(120, description="回看天数"),
    top_n: int = Query(20, description="返回前N只"),
    db: Session = Depends(get_db),
):
    """全市场选股扫描"""
    ds = _get_data_service(db)
    service = ScreeningService(db, ds)

    strategy_keys = strategies.split(",") if strategies else None
    stock_codes = stocks.split(",") if stocks else None

    results = service.scan_market(
        strategy_keys=strategy_keys,
        stock_codes=stock_codes,
        days=days,
        preset=preset,
        top_n=top_n,
    )
    return {
        "total": len(results),
        "preset": preset,
        "items": results,
    }


@router.get("/analyze/{ts_code}", summary="单只股票深度分析")
def analyze_stock(
    ts_code: str,
    days: int = Query(250, description="分析天数"),
    db: Session = Depends(get_db),
):
    """单只股票深度分析"""
    ds = _get_data_service(db)
    service = ScreeningService(db, ds)
    return service.analyze_stock(ts_code, days=days)


@router.get("/presets", summary="获取选股预设模板")
def get_presets():
    """获取选股预设模板"""
    return {
        "items": [
            {"key": k, **v}
            for k, v in ScreeningService.SCREENING_PRESETS.items()
        ]
    }


# ==================== 每日信号 ====================

@router.get("/signals", summary="获取今日交易信号")
def get_daily_signals(
    stocks: Optional[str] = Query(None, description="指定股票，逗号分隔"),
    strategies: Optional[str] = Query(None, description="指定策略，逗号分隔"),
    db: Session = Depends(get_db),
):
    """获取今日交易信号"""
    ds = _get_data_service(db)
    service = SignalService(db, ds)

    stock_codes = stocks.split(",") if stocks else None
    strategy_keys = strategies.split(",") if strategies else None

    return service.generate_daily_signals(
        stock_codes=stock_codes,
        strategy_keys=strategy_keys,
    )


@router.get("/morning-brief", summary="早盘提醒文本")
def get_morning_brief(
    stocks: Optional[str] = Query(None, description="指定股票，逗号分隔"),
    db: Session = Depends(get_db),
):
    """获取早盘提醒文本（用于微信通知）"""
    ds = _get_data_service(db)
    service = SignalService(db, ds)
    stock_codes = stocks.split(",") if stocks else None
    text = service.generate_morning_brief(stock_codes=stock_codes)
    return {"text": text}


# ==================== 关注列表 ====================

@router.get("/watchlist", summary="获取关注列表")
def get_watchlist(
    group: Optional[str] = Query(None, description="分组筛选"),
    db: Session = Depends(get_db),
):
    ds = _get_data_service(db)
    return {"items": ds.get_watchlist(group=group)}


@router.post("/watchlist", summary="添加关注")
def add_watchlist(
    ts_code: str = Query(..., description="股票/ETF代码"),
    name: str = Query("", description="名称"),
    asset_type: str = Query("stock", description="类型:stock/etf"),
    group: str = Query("默认", description="分组"),
    notes: str = Query("", description="备注"),
    db: Session = Depends(get_db),
):
    ds = _get_data_service(db)
    ok = ds.add_to_watchlist(ts_code, name, asset_type, group, notes)
    return {"success": ok, "message": "添加成功" if ok else "添加失败"}


@router.delete("/watchlist/{ts_code}", summary="取消关注")
def remove_watchlist(ts_code: str, db: Session = Depends(get_db)):
    ds = _get_data_service(db)
    ok = ds.remove_from_watchlist(ts_code)
    return {"success": ok, "message": "已取消关注" if ok else "操作失败"}


# ==================== ETF ====================

@router.get("/etf/list", summary="获取ETF列表")
def get_etf_list(
    keyword: Optional[str] = Query(None, description="搜索关键词"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    from ..models.models import ETFInfo
    query = db.query(ETFInfo).filter(ETFInfo.is_active == True)
    if keyword:
        query = query.filter(
            (ETFInfo.ts_code.contains(keyword)) |
            (ETFInfo.name.contains(keyword))
        )
    total = query.count()
    items = query.offset((page - 1) * size).limit(size).all()
    return {
        "total": total,
        "page": page,
        "size": size,
        "items": [
            {
                "ts_code": e.ts_code,
                "name": e.name,
                "fund_type": e.fund_type,
                "management_fee": e.management_fee,
            }
            for e in items
        ],
    }


@router.post("/etf/sync", summary="同步ETF列表")
def sync_etf_list(db: Session = Depends(get_db)):
    ds = _get_data_service(db)
    count = ds.sync_etf_list()
    return {"message": f"ETF同步完成，新增 {count} 只", "count": count}


@router.get("/etf/daily/{ts_code}", summary="获取ETF日线数据")
def get_etf_daily(
    ts_code: str,
    start_date: str = Query(..., description="开始日期"),
    end_date: str = Query(..., description="结束日期"),
    db: Session = Depends(get_db),
):
    ds = _get_data_service(db)
    df = ds.fetch_etf_daily(ts_code, start_date, end_date)
    if df.empty:
        return {"items": [], "total": 0}
    return {"total": len(df), "items": df.to_dict(orient="records")}
