"""
QuantWeave - 一键选股服务
直接集成 daily_picks 的双均线+回调企稳策略扫描逻辑
复用 core_signals.py 共用策略模块，确保与回测系统一致
支持异步模式：扫描结果存入 scan_results 表，页面加载读取最新结果
"""

import sys
import sqlite3
import json
import warnings
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from loguru import logger
from sqlalchemy.orm import Session

warnings.filterwarnings("ignore")

# 引用 core_signals 共用策略模块
CORE_SIGNALS_PATH = Path(__file__).resolve().parent.parent / "strategy"
if str(CORE_SIGNALS_PATH) not in sys.path:
    sys.path.insert(0, str(CORE_SIGNALS_PATH))

from core_signals import (
    CORE_STRATEGIES,
    signals_dual_ma,
    signals_pullback_stable,
)

# ============================================================================
# scan_results 表管理（SQLite）
# ============================================================================

SCAN_RESULTS_DDL = """
CREATE TABLE IF NOT EXISTS scan_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_time TEXT NOT NULL,
    data_date TEXT NOT NULL,
    result_json TEXT NOT NULL,
    total_stocks INTEGER DEFAULT 0,
    total_signals INTEGER DEFAULT 0,
    resonance_count INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);
"""

def _ensure_scan_results_table(db_path: Path):
    """确保 scan_results 表存在"""
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(SCAN_RESULTS_DDL)
        conn.commit()
    finally:
        conn.close()


def save_scan_result(db_path: Path, result: Dict) -> int:
    """保存扫描结果到数据库，返回记录ID"""
    _ensure_scan_results_table(db_path)
    conn = sqlite3.connect(str(db_path))
    try:
        cursor = conn.execute(
            """INSERT INTO scan_results (scan_time, data_date, result_json, total_stocks, total_signals, resonance_count)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                result.get("scan_time", ""),
                result.get("data_date", ""),
                json.dumps(result, ensure_ascii=False, default=str),
                result.get("total_stocks_scanned", 0),
                result.get("total_signals_found", 0),
                len(result.get("resonance", [])),
            ),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def get_latest_scan_result(db_path: Path) -> Optional[Dict]:
    """获取最新一次扫描结果"""
    _ensure_scan_results_table(db_path)
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT id, scan_time, data_date, result_json, total_stocks, total_signals, resonance_count "
            "FROM scan_results ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if not row:
            return None
        return {
            "id": row[0],
            "scan_time": row[1],
            "data_date": row[2],
            "result": json.loads(row[3]),
            "total_stocks": row[4],
            "total_signals": row[5],
            "resonance_count": row[6],
        }
    finally:
        conn.close()

# ============================================================================
# 配置参数（与 quant-daily-picks skill 一致）
# ============================================================================
SIGNAL_WINDOW_DAYS = 1
MAX_MA20_DEVIATION = 0.12
MAX_ATR_RATIO = 0.08
MIN_AVG_VOLUME_5D = 5.0
MAX_DAILY_CHANGE = 0.095
MIN_HIGH20_DISTANCE = -0.03

# 使用的策略（只保留实盘两策略）
ACTIVE_STRATEGIES = {
    "dual_ma": {
        "name": "双均线交叉",
        "func": signals_dual_ma,
        "needs_full": False,
        "params": CORE_STRATEGIES["dual_ma"]["default_params"],
    },
    "pullback_stable": {
        "name": "回调企稳",
        "func": signals_pullback_stable,
        "needs_full": True,
        "params": CORE_STRATEGIES["pullback_stable"]["default_params"],
    },
}


class QuickPicksService:
    """一键选股服务 — 双均线+回调企稳全市场扫描"""

    def __init__(self, db_session: Session = None):
        self.db = db_session  # 可选：FastAPI 注入时非空，脚本调用时可为 None
        # SQLite 路径（策略数据在 SQLite）
        self._db_path = Path(__file__).resolve().parent.parent.parent.parent / "quantweave.db"
        _ensure_scan_results_table(self._db_path)

    def _get_sqlite_conn(self):
        return sqlite3.connect(str(self._db_path))

    def run_scan(self) -> Dict:
        """
        执行全市场扫描，返回与 daily_picks 一致的结构

        优化点（v2.3 先选股后风控）：
        1. 批量加载：一次 SQL 获取所有数据，内存 groupby（替代逐股 11000 次查询）
        2. 数据新鲜度校验：确保数据日期是最近交易日（防止 token 失效静默失败）
        3. ★先选股后风控：先算全部信号（快），再只对有信号的股票跑风控（省API调用）
           - 原来：风控5500只→信号（慢，5500次API）
           - 现在：信号全部→风控20-50只（快，只调几十次API）
        """
        logger.info("🚀 一键选股扫描开始...")

        conn = self._get_sqlite_conn()
        try:
            # 1. 获取股票列表
            stocks_df = pd.read_sql(
                "SELECT ts_code, name, industry FROM stocks WHERE is_active = 1",
                conn,
            )
            logger.info(f"活跃股票数量: {len(stocks_df)}")

            # 2. 获取最新交易日期和信号窗口
            latest_date = pd.read_sql(
                "SELECT MAX(trade_date) as max_date FROM stock_daily", conn
            )["max_date"].iloc[0]

            # ===== 🦉 夜枭补充：数据新鲜度校验 =====
            # 防止 token 失效导致数据停在旧日期，用户误以为是今日信号
            freshness_ok, freshness_warn = self._validate_data_freshness(latest_date)
            if not freshness_ok:
                logger.warning(
                    f"⚠️ 数据新鲜度警告: latest_date={latest_date}, {freshness_warn}"
                )
            # ===== 夜枭补充结束 =====

            window_dates_df = pd.read_sql(
                f"SELECT DISTINCT trade_date FROM stock_daily "
                f"ORDER BY trade_date DESC LIMIT {SIGNAL_WINDOW_DAYS}",
                conn,
            )
            window_dates = window_dates_df["trade_date"].tolist()

            logger.info(f"数据最新日期: {latest_date}, 信号窗口: {window_dates}")

            name_map = dict(zip(stocks_df["ts_code"], stocks_df["name"]))
            industry_map = dict(zip(stocks_df["ts_code"], stocks_df["industry"]))

            # ===== 🦅 鹰眼优化：批量加载 + groupby（替代逐股查询）=====
            # 根因：5500只 × 2策略 = 11000次 pd.read_sql，每次~25ms，共~137秒 I/O 等待
            # 优化：一次 SQL + 内存 groupby，I/O 时间降至约 1 秒
            logger.info("📥 批量加载日K线数据...")

            # 限制只加载最近 N 天（策略需要最多 75 天数据，zlcmmq_window=75）
            hist_start = pd.read_sql(
                "SELECT DISTINCT trade_date FROM stock_daily "
                "ORDER BY trade_date DESC LIMIT 80",
                conn,
            )["trade_date"].iloc[-1]

            all_daily = pd.read_sql(
                f"SELECT ts_code, trade_date, open, high, low, close, vol, "
                f"COALESCE(change_pct, 0) as change_pct "
                f"FROM stock_daily WHERE trade_date >= '{hist_start}' "
                f"ORDER BY ts_code, trade_date",
                conn,
            )
            logger.info(f"批量加载完成: {len(all_daily)} 条记录")

            # 列名适配
            if "pct_chg" in all_daily.columns and "change_pct" not in all_daily.columns:
                all_daily.rename(columns={"pct_chg": "change_pct"}, inplace=True)

            # 建立 ts_code → DataFrame 索引
            stock_data: Dict[str, pd.DataFrame] = {}
            for tc, grp in all_daily.groupby("ts_code"):
                df = grp.sort_values("trade_date").reset_index(drop=True)
                stock_data[tc] = df

            logger.info(f"内存索引构建完成: {len(stock_data)} 只股票")

            # ===== 🦉 v2.3 先选股后风控（信号先行，风控后置） =====
            # 旧流程：风控5500只(API慢) → 信号计算(快) → 结果
            # 新流程：信号计算(快，本地) → 只风控有信号的20~50只(API快) → 结果
            # 核心洞察：信号计算只用本地SQLite数据，零API调用；风控要调Tushare/AKShare
            # ===== 逐股扫描（全部股票都算信号，不做前置过滤）=====
            all_results = {key: [] for key in ACTIVE_STRATEGIES}
            stock_signal_count: Dict[str, set] = {}
            total = len(stocks_df)
            scanned = 0

            for idx, row in stocks_df.iterrows():
                ts_code = row["ts_code"]
                name = row["name"]

                df = stock_data.get(ts_code)
                if df is None or len(df) < 80:
                    scanned += 1
                    continue

                for key, strat_cfg in ACTIVE_STRATEGIES.items():
                    try:
                        signals = self._generate_signals(df, ts_code, strat_cfg)
                        buy_signals = [
                            s for s in signals
                            if s["signal"] == "buy" and s["date"] in window_dates
                        ]
                        if not buy_signals:
                            continue

                        latest_signal = max(buy_signals, key=lambda s: s["date"])
                        risk = self._calculate_risk(df)
                        entry = self._calculate_entry_points(df)
                        score_data = self._calculate_composite_score(
                            df, industry_map.get(ts_code, "")
                        )
                        trend_strength = self._calculate_trend_strength(df)
                        volume_score = self._calculate_volume_score(df)
                        recent_gain = self._calculate_recent_gain(df, window_dates)

                        all_results[key].append({
                            "ts_code": ts_code,
                            "name": name,
                            "industry": industry_map.get(ts_code, ""),
                            "signal": latest_signal,
                            "risk": risk,
                            "entry_points": entry,
                            "score": score_data,
                            "trend_strength": round(trend_strength, 1),
                            "volume_score": round(volume_score, 1),
                            "recent_gain": round(recent_gain * 100, 2),
                        })

                        if ts_code not in stock_signal_count:
                            stock_signal_count[ts_code] = set()
                        stock_signal_count[ts_code].add(key)
                    except Exception:
                        pass

                scanned += 1
                # 每 500 只输出一次进度
                if scanned % 500 == 0:
                    logger.info(f"扫描进度: {scanned}/{total} ({scanned*100//total}%)")

            logger.info(f"✅ 信号扫描完成: {total} 只股票, 策略信号: "
                       + ", ".join(f"{ACTIVE_STRATEGIES[k]['name']}:{len(v)} 只"
                                  for k, v in all_results.items()))

        finally:
            conn.close()

        # ===== 风控后置：只对有信号的股票执行风控扫描 =====
        signal_stocks = set()
        for key, picks in all_results.items():
            for p in picks:
                signal_stocks.add(p["ts_code"])

        risk_data = {}
        blocked_codes = set()

        if signal_stocks:
            logger.info(f"🛡️ 风控后置扫描: {len(signal_stocks)} 只有信号的股票...")
            try:
                from app.services.risk.risk_filter_service import RiskFilterService
                risk_svc = RiskFilterService(self._db_path)
                # 只扫描有信号的股票，而不是全部5500只
                risk_data = risk_svc.scan_risks(list(signal_stocks))
                blocked_codes = {c for c, d in risk_data.items()
                                if d.get("risk_level") == "block"}
                if blocked_codes:
                    logger.info(f"🛡️ 风控排除: {len(blocked_codes)} 只 → {blocked_codes}")
                    # 从结果中移除被风控排除的股票
                    for key in all_results:
                        all_results[key] = [
                            p for p in all_results[key]
                            if p["ts_code"] not in blocked_codes
                        ]
                    # 从共振计数中移除
                    for bc in blocked_codes:
                        stock_signal_count.pop(bc, None)
            except Exception as e:
                logger.warning(f"风控扫描失败（跳过）: {e}")

        # 5. 多策略共振检测（含评分+风控标记）
        resonance = []
        for ts_code, strategies_hit in stock_signal_count.items():
            if len(strategies_hit) >= 2:
                resonance_item = {"ts_code": ts_code, "name": name_map.get(ts_code, "")}
                hit_details = []
                best_score = None
                for key in strategies_hit:
                    for r in all_results[key]:
                        if r["ts_code"] == ts_code:
                            hit_details.append({
                                "strategy": ACTIVE_STRATEGIES[key]["name"],
                                "reason": r["signal"]["reason"],
                            })
                            # 取最高评分（可能不同策略给出不同评分，取最高）
                            s = r.get("score", {})
                            if best_score is None or s.get("total", 0) > best_score.get("total", 0):
                                best_score = s
                            break
                resonance_item["hit_count"] = len(strategies_hit)
                resonance_item["strategies"] = hit_details
                # 带上风控和入场点（取第一个策略的数据）
                for key in strategies_hit:
                    for r in all_results[key]:
                        if r["ts_code"] == ts_code:
                            resonance_item["risk"] = r["risk"]
                            resonance_item["entry_points"] = r["entry_points"]
                            resonance_item["price"] = r["signal"]["price"]
                            if not best_score:
                                best_score = r.get("score", {})
                            break
                    break
                # 写入评分数据
                if best_score:
                    resonance_item["score"] = best_score
                else:
                    resonance_item["score"] = {"total": 0, "advice": "—", "icon": "⚪"}
                # 风控标记
                rd = risk_data.get(ts_code, {})
                resonance_item["risk_flags"] = rd.get("flags", [])
                resonance_item["risk_level"] = rd.get("risk_level", "safe")
                resonance_item["risk_summary"] = rd.get("summary", "")
                resonance.append(resonance_item)

        # 按综合评分排序（不再是简单 hit_count）
        resonance.sort(key=lambda x: x.get("score", {}).get("total", 0), reverse=True)

        # 5. 行业分布
        all_picks = []
        for key, picks in all_results.items():
            all_picks.extend(picks)
        industry_dist = {}
        for s in all_picks:
            ind = s.get("industry", "未知")
            industry_dist[ind] = industry_dist.get(ind, 0) + 1

        # 6. 组装结果（含数据新鲜度信息）
        freshness_ok, freshness_msg = self._validate_data_freshness(latest_date)
        result = {
            "scan_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "data_date": latest_date,
            "data_date_fresh": freshness_ok,  # 前端可据此显示警告标签
            "data_freshness_msg": freshness_msg,  # 警告信息
            "signal_window": window_dates,
            "total_stocks_scanned": total,
            "total_signals_found": sum(len(r) for r in all_results.values()),
            "resonance": resonance,
            "strategies": {},
            "industry_distribution": dict(sorted(industry_dist.items(), key=lambda x: -x[1])[:10]),
        }

        for key in ACTIVE_STRATEGIES:
            sorted_picks = sorted(all_results[key], key=lambda x: x.get("score", {}).get("total", 0), reverse=True)
            # 给每只信号股添加风控标记
            for p in sorted_picks:
                rd = risk_data.get(p["ts_code"], {})
                p["risk_flags"] = rd.get("flags", [])
                p["risk_level"] = rd.get("risk_level", "safe")
                p["risk_summary"] = rd.get("summary", "")
            result["strategies"][key] = {
                "name": ACTIVE_STRATEGIES[key]["name"],
                "top_picks": sorted_picks,
                "total_signals": len(all_results[key]),
            }

        # 风控统计
        result["risk_summary"] = {
            "blocked_count": len(blocked_codes),
            "blocked_codes": list(blocked_codes),
            "warning_count": sum(1 for v in risk_data.values() if v.get("risk_level") in ("warning",)),
            "safe_count": sum(1 for v in risk_data.values() if v.get("risk_level") == "safe"),
        }

        return result

    def run_and_save(self) -> Dict:
        """执行扫描并保存结果到数据库"""
        result = self.run_scan()
        record_id = save_scan_result(self._db_path, result)
        logger.info(f"✅ 一键选股结果已保存 (id={record_id})")
        result["saved_id"] = record_id
        return result

    @staticmethod
    def get_latest(db_path: Path = None) -> Optional[Dict]:
        """获取最新一次扫描结果"""
        if db_path is None:
            db_path = Path(__file__).resolve().parent.parent.parent.parent / "quantweave.db"
        return get_latest_scan_result(db_path)

    def _generate_signals(self, df: pd.DataFrame, ts_code: str, strat_cfg: dict) -> List[Dict]:
        """为单只股票生成信号"""
        df = df.sort_values("trade_date").copy()
        close = df["close"].values.astype(float)
        dates = df["trade_date"].astype(str).tolist()

        params = strat_cfg["params"]

        if strat_cfg["needs_full"]:
            high = df["high"].values.astype(float) if "high" in df.columns else close.copy()
            low = df["low"].values.astype(float) if "low" in df.columns else close.copy()
            vol = df["vol"].values.astype(float) if "vol" in df.columns else np.zeros(len(df))
            open_ = df["open"].values.astype(float) if "open" in df.columns else close.copy()
            raw = strat_cfg["func"](close, high, low, vol, open_, dates, params)
        else:
            raw = strat_cfg["func"](close, dates, params)

        # 构建 date → row index 映射
        date_to_idx = {str(d): i for i, d in enumerate(df["trade_date"].values)}

        signals = []
        for date_str, sig_type in raw.items():
            if date_str not in date_to_idx:
                continue
            row = df.iloc[date_to_idx[date_str]]
            price = float(row["close"])

            if sig_type == "buy":
                reason = self._buy_reason(strat_cfg, params)
                signals.append({
                    "signal": "buy",
                    "ts_code": ts_code,
                    "price": price,
                    "date": date_str,
                    "reason": reason,
                    "confidence": 0.85,
                })
            elif sig_type == "sell":
                reason = self._sell_reason(strat_cfg, params)
                signals.append({
                    "signal": "sell",
                    "ts_code": ts_code,
                    "price": price,
                    "date": date_str,
                    "reason": reason,
                    "confidence": 0.80,
                })

        return signals

    @staticmethod
    def _buy_reason(strat_cfg: dict, params: dict) -> str:
        key = None
        for k, v in ACTIVE_STRATEGIES.items():
            if v["name"] == strat_cfg["name"]:
                key = k
                break
        if key == "dual_ma":
            return f"MA{params.get('short_period',7)}上穿MA{params.get('long_period',60)}（金叉）"
        elif key == "pullback_stable":
            return "强势股回调企稳"
        return f"{strat_cfg['name']}买入信号"

    @staticmethod
    def _sell_reason(strat_cfg: dict, params: dict) -> str:
        key = None
        for k, v in ACTIVE_STRATEGIES.items():
            if v["name"] == strat_cfg["name"]:
                key = k
                break
        if key == "dual_ma":
            return f"MA{params.get('short_period',7)}下穿MA{params.get('long_period',60)}（死叉）"
        elif key == "pullback_stable":
            return "ZLCMQ极低或跌破MA60"
        return f"{strat_cfg['name']}卖出信号"

    @staticmethod
    def _calculate_composite_score(df: pd.DataFrame, industry: str = "") -> dict:
        """
        StockSense AI 多维度评分 — 与 batch_analyze.py / stock-sense-ai skill 一致
        技术面30% + 基本面25% + 消息面20% + 资金面15% = 综合得分
        
        Returns: dict with score breakdown + advice + key indicators
        """
        if len(df) < 60:
            return {"total": 0, "advice": "数据不足", "icon": "⚪"}

        closes = df["close"].values.astype(float)
        highs = df["high"].values.astype(float) if "high" in df.columns else closes.copy()
        lows = df["low"].values.astype(float) if "low" in df.columns else closes.copy()
        vols = df["vol"].values.astype(float) if "vol" in df.columns else np.ones(len(df))
        changes = df["change_pct"].values.astype(float) if "change_pct" in df.columns else np.zeros(len(df))

        last_close = closes[-1]

        # ===== 技术面 (30%) =====
        tech_score = 50
        ma5 = np.mean(closes[-5:])
        ma10 = np.mean(closes[-10:])
        ma20 = np.mean(closes[-20:])
        ma60 = np.mean(closes[-60:])

        # 均线排列
        if ma5 > ma10 > ma20 > ma60:
            tech_score += 15
        elif ma5 > ma10 > ma20:
            tech_score += 10
        elif ma5 > ma10:
            tech_score += 5

        # MACD 金叉/死叉
        ema12, ema26 = float(closes[0]), float(closes[0])
        dif_list = []
        for c in closes:
            ema12 = float(c) * 2 / 13 + ema12 * 11 / 13
            ema26 = float(c) * 2 / 27 + ema26 * 25 / 27
            dif_list.append(ema12 - ema26)
        dif_arr = np.array(dif_list)
        dea_arr = np.zeros(len(dif_arr))
        for i in range(1, len(dif_arr)):
            dea_arr[i] = dif_arr[i] * 2 / 10 + dea_arr[i - 1] * 8 / 10
        macd_cross = "金叉" if dif_arr[-1] > dea_arr[-1] else "死叉"
        if dif_arr[-1] > dea_arr[-1]:
            tech_score += 10
        macd_bar = (dif_arr - dea_arr) * 2
        if len(macd_bar) >= 3 and macd_bar[-1] < macd_bar[-2] and dif_arr[-1] > dea_arr[-1]:
            tech_score -= 5  # MACD动能减弱

        # RSI
        deltas = np.diff(closes[-15:])
        gains = np.where(deltas > 0, deltas, 0)
        losses_arr = np.where(deltas < 0, -deltas, 0)
        avg_gain = np.mean(gains[-14:])
        avg_loss = np.mean(losses_arr[-14:])
        rsi = 100 - (100 / (1 + avg_gain / avg_loss)) if avg_loss > 0 else 100
        if 40 <= rsi <= 60:
            tech_score += 10
        elif 30 <= rsi <= 70:
            tech_score += 5
        elif rsi > 80:
            tech_score -= 10
        elif rsi > 70:
            tech_score -= 5

        # 量比
        vol5 = np.mean(vols[-5:])
        vol20 = np.mean(vols[-20:])
        vol_ratio = vol5 / vol20 if vol20 > 0 else 1
        if 0.8 <= vol_ratio <= 1.5:
            tech_score += 10
        elif vol_ratio > 2:
            tech_score -= 5

        # MA60偏离
        ma60_dev = (last_close / ma60 - 1) * 100
        if abs(ma60_dev) < 5:
            tech_score += 5
        elif ma60_dev > 15:
            tech_score -= 10

        tech_score = min(100, max(0, tech_score))

        # ===== 基本面 (25%) =====
        base_score = 50
        daily_returns = changes[-30:] if len(changes) >= 30 else changes
        volatility = np.std(daily_returns) if len(daily_returns) > 0 else 0
        if volatility < 1.5:
            base_score += 15
        elif volatility < 2.5:
            base_score += 10
        elif volatility < 4:
            base_score += 0
        else:
            base_score -= 10

        high60 = max(closes[-60:])
        low60 = min(closes[-60:])
        price_pos = (last_close - low60) / (high60 - low60) * 100 if high60 != low60 else 50
        if 30 <= price_pos <= 70:
            base_score += 15
        elif price_pos > 85:
            base_score -= 10
        elif price_pos < 20:
            base_score += 10

        # 趋势斜率
        y = closes[-20:]
        x = np.arange(len(y))
        slope = np.polyfit(x, y, 1)[0]
        trend_pct = slope / last_close * 100
        if 0 < trend_pct < 0.3:
            base_score += 10
        elif trend_pct >= 0.3:
            base_score += 5
        elif -0.1 < trend_pct <= 0:
            base_score += 5
        else:
            base_score -= 5

        base_score = min(100, max(0, base_score))

        # ===== 消息面 (20%) =====
        news_score = 50
        hot_kw = ["半导体", "人工智能", "软件", "通信", "新能源", "军工", "医药", "机器人", "信息", "电子"]
        if any(h in (industry or "") for h in hot_kw):
            news_score += 15
        chg5 = (last_close / closes[-6] - 1) * 100 if len(closes) >= 6 else 0
        if 0 < chg5 < 5:
            news_score += 15
        elif chg5 >= 5:
            news_score += 5
        elif -2 < chg5 <= 0:
            news_score += 5
        elif chg5 <= -5:
            news_score -= 10
        news_score = min(100, max(0, news_score))

        # ===== 资金面 (15%) =====
        fund_score = 50
        if vol_ratio > 1.5:
            fund_score += 15
        elif vol_ratio > 1:
            fund_score += 10
        elif vol_ratio > 0.7:
            fund_score += 0
        else:
            fund_score -= 5

        today_chg = changes[-1] if len(changes) > 0 else 0
        if 0 < today_chg < 3:
            fund_score += 15
        elif 3 <= today_chg < 6:
            fund_score += 10
        elif today_chg >= 6:
            fund_score += 0
        elif -1 < today_chg <= 0:
            fund_score += 5
        else:
            fund_score -= 10

        fund_score = min(100, max(0, fund_score))

        # ===== 综合 =====
        total_score = round(
            tech_score * 0.30 + base_score * 0.25 + news_score * 0.20 + fund_score * 0.15, 1
        )

        if total_score >= 80:
            advice, icon = "强烈买入", "🔥🔥"
        elif total_score >= 65:
            advice, icon = "买入/加仓", "🟢"
        elif total_score >= 50:
            advice, icon = "持有观望", "🟡"
        elif total_score >= 35:
            advice, icon = "减仓", "🟠"
        else:
            advice, icon = "卖出", "🔴"

        ma_status = (
            "多头"
            if ma5 > ma10 > ma20 > ma60
            else ("短多" if ma5 > ma10 else "震荡")
        )

        return {
            "total": total_score,
            "tech": tech_score,
            "base": base_score,
            "news": news_score,
            "fund": fund_score,
            "advice": advice,
            "icon": icon,
            "rsi": round(float(rsi), 1),
            "vol_ratio": round(float(vol_ratio), 2),
            "ma60_dev": round(float(ma60_dev), 1),
            "macd": macd_cross,
            "ma_status": ma_status,
            "today_chg": round(float(today_chg), 2),
        }

    @staticmethod
    def _validate_data_freshness(latest_date: str) -> tuple[bool, str]:
        """
        🦉 夜枭补充：数据新鲜度校验

        检查 stock_daily 的最新日期是否是最近交易日。
        防止因 Tushare Token 失效/同步中断导致数据停在旧日期，
        用户误以为选的是今日信号。

        Returns:
            (is_fresh, warning_msg)
            - is_fresh=True: 数据是最近交易日，正常
            - is_fresh=False: 数据不是最近交易日，需要警告
        """
        from datetime import date, timedelta

        if not latest_date:
            return False, "latest_date 为空，无法判断数据新鲜度"

        try:
            latest = date.fromisoformat(str(latest_date))
        except (ValueError, TypeError):
            return False, f"latest_date 格式异常: {latest_date}"

        today = date.today()
        # 考虑周末：周六(weekday=5)、周日(weekday=6) 市场休市
        # 最近交易日：周五 → today 是周六/周日则取上周五
        days_since = (today - latest).days

        # 如果 latest_date 在未来，异常
        if latest > today:
            return False, f"latest_date({latest_date}) 晚于今天({today})，数据异常"

        # 今天的数据通常 15:30 后才同步，先检查是否已收盘
        if days_since == 0:
            return True, ""  # 当天数据存在，正常

        # 周末情况：周五之后是周六/周日，最近交易日仍是上周五
        if today.weekday() in (5, 6):
            # 上一个周五
            days_to_last_fri = today.weekday() - 4  # 周六=1, 周日=2
            expected_latest = today - timedelta(days=days_to_last_fri)
            if latest == expected_latest:
                return True, ""  # 是最近交易日（周五），正常
            return False, (
                f"数据最新日期({latest_date})不是最近交易日(应为{expected_latest})，"
                f"可能因Token失效或同步中断导致"
            )

        # 平日：数据应与今天一致
        if days_since == 1:
            # 昨天（可能盘后不久数据刚同步）
            return True, ""
        elif days_since >= 2:
            return False, (
                f"数据最新日期({latest_date})距今天({today})已有{days_since}天，"
                f"可能因Token失效或同步中断导致，建议检查Tushare Token"
            )

        return True, ""

    @staticmethod
    def _calculate_risk(df: pd.DataFrame) -> dict:
        """风控指标计算"""
        if len(df) < 20:
            return {"pass": False, "reason": "数据不足"}

        recent = df.tail(20)
        last = recent.iloc[-1]
        price = float(last["close"])

        risks = {"pass": True, "warnings": []}

        # MA20 偏离
        ma20 = recent["close"].mean()
        if ma20 > 0:
            deviation = (price - ma20) / ma20
            risks["ma20_deviation"] = round(deviation * 100, 2)
            if deviation > MAX_MA20_DEVIATION:
                risks["pass"] = False
                risks["warnings"].append(f"偏离MA20达{deviation*100:.1f}%")

        # ATR 波动率
        if "high" in df.columns and "low" in df.columns:
            tr_list = []
            for i in range(1, len(recent)):
                h, l = float(recent.iloc[i]["high"]), float(recent.iloc[i]["low"])
                pc = float(recent.iloc[i-1]["close"])
                tr_list.append(max(h - l, abs(h - pc), abs(l - pc)))
            if tr_list:
                atr = sum(tr_list) / len(tr_list)
                atr_ratio = atr / price if price > 0 else 0
                risks["atr_ratio"] = round(atr_ratio * 100, 2)
                if atr_ratio > MAX_ATR_RATIO:
                    risks["pass"] = False
                    risks["warnings"].append(f"波动率ATR={atr_ratio*100:.1f}%")

        # 流动性
        if "vol" in df.columns and len(df) >= 5:
            vol_5d = df.tail(5)["vol"].mean()
            risks["avg_vol_5d"] = round(vol_5d, 1)

        # 当日涨幅
        chg = float(last.get("change_pct", 0))
        risks["daily_change"] = round(chg, 2)

        return risks

    @staticmethod
    def _calculate_recent_gain(df: pd.DataFrame, window_dates: list) -> float:
        """计算近N日涨幅"""
        if not window_dates or df.empty:
            return 0.0
        recent = df[df["trade_date"].isin(window_dates)]
        if len(recent) < 2:
            return 0.0
        first_price = recent.iloc[0]["close"]
        last_price = recent.iloc[-1]["close"]
        if first_price == 0:
            return 0.0
        return (last_price - first_price) / first_price

    @staticmethod
    def _calculate_trend_strength(df: pd.DataFrame) -> float:
        """计算趋势强度（基于MA排列和价格位置）— 与 daily_picks.py skill 一致"""
        if len(df) < 60:
            return 0.0
        recent = df.tail(60).copy()
        recent["ma5"] = recent["close"].rolling(5).mean()
        recent["ma20"] = recent["close"].rolling(20).mean()
        recent["ma60"] = recent["close"].rolling(60).mean()

        last = recent.iloc[-1]
        if pd.isna(last["ma60"]):
            return 0.0

        score = 0.0
        if last["close"] > last["ma60"]:
            score += 30
        if not pd.isna(last["ma5"]) and not pd.isna(last["ma20"]):
            if last["ma5"] > last["ma20"]:
                score += 30
        if not pd.isna(last["ma20"]) and last["ma20"] > last["ma60"]:
            score += 20
        if len(recent) >= 20:
            chg = (recent.iloc[-1]["close"] - recent.iloc[-20]["close"]) / recent.iloc[-20]["close"]
            score += min(max(chg * 100, -20), 20)

        return max(0, min(100, score))

    @staticmethod
    def _calculate_volume_score(df: pd.DataFrame) -> float:
        """计算量能配合得分 — 与 daily_picks.py skill 一致"""
        if len(df) < 20 or "vol" not in df.columns:
            return 50.0
        recent = df.tail(20)
        vol_avg = recent["vol"].mean()
        last_vol = recent.iloc[-1]["vol"]
        if vol_avg == 0:
            return 50.0
        ratio = last_vol / vol_avg
        if 1.0 <= ratio <= 2.0:
            return 80.0
        elif 0.8 <= ratio < 1.0:
            return 60.0
        elif ratio > 2.0:
            return 70.0
        else:
            return 40.0

    @staticmethod
    def _calculate_entry_points(df: pd.DataFrame) -> dict:
        """计算明日买入关键点位 — 与 daily_picks.py skill 的丰富版本一致

        包含：买入区间、ATR止损、支撑止损、破位放弃价、目标价、前高压力、关键价位列表
        """
        if len(df) < 60:
            return {}

        recent = df.tail(60).copy()
        last = recent.iloc[-1]
        price = float(last["close"])
        high = float(last["high"]) if "high" in last.index else price
        low = float(last["low"]) if "low" in last.index else price

        # 计算均线
        recent["ma5"] = recent["close"].rolling(5).mean()
        recent["ma10"] = recent["close"].rolling(10).mean()
        recent["ma20"] = recent["close"].rolling(20).mean()
        recent["ma60"] = recent["close"].rolling(60).mean()

        ma5 = float(recent["ma5"].iloc[-1]) if not pd.isna(recent["ma5"].iloc[-1]) else None
        ma10 = float(recent["ma10"].iloc[-1]) if not pd.isna(recent["ma10"].iloc[-1]) else None
        ma20 = float(recent["ma20"].iloc[-1]) if not pd.isna(recent["ma20"].iloc[-1]) else None
        ma60 = float(recent["ma60"].iloc[-1]) if not pd.isna(recent["ma60"].iloc[-1]) else None

        # ATR（20日）
        atr = None
        if "high" in recent.columns and "low" in recent.columns:
            tr_list = []
            for i in range(1, len(recent)):
                h = float(recent.iloc[i]["high"])
                l = float(recent.iloc[i]["low"])
                pc = float(recent.iloc[i-1]["close"])
                tr_list.append(max(h - l, abs(h - pc), abs(l - pc)))
            if tr_list:
                atr = sum(tr_list[-20:]) / min(20, len(tr_list[-20:]))

        # 近5日最低价
        low_5d = float(recent.tail(5)["low"].min()) if "low" in recent.columns else None

        # 近20日最高/最低
        high_20d = float(recent.tail(20)["high"].max()) if "high" in recent.columns else None
        low_20d = float(recent.tail(20)["low"].min()) if "low" in recent.columns else None

        points = {"current_price": round(price, 2)}

        # --- 建议买入区间 ---
        buy_low = None
        buy_high = None
        if ma5 and low_5d:
            buy_low = round(min(low_5d, ma5 * 0.98), 2)
            buy_high = round(max(ma5, price * 0.99), 2)
        elif ma5:
            buy_low = round(ma5 * 0.98, 2)
            buy_high = round(price, 2)
        else:
            buy_low = round(price * 0.97, 2)
            buy_high = round(price, 2)
        points["buy_zone"] = [buy_low, buy_high]

        # --- 止损价 ---
        if atr:
            points["stop_loss_atr"] = round(price - 1.5 * atr, 2)
        # 关键支撑位
        supports = []
        if ma10:
            supports.append(("MA10", round(ma10, 2)))
        if ma20:
            supports.append(("MA20", round(ma20, 2)))
        if low_20d:
            supports.append(("20日低点", round(low_20d, 2)))
        supports_below = [(n, v) for n, v in supports if v < price]
        supports_below.sort(key=lambda x: x[1], reverse=True)
        if supports_below:
            stop_support = round(supports_below[0][1] * 0.99, 2)
            points["stop_loss_support"] = stop_support
            points["key_support"] = supports_below[0]
        # 最终止损取更合理的那个
        if "stop_loss_atr" in points and "stop_loss_support" in points:
            points["stop_loss"] = max(points["stop_loss_atr"], points["stop_loss_support"])
        elif "stop_loss_atr" in points:
            points["stop_loss"] = points["stop_loss_atr"]
        elif "stop_loss_support" in points:
            points["stop_loss"] = points["stop_loss_support"]
        else:
            points["stop_loss"] = round(price * 0.95, 2)

        # --- 破位放弃价 ---
        if ma10:
            points["invalid_price"] = round(ma10 * 0.98, 2)
        elif ma5:
            points["invalid_price"] = round(ma5 * 0.98, 2)
        else:
            points["invalid_price"] = round(price * 0.95, 2)

        # --- 目标价（止盈参考） ---
        if atr:
            points["target_1"] = round(price + 2 * atr, 2)
            points["target_2"] = round(price + 3.5 * atr, 2)
        else:
            points["target_1"] = round(price * 1.08, 2)
            points["target_2"] = round(price * 1.15, 2)
        if high_20d:
            points["resistance"] = round(high_20d, 2)

        # --- 关键价位列表 ---
        levels = []
        if points.get("target_1"):
            levels.append((points["target_1"], "目标1"))
        if points.get("resistance") and points["resistance"] > price:
            levels.append((points["resistance"], "前高压力"))
        levels.append((price, "当前价"))
        if buy_low:
            levels.append((buy_low, "买入区间下沿"))
        if supports_below:
            levels.append((supports_below[0][1], supports_below[0][0]))
        if len(supports_below) >= 2:
            levels.append((supports_below[1][1], supports_below[1][0]))
        if points.get("stop_loss"):
            levels.append((points["stop_loss"], "止损"))
        levels.sort(key=lambda x: x[0], reverse=True)
        points["key_levels"] = levels

        return points
