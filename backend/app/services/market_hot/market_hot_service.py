"""
QuantWeave — 市场热度数据服务

四大模块：
  1. 涨停&连板榜  (limit_list_d)
  2. 龙虎榜       (top_list + top_inst + hm_detail)
  3. 资金流向     (moneyflow_hsgt + moneyflow)
  4. 市场情绪聚合 dashboard

数据源：Tushare Pro（主）+ AKShare（备用）
"""
import os
import time
import threading
import tushare as ts
import akshare as ak
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from loguru import logger
from typing import Dict, List, Optional
from functools import lru_cache


class MarketHotService:
    """市场热度数据服务 — 涨停连板/龙虎榜/资金流/情绪聚合"""

    # 缓存 TTL（秒）
    CACHE_TTL = {
        "limit_list": 3600,      # 涨停榜 1小时（Tushare 限频 1次/小时）
        "top_list": 60,          # 龙虎榜 1分钟
        "moneyflow_hsgt": 60,    # 北向资金 1分钟
        "moneyflow": 60,         # 个股资金流 1分钟
    }

    def __init__(self, tushare_token: str = None):
        if tushare_token:
            ts.set_token(tushare_token)
        self.pro = ts.pro_api()

        # 内存缓存 {key: (timestamp, data)} — 线程安全
        self._cache: Dict[str, tuple] = {}
        self._cache_lock = threading.Lock()

    def _get_cached(self, key: str) -> Optional[dict]:
        """读缓存（线程安全）"""
        with self._cache_lock:
            if key in self._cache:
                ts_cached, data = self._cache[key]
                ttl = self.CACHE_TTL.get(key.split(":")[0], 300)
                if time.time() - ts_cached < ttl:
                    return data
        return None

    def _set_cached(self, key: str, data):
        """写缓存（线程安全）"""
        with self._cache_lock:
            self._cache[key] = (time.time(), data)

    def clear_cache(self, prefix: str = None):
        """
        清除缓存
        
        Args:
            prefix: 按前缀清除，如 "limit_list"、"top_list"、"moneyflow"、"sentiment"
                    为 None 时清除全部
        """
        with self._cache_lock:
            if prefix is None:
                self._cache.clear()
                logger.info("MarketHotService 缓存已全部清除")
            else:
                keys_to_remove = [k for k in self._cache if k.startswith(prefix)]
                for k in keys_to_remove:
                    del self._cache[k]
                logger.info(f"MarketHotService 缓存已清除: {prefix} ({len(keys_to_remove)} 项)")

    def cache_status(self) -> Dict:
        """返回当前缓存状态"""
        with self._cache_lock:
            status = {}
            now = time.time()
            for key, (ts_cached, data) in self._cache.items():
                prefix = key.split(":")[0]
                ttl = self.CACHE_TTL.get(prefix, 300)
                remaining = max(0, round(ttl - (now - ts_cached)))
                status[key] = {
                    "ttl_remaining_sec": remaining,
                    "expired": remaining <= 0,
                }
            return {
                "total_entries": len(status),
                "entries": status,
            }

    # ================================================================
    # 1. 涨停&连板榜
    # ================================================================
    def get_limit_list(self, trade_date: str = None) -> Dict:
        """
        获取涨停板明细 + 连板统计

        Tushare limit_list_d（1次/小时）
        返回: { date, limit_up_list, consecutive_stats, summary }
        """
        if trade_date is None:
            trade_date = datetime.now().strftime("%Y%m%d")

        cache_key = f"limit_list:{trade_date}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        try:
            # Tushare limit_list_d
            df = self.pro.limit_list_d(trade_date=trade_date)

            if df is None or df.empty:
                # 尝试前一个交易日
                prev = (datetime.strptime(trade_date, "%Y%m%d") - timedelta(days=1)).strftime("%Y%m%d")
                df = self.pro.limit_list_d(trade_date=prev)
                trade_date = prev

            if df is None or df.empty:
                # 尝试 AKShare 兜底
                return self._get_limit_list_akshare(trade_date)

            # 解析涨停明细
            limit_up_list = self._parse_limit_list_df(df)

            # 连板统计
            consecutive_stats = self._calc_consecutive_stats(df, limit_up_list)

            result = {
                "date": trade_date,
                "limit_up_list": limit_up_list,
                "consecutive_stats": consecutive_stats,
                "summary": {
                    "total_limit_up": len(limit_up_list),
                    "max_consecutive": consecutive_stats.get("max_days", 0) if consecutive_stats else 0,
                    "consecutive_2_plus": sum(1 for s in consecutive_stats.get("by_days", {}).values()
                                              if int(s.get("days", 0)) >= 2) if consecutive_stats else 0,
                }
            }

            self._set_cached(cache_key, result)
            return result

        except Exception as e:
            logger.warning(f"Tushare limit_list_d 失败: {e}")
            return self._get_limit_list_akshare(trade_date)

    def _parse_limit_list_df(self, df: pd.DataFrame) -> List[Dict]:
        """解析 Tushare limit_list_d DataFrame"""
        result = []
        # limit_list_d 关键列: ts_code, name, close, pct_chg, amount, limit_amount, fd_amount, first_time, last_time, limit_times
        col_map = {
            "ts_code": "ts_code", "name": "name", "close": "price",
            "pct_chg": "pct_chg", "amount": "amount",
            "limit_times": "limit_days", "first_time": "first_time",
            "last_time": "last_time",
        }

        for _, row in df.iterrows():
            item = {}
            for src, dst in col_map.items():
                if src in df.columns:
                    val = row[src]
                    if pd.isna(val):
                        item[dst] = None
                    elif isinstance(val, (np.integer,)):
                        item[dst] = int(val)
                    elif isinstance(val, (np.floating,)):
                        item[dst] = round(float(val), 2)
                    else:
                        item[dst] = str(val) if val else None

            # 封板强度 = 封单成交额 / 总成交额
            if "limit_amount" in df.columns and "amount" in df.columns:
                total_amt = row.get("amount", 0) or 0
                limit_amt = row.get("limit_amount", 0) or 0
                item["seal_ratio"] = round(limit_amt / total_amt * 100, 1) if total_amt > 0 else 0
            else:
                item["seal_ratio"] = None

            item.setdefault("limit_days", 1)
            result.append(item)

        # 按连板天数降序、成交额降序
        result.sort(key=lambda x: (-(x.get("limit_days") or 1), -(x.get("amount") or 0)))
        return result

    def _calc_consecutive_stats(self, df: pd.DataFrame, limit_list: List[Dict]) -> Dict:
        """连板统计"""
        if not limit_list:
            return {}

        by_days = {}
        for item in limit_list:
            days = item.get("limit_days") or 1
            key = f"{days}连板" if days > 1 else "首板"
            if key not in by_days:
                by_days[key] = {"days": days, "count": 0, "stocks": []}
            by_days[key]["count"] += 1
            by_days[key]["stocks"].append({
                "ts_code": item.get("ts_code"),
                "name": item.get("name"),
                "price": item.get("price"),
            })

        max_days = max((item.get("limit_days") or 1 for item in limit_list), default=0)

        return {
            "max_days": max_days,
            "by_days": by_days,
        }

    def _get_limit_list_akshare(self, trade_date: str) -> Dict:
        """AKShare 兜底获取涨停数据"""
        try:
            # stock_zt_pool_em — 东方财富涨停板
            date_fmt = f"{trade_date[:4]}{trade_date[4:6]}{trade_date[6:]}"
            df = ak.stock_zt_pool_em(date=date_fmt)

            if df is None or df.empty:
                return {"date": trade_date, "limit_up_list": [], "consecutive_stats": {}, "summary": {"total_limit_up": 0}}

            limit_list = []
            for _, row in df.iterrows():
                item = {
                    "ts_code": str(row.get("代码", "")),
                    "name": str(row.get("名称", "")),
                    "price": float(row.get("最新价", 0)),
                    "pct_chg": float(row.get("涨跌幅", 0)),
                    "amount": float(row.get("成交额", 0)),
                    "limit_days": int(row.get("连板数", 1)) if "连板数" in df.columns else 1,
                    "first_time": str(row.get("首次封板时间", "")) if "首次封板时间" in df.columns else None,
                    "last_time": str(row.get("最后封板时间", "")) if "最后封板时间" in df.columns else None,
                    "seal_ratio": None,
                }
                limit_list.append(item)

            limit_list.sort(key=lambda x: (-(x.get("limit_days") or 1), -(x.get("amount") or 0)))

            consecutive_stats = self._calc_consecutive_stats(df, limit_list)

            result = {
                "date": trade_date,
                "limit_up_list": limit_list,
                "consecutive_stats": consecutive_stats,
                "summary": {
                    "total_limit_up": len(limit_list),
                    "max_consecutive": consecutive_stats.get("max_days", 0) if consecutive_stats else 0,
                },
                "source": "akshare",
            }
            return result

        except Exception as e:
            logger.warning(f"AKShare 涨停数据也失败: {e}")
            return {
                "date": trade_date,
                "limit_up_list": [],
                "consecutive_stats": {},
                "summary": {"total_limit_up": 0},
                "error": str(e),
            }

    # ================================================================
    # 2. 龙虎榜
    # ================================================================
    def get_top_list(self, trade_date: str = None) -> Dict:
        """
        获取龙虎榜数据

        Tushare top_list + top_inst + hm_detail
        """
        if trade_date is None:
            trade_date = datetime.now().strftime("%Y%m%d")

        cache_key = f"top_list:{trade_date}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        try:
            # 龙虎榜上榜明细
            df_top = self.pro.top_list(trade_date=trade_date)

            if df_top is None or df_top.empty:
                prev = (datetime.strptime(trade_date, "%Y%m%d") - timedelta(days=1)).strftime("%Y%m%d")
                df_top = self.pro.top_list(trade_date=prev)
                trade_date = prev

            if df_top is None or df_top.empty:
                return self._get_top_list_akshare(trade_date)

            top_list = self._parse_top_list_df(df_top)

            # 龙虎榜机构明细
            inst_detail = {}
            try:
                df_inst = self.pro.top_inst(trade_date=trade_date)
                if df_inst is not None and not df_inst.empty:
                    inst_detail = self._parse_inst_detail(df_inst, top_list)
            except Exception as e:
                logger.warning(f"top_inst 获取失败: {e}")

            # 游资明细
            hm_detail = {}
            try:
                df_hm = self.pro.hm_detail(trade_date=trade_date)
                if df_hm is not None and not df_hm.empty:
                    hm_detail = self._parse_hm_detail(df_hm, top_list)
            except Exception as e:
                logger.warning(f"hm_detail 获取失败: {e}")

            result = {
                "date": trade_date,
                "top_list": top_list,
                "institutional": inst_detail,
                "hot_money": hm_detail,
                "summary": {
                    "total_stocks": len(top_list),
                    "total_net_buy": sum(t.get("net_buy", 0) for t in top_list),
                }
            }

            self._set_cached(cache_key, result)
            return result

        except Exception as e:
            logger.warning(f"Tushare top_list 失败: {e}")
            return self._get_top_list_akshare(trade_date)

    def _parse_top_list_df(self, df: pd.DataFrame) -> List[Dict]:
        """解析龙虎榜 DataFrame"""
        result = []
        for _, row in df.iterrows():
            item = {
                "ts_code": self._safe_str(row.get("ts_code")),
                "name": self._safe_str(row.get("name")),
                "close": self._safe_float(row.get("close")),
                "pct_chg": self._safe_float(row.get("pct_chg")),
                "reason": self._safe_str(row.get("reason")),
                "buy_amount": self._safe_float(row.get("buy_amount"), 0),
                "sell_amount": self._safe_float(row.get("sell_amount"), 0),
                "net_buy": self._safe_float(row.get("net_amount"), 0),
                "buy_broker": self._safe_str(row.get("broker_buy")),
                "sell_broker": self._safe_str(row.get("broker_sell")),
            }
            # 补充 net_buy
            if item["net_buy"] == 0 and item["buy_amount"] > 0:
                item["net_buy"] = round(item["buy_amount"] - item["sell_amount"], 2)
            result.append(item)

        result.sort(key=lambda x: -abs(x.get("net_buy", 0)))
        return result

    def _parse_inst_detail(self, df_inst: pd.DataFrame, top_list: List[Dict]) -> Dict:
        """解析机构明细 — 按股票汇总"""
        by_stock = {}
        for _, row in df_inst.iterrows():
            code = self._safe_str(row.get("ts_code"))
            if code not in by_stock:
                by_stock[code] = {"buy": 0, "sell": 0, "net": 0, "details": []}
            buy = self._safe_float(row.get("buy"), 0)
            sell = self._safe_float(row.get("sell"), 0)
            by_stock[code]["buy"] += buy
            by_stock[code]["sell"] += sell
            by_stock[code]["net"] += (buy - sell)
            by_stock[code]["details"].append({
                "exalter": self._safe_str(row.get("exalter")),
                "buy": buy,
                "sell": sell,
                "net": round(buy - sell, 2),
            })
        return by_stock

    def _parse_hm_detail(self, df_hm: pd.DataFrame, top_list: List[Dict]) -> Dict:
        """解析游资明细 — 按营业部汇总"""
        by_broker = {}
        for _, row in df_hm.iterrows():
            broker = self._safe_str(row.get("exalter"))
            if broker not in by_broker:
                by_broker[broker] = {"buy": 0, "sell": 0, "net": 0, "stocks": []}
            buy = self._safe_float(row.get("buy"), 0)
            sell = self._safe_float(row.get("sell"), 0)
            by_broker[broker]["buy"] += buy
            by_broker[broker]["sell"] += sell
            by_broker[broker]["net"] += (buy - sell)
            by_broker[broker]["stocks"].append({
                "ts_code": self._safe_str(row.get("ts_code")),
                "name": self._safe_str(row.get("name")),
                "buy": buy,
                "sell": sell,
            })
        # 按净买入额排序取前20
        sorted_brokers = sorted(by_broker.items(), key=lambda x: -abs(x[1]["net"]))[:20]
        return {k: v for k, v in sorted_brokers}

    def _get_top_list_akshare(self, trade_date: str) -> Dict:
        """AKShare 兜底获取龙虎榜"""
        try:
            date_str = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}"
            df = ak.stock_lhb_detail_em(start_date=date_str, end_date=date_str)

            if df is None or df.empty:
                return {"date": trade_date, "top_list": [], "institutional": {}, "hot_money": {},
                        "summary": {"total_stocks": 0}}

            top_list = []
            for _, row in df.iterrows():
                top_list.append({
                    "ts_code": str(row.get("代码", "")),
                    "name": str(row.get("名称", "")),
                    "close": 0,
                    "pct_chg": float(row.get("涨跌幅", 0)) if "涨跌幅" in df.columns else 0,
                    "reason": str(row.get("上榜原因", "")) if "上榜原因" in df.columns else "",
                    "buy_amount": float(row.get("买入额", 0)) if "买入额" in df.columns else 0,
                    "sell_amount": float(row.get("卖出额", 0)) if "卖出额" in df.columns else 0,
                    "net_buy": 0,
                })

            result = {
                "date": trade_date,
                "top_list": top_list,
                "institutional": {},
                "hot_money": {},
                "summary": {"total_stocks": len(top_list)},
                "source": "akshare",
            }
            return result

        except Exception as e:
            logger.warning(f"AKShare 龙虎榜失败: {e}")
            return {"date": trade_date, "top_list": [], "institutional": {}, "hot_money": {},
                    "summary": {"total_stocks": 0}, "error": str(e)}

    # ================================================================
    # 3. 资金流向
    # ================================================================
    def get_moneyflow(self, days: int = 5) -> Dict:
        """
        获取北向资金 + 个股资金流

        Tushare moneyflow_hsgt + moneyflow
        """
        cache_key = f"moneyflow:{days}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=days * 2)).strftime("%Y%m%d")

        result = {
            "period": f"{start_date} ~ {end_date}",
            "northbound": {},
            "top_inflow": [],
            "top_outflow": [],
        }

        # 北向资金
        try:
            df_nb = self.pro.moneyflow_hsgt(start_date=start_date, end_date=end_date)
            if df_nb is not None and not df_nb.empty:
                df_nb = df_nb.sort_values("trade_date", ascending=False)
                northbound = []
                for _, row in df_nb.iterrows():
                    northbound.append({
                        "date": self._safe_str(row.get("trade_date")),
                        "north_money": round(self._safe_float(row.get("north_money"), 0) / 10000, 2),  # 万元→亿元
                        "north_buy": round(self._safe_float(row.get("north_buy"), 0) / 10000, 2),
                        "north_sell": round(self._safe_float(row.get("north_sell"), 0) / 10000, 2),
                        "sgt_money": round(self._safe_float(row.get("sgt_money"), 0) / 10000, 2),
                        "hgt_money": round(self._safe_float(row.get("hgt_money"), 0) / 10000, 2),
                    })
                result["northbound"] = {
                    "latest": northbound[0] if northbound else {},
                    "history": northbound,
                    "total_net": sum(n.get("north_money", 0) for n in northbound),
                    "avg_daily": round(sum(n.get("north_money", 0) for n in northbound) / max(len(northbound), 1), 2),
                }
        except Exception as e:
            logger.warning(f"moneyflow_hsgt 失败: {e}")

        # 个股资金流 TOP
        try:
            # 取最近一天
            df_mf = self.pro.moneyflow(trade_date=end_date)
            if df_mf is not None and not df_mf.empty:
                # 净流入TOP20
                df_mf["net_mf"] = df_mf["buy_elg_amount"] - df_mf["sell_elg_amount"]
                top_in = df_mf.nlargest(20, "net_mf")
                top_out = df_mf.nsmallest(20, "net_mf")

                result["top_inflow"] = self._parse_moneyflow_df(top_in)
                result["top_outflow"] = self._parse_moneyflow_df(top_out)
        except Exception as e:
            logger.warning(f"moneyflow 个股资金流失败: {e}")

        self._set_cached(cache_key, result)
        return result

    def _parse_moneyflow_df(self, df: pd.DataFrame) -> List[Dict]:
        """解析个股资金流 DataFrame"""
        result = []
        for _, row in df.iterrows():
            result.append({
                "ts_code": self._safe_str(row.get("ts_code")),
                "name": self._safe_str(row.get("name")) if "name" in df.columns else "",
                "buy_amount": self._safe_float(row.get("buy_elg_amount"), 0),
                "sell_amount": self._safe_float(row.get("sell_elg_amount"), 0),
                "net_mf": self._safe_float(row.get("net_mf"), 0),
            })
        return result

    # ================================================================
    # 4. 市场情绪聚合 Dashboard
    # ================================================================
    def get_sentiment_dashboard(self) -> Dict:
        """
        市场情绪聚合 — 汇总以上三个模块的核心指标

        轻量级，不重复调用已有的 heavy API
        """
        cache_key = "sentiment_dashboard"
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        result = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "limit_summary": {},
            "top_list_summary": {},
            "moneyflow_summary": {},
        }

        # 涨停概况
        try:
            limit_data = self.get_limit_list()
            if limit_data and "summary" in limit_data:
                result["limit_summary"] = {
                    "total_limit_up": limit_data["summary"].get("total_limit_up", 0),
                    "max_consecutive": limit_data["summary"].get("max_consecutive", 0),
                    "consecutive_2_plus": limit_data["summary"].get("consecutive_2_plus", 0),
                    "date": limit_data.get("date"),
                }
        except Exception as e:
            logger.warning(f"情绪聚合-涨停失败: {e}")

        # 龙虎榜概况
        try:
            top_data = self.get_top_list()
            if top_data and "summary" in top_data:
                result["top_list_summary"] = {
                    "total_stocks": top_data["summary"].get("total_stocks", 0),
                    "total_net_buy": round(top_data["summary"].get("total_net_buy", 0), 2),
                    "hot_money_count": len(top_data.get("hot_money", {})),
                    "institutional_count": len(top_data.get("institutional", {})),
                }
        except Exception as e:
            logger.warning(f"情绪聚合-龙虎榜失败: {e}")

        # 资金流向概况
        try:
            mf_data = self.get_moneyflow(days=3)
            if mf_data and "northbound" in mf_data:
                nb = mf_data["northbound"]
                result["moneyflow_summary"] = {
                    "latest_flow": nb.get("latest", {}).get("north_money", 0),
                    "avg_daily": nb.get("avg_daily", 0),
                    "total_net": nb.get("total_net", 0),
                }
        except Exception as e:
            logger.warning(f"情绪聚合-资金流失败: {e}")

        # 综合情绪评分
        score = 50
        ls = result["limit_summary"]
        ms = result["moneyflow_summary"]

        if ls:
            # 涨停家数评分 (0-30分)
            limit_up = ls.get("total_limit_up", 0)
            score += min(15, limit_up / 5)
            # 连板加分 (0-10分)
            score += min(10, ls.get("max_consecutive", 0) * 2)

        if ms:
            # 北向资金评分 (0-10分)
            avg_flow = ms.get("avg_daily", 0)
            if avg_flow > 0:
                score += min(10, avg_flow / 5)
            else:
                score += max(-10, avg_flow / 5)

        score = max(0, min(100, round(score)))

        # 情绪标签
        if score >= 75:
            label = "🔥 极度亢奋"
        elif score >= 60:
            label = "☀️ 偏强"
        elif score >= 40:
            label = "🌤️ 中性"
        elif score >= 25:
            label = "🍂 偏弱"
        else:
            label = "❄️ 极度低迷"

        result["sentiment_score"] = score
        result["sentiment_label"] = label

        self._set_cached(cache_key, result)
        return result

    # ================================================================
    # 工具方法
    # ================================================================
    @staticmethod
    def _safe_float(val, default=0.0) -> float:
        if val is None or (isinstance(val, float) and np.isnan(val)):
            return default
        try:
            return round(float(val), 2)
        except (ValueError, TypeError):
            return default

    @staticmethod
    def _safe_str(val) -> str:
        if val is None or (isinstance(val, float) and np.isnan(val)):
            return ""
        return str(val)
