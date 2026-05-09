"""
QuantWeave - StockSense AI 深度分析服务
多维度股票分析：技术面 + 基本面 + 消息面 + 资金面 + 风控 + 实时行情
复用 QuickPicksService 的静态方法确保评分一致性
"""

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from datetime import datetime, timedelta
from typing import Dict, Optional

import numpy as np
import pandas as pd
from loguru import logger
from sqlalchemy.orm import Session

from ..screening.quick_picks_service import QuickPicksService
from ...models.models import Stock


def _safe_float(val, default=0.0):
    """Safely convert to float, handling null, '-', and other non-numeric"""
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


class StockSenseService:
    """StockSense AI 多维度深度分析"""

    def __init__(self, db: Session, data_service):
        self.db = db
        self.data_service = data_service

    def analyze(self, ts_code: str, days: int = 250) -> dict:
        """主入口 — 返回综合分析结果"""
        # ===== A. 获取历史数据 =====
        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")

        df = self.data_service.fetch_daily(ts_code, start_date, end_date)
        if df is None or df.empty or len(df) < 20:
            return {
                "error": f"数据不足: {ts_code}，获取到 {len(df) if df is not None else 0} 条记录",
                "ts_code": ts_code,
            }

        df = self.data_service.calculate_ma(df)
        df = df.sort_values("trade_date").reset_index(drop=True)

        # ===== I. 获取股票名称和行业 =====
        stock = self.db.query(Stock).filter(Stock.ts_code == ts_code).first()
        name = str(stock.name) if stock and stock.name else ts_code
        industry = str(stock.industry) if stock and stock.industry else ""

        # ===== B. 综合评分 =====
        scores = QuickPicksService._calculate_composite_score(df, industry)

        # ===== C. 入场点位 =====
        entry_points = QuickPicksService._calculate_entry_points(df)

        # ===== D. 风控指标 =====
        risk = QuickPicksService._calculate_risk(df)

        # ===== E. 趋势强度 + 量能得分 =====
        trend_strength = QuickPicksService._calculate_trend_strength(df)
        volume_score = QuickPicksService._calculate_volume_score(df)

        # ===== F. 风控扫描（可选，5s超时） =====
        risk_flags = []
        try:
            from pathlib import Path
            from ...risk.risk_filter_service import RiskFilterService

            def _run_risk_scan():
                db_path = Path(__file__).resolve().parent.parent.parent.parent / "quantweave.db"
                risk_svc = RiskFilterService(db_path)
                return risk_svc.scan_risks([ts_code])

            with ThreadPoolExecutor(max_workers=1) as pool:
                risk_data = pool.submit(_run_risk_scan).result(timeout=5)
            stock_risk = risk_data.get(ts_code, {})
            risk_flags = stock_risk.get("flags", [])
        except FuturesTimeout:
            logger.debug(f"风控扫描超时 {ts_code}")
        except Exception as e:
            logger.debug(f"风控扫描跳过 {ts_code}: {e}")

        # ===== G. 实时行情（雪球，可选，5s超时） =====
        realtime = None
        try:
            from ...data.xueqiu_data import get_realtime_quote

            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(get_realtime_quote, ts_code)
                quote = future.result(timeout=5)
            if quote:
                realtime = {
                    "price": _safe_float(quote.get("current")),
                    "change_pct": _safe_float(quote.get("percent")),
                    "volume": _safe_float(quote.get("volume")),
                    "turnover_rate": _safe_float(quote.get("turnover_rate")),
                    "market_cap": _safe_float(quote.get("market_capital")),
                    "pe": _safe_float(quote.get("pe_ttm")),
                    "pb": _safe_float(quote.get("pb")),
                    "high": _safe_float(quote.get("high")),
                    "low": _safe_float(quote.get("low")),
                    "open": _safe_float(quote.get("open")),
                    "last_close": _safe_float(quote.get("last_close")),
                    "amplitude": _safe_float(quote.get("amplitude")),
                    "is_trade": quote.get("is_trade"),
                }
        except FuturesTimeout:
            logger.debug(f"雪球实时行情超时 {ts_code}")
        except Exception as e:
            logger.debug(f"雪球实时行情跳过 {ts_code}: {e}")

        # ===== H. 新闻情绪（可选，5s超时） =====
        news_sentiment = None
        try:
            from ...news.news_service import NewsService

            news_svc = NewsService(self.db)

            def _fetch_and_analyze():
                ndf = news_svc.fetch_news(days=1)
                if ndf is not None and not ndf.empty:
                    return news_svc.analyze_news_sentiment(ndf), news_svc.extract_stock_mentions(ndf)
                return None, None

            with ThreadPoolExecutor(max_workers=1) as pool:
                sentiment, mentions_map = pool.submit(_fetch_and_analyze).result(timeout=5)

            if sentiment:
                mention_count = mentions_map.get(ts_code, 0) if mentions_map else 0
                categories = sentiment.get("categories", {})
                if not isinstance(categories, dict):
                    categories = {}
                news_sentiment = {
                    "score": float(sentiment.get("score", 0.0) or 0),
                    "hot_topics": list(categories.keys())[:5],
                    "stock_mentions": int(mention_count or 0),
                }
        except FuturesTimeout:
            logger.debug(f"新闻情绪分析超时 {ts_code}")
        except Exception as e:
            logger.debug(f"新闻情绪分析跳过 {ts_code}: {e}")

        # ===== J. 组装结果 =====
        last_row = df.iloc[-1]
        data_date = str(last_row.get("trade_date", ""))
        latest = {
            "date": str(last_row.get("trade_date", "")),
            "close": float(last_row.get("close", 0)),
            "change_pct": float(last_row.get("change_pct", 0)) if "change_pct" in df.columns else 0.0,
            "vol": float(last_row.get("vol", 0)) if "vol" in df.columns else 0.0,
            "amount": float(last_row.get("amount", 0)) if "amount" in df.columns else 0.0,
            "open": float(last_row.get("open", 0)) if "open" in df.columns else 0.0,
            "high": float(last_row.get("high", 0)) if "high" in df.columns else 0.0,
            "low": float(last_row.get("low", 0)) if "low" in df.columns else 0.0,
        }

        # MA 数据
        ma = {}
        for period in [5, 10, 20, 60]:
            col = f"ma{period}"
            if col in df.columns and not pd.isna(last_row.get(col)):
                ma[col] = round(float(last_row[col]), 3)
            else:
                # 手动计算兜底
                if len(df) >= period:
                    ma[col] = round(float(df["close"].tail(period).mean()), 3)
                else:
                    ma[col] = None

        # 清理 entry_points 中的 tuple → list
        clean_entry = {}
        if entry_points:
            for k, v in entry_points.items():
                if k == "key_levels" and isinstance(v, list):
                    clean_entry[k] = [[lvl[0], lvl[1]] for lvl in v]
                elif k == "buy_zone" and isinstance(v, list):
                    clean_entry[k] = v
                elif k == "key_support" and isinstance(v, tuple):
                    clean_entry[k] = list(v)
                else:
                    clean_entry[k] = v

        # 风控 flags 清理
        clean_risk_flags = []
        for flag in risk_flags:
            if isinstance(flag, dict):
                clean_risk_flags.append({
                    "dimension": flag.get("dimension", ""),
                    "level": flag.get("level", ""),
                    "detail": flag.get("detail", ""),
                })

        return {
            "ts_code": ts_code,
            "data_date": data_date,
            "name": name,
            "industry": industry,
            "latest": latest,
            "realtime": realtime,
            "scores": {
                "total": scores.get("total", 0),
                "tech": scores.get("tech", 0),
                "base": scores.get("base", 0),
                "news": scores.get("news", 0),
                "fund": scores.get("fund", 0),
                "advice": scores.get("advice", ""),
                "icon": scores.get("icon", ""),
                "rsi": scores.get("rsi", 0),
                "vol_ratio": scores.get("vol_ratio", 0),
                "ma60_dev": scores.get("ma60_dev", 0),
                "macd": scores.get("macd", ""),
                "ma_status": scores.get("ma_status", ""),
            },
            "ma": ma,
            "risk": {
                "pass": risk.get("pass", False),
                "warnings": risk.get("warnings", []),
                "ma20_deviation": risk.get("ma20_deviation", 0),
                "atr_ratio": risk.get("atr_ratio", 0),
                "flags": clean_risk_flags,
            },
            "entry_points": clean_entry,
            "trend_strength": round(float(trend_strength), 1),
            "volume_score": round(float(volume_score), 1),
            "news_sentiment": news_sentiment,
        }
