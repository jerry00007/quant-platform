"""
QuantWeave - 数据缓存服务
本地 SQLite 缓存，减少对 Tushare/AKShare API 的请求频率
"""
import pandas as pd
import numpy as np
from loguru import logger
from datetime import datetime, timedelta
from typing import Optional


class DataCache:
    """基于 SQLite 的数据缓存层

    策略：先查本地数据库缓存，命中则直接返回，未命中则调用远程API并写入缓存。
    """

    def __init__(self, db_session, cache_days: int = 30):
        """
        Args:
            db_session: SQLAlchemy Session
            cache_days: 缓存有效期（天），默认30天
        """
        self.db = db_session
        self.cache_days = cache_days

    def get_daily(self, ts_code: str, start_date: str, end_date: str,
                  stock_daily_model) -> Optional[pd.DataFrame]:
        """从本地缓存获取日线数据

        Args:
            ts_code: 股票代码
            start_date: 开始日期 YYYYMMDD
            end_date: 结束日期 YYYYMMDD
            stock_daily_model: StockDaily 模型类

        Returns:
            DataFrame or None（缓存未命中）
        """
        try:
            rows = (
                self.db.query(stock_daily_model)
                .filter(
                    stock_daily_model.ts_code == ts_code,
                    stock_daily_model.trade_date >= start_date,
                    stock_daily_model.trade_date <= end_date,
                )
                .order_by(stock_daily_model.trade_date)
                .all()
            )
            if not rows:
                return None

            data = []
            for r in rows:
                data.append({
                    "ts_code": r.ts_code,
                    "trade_date": r.trade_date,
                    "open": r.open,
                    "high": r.high,
                    "low": r.low,
                    "close": r.close,
                    "pre_close": r.pre_close,
                    "change_pct": r.change_pct,
                    "vol": r.vol,
                    "amount": r.amount,
                    "turnover_rate": r.turnover_rate,
                })

            df = pd.DataFrame(data)

            # 检查缓存是否覆盖了请求的时间范围
            cached_start = df["trade_date"].min()
            cached_end = df["trade_date"].max()

            # 计算实际交易日的预期数量（粗略：一年244天）
            start_dt = datetime.strptime(start_date, "%Y%m%d")
            end_dt = datetime.strptime(end_date, "%Y%m%d")
            expected_days = (end_dt - start_dt).days * 244 // 365

            if len(df) >= expected_days * 0.9:
                logger.info(f"缓存命中: {ts_code} {start_date}-{end_date}, {len(df)}条")
                return df
            else:
                logger.info(
                    f"缓存不完整: {ts_code} 需要~{expected_days}条, 缓存{len(df)}条"
                )
                return None

        except Exception as e:
            logger.warning(f"缓存查询失败: {e}")
            return None

    def is_cache_fresh(self, ts_code: str, latest_date_model) -> bool:
        """检查缓存数据是否新鲜（在有效期内）"""
        try:
            from ...models.models import StockDaily
            latest = (
                self.db.query(StockDaily.trade_date)
                .filter(StockDaily.ts_code == ts_code)
                .order_by(StockDaily.trade_date.desc())
                .first()
            )
            if not latest:
                return False
            latest_dt = datetime.strptime(latest[0], "%Y%m%d")
            return (datetime.now() - latest_dt).days <= self.cache_days
        except Exception:
            return False
