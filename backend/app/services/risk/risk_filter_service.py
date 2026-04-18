"""
QuantWeave - 风控排雷服务（完整版）

6大过滤维度：
1. ST/*ST 排除 — 股票名称含ST直接排除
2. 业绩预告排雷 — 首亏/预减/续亏 排除
3. 财报披露窗口 — 未来7天有财报披露 → 降分标记
4. 大股东减持 — 近30天减持>1% → 排除
5. 连续亏损 — 近2季净利润为负 → 排除
6. 高负债率 — 资产负债率>80%（非金融） → 降分

数据源：Tushare Pro API
缓存策略：风控数据存 stock_risk_flags 表，当日有效，避免重复请求
"""

import os
import sqlite3
import json
import time
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from loguru import logger

import pandas as pd
from dotenv import load_dotenv

# 确保加载 .env（Pydantic Settings 不会注入到 os.environ）
load_dotenv(Path(__file__).resolve().parent.parent.parent.parent / ".env")


# ============================================================================
# 数据库表结构
# ============================================================================

RISK_FLAGS_DDL = """
CREATE TABLE IF NOT EXISTS stock_risk_flags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_code TEXT NOT NULL,
    flag_date TEXT NOT NULL,
    risk_level TEXT NOT NULL DEFAULT 'safe',
    -- 硬性排除项（一票否决）
    is_st INTEGER DEFAULT 0,
    is_loss_warning INTEGER DEFAULT 0,
    loss_warning_type TEXT DEFAULT '',
    is_heavy_reduction INTEGER DEFAULT 0,
    reduction_detail TEXT DEFAULT '',
    is_consecutive_loss INTEGER DEFAULT 0,
    -- 软性降分项
    has_upcoming_report INTEGER DEFAULT 0,
    report_date TEXT DEFAULT '',
    is_high_debt INTEGER DEFAULT 0,
    debt_ratio REAL DEFAULT 0,
    -- 摘要
    flags TEXT DEFAULT '[]',
    summary TEXT DEFAULT '',
    raw_data TEXT DEFAULT '{}',
    updated_at TEXT DEFAULT (datetime('now')),
    UNIQUE(ts_code, flag_date)
);
"""

RISK_FILTER_CACHE_DDL = """
CREATE INDEX IF NOT EXISTS idx_risk_flags_date ON stock_risk_flags(flag_date);
CREATE INDEX IF NOT EXISTS idx_risk_flags_ts_code ON stock_risk_flags(ts_code);
"""


def _ensure_risk_tables(db_path: Path):
    """确保风控表存在"""
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(RISK_FLAGS_DDL)
        # executescript 支持多条SQL语句
        conn.executescript(RISK_FILTER_CACHE_DDL)
        conn.commit()
    finally:
        conn.close()


class RiskFilterService:
    """风控排雷服务 — 前置于选股流水线"""

    # Tushare API 频率控制（每分钟不超过200次）
    _last_api_call = 0
    _api_interval = 0.35  # 秒

    def __init__(self, db_path: Path = None):
        if db_path is None:
            db_path = Path(__file__).resolve().parent.parent.parent.parent / "quantweave.db"
        self._db_path = db_path
        _ensure_risk_tables(db_path)

        # 初始化 Tushare
        self._pro = None
        self._init_tushare()

    def _init_tushare(self):
        """初始化 Tushare Pro API"""
        try:
            import tushare as ts
            token = os.getenv("TUSHARE_TOKEN", "")
            if token:
                ts.set_token(token)
                self._pro = ts.pro_api()
                logger.info("🛡️ 风控服务 Tushare 已连接")
            else:
                logger.warning("TUSHARE_TOKEN 未配置，风控数据将不可用")
        except Exception as e:
            logger.warning(f"风控服务 Tushare 初始化失败: {e}")

    def _rate_limit(self):
        """API 频率控制"""
        now = time.time()
        elapsed = now - RiskFilterService._last_api_call
        if elapsed < RiskFilterService._api_interval:
            time.sleep(RiskFilterService._api_interval - elapsed)
        RiskFilterService._last_api_call = time.time()

    def _safe_api_call(self, func, **kwargs) -> Optional[pd.DataFrame]:
        """安全的 API 调用（带频率控制和错误处理）"""
        if self._pro is None:
            return None
        self._rate_limit()
        try:
            df = func(**kwargs)
            return df if df is not None and not df.empty else None
        except Exception as e:
            logger.warning(f"Tushare API 调用失败: {e}")
            return None

    # ========================================================================
    # 核心：批量风控扫描
    # ========================================================================

    def scan_risks(self, ts_codes: List[str], force: bool = False) -> Dict[str, dict]:
        """
        批量扫描股票风控风险

        Args:
            ts_codes: 股票代码列表
            force: 是否强制重新扫描（忽略缓存）

        Returns:
            {ts_code: {risk_level, flags, summary, ...}}
        """
        today = datetime.now().strftime("%Y%m%d")
        results = {}

        # 1. 先查缓存
        cached = self._load_cache(ts_codes, today) if not force else {}
        uncached = [c for c in ts_codes if c not in cached]

        if cached:
            logger.info(f"🛡️ 风控缓存命中: {len(cached)}/{len(ts_codes)}")

        if uncached:
            logger.info(f"🛡️ 风控扫描: {len(uncached)} 只股票...")

            # 2. 批量获取各维度数据
            st_flags = self._check_st_batch(uncached)
            forecast_flags = self._check_forecast_batch(uncached)
            disclosure_flags = self._check_disclosure_batch(uncached, today)
            reduction_flags = self._check_reduction_batch(uncached)
            financial_flags = self._check_financial_batch(uncached)

            # 3. 组装结果
            for ts_code in uncached:
                flags = []
                risk_level = "safe"
                raw = {}

                # --- 硬性排除项 ---
                # ST
                st = st_flags.get(ts_code, {})
                if st.get("is_st"):
                    flags.append({"type": "block", "code": "ST", "msg": f"ST股票: {st.get('name', '')}", "level": "critical"})
                    risk_level = "block"
                raw["st"] = st

                # 业绩预告
                fc = forecast_flags.get(ts_code, {})
                if fc.get("is_loss_warning"):
                    flags.append({"type": "block", "code": "LOSS_WARNING", "msg": f"业绩预告: {fc.get('type', '')}", "level": "critical"})
                    risk_level = "block"
                raw["forecast"] = fc

                # 大股东减持
                rd = reduction_flags.get(ts_code, {})
                if rd.get("is_heavy_reduction"):
                    flags.append({"type": "block", "code": "REDUCTION", "msg": f"大股东减持: {rd.get('detail', '')}", "level": "critical"})
                    risk_level = "block"
                raw["reduction"] = rd

                # 连续亏损
                fn = financial_flags.get(ts_code, {})
                if fn.get("is_consecutive_loss"):
                    flags.append({"type": "block", "code": "CONSECUTIVE_LOSS", "msg": "近2季度净利润为负", "level": "critical"})
                    risk_level = "block"
                raw["financial"] = fn

                # --- 软性降分项 ---
                # 财报披露窗口
                dc = disclosure_flags.get(ts_code, {})
                if dc.get("has_upcoming_report"):
                    flags.append({"type": "warning", "code": "REPORT_SOON", "msg": f"财报窗口: {dc.get('report_date', '')}披露", "level": "warning"})
                    if risk_level == "safe":
                        risk_level = "warning"
                raw["disclosure"] = dc

                # 高负债率
                if fn.get("is_high_debt"):
                    flags.append({"type": "warning", "code": "HIGH_DEBT", "msg": f"资产负债率: {fn.get('debt_ratio', 0):.1f}%", "level": "warning"})
                    if risk_level == "safe":
                        risk_level = "warning"

                summary = "；".join(f["msg"] for f in flags) if flags else "无风险"
                result = {
                    "risk_level": risk_level,
                    "is_st": 1 if st.get("is_st") else 0,
                    "is_loss_warning": 1 if fc.get("is_loss_warning") else 0,
                    "loss_warning_type": fc.get("type", ""),
                    "is_heavy_reduction": 1 if rd.get("is_heavy_reduction") else 0,
                    "reduction_detail": rd.get("detail", ""),
                    "is_consecutive_loss": 1 if fn.get("is_consecutive_loss") else 0,
                    "has_upcoming_report": 1 if dc.get("has_upcoming_report") else 0,
                    "report_date": dc.get("report_date", ""),
                    "is_high_debt": 1 if fn.get("is_high_debt") else 0,
                    "debt_ratio": fn.get("debt_ratio", 0),
                    "flags": flags,
                    "summary": summary,
                    "raw_data": raw,
                }
                results[ts_code] = result
                self._save_cache(ts_code, today, result)

        # 合并缓存
        results.update(cached)

        # 统计
        blocked = sum(1 for r in results.values() if r["risk_level"] == "block")
        warned = sum(1 for r in results.values() if r["risk_level"] == "warning")
        safe = sum(1 for r in results.values() if r["risk_level"] == "safe")
        logger.info(f"🛡️ 风控扫描完成: {len(results)}只 → 排除{blocked} / 警告{warned} / 安全{safe}")

        return results

    def filter_stocks(self, ts_codes: List[str]) -> Tuple[List[str], Dict[str, dict]]:
        """
        过滤股票：返回安全股票列表 + 全部风控数据

        Returns:
            (safe_codes, all_risk_data)
        """
        risk_data = self.scan_risks(ts_codes)
        safe_codes = [c for c in ts_codes if risk_data.get(c, {}).get("risk_level") != "block"]
        return safe_codes, risk_data

    # ========================================================================
    # 维度1: ST 检查（本地数据库即可）
    # ========================================================================

    def _check_st_batch(self, ts_codes: List[str]) -> Dict[str, dict]:
        """批量检查 ST 股票"""
        results = {}
        conn = sqlite3.connect(str(self._db_path))
        try:
            placeholders = ",".join(["?"] * len(ts_codes))
            rows = conn.execute(
                f"SELECT ts_code, name FROM stocks WHERE ts_code IN ({placeholders})",
                ts_codes,
            ).fetchall()
            for ts_code, name in rows:
                is_st = 0
                if name and ("ST" in name or "st" in name.lower()):
                    is_st = 1
                results[ts_code] = {"is_st": is_st, "name": name or ""}
        finally:
            conn.close()
        return results

    # ========================================================================
    # 维度2: 业绩预告（Tushare forecast）
    # ========================================================================

    def _check_forecast_batch(self, ts_codes: List[str]) -> Dict[str, dict]:
        """批量检查业绩预告（首亏/预减/续亏）"""
        results = {c: {"is_loss_warning": False, "type": ""} for c in ts_codes}

        if self._pro is None:
            return results

        # 获取当年业绩预告
        year = datetime.now().year
        # 尝试当年和去年的数据
        for period in [f"{year}1231", f"{year - 1}1231", f"{year}0630", f"{year - 1}0630"]:
            df = self._safe_api_call(
                self._pro.forecast,
                ts_code=",".join(ts_codes[:50]),  # Tushare 批量限制
                period=period,
                fields="ts_code,type,p_change_min,p_change_max,summary",
            )
            if df is None:
                continue

            for _, row in df.iterrows():
                tc = row.get("ts_code", "")
                ftype = row.get("type", "")
                # 首亏 / 预减 / 续亏 / 增亏 — 排除
                bad_types = ["首亏", "预减", "续亏", "增亏"]
                if any(b in ftype for b in bad_types):
                    if tc in results and not results[tc]["is_loss_warning"]:
                        summary = row.get("summary", ftype)
                        results[tc] = {
                            "is_loss_warning": True,
                            "type": f"{ftype}（{period[:4]}年报季）",
                            "summary": summary or "",
                        }
            break  # 拿到最新一期的就行

        return results

    # ========================================================================
    # 维度3: 财报披露日期（Tushare disclosure_date）
    # ========================================================================

    def _check_disclosure_batch(self, ts_codes: List[str], today: str) -> Dict[str, dict]:
        """批量检查未来7天是否有财报披露"""
        results = {c: {"has_upcoming_report": False, "report_date": ""} for c in ts_codes}

        if self._pro is None:
            return results

        # 计算未来7天
        today_dt = datetime.strptime(today, "%Y%m%d")
        future_7 = (today_dt + timedelta(days=7)).strftime("%Y%m%d")

        year = datetime.now().year
        # 查询年报和半年报的披露日期
        for period in [f"{year}1231", f"{year - 1}1231", f"{year}0630", f"{year - 1}0630"]:
            df = self._safe_api_call(
                self._pro.disclosure_date,
                ts_code=",".join(ts_codes[:50]),
                period=period,
                fields="ts_code,actual_date,end_date,report_type",
            )
            if df is None:
                continue

            for _, row in df.iterrows():
                tc = row.get("ts_code", "")
                actual_date = str(row.get("actual_date", ""))
                if tc in results and actual_date:
                    # 检查是否在未来7天内
                    if today <= actual_date <= future_7:
                        results[tc] = {
                            "has_upcoming_report": True,
                            "report_date": actual_date,
                            "period": period,
                        }
            break  # 拿到最新一期的就行

        return results

    # ========================================================================
    # 维度4: 大股东减持（Tushare stk_holdertrade）
    # ========================================================================

    def _check_reduction_batch(self, ts_codes: List[str]) -> Dict[str, dict]:
        """批量检查近30天大股东减持"""
        results = {c: {"is_heavy_reduction": False, "detail": ""} for c in ts_codes}

        if self._pro is None:
            return results

        start_date = (datetime.now() - timedelta(days=30)).strftime("%Y%m%d")
        end_date = datetime.now().strftime("%Y%m%d")

        for batch_start in range(0, len(ts_codes), 50):
            batch = ts_codes[batch_start:batch_start + 50]
            df = self._safe_api_call(
                self._pro.stk_holdertrade,
                ts_code=",".join(batch),
                start_date=start_date,
                end_date=end_date,
                fields="ts_code,trade_date,holder_type,change_vol,change_ratio",
            )
            if df is None:
                continue

            # 只看减持（change_vol < 0），只看大股东/高管
            sell_df = df[df["change_vol"] < 0]
            for tc in batch:
                tc_sells = sell_df[sell_df["ts_code"] == tc]
                if tc_sells.empty:
                    continue
                total_ratio = tc_sells["change_ratio"].sum()
                if abs(total_ratio) >= 1.0:  # 减持超过1%
                    results[tc] = {
                        "is_heavy_reduction": True,
                        "detail": f"近30天减持{abs(total_ratio):.2f}%",
                        "total_ratio": float(abs(total_ratio)),
                        "count": len(tc_sells),
                    }

        return results

    # ========================================================================
    # 维度5+6: 财务指标（Tushare fina_indicator）
    # ========================================================================

    def _check_financial_batch(self, ts_codes: List[str]) -> Dict[str, dict]:
        """批量检查财务指标（连续亏损 + 高负债率）"""
        results = {c: {
            "is_consecutive_loss": False,
            "is_high_debt": False,
            "debt_ratio": 0,
            "net_profits": [],
        } for c in ts_codes}

        if self._pro is None:
            return results

        # 获取最近2期的利润数据
        year = datetime.now().year
        for period in [f"{year}0630", f"{year - 1}1231", f"{year - 1}0630"]:
            df = self._safe_api_call(
                self._pro.income,
                ts_code=",".join(ts_codes[:50]),
                period=period,
                fields="ts_code,period,n_income",
            )
            if df is None:
                continue

            for _, row in df.iterrows():
                tc = row.get("ts_code", "")
                if tc not in results:
                    continue
                ni = row.get("n_income")
                results[tc]["net_profits"].append({
                    "period": period,
                    "n_income": float(ni) if pd.notna(ni) else 0,
                })
            break  # 拿到最新一期利润表

        # 获取资产负债率
        for period in [f"{year}0630", f"{year - 1}1231"]:
            df = self._safe_api_call(
                self._pro.fina_indicator,
                ts_code=",".join(ts_codes[:50]),
                period=period,
                fields="ts_code,debt_to_assets",
            )
            if df is None:
                continue

            for _, row in df.iterrows():
                tc = row.get("ts_code", "")
                if tc not in results:
                    continue
                debt_ratio = row.get("debt_to_assets")
                if pd.notna(debt_ratio):
                    results[tc]["debt_ratio"] = float(debt_ratio)
                    # 非金融企业资产负债率>80%
                    if debt_ratio > 80:
                        results[tc]["is_high_debt"] = True
            break

        # 检查连续亏损
        for tc in ts_codes:
            profits = results[tc].get("net_profits", [])
            if len(profits) >= 2:
                negative_count = sum(1 for p in profits if p["n_income"] < 0)
                if negative_count >= 2:
                    results[tc]["is_consecutive_loss"] = True
            elif len(profits) == 1 and profits[0]["n_income"] < 0:
                # 只有一期数据且亏损，再查一期
                df2 = self._safe_api_call(
                    self._pro.income,
                    ts_code=tc,
                    period=f"{year - 1}1231" if profits[0]["period"] == f"{year}0630" else f"{year - 1}0630",
                    fields="ts_code,n_income",
                )
                if df2 is not None and not df2.empty:
                    prev_ni = df2.iloc[0].get("n_income")
                    if pd.notna(prev_ni) and float(prev_ni) < 0:
                        results[tc]["is_consecutive_loss"] = True

        return results

    # ========================================================================
    # 缓存管理
    # ========================================================================

    def _load_cache(self, ts_codes: List[str], flag_date: str) -> Dict[str, dict]:
        """从缓存加载风控数据"""
        results = {}
        conn = sqlite3.connect(str(self._db_path))
        try:
            placeholders = ",".join(["?"] * len(ts_codes))
            rows = conn.execute(
                f"SELECT ts_code, risk_level, is_st, is_loss_warning, loss_warning_type, "
                f"is_heavy_reduction, reduction_detail, is_consecutive_loss, "
                f"has_upcoming_report, report_date, is_high_debt, debt_ratio, "
                f"flags, summary, raw_data "
                f"FROM stock_risk_flags WHERE flag_date = ? AND ts_code IN ({placeholders})",
                [flag_date] + ts_codes,
            ).fetchall()

            for row in rows:
                tc = row[0]
                results[tc] = {
                    "risk_level": row[1],
                    "is_st": row[2],
                    "is_loss_warning": row[3],
                    "loss_warning_type": row[4] or "",
                    "is_heavy_reduction": row[5],
                    "reduction_detail": row[6] or "",
                    "is_consecutive_loss": row[7],
                    "has_upcoming_report": row[8],
                    "report_date": row[9] or "",
                    "is_high_debt": row[10],
                    "debt_ratio": row[11] or 0,
                    "flags": json.loads(row[12]) if row[12] else [],
                    "summary": row[13] or "",
                    "raw_data": json.loads(row[14]) if row[14] else {},
                }
        finally:
            conn.close()
        return results

    def _save_cache(self, ts_code: str, flag_date: str, data: dict):
        """保存风控数据到缓存"""
        conn = sqlite3.connect(str(self._db_path))
        try:
            conn.execute(
                """INSERT OR REPLACE INTO stock_risk_flags 
                (ts_code, flag_date, risk_level, is_st, is_loss_warning, loss_warning_type,
                 is_heavy_reduction, reduction_detail, is_consecutive_loss,
                 has_upcoming_report, report_date, is_high_debt, debt_ratio,
                 flags, summary, raw_data)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    ts_code, flag_date, data["risk_level"],
                    data.get("is_st", 0), data.get("is_loss_warning", 0),
                    data.get("loss_warning_type", ""),
                    data.get("is_heavy_reduction", 0), data.get("reduction_detail", ""),
                    data.get("is_consecutive_loss", 0),
                    data.get("has_upcoming_report", 0), data.get("report_date", ""),
                    data.get("is_high_debt", 0), data.get("debt_ratio", 0),
                    json.dumps(data.get("flags", []), ensure_ascii=False),
                    data.get("summary", ""),
                    json.dumps(data.get("raw_data", {}), ensure_ascii=False, default=str),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    # ========================================================================
    # 辅助方法
    # ========================================================================

    def get_risk_summary(self, ts_codes: List[str]) -> Dict[str, str]:
        """获取股票风控摘要（供前端展示）"""
        today = datetime.now().strftime("%Y%m%d")
        cached = self._load_cache(ts_codes, today)
        if len(cached) < len(ts_codes):
            risk_data = self.scan_risks(ts_codes)
        else:
            risk_data = cached

        return {
            tc: {
                "level": rd["risk_level"],
                "summary": rd["summary"],
                "flags": rd.get("flags", []),
            }
            for tc, rd in risk_data.items()
        }

    # ========================================================================
    # 全市场扫描（夜间批量）
    # ========================================================================

    def scan_full_market(self, force: bool = False) -> dict:
        """
        全市场风控扫描 — 扫描所有活跃股票并缓存结果

        设计：每天晚上慢悠悠扫一遍全市场 ~5500 只股票，
        结果存 stock_risk_flags 表，后续回测 / 选股直接查缓存。

        Returns:
            {total, blocked, warning, safe, elapsed_seconds}
        """
        t0 = time.time()
        today = datetime.now().strftime("%Y%m%d")

        # 1. 获取全量活跃股票代码
        all_codes = self._get_all_active_codes()
        total = len(all_codes)
        if total == 0:
            logger.warning("🛡️ 全市场扫描: 无活跃股票")
            return {"total": 0, "blocked": 0, "warning": 0, "safe": 0, "elapsed": 0}

        logger.info(f"🛡️ 全市场风控扫描启动: {total} 只股票, 日期={today}")

        # 2. 检查已有缓存（非强制模式）
        if not force:
            cached = self._load_cache(all_codes, today)
            uncached = [c for c in all_codes if c not in cached]
            if len(cached) == total:
                logger.info(f"🛡️ 今日已全量扫描过（{total}只），跳过")
                return self._summarize_cache(today)
            logger.info(f"🛡️ 缓存命中: {len(cached)}/{total}, 需扫描: {len(uncached)}")
        else:
            uncached = all_codes

        # 3. 分批扫描（每批200只，避免内存暴涨）
        batch_size = 200
        for i in range(0, len(uncached), batch_size):
            batch = uncached[i:i + batch_size]
            batch_num = i // batch_size + 1
            total_batches = (len(uncached) + batch_size - 1) // batch_size
            logger.info(f"🛡️ 扫描批次 {batch_num}/{total_batches}: {len(batch)} 只...")
            try:
                self.scan_risks(batch, force=True)
            except Exception as e:
                logger.error(f"🛡️ 批次 {batch_num} 扫描失败: {e}")
                continue

        elapsed = time.time() - t0
        result = self._summarize_cache(today)
        result["elapsed"] = round(elapsed, 1)

        logger.info(
            f"🛡️ 全市场扫描完成: {total}只 → "
            f"排除{result['blocked']} / 警告{result['warning']} / 安全{result['safe']} "
            f"({elapsed:.0f}s)"
        )
        return result

    def _get_all_active_codes(self) -> List[str]:
        """获取所有活跃股票代码"""
        conn = sqlite3.connect(str(self._db_path))
        try:
            rows = conn.execute(
                "SELECT ts_code FROM stocks WHERE is_active = 1"
            ).fetchall()
            return [r[0] for r in rows]
        finally:
            conn.close()

    def _summarize_cache(self, flag_date: str) -> dict:
        """汇总某日缓存的风控数据"""
        conn = sqlite3.connect(str(self._db_path))
        try:
            rows = conn.execute(
                "SELECT risk_level, COUNT(*) FROM stock_risk_flags "
                "WHERE flag_date = ? GROUP BY risk_level",
                (flag_date,),
            ).fetchall()
            stats = {"blocked": 0, "warning": 0, "safe": 0, "total": 0}
            for level, cnt in rows:
                stats["total"] += cnt
                if level in ("block", "blocked"):
                    stats["blocked"] += cnt
                elif level == "warning":
                    stats["warning"] += cnt
                else:
                    stats["safe"] += cnt
            return stats
        finally:
            conn.close()

    def load_snapshot_for_date(self, flag_date: str) -> Dict[str, str]:
        """
        加载某日全量风控快照（供回测使用）

        Returns:
            {ts_code: risk_level} — 只有 block/warning/safe
        """
        conn = sqlite3.connect(str(self._db_path))
        try:
            rows = conn.execute(
                "SELECT ts_code, risk_level FROM stock_risk_flags WHERE flag_date = ?",
                (flag_date,),
            ).fetchall()
            return {r[0]: r[1] for r in rows}
        finally:
            conn.close()

    def get_st_codes(self) -> set:
        """获取当前ST股票代码集合（本地数据库查询）"""
        conn = sqlite3.connect(str(self._db_path))
        try:
            rows = conn.execute(
                "SELECT ts_code FROM stocks WHERE is_active = 1 AND (name LIKE '%ST%' OR name LIKE '%st%')"
            ).fetchall()
            return {r[0] for r in rows}
        finally:
            conn.close()
