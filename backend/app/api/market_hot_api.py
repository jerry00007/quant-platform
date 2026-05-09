"""
QuantWeave — 市场热度 API

提供涨停连板、龙虎榜、资金流向、市场情绪聚合数据：
  - GET /market-hot/limit-list          涨停&连板榜
  - GET /market-hot/top-list            龙虎榜
  - GET /market-hot/moneyflow           资金流向（北向+个股TOP）
  - GET /market-hot/sentiment           市场情绪聚合 Dashboard

v2: 单例 Service，内存缓存跨请求生效，减少 Tushare API 调用
"""
import os
import threading
from fastapi import APIRouter, Query
from loguru import logger

from ..services.market_hot import MarketHotService

router = APIRouter(prefix="/market-hot", tags=["市场热度"])

# ── 单例 Service ──────────────────────────────────────────────
_service_instance: MarketHotService = None
_service_lock = threading.Lock()


def _get_service() -> MarketHotService:
    """获取单例 MarketHotService（线程安全）"""
    global _service_instance
    if _service_instance is None:
        with _service_lock:
            # double-check
            if _service_instance is None:
                token = os.environ.get("TUSHARE_TOKEN", "")
                if not token:
                    try:
                        from ..core.config import get_settings
                        token = get_settings().TUSHARE_TOKEN or ""
                    except Exception:
                        pass
                _service_instance = MarketHotService(tushare_token=token)
                logger.info("MarketHotService 单例已创建")
    return _service_instance


@router.get("/limit-list", summary="涨停&连板榜")
def get_limit_list(
    trade_date: str = Query(None, description="交易日 YYYYMMDD，默认今天"),
):
    """获取涨停板明细 + 连板统计

    数据源：Tushare limit_list_d（主）+ AKShare（备用）
    """
    try:
        svc = _get_service()
        data = svc.get_limit_list(trade_date=trade_date)
        return {"success": True, "data": data}
    except Exception as e:
        logger.error(f"涨停连板榜 API 失败: {e}")
        return {"success": False, "data": None, "message": str(e)}


@router.get("/top-list", summary="龙虎榜")
def get_top_list(
    trade_date: str = Query(None, description="交易日 YYYYMMDD，默认今天"),
):
    """获取龙虎榜上榜明细 + 机构/游资操作

    数据源：Tushare top_list + top_inst + hm_detail
    """
    try:
        svc = _get_service()
        data = svc.get_top_list(trade_date=trade_date)
        return {"success": True, "data": data}
    except Exception as e:
        logger.error(f"龙虎榜 API 失败: {e}")
        return {"success": False, "data": None, "message": str(e)}


@router.get("/moneyflow", summary="资金流向")
def get_moneyflow(
    days: int = Query(5, ge=1, le=30, description="回溯天数"),
):
    """获取北向资金流向 + 个股资金流 TOP20

    数据源：Tushare moneyflow_hsgt + moneyflow
    """
    try:
        svc = _get_service()
        data = svc.get_moneyflow(days=days)
        return {"success": True, "data": data}
    except Exception as e:
        logger.error(f"资金流向 API 失败: {e}")
        return {"success": False, "data": None, "message": str(e)}


@router.get("/sentiment", summary="市场情绪聚合")
def get_sentiment_dashboard():
    """市场情绪聚合 Dashboard

    汇总涨停、龙虎榜、资金流的核心指标，计算综合情绪评分
    """
    try:
        svc = _get_service()
        data = svc.get_sentiment_dashboard()
        return {"success": True, "data": data}
    except Exception as e:
        logger.error(f"市场情绪 API 失败: {e}")
        return {"success": False, "data": None, "message": str(e)}


# ── 缓存管理 ──────────────────────────────────────────────────
@router.get("/cache-status", summary="缓存状态")
def get_cache_status():
    """查看当前缓存条目及剩余 TTL"""
    try:
        svc = _get_service()
        return {"success": True, "data": svc.cache_status()}
    except Exception as e:
        return {"success": False, "data": None, "message": str(e)}


@router.post("/refresh", summary="手动刷新缓存")
def refresh_cache(
    module: str = Query(None, description="模块名: limit_list / top_list / moneyflow / sentiment，为空则刷新全部"),
):
    """手动清除缓存，下次请求将拉取最新数据

    - 不传 module：清除全部缓存
    - 传模块名：只清除对应模块
    """
    try:
        svc = _get_service()
        svc.clear_cache(prefix=module)
        return {
            "success": True,
            "message": f"缓存已清除: {module or '全部'}",
            "data": svc.cache_status(),
        }
    except Exception as e:
        logger.error(f"刷新缓存失败: {e}")
        return {"success": False, "message": str(e)}
