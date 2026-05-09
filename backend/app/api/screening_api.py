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
from ..services.screening.quick_picks_service import QuickPicksService, get_latest_scan_result
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


@router.get("/quick-picks", summary="一键选股（双均线+回调企稳）")
def quick_picks(
    db: Session = Depends(get_db),
):
    """
    一键选股 — 使用实盘验证的双均线交叉(7/60) + 回调企稳(8/95/5)两大策略
    对全市场进行扫描，返回当日买入信号股，含多策略共振检测和入场点位建议
    """
    service = QuickPicksService(db)
    result = service.run_scan()
    return result


@router.post("/quick-picks/trigger", summary="触发一键选股扫描（后台执行）")
def trigger_quick_picks(
    background_tasks: BackgroundTasks,
    force: bool = Query(False, description="强制重新扫描，忽略今日已有结果"),
    db: Session = Depends(get_db),
):
    """
    触发一键选股扫描 — 后台异步执行，立即返回
    扫描结果存入 scan_results 表，前端通过 /quick-picks/latest 获取
    默认同一天不重复扫描，传 force=true 可强制重扫
    """
    # 检查是否已有今天的扫描结果（非强制模式下跳过）
    # 🦊 狐探优化：改用 data_date 而非 scan_time 判断缓存
    # 原因：token 失效时数据停在旧日期，但 scan_time 是今天，
    #       用户点击"今日已扫描"会看到旧数据的信号，误以为今天有信号
    if not force:
        from pathlib import Path
        db_path = Path(__file__).resolve().parent.parent.parent.parent / "quantweave.db"
        latest = get_latest_scan_result(db_path)

        if latest:
            data_date = latest.get("data_date", "")
            scan_time = latest.get("scan_time", "")
            result_data = latest.get("result", {})

            data_fresh, data_fresh_msg = QuickPicksService._validate_data_freshness(data_date)

            if data_fresh:
                return {
                    "status": "already_done",
                    "message": f"数据日期({data_date})为最近交易日，数据新鲜",
                    "latest_id": latest["id"],
                    "scan_time": scan_time,
                    "data_date": data_date,
                    "data_fresh": True,
                    "data_fresh_msg": data_fresh_msg or result_data.get("data_freshness_msg", ""),
                }
            else:
                return {
                    "status": "already_done",
                    "message": f"数据日期({data_date})不是最近交易日，请强制重新扫描",
                    "latest_id": latest["id"],
                    "scan_time": scan_time,
                    "data_date": data_date,
                    "data_fresh": False,
                    "data_fresh_msg": data_fresh_msg or result_data.get("data_freshness_msg", ""),
                }

    # 后台执行扫描
    service = QuickPicksService(db)
    background_tasks.add_task(service.run_and_save)
    
    return {
        "status": "scanning",
        "message": "扫描已启动，预计2~3分钟完成",
    }


@router.get("/quick-picks/latest", summary="获取最新一键选股结果")
def get_latest_quick_picks():
    """
    获取最新一次一键选股扫描结果（从数据库读取）
    """
    from ..services.screening.quick_picks_service import get_latest_scan_result
    from pathlib import Path
    db_path = Path(__file__).resolve().parent.parent.parent.parent / "quantweave.db"
    latest = get_latest_scan_result(db_path)
    
    if not latest:
        return {"status": "no_data", "message": "暂无扫描结果，请先点击选股"}

    result_data = latest.get("result", {})
    return {
        "status": "ok",
        "scan_time": latest["scan_time"],
        "data_date": latest["data_date"],
        "data_fresh": result_data.get("data_date_fresh", False),
        "data_fresh_msg": result_data.get("data_freshness_msg", ""),
        "result": result_data,
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


@router.get("/sense/{ts_code}", summary="StockSense AI 深度分析")
def stock_sense_analysis(
    ts_code: str,
    days: int = Query(250, description="分析天数"),
    db: Session = Depends(get_db),
):
    """StockSense AI 多维度深度分析 — 技术面30% + 基本面25% + 消息面20% + 资金面15%"""
    from ..services.analysis.stock_sense_service import StockSenseService
    ds = _get_data_service(db)
    service = StockSenseService(db, ds)
    return service.analyze(ts_code, days=days)


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
    stocks: Optional[str] = Query(None, description="指定股票，逗号分隔；支持关键字: portfolio/tracking_pool/watchlist"),
    strategies: Optional[str] = Query(None, description="指定策略，逗号分隔"),
    db: Session = Depends(get_db),
):
    """获取今日交易信号"""
    ds = _get_data_service(db)
    service = SignalService(db, ds)

    stock_codes = None
    strategy_keys = strategies.split(",") if strategies else None

    # 解析特殊关键字
    if stocks:
        if stocks == "tracking_pool":
            # 从跟踪池获取 tracking 状态的股票
            from ..services.tracking.tracking_pool_service import TrackingPoolService
            tp_service = TrackingPoolService(db)
            pool = tp_service.get_tracking_pool()
            stock_codes = [item["ts_code"] for item in pool] if pool else []
        elif stocks == "watchlist":
            # 从关注列表获取
            wl = ds.get_watchlist()
            stock_codes = [item["ts_code"] for item in wl] if wl else []
        else:
            stock_codes = stocks.split(",")

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
