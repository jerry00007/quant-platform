"""
QuantWeave - 数据采集服务
支持 Tushare Pro + AKShare 双数据源
"""
import akshare as ak
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from loguru import logger
from typing import Optional, List
from sqlalchemy.orm import Session

from ...models.models import Stock, StockDaily, ETFInfo, Watchlist


class DataService:
    """数据采集引擎（支持本地缓存优先）"""

    # 类级别缓存，避免实时行情频繁全量拉取
    _realtime_cache = None
    _realtime_cache_time = 0
    _realtime_cache_ttl = 30  # 30秒缓存

    def __init__(self, db: Session, tushare_token: str = ""):
        self.db = db
        self.tushare_token = tushare_token
        self._cache = None  # 延迟初始化缓存

        if tushare_token:
            try:
                import tushare as ts
                ts.set_token(tushare_token)
                self.ts_pro = ts.pro_api()
                logger.info("Tushare Pro 已连接")
            except Exception as e:
                logger.warning(f"Tushare 初始化失败: {e}，将使用 AKShare")
                self.ts_pro = None
        else:
            self.ts_pro = None

    @property
    def cache(self):
        """延迟初始化数据缓存"""
        if self._cache is None:
            from .data_cache import DataCache
            self._cache = DataCache(self.db)
        return self._cache

    # ==================== 股票基础信息 ====================

    def sync_stock_list(self) -> int:
        """同步A股股票列表（Tushare优先，AKShare备用，批量优化版）"""
        count = 0
        
        # 优先使用 Tushare
        if self.ts_pro:
            try:
                df = self.ts_pro.stock_basic(
                    exchange='', list_status='L',
                    fields='ts_code,symbol,name,area,industry,market,list_date'
                )
                if df is not None and not df.empty:
                    existing_stocks = {s.ts_code: s for s in self.db.query(Stock).all()}
                    new_records = []
                    
                    for _, row in df.iterrows():
                        ts_code = row.get("ts_code", "")
                        if not ts_code:
                            continue
                        existing = existing_stocks.get(ts_code)
                        if existing:
                            existing.name = row.get("name", existing.name)
                            existing.industry = row.get("industry", existing.industry)
                            existing.market = row.get("market", existing.market)
                            existing.list_date = row.get("list_date", existing.list_date)
                            existing.updated_at = datetime.now()
                        else:
                            stock = Stock(
                                ts_code=ts_code,
                                symbol=row.get("symbol", ""),
                                name=row.get("name", ""),
                                industry=row.get("industry", ""),
                                market=row.get("market", ""),
                                list_date=row.get("list_date", ""),
                                is_active=True,
                            )
                            new_records.append(stock)
                            count += 1
                    
                    if new_records:
                        self.db.bulk_save_objects(new_records)
                    self.db.commit()
                    logger.info(f"Tushare同步股票列表完成，新增 {count} 只")
                    return count
            except Exception as e:
                logger.warning(f"Tushare同步股票列表失败: {e}，尝试AKShare")

        # 备用: AKShare
        try:
            df = ak.stock_zh_a_spot_em()
            
            # 批量查询已有代码，避免逐行查询
            existing_stocks = {
                s.ts_code: s for s in self.db.query(Stock).all()
            }
            
            new_records = []
            for _, row in df.iterrows():
                code = str(row.get("代码", ""))
                if not code:
                    continue
                # 转换为 ts_code 格式
                if code.startswith("6"):
                    ts_code = f"{code}.SH"
                elif code.startswith(("0", "3")):
                    ts_code = f"{code}.SZ"
                elif code.startswith("4") or code.startswith("8"):
                    ts_code = f"{code}.BJ"
                else:
                    continue

                existing = existing_stocks.get(ts_code)
                if existing:
                    existing.name = row.get("名称", existing.name)
                    existing.updated_at = datetime.now()
                else:
                    stock = Stock(
                        ts_code=ts_code,
                        symbol=code,
                        name=row.get("名称", ""),
                        is_active=True,
                    )
                    new_records.append(stock)
                    count += 1

            if new_records:
                self.db.bulk_save_objects(new_records)
            self.db.commit()
            logger.info(f"AKShare同步股票列表完成，新增 {count} 只")
            return count
        except Exception as e:
            logger.error(f"同步股票列表失败: {e}")
            self.db.rollback()
            return 0

    # ==================== ETF数据 ====================

    def sync_etf_list(self) -> int:
        """同步ETF列表"""
        try:
            # Tushare: fund_basic 获取ETF
            count = 0
            if self.ts_pro:
                try:
                    df = self.ts_pro.fund_basic(
                        market="E",
                        fields="ts_code,name,fund_type,management,fee_rate"
                    )
                    # 只保留ETF（过滤掉其他基金类型）
                    etf_df = df[df["ts_code"].str.match(r"^\d{6}\.(SH|SZ)$")]
                    for _, row in etf_df.iterrows():
                        existing = self.db.query(ETFInfo).filter(
                            ETFInfo.ts_code == row["ts_code"]
                        ).first()
                        if existing:
                            existing.name = row["name"]
                            existing.updated_at = datetime.now()
                        else:
                            etf = ETFInfo(
                                ts_code=row["ts_code"],
                                name=row["name"],
                                fund_type=row.get("fund_type", ""),
                                management_fee=float(row.get("fee_rate", 0) or 0),
                                is_active=True,
                            )
                            self.db.add(etf)
                            count += 1
                    self.db.commit()
                except Exception as e:
                    logger.warning(f"Tushare ETF列表获取失败: {e}")
            return count
        except Exception as e:
            logger.error(f"同步ETF列表失败: {e}")
            self.db.rollback()
            return 0

    def fetch_etf_daily(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """获取ETF日线数据"""
        # ETF数据复用 StockDaily 表（结构一致）
        if self.ts_pro:
            try:
                df = self.ts_pro.fund_daily(
                    ts_code=ts_code,
                    start_date=start_date,
                    end_date=end_date,
                    fields="ts_code,trade_date,open,high,low,close,vol,amount,pre_close,change_pct"
                )
                if df is not None and not df.empty:
                    df["trade_date"] = df["trade_date"].astype(str)
                    return df
            except Exception as e:
                logger.warning(f"Tushare ETF数据获取失败 {ts_code}: {e}")

        # 备用: AKShare
        try:
            symbol = ts_code.split(".")[0]
            start_fmt = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:]}"
            end_fmt = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:]}"
            df = ak.fund_etf_hist_em(
                symbol=symbol,
                period="daily",
                start_date=start_fmt,
                end_date=end_fmt,
                adjust="qfq"
            )
            if df is not None and not df.empty:
                df = df.rename(columns={
                    "日期": "trade_date", "开盘": "open", "收盘": "close",
                    "最高": "high", "最低": "low", "涨跌幅": "change_pct",
                    "成交量": "vol", "成交额": "amount",
                })
                df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.strftime("%Y%m%d")
                df["ts_code"] = ts_code
                df["pre_close"] = df["close"].shift(1)
                return df[["ts_code", "trade_date", "open", "high", "low", "close",
                           "pre_close", "change_pct", "vol", "amount"]]
        except Exception as e:
            logger.warning(f"AKShare ETF数据获取失败 {ts_code}: {e}")

        return pd.DataFrame()

    # ==================== 关注列表 ====================

    def get_watchlist(self, group: str = None) -> List[dict]:
        """获取关注列表"""
        query = self.db.query(Watchlist).filter(Watchlist.is_active == True)
        if group:
            query = query.filter(Watchlist.group_name == group)
        items = query.all()
        return [
            {
                "ts_code": w.ts_code,
                "name": w.name,
                "asset_type": w.asset_type,
                "group_name": w.group_name,
                "notes": w.notes,
            }
            for w in items
        ]

    def add_to_watchlist(
        self, ts_code: str, name: str = "",
        asset_type: str = "stock", group: str = "默认", notes: str = ""
    ) -> bool:
        """添加到关注列表"""
        try:
            existing = self.db.query(Watchlist).filter(Watchlist.ts_code == ts_code).first()
            if existing:
                existing.is_active = True
                existing.group_name = group
                existing.notes = notes
            else:
                item = Watchlist(
                    ts_code=ts_code,
                    name=name or ts_code,
                    asset_type=asset_type,
                    group_name=group,
                    notes=notes,
                )
                self.db.add(item)
            self.db.commit()
            return True
        except Exception as e:
            logger.error(f"添加关注失败: {e}")
            self.db.rollback()
            return False

    def remove_from_watchlist(self, ts_code: str) -> bool:
        """从关注列表移除"""
        try:
            item = self.db.query(Watchlist).filter(Watchlist.ts_code == ts_code).first()
            if item:
                item.is_active = False
                self.db.commit()
            return True
        except Exception as e:
            logger.error(f"移除关注失败: {e}")
            self.db.rollback()
            return False

    # ==================== 通用数据获取 ====================

    def fetch_daily(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        获取日线行情数据（自动判断股票/ETF）
        ts_code: 000001.SZ / 510050.SH
        start_date: 20250101
        end_date: 20250410
        """
        # 先查本地缓存
        cached = self.cache.get_daily(ts_code, start_date, end_date, StockDaily)
        if cached is not None:
            return cached

        # 判断是否ETF（代码以51/15/16/18/51开头的通常为ETF）
        is_etf = self._is_etf(ts_code)

        if is_etf:
            return self.fetch_etf_daily(ts_code, start_date, end_date)

        # 普通股票数据
        try:
            if self.ts_pro:
                return self._fetch_daily_tushare(ts_code, start_date, end_date)
            return self._fetch_daily_akshare(ts_code, start_date, end_date)
        except Exception as e:
            logger.warning(f"主数据源失败 {ts_code}: {e}，尝试备用")
            try:
                if self.ts_pro:
                    return self._fetch_daily_akshare(ts_code, start_date, end_date)
                return self._fetch_daily_akshare(ts_code, start_date, end_date)
            except Exception as e2:
                logger.error(f"备用数据源也失败 {ts_code}: {e2}")
                return pd.DataFrame()

    @staticmethod
    def _is_etf(ts_code: str) -> bool:
        """判断是否ETF代码"""
        code = ts_code.split(".")[0]
        # ETF常见前缀: 51(上海ETF), 15(深圳ETF), 16(深圳LOF), 18(深圳ETF)
        return code.startswith(("51", "15", "16", "18", "56", "58"))

    def _fetch_daily_tushare(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """Tushare 数据源"""
        df = self.ts_pro.daily(
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date
        )
        df = df.rename(columns={
            "pct_chg": "change_pct",
            "vol": "vol",
            "amount": "amount",
        })
        df["trade_date"] = df["trade_date"].astype(str)
        return df

    def _fetch_daily_akshare(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """AKShare 数据源"""
        symbol = ts_code.split(".")[0]
        start_fmt = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:]}"
        end_fmt = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:]}"

        df = ak.stock_zh_a_hist(
            symbol=symbol,
            period="daily",
            start_date=start_fmt,
            end_date=end_fmt,
            adjust="qfq"  # 前复权
        )
        df = df.rename(columns={
            "日期": "trade_date",
            "开盘": "open",
            "收盘": "close",
            "最高": "high",
            "最低": "low",
            "涨跌幅": "change_pct",
            "成交量": "vol",
            "成交额": "amount",
            "换手率": "turnover_rate",
        })
        df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.strftime("%Y%m%d")
        df["ts_code"] = ts_code
        df["pre_close"] = df["close"].shift(1)
        return df[["ts_code", "trade_date", "open", "high", "low", "close",
                    "pre_close", "change_pct", "vol", "amount", "turnover_rate"]]

    def save_daily_data(self, df: pd.DataFrame) -> int:
        """将行情数据保存到数据库（批量写入优化版）"""
        if df.empty:
            return 0

        # 1. 批量查询已有记录
        ts_codes = df["ts_code"].unique().tolist()
        trade_dates = df["trade_date"].astype(str).unique().tolist()

        existing = set()
        if ts_codes and trade_dates:
            rows = (
                self.db.query(StockDaily.ts_code, StockDaily.trade_date)
                .filter(
                    StockDaily.ts_code.in_(ts_codes),
                    StockDaily.trade_date.in_(trade_dates),
                )
                .all()
            )
            existing = {(r[0], str(r[1])) for r in rows}

        # 2. 批量构建新记录
        new_records = []
        for _, row in df.iterrows():
            key = (row.get("ts_code"), str(row.get("trade_date")))
            if key in existing:
                continue
            new_records.append(StockDaily(
                ts_code=row.get("ts_code"),
                trade_date=str(row.get("trade_date")),
                open=row.get("open"),
                high=row.get("high"),
                low=row.get("low"),
                close=row.get("close"),
                pre_close=row.get("pre_close"),
                change_pct=row.get("change_pct"),
                vol=row.get("vol"),
                amount=row.get("amount"),
                turnover_rate=row.get("turnover_rate"),
            ))

        # 3. 批量插入
        if new_records:
            self.db.bulk_save_objects(new_records)
            self.db.commit()

        logger.info(f"保存日线数据 {len(new_records)} 条（跳过已有 {len(existing)} 条）")
        return len(new_records)

    def calculate_ma(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算均线指标"""
        if df.empty or len(df) < 5:
            return df
        df = df.sort_values("trade_date")
        for period in [5, 10, 20, 60]:
            if len(df) >= period:
                df[f"ma{period}"] = df["close"].rolling(window=period).mean()
        return df

    def get_realtime_quote(self, ts_codes: List[str]) -> List[dict]:
        """获取实时行情（30秒缓存）"""
        import time as _time
        now = _time.time()
        
        # 检查缓存是否有效
        if (DataService._realtime_cache is not None and 
            now - DataService._realtime_cache_time < DataService._realtime_cache_ttl):
            df = DataService._realtime_cache
        else:
            try:
                df = ak.stock_zh_a_spot_em()
                DataService._realtime_cache = df
                DataService._realtime_cache_time = now
            except Exception as e:
                logger.error(f"获取实时行情失败: {e}")
                return []
        
        try:
            filtered = df[df["代码"].isin([c.split(".")[0] for c in ts_codes])]
            results = []
            for _, row in filtered.iterrows():
                code = str(row.get("代码", ""))
                ts_code = next((c for c in ts_codes if c.startswith(code)), code)
                results.append({
                    "ts_code": ts_code,
                    "name": row.get("名称", ""),
                    "price": float(row.get("最新价", 0)),
                    "change_pct": float(row.get("涨跌幅", 0)),
                    "vol": float(row.get("成交量", 0)),
                    "amount": float(row.get("成交额", 0)),
                    "high": float(row.get("最高", 0)),
                    "low": float(row.get("最低", 0)),
                    "open": float(row.get("今开", 0)),
                })
            return results
        except Exception as e:
            logger.error(f"解析实时行情失败: {e}")
            return []
