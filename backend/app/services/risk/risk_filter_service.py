"""
QuantWeave - 风控排雷服务（v2.5 多数据源版）

11大过滤维度：
1. ST/*ST 排除 — 名称含ST / AKShare ST列表 / Tushare stock_st
2. 业绩预告排雷 — 首亏/续亏/增亏 block; 预减按幅度: >50% block, 30%-50% warning, <30% 不处理
3. 财报披露窗口 — 未来7天有财报披露 → 降分标记
4. 大股东减持 — 近30天减持>1% → 排除
5. 连续亏损 — 近2季净利润为负 → 警告（不block，周期股正常）
6. 高负债率 — 资产负债率>80%（非金融） → 降分
7. ★退市风险预警 — 营收<1亿+净利润为负 → block（匹配真实*ST规则）
8. ★数据质量标记 — API失败标记unknown而非safe（NEW）
9. ★大幅预减预警（v2.4）— 预减>50% block, 30%-50% warning
10. ★限售股解禁（v2.5）— 未来30天有解禁，大额(>总股本2%) warning
11. ★股权质押（v2.5）— 未解押质押比例过高(>50%) warning

数据源优先级：
  1. Tushare Pro API（主源，可能因权限不足失效）
  2. AKShare 免费接口（备用，无需Token，批量性能好）
  3. 本地SQLite缓存（兜底）

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

# AKShare 备用数据源（免费，无需Token）
try:
    import akshare as ak
    _AKSHARE_AVAILABLE = True
except ImportError:
    _AKSHARE_AVAILABLE = False
    logger.warning("AKShare 未安装，风控备用数据源不可用")

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
    -- ★ 退市风险（v2.0新增）
    is_delist_risk INTEGER DEFAULT 0,
    delist_detail TEXT DEFAULT '',
    revenue_latest REAL DEFAULT 0,
    net_profit_latest REAL DEFAULT 0,
    -- ★ 数据质量（v2.0新增）
    data_quality TEXT DEFAULT 'full',
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
    """确保风控表存在（含v2.0新字段迁移）"""
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(RISK_FLAGS_DDL)
        # executescript 支持多条SQL语句
        conn.executescript(RISK_FILTER_CACHE_DDL)
        
        # v2.0 新字段迁移（安全的 ADD COLUMN，已存在则忽略）
        new_columns = [
            ("is_delist_risk", "INTEGER DEFAULT 0"),
            ("delist_detail", "TEXT DEFAULT ''"),
            ("revenue_latest", "REAL DEFAULT 0"),
            ("net_profit_latest", "REAL DEFAULT 0"),
            ("data_quality", "TEXT DEFAULT 'full'"),
        ]
        for col_name, col_type in new_columns:
            try:
                conn.execute(f"ALTER TABLE stock_risk_flags ADD COLUMN {col_name} {col_type}")
            except sqlite3.OperationalError:
                pass  # 列已存在，忽略
        
        conn.commit()
    finally:
        conn.close()


class RiskFilterService:
    """风控排雷服务 — 前置于选股流水线"""

    # Tushare API 频率控制（2100积分=100次/分钟，留余量用50次/分钟）
    _last_api_call = 0
    _api_interval = 1.2  # 秒（60/50=1.2）

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
        批量扫描股票风控风险（v2.0 多数据源版）

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

            # ===== 第一轮：AKShare 批量数据源（主源，一次全拉） =====
            ak_financial = {}
            ak_forecast = {}
            st_flags = self._check_st_batch(uncached)  # Tushare 名称匹配
            if _AKSHARE_AVAILABLE:
                logger.info("🛡️ AKShare 批量获取全市场财报数据...")
                ak_financial = self._check_financial_batch_akshare(uncached)
                ak_forecast = self._check_forecast_batch_akshare(uncached)
                # AKShare 增强 ST 检查
                st_flags = self._check_st_batch_akshare(uncached, st_flags)

            # ===== 第二轮：Tushare 补充（逐只查询，有权限后更准确） =====
            forecast_flags = self._check_forecast_batch(uncached)
            disclosure_flags = self._check_disclosure_batch(uncached, today)
            reduction_flags = self._check_reduction_batch(uncached)
            financial_flags = self._check_financial_batch(uncached)
            unlock_flags = self._check_unlock_batch(uncached)
            pledge_flags = self._check_pledge_batch(uncached)

            # ===== 第三轮：退市风险检测（合并双源数据） =====
            delist_flags = self._check_delist_risk(
                uncached, financial_flags, ak_financial
            )

            # 3. 组装结果
            for ts_code in uncached:
                flags = []
                risk_level = "safe"
                raw = {}
                data_quality = "full"  # 跟踪数据完整性

                # --- 硬性排除项 ---
                # ST
                st = st_flags.get(ts_code, {})
                if st.get("is_st"):
                    flags.append({"type": "block", "code": "ST", "msg": f"ST股票: {st.get('name', '')}", "level": "critical"})
                    risk_level = "block"
                raw["st"] = st

                # 业绩预告（Tushare 优先，AKShare 备用）
                fc = forecast_flags.get(ts_code, {})
                fc_ak = ak_forecast.get(ts_code, {})
                if not fc.get("is_loss_warning") and fc_ak.get("is_loss_warning"):
                    fc = fc_ak  # 用 AKShare 补充
                if fc.get("is_loss_warning"):
                    flags.append({"type": "block", "code": "LOSS_WARNING", "msg": f"业绩预告: {fc.get('type', '')}", "level": "critical"})
                    risk_level = "block"
                elif fc.get("is_profit_warning"):
                    # 大幅预减 warning（v2.4）
                    flags.append({"type": "warning", "code": "PROFIT_WARNING", "msg": f"业绩预警: {fc.get('type', '')}", "level": "medium"})
                    if risk_level == "safe":
                        risk_level = "warning"
                raw["forecast"] = fc

                # 大股东减持
                rd = reduction_flags.get(ts_code, {})
                if rd.get("is_heavy_reduction"):
                    flags.append({"type": "block", "code": "REDUCTION", "msg": f"大股东减持: {rd.get('detail', '')}", "level": "critical"})
                    risk_level = "block"
                raw["reduction"] = rd

                # 连续亏损（Tushare 优先，AKShare 备用）
                fn = financial_flags.get(ts_code, {})
                fn_ak = ak_financial.get(ts_code, {})
                # 合并：如果 Tushare 没数据，用 AKShare 的
                if not fn.get("net_profits") and fn_ak:
                    fn = fn_ak
                if fn.get("is_consecutive_loss"):
                    flags.append({"type": "warning", "code": "CONSECUTIVE_LOSS", "msg": "近2季度净利润为负", "level": "warning"})
                    if risk_level == "safe":
                        risk_level = "warning"
                raw["financial"] = fn

                # ★ 退市风险（v2.0新增）
                dl = delist_flags.get(ts_code, {})
                if dl.get("is_delist_risk"):
                    flags.append({"type": "block", "code": "DELIST_RISK", "msg": f"退市风险: {dl.get('detail', '')}", "level": "critical"})
                    risk_level = "block"
                raw["delist"] = dl

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

                # 限售股解禁（v2.5新增）
                uk = unlock_flags.get(ts_code, {})
                if uk.get("has_unlock"):
                    flags.append({"type": "warning", "code": "UNLOCK_SOON", "msg": f"限售解禁: {uk.get('detail', '')}", "level": "warning"})
                    if risk_level == "safe":
                        risk_level = "warning"
                raw["unlock"] = uk

                # 股权质押（v2.5新增）
                pg = pledge_flags.get(ts_code, {})
                if pg.get("is_high_pledge"):
                    flags.append({"type": "warning", "code": "HIGH_PLEDGE", "msg": f"股权质押: {pg.get('detail', '')}", "level": "warning"})
                    if risk_level == "safe":
                        risk_level = "warning"
                raw["pledge"] = pg

                # ★ 数据质量检查（v2.1修正：没预告不等于数据缺失）
                has_financial = bool(fn.get("net_profits") or fn.get("revenue"))
                # 大部分股票没有业绩预告是正常的，不算数据缺失
                if not has_financial:
                    data_quality = "partial"
                    if risk_level == "safe":
                        flags.append({"type": "warning", "code": "DATA_UNAVAILABLE", "msg": "财务数据获取失败，风控可能不完整", "level": "warning"})
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
                    "is_delist_risk": 1 if dl.get("is_delist_risk") else 0,
                    "delist_detail": dl.get("detail", ""),
                    "revenue_latest": fn.get("revenue", 0) or dl.get("revenue", 0),
                    "net_profit_latest": fn.get("net_profit", 0) or dl.get("net_profit", 0),
                    "data_quality": data_quality,
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
        delist = sum(1 for r in results.values() if r.get("is_delist_risk"))
        logger.info(f"🛡️ 风控扫描完成: {len(results)}只 → 排除{blocked}(含退市{delist}) / 警告{warned} / 安全{safe}")

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
        """批量检查业绩预告（首亏/续亏/增亏 block; 预减按幅度分级）"""
        results = {c: {"is_loss_warning": False, "type": "", "p_change": None, "severity": ""} for c in ts_codes}

        if self._pro is None:
            return results

        # 获取当年业绩预告
        year = datetime.now().year
        # 尝试当年和去年的数据，遍历所有 period 直到找到最新一期有数据的
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
                if tc not in results or results[tc]["is_loss_warning"]:
                    continue  # 已有更早的记录，跳过

                p_change = row.get("p_change_min")
                p_change_val = float(p_change) if p_change is not None and str(p_change) != 'None' else None

                # 首亏 / 续亏 / 增亏 — 直接 block
                block_types = ["首亏", "续亏", "增亏"]
                if any(b in ftype for b in block_types):
                    summary = row.get("summary", ftype)
                    results[tc] = {
                        "is_loss_warning": True,
                        "type": f"{ftype}（{period[:4]}年报季）",
                        "summary": summary or "",
                        "p_change": p_change_val,
                        "severity": "block",
                    }
                # 预减 — 按幅度分级
                elif "预减" in ftype:
                    summary = row.get("summary", ftype)
                    if p_change_val is not None and p_change_val <= -50:
                        # 大幅预减(>50%) → block
                        results[tc] = {
                            "is_loss_warning": True,
                            "type": f"{ftype}（{period[:4]}年报季，降幅{abs(p_change_val):.0f}%）",
                            "summary": summary or "",
                            "p_change": p_change_val,
                            "severity": "block",
                        }
                    elif p_change_val is not None and p_change_val <= -30:
                        # 中度预减(30%-50%) → warning
                        results[tc] = {
                            "is_loss_warning": False,
                            "is_profit_warning": True,
                            "type": f"{ftype}（{period[:4]}年报季，降幅{abs(p_change_val):.0f}%）",
                            "summary": summary or "",
                            "p_change": p_change_val,
                            "severity": "warning",
                        }
                    # 小幅预减(<30%) → 不处理

            # 注意：不 break，继续查下一个 period，因为不同股票可能在不同 period 有预告

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
        """批量检查财务指标（连续亏损 + 高负债率 + 营业收入）"""
        results = {c: {
            "is_consecutive_loss": False,
            "is_high_debt": False,
            "debt_ratio": 0,
            "net_profits": [],
            "revenue": 0,        # 营业收入（交易所退市规则用这个）
            "total_revenue": 0,   # 营业总收入（含投资收益等）
            "period": "",         # 数据对应的报告期
        } for c in ts_codes}

        if self._pro is None:
            return results

        # 获取最近几期的利润数据（按可用性排序：最新季报优先）
        year = datetime.now().year
        month = datetime.now().month
        # 动态生成报告期列表
        periods = []
        if month >= 11:
            periods = [f"{year}0930", f"{year}0630", f"{year - 1}1231"]
        elif month >= 9:
            periods = [f"{year}0630", f"{year - 1}1231", f"{year - 1}0930"]
        elif month >= 5:
            periods = [f"{year}0331", f"{year - 1}1231", f"{year - 1}0930"]
        else:
            # 1-4月：先试去年年报(可能还没出)，再Q3，再中报
            periods = [f"{year - 1}1231", f"{year - 1}0930", f"{year - 1}0630"]

        latest_period = ""
        # ⚠️ 关键：不能因为某些股票有数据就 break 整个 period 循环
        # 因为有些股票（如300295）年报数据还没入库，只有Q3数据
        # 需要：逐 period 遍历，跳过已有数据的股票，直到所有股票都有数据或 period 用完
        still_need = set(ts_codes)  # 还需要查数据的股票
        for period in periods:
            if not still_need:
                break  # 所有股票都有数据了
            # ⚠️ Tushare income API 不支持逗号分隔多代码查询（返回空DataFrame）
            # 必须逐只查询获取 revenue（营业收入，退市规则核心指标）
            for tc in list(still_need):  # 用 list() 因为循环中会修改 set
                df = self._safe_api_call(
                    self._pro.income,
                    ts_code=tc,
                    period=period,
                    fields="ts_code,period,n_income,revenue,total_revenue",
                )
                if df is None or df.empty:
                    continue
                row = df.iloc[0]
                ni = row.get("n_income")
                rev = row.get("revenue")
                total_rev = row.get("total_revenue")
                results[tc]["net_profits"].append({
                    "period": period,
                    "n_income": float(ni) if pd.notna(ni) else 0,
                })
                if pd.notna(rev):
                    results[tc]["revenue"] = float(rev)
                    results[tc]["total_revenue"] = float(total_rev) if pd.notna(total_rev) else 0
                    results[tc]["period"] = period
                    still_need.discard(tc)  # 从待查列表移除
                    latest_period = period

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
    # 维度10: 限售股解禁（Tushare share_float）
    # ========================================================================

    def _check_unlock_batch(self, ts_codes: List[str]) -> Dict[str, dict]:
        """批量检查未来30天限售股解禁"""
        results = {c: {"has_unlock": False, "detail": ""} for c in ts_codes}

        if self._pro is None:
            return results

        today = datetime.now()
        start_date = today.strftime("%Y%m%d")
        end_date = (today + timedelta(days=30)).strftime("%Y%m%d")

        for batch_start in range(0, len(ts_codes), 50):
            batch = ts_codes[batch_start:batch_start + 50]
            for tc in batch:
                df = self._safe_api_call(
                    self._pro.share_float,
                    ts_code=tc,
                    start_date=start_date,
                    end_date=end_date,
                    fields="ts_code,float_date,float_share",
                )
                if df is not None and len(df) > 0:
                    total_shares = df["float_share"].sum()
                    # 解禁股数 > 500万股 才预警（过滤小额解禁噪音）
                    if total_shares >= 500:
                        results[tc] = {
                            "has_unlock": True,
                            "detail": f"未来30天解禁{len(df)}笔，合计{total_shares/1e4:.0f}万股",
                            "unlock_count": len(df),
                            "total_shares": float(total_shares),
                        }
                self._rate_limit()

        unlock_cnt = sum(1 for c in ts_codes if results[c]["has_unlock"])
        if unlock_cnt:
            logger.info(f"🛡️ 限售解禁: {unlock_cnt}只有近期解禁")

        return results

    # ========================================================================
    # 维度11: 股权质押（Tushare pledge_detail）
    # ========================================================================

    def _check_pledge_batch(self, ts_codes: List[str]) -> Dict[str, dict]:
        """批量检查股权质押情况（未解押笔数占比）"""
        results = {c: {"is_high_pledge": False, "detail": ""} for c in ts_codes}

        if self._pro is None:
            return results

        for batch_start in range(0, len(ts_codes), 50):
            batch = ts_codes[batch_start:batch_start + 50]
            for tc in batch:
                df = self._safe_api_call(
                    self._pro.pledge_detail,
                    ts_code=tc,
                    fields="ts_code,ann_date,pledge_amount,is_release",
                )
                if df is not None and len(df) > 0:
                    total = len(df)
                    unreleased = len(df[df["is_release"] == 0])
                    if total > 0 and unreleased > 0:
                        ratio = unreleased / total
                        # 未解押占比>50% 或 未解押笔数>=5 → 预警
                        if ratio >= 0.5 or unreleased >= 5:
                            results[tc] = {
                                "is_high_pledge": True,
                                "detail": f"质押{total}笔，未解押{unreleased}笔({ratio*100:.0f}%)",
                                "total": total,
                                "unreleased": unreleased,
                                "ratio": float(ratio),
                            }
                self._rate_limit()

        pledge_cnt = sum(1 for c in ts_codes if results[c]["is_high_pledge"])
        if pledge_cnt:
            logger.info(f"🛡️ 股权质押: {pledge_cnt}只高质押预警")

        return results

    # ========================================================================
    # 缓存管理
    # ========================================================================

    def _load_cache(self, ts_codes: List[str], flag_date: str) -> Dict[str, dict]:
        """从缓存加载风控数据（兼容新旧表结构）"""
        results = {}
        conn = sqlite3.connect(str(self._db_path))
        try:
            placeholders = ",".join(["?"] * len(ts_codes))
            # 尝试读取新字段，若旧表无这些列则降级
            try:
                rows = conn.execute(
                    f"SELECT ts_code, risk_level, is_st, is_loss_warning, loss_warning_type, "
                    f"is_heavy_reduction, reduction_detail, is_consecutive_loss, "
                    f"has_upcoming_report, report_date, is_high_debt, debt_ratio, "
                    f"is_delist_risk, delist_detail, revenue_latest, net_profit_latest, "
                    f"data_quality, "
                    f"flags, summary, raw_data "
                    f"FROM stock_risk_flags WHERE flag_date = ? AND ts_code IN ({placeholders})",
                    [flag_date] + ts_codes,
                ).fetchall()
            except sqlite3.OperationalError:
                # 旧表无新列，降级查询
                rows = conn.execute(
                    f"SELECT ts_code, risk_level, is_st, is_loss_warning, loss_warning_type, "
                    f"is_heavy_reduction, reduction_detail, is_consecutive_loss, "
                    f"has_upcoming_report, report_date, is_high_debt, debt_ratio, "
                    f"flags, summary, raw_data "
                    f"FROM stock_risk_flags WHERE flag_date = ? AND ts_code IN ({placeholders})",
                    [flag_date] + ts_codes,
                ).fetchall()
                # 补齐新字段默认值
                rows = [list(r) + [0, "", 0, 0, "full"] for r in rows]

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
                    "is_delist_risk": row[12] if len(row) > 16 else 0,
                    "delist_detail": row[13] if len(row) > 16 else "",
                    "revenue_latest": row[14] if len(row) > 16 else 0,
                    "net_profit_latest": row[15] if len(row) > 16 else 0,
                    "data_quality": row[16] if len(row) > 16 else "full",
                    "flags": json.loads(row[-3]) if row[-3] else [],
                    "summary": row[-2] or "",
                    "raw_data": json.loads(row[-1]) if row[-1] else {},
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
                 is_delist_risk, delist_detail, revenue_latest, net_profit_latest,
                 data_quality,
                 flags, summary, raw_data)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    ts_code, flag_date, data["risk_level"],
                    data.get("is_st", 0), data.get("is_loss_warning", 0),
                    data.get("loss_warning_type", ""),
                    data.get("is_heavy_reduction", 0), data.get("reduction_detail", ""),
                    data.get("is_consecutive_loss", 0),
                    data.get("has_upcoming_report", 0), data.get("report_date", ""),
                    data.get("is_high_debt", 0), data.get("debt_ratio", 0),
                    data.get("is_delist_risk", 0), data.get("delist_detail", ""),
                    data.get("revenue_latest", 0), data.get("net_profit_latest", 0),
                    data.get("data_quality", "full"),
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

    # ========================================================================
    # ★ AKShare 备用数据源（v2.0新增）
    # ========================================================================

    def _check_st_batch_akshare(self, ts_codes: List[str], existing_st: Dict) -> Dict[str, dict]:
        """
        AKShare增强ST检查：用东财ST列表补充本地名称匹配的不足
        
        场景：股票名称还没改成"*ST"但即将被ST，本地DB查不到
        """
        if not _AKSHARE_AVAILABLE:
            return existing_st
        
        try:
            # 东财风险警示板（用线程+超时避免网络挂死）
            import concurrent.futures as _cf
            with _cf.ThreadPoolExecutor(max_workers=1) as ex:
                fut = ex.submit(ak.stock_zh_a_st_em)
                try:
                    df = fut.result(timeout=8)  # 8秒超时
                except _cf.TimeoutError:
                    logger.warning("AKShare ST接口超时(8s)，跳过")
                    return existing_st
            if df is None or df.empty:
                return existing_st
            
            st_codes_set = set()
            for _, row in df.iterrows():
                code = str(row.get("代码", ""))
                name = str(row.get("名称", ""))
                if code.startswith("6"):
                    ts_code = code + ".SH"
                elif code.startswith("0") or code.startswith("3"):
                    ts_code = code + ".SZ"
                elif code.startswith(("4", "8", "9")):
                    ts_code = code + ".BJ"
                else:
                    continue
                st_codes_set.add(ts_code)
            
            # 补充到已有结果
            for tc in ts_codes:
                if tc in st_codes_set:
                    if tc not in existing_st:
                        existing_st[tc] = {"is_st": 1, "name": "AKShare-ST"}
                    elif not existing_st[tc].get("is_st"):
                        existing_st[tc]["is_st"] = 1
                        existing_st[tc]["name"] = existing_st[tc].get("name", "") + " [AKShare验证]"
            
            logger.info(f"🛡️ AKShare ST列表: 发现{len(st_codes_set)}只ST股")
        except Exception as e:
            logger.warning(f"AKShare ST检查失败: {e}")
        
        return existing_st

    def _check_financial_batch_akshare(self, ts_codes: List[str]) -> Dict[str, dict]:
        """
        AKShare备用财务数据：用东财业绩报表一次获取全市场营收+净利润
        
        替代 Tushare income + fina_indicator（权限不足时自动启用）
        """
        results = {c: {
            "is_consecutive_loss": False,
            "is_high_debt": False,
            "debt_ratio": 0,
            "net_profits": [],
            "revenue": 0,
            "net_profit": 0,
        } for c in ts_codes}
        
        if not _AKSHARE_AVAILABLE:
            return results
        
        try:
            # 动态计算财报期间
            year = datetime.now().year
            month = datetime.now().month

            # 退市风险需要看【完整年度】营收，优先取最近年报
            # 如果当年年报还没出（<4月），用去年的
            annual_period = f"{year - 1}1231" if month < 5 else f"{year}1231"

            # 连续亏损看最近2期（可以是季报）
            if month >= 11:
                quarterly_periods = [f"{year}0930", f"{year}0630"]
            elif month >= 9:
                quarterly_periods = [f"{year}0630", f"{year - 1}1231"]
            elif month >= 5:
                quarterly_periods = [f"{year}0331", f"{year - 1}1231"]
            else:
                quarterly_periods = [f"{year - 1}1231", f"{year - 1}0930"]

            # 1. 拉年报数据（退市风险用）
            annual_revenue = {}
            annual_np = {}
            df_annual = ak.stock_yjbb_em(date=annual_period)
            if df_annual is not None and not df_annual.empty:
                for _, row in df_annual.iterrows():
                    code = str(row.get("股票代码", ""))
                    if code.startswith("6"):
                        tc = code + ".SH"
                    elif code.startswith("0") or code.startswith("3"):
                        tc = code + ".SZ"
                    elif code.startswith(("4", "8", "9")):
                        tc = code + ".BJ"
                    else:
                        continue
                    rev = float(row.get("营业总收入-营业总收入", 0) or 0)
                    np_val = float(row.get("净利润-净利润", 0) or 0)
                    annual_revenue[tc] = rev
                    annual_np[tc] = np_val

            # 2. 拉季度数据（连续亏损用）
            for period_label in quarterly_periods:
                df = ak.stock_yjbb_em(date=period_label)
                if df is None or df.empty:
                    continue
                
                # 建立代码映射（AKShare用纯数字，我们用带后缀的）
                code_map = {}
                for _, row in df.iterrows():
                    code = str(row.get("股票代码", ""))
                    if code.startswith("6"):
                        ts_code = code + ".SH"
                    elif code.startswith("0") or code.startswith("3"):
                        ts_code = code + ".SZ"
                    elif code.startswith(("4", "8", "9")):
                        ts_code = code + ".BJ"
                    else:
                        continue
                    code_map[ts_code] = row
                
                for tc in ts_codes:
                    row = code_map.get(tc)
                    if row is None:
                        continue
                    
                    revenue = float(row.get("营业总收入-营业总收入", 0) or 0)
                    net_profit = float(row.get("净利润-净利润", 0) or 0)
                    
                    results[tc]["net_profits"].append({
                        "period": period_label,
                        "n_income": net_profit,
                    })
                    # 取最新一期的营收和净利润（季度数据）
                    if not results[tc]["revenue"]:
                        results[tc]["revenue"] = revenue
                        results[tc]["net_profit"] = net_profit

            # 3. 用年报数据补充营收（注意：AKShare 是"营业总收入"，退市规则用"营业收入"）
            for tc in ts_codes:
                if tc in annual_revenue:
                    # 存储年报营收（注意是"营业总收入"，偏高，仅供参考）
                    results[tc]["annual_revenue"] = annual_revenue.get(tc, 0)
                    results[tc]["annual_net_profit"] = annual_np.get(tc, 0)
                    # 如果季度营收为空，用年报兜底
                    if not results[tc]["revenue"]:
                        results[tc]["revenue"] = annual_revenue[tc]
                        results[tc]["net_profit"] = annual_np.get(tc, 0)
            
            # 检查连续亏损
            for tc in ts_codes:
                profits = results[tc].get("net_profits", [])
                if len(profits) >= 2:
                    neg_count = sum(1 for p in profits if p["n_income"] < 0)
                    if neg_count >= 2:
                        results[tc]["is_consecutive_loss"] = True
                elif len(profits) == 1 and profits[0]["n_income"] < 0:
                    # 再查一期历史数据
                    try:
                        prev_period = f"{year-1}1231"
                        df2 = ak.stock_yjbb_em(date=prev_period)
                        if df2 is not None and not df2.empty:
                            code_num = tc.split(".")[0]
                            row2 = df2[df2["股票代码"] == code_num]
                            if not row2.empty:
                                prev_np = float(row2.iloc[0].get("净利润-净利润", 0) or 0)
                                if prev_np < 0:
                                    results[tc]["is_consecutive_loss"] = True
                    except Exception:
                        pass
            
            covered = sum(1 for c in ts_codes if results[c]["revenue"] > 0)
            logger.info(f"🛡️ AKShare财务数据: 覆盖{covered}/{len(ts_codes)}只")
        except Exception as e:
            logger.warning(f"AKShare财务数据获取失败: {e}")
        
        return results

    def _check_forecast_batch_akshare(self, ts_codes: List[str]) -> Dict[str, dict]:
        """
        AKShare备用业绩预告：东财业绩预告数据
        
        替代 Tushare forecast（权限不足时自动启用）
        """
        results = {c: {"is_loss_warning": False, "type": "", "p_change": None, "severity": ""} for c in ts_codes}
        
        if not _AKSHARE_AVAILABLE:
            return results
        
        try:
            year = datetime.now().year
            df = ak.stock_yjyg_em(date=f"{year}1231")
            if df is None or df.empty:
                return results
            
            # 建立代码映射
            code_map = {}
            for _, row in df.iterrows():
                code = str(row.get("股票代码", ""))
                if code.startswith("6"):
                    ts_code = code + ".SH"
                elif code.startswith("0") or code.startswith("3"):
                    ts_code = code + ".SZ"
                elif code.startswith(("4", "8", "9")):
                    ts_code = code + ".BJ"
                else:
                    continue
                code_map[ts_code] = row
            
            block_types = ["首亏", "续亏", "增亏"]
            for tc in ts_codes:
                row = code_map.get(tc)
                if row is None:
                    continue
                ftype = str(row.get("预告类型", ""))
                # 解析变动幅度
                change_str = str(row.get("业绩变动", ""))
                p_change_val = None
                import re
                m = re.search(r'([-]?\d+(?:\.\d+)?)%', change_str)
                if m:
                    p_change_val = float(m.group(1))
                
                if any(b in ftype for b in block_types):
                    results[tc] = {
                        "is_loss_warning": True,
                        "type": f"{ftype}（{year}年报，AKShare）",
                        "summary": change_str[:100],
                        "p_change": p_change_val,
                        "severity": "block",
                    }
                elif "预减" in ftype:
                    if p_change_val is not None and p_change_val <= -50:
                        results[tc] = {
                            "is_loss_warning": True,
                            "type": f"{ftype}（{year}年报，降幅{abs(p_change_val):.0f}%，AKShare）",
                            "summary": change_str[:100],
                            "p_change": p_change_val,
                            "severity": "block",
                        }
                    elif p_change_val is not None and p_change_val <= -30:
                        results[tc] = {
                            "is_loss_warning": False,
                            "is_profit_warning": True,
                            "type": f"{ftype}（{year}年报，降幅{abs(p_change_val):.0f}%，AKShare）",
                            "summary": change_str[:100],
                            "p_change": p_change_val,
                            "severity": "warning",
                        }
            
            warned = sum(1 for c in ts_codes if results[c]["is_loss_warning"])
            warned_cnt = sum(1 for c in ts_codes if results[c].get("is_profit_warning"))
            logger.info(f"🛡️ AKShare业绩预告: {warned}只block + {warned_cnt}只warning")
        except Exception as e:
            logger.warning(f"AKShare业绩预告获取失败: {e}")
        
        return results

    def _check_delist_risk(
        self,
        ts_codes: List[str],
        tushare_financial: Dict[str, dict],
        akshare_financial: Dict[str, dict],
    ) -> Dict[str, dict]:
        """
        ★ 退市风险检测（v2.2 营业收入修正版）

        触发条件（匹配真实*ST退市风险警示规则）：
        - 最新报告期 营业收入 < 1亿元 且 净利润 < 0
        - 对应创业板退市新规：营业收入<1亿+亏损 → *ST

        ⚠️ 关键：交易所规则用的是"营业收入"，不是"营业总收入"
        - 营业收入 = 主营业务收入 + 其他业务收入（交易所标准）
        - 营业总收入 = 营业收入 + 投资收益 + 其他收益 + ...（AKShare返回的是这个）

        数据源优先级：
        1. Tushare income.revenue（营业收入，最准确）
        2. AKShare 季度 营业总收入（略偏高的近似值）
        3. AKShare 年度 营业总收入（最后兜底）
        """
        results = {c: {
            "is_delist_risk": False,
            "detail": "",
            "revenue": 0,
            "net_profit": 0,
        } for c in ts_codes}

        REVENUE_THRESHOLD = 1e8  # 1亿元
        delist_count = 0

        for tc in ts_codes:
            # 合并数据源
            fn = tushare_financial.get(tc, {})
            fn_ak = akshare_financial.get(tc, {})

            # ★ 关键修正：优先用 Tushare revenue（营业收入），而非营业总收入
            # Tushare income.revenue = 交易所认可的"营业收入"
            # AKShare annual_revenue = "营业总收入"（偏高，300295正是因此漏网）
            tushare_revenue = fn.get("revenue", 0) or 0
            ak_quarterly_revenue = fn_ak.get("revenue", 0) or 0
            ak_annual_revenue = fn_ak.get("annual_revenue", 0) or 0

            # 优先级：Tushare营业收入 > AKShare季度 > AKShare年报
            if tushare_revenue > 0:
                revenue = tushare_revenue
                source = f"Tushare营业收入({fn.get('period', '')})"
            elif ak_quarterly_revenue > 0:
                revenue = ak_quarterly_revenue
                source = "AKShare季度营业总收入"
            else:
                revenue = ak_annual_revenue
                source = "AKShare年报营业总收入"

            # 净利润用最新的
            net_profit = fn.get("net_profits", [{}])[0].get("n_income", 0) if fn.get("net_profits") else 0
            if not net_profit:
                net_profit = fn_ak.get("net_profit", 0) or 0

            results[tc]["revenue"] = revenue
            results[tc]["net_profit"] = net_profit

            # 唯一规则：营收<1亿 + 净利润<0 → 退市风险
            if revenue > 0 and revenue < REVENUE_THRESHOLD and net_profit < 0:
                results[tc]["is_delist_risk"] = True
                results[tc]["detail"] = (
                    f"营收{revenue/1e8:.2f}亿(<1亿) + 净利润{net_profit/1e8:.4f}亿(<0) "
                    f"[数据源:{source}]"
                )
                delist_count += 1

        if delist_count > 0:
            logger.info(f"🛡️ 退市风险预警: {delist_count}只")

        return results
