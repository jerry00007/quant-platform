"""
QuantWeave - 一键选股策略回测引擎

模拟完整的一键选股流水线：
  全市场扫描 → 策略信号 → 综合评分 → Top-N 选股建仓 → 持仓管理 → 止损止盈

关键设计：
  1. 预计算所有股票的策略信号（dual_ma + pullback_stable）
  2. 每日从预计算结果中提取当日买入信号股，综合评分
  3. 按评分排序取 Top-N 建仓
  4. 持仓管理：固定止损 -8% + 策略专属止盈 + 策略卖出信号
"""

import sqlite3
import sys
import time
import warnings
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from loguru import logger

warnings.filterwarnings("ignore")

CORE_SIGNALS_PATH = Path(__file__).resolve().parent.parent / "strategy"
if str(CORE_SIGNALS_PATH) not in sys.path:
    sys.path.insert(0, str(CORE_SIGNALS_PATH))

from core_signals import CORE_STRATEGIES, signals_dual_ma, signals_pullback_stable

# 使用策略
ACTIVE_STRATEGIES = {
    "dual_ma": {
        "name": "双均线交叉",
        "func": signals_dual_ma,
        "needs_full": False,
        "params": CORE_STRATEGIES["dual_ma"]["default_params"],
        "exit_config": CORE_STRATEGIES["dual_ma"]["exit_config"],
    },
    "pullback_stable": {
        "name": "回调企稳",
        "func": signals_pullback_stable,
        "needs_full": True,
        "params": CORE_STRATEGIES["pullback_stable"]["default_params"],
        "exit_config": CORE_STRATEGIES["pullback_stable"]["exit_config"],
    },
}

UNIVERSAL_STOP_LOSS = -0.08
MAX_HOLD_DAYS = 60  # 参数优化最优值（原30天 → 60天，收益+15%→+58%）

# === Round 1 新增常量 ===
# 涨停板过滤阈值（%），>=此值视为涨停无法买入
LIMIT_UP_THRESHOLD = 9.8
# 分级滑点：小市值/中等/大市值（按信号日收盘价*持仓估算总市值粗判）
SMALL_CAP_THRESHOLD = 50_0000_0000  # <50亿用0.3%滑点
MID_CAP_THRESHOLD = 200_0000_0000   # <200亿用0.2%滑点
SLIPPAGE_SMALL = 0.003   # 小市值滑点0.3%
SLIPPAGE_MID   = 0.002   # 中等市值滑点0.2%
SLIPPAGE_LARGE = 0.001   # 大市值滑点0.1%
# 印花税（仅卖出，沪市0.1%+深市0.1%，统一按0.1%）
STAMP_TAX = 0.001
# 北交所排除
BJ_EXCLUDE = True  # True=排除北交所股票


class QuickPicksBacktestEngine:
    """一键选股策略回测引擎"""

    def __init__(self, db_path=None, initial_cash=1_000_000, max_positions=5,
                 top_n=3, commission=0.0003, slippage=None, scan_interval=2,
                 stop_loss=None, max_hold_days=None,
                 stamp_tax=None, limit_up_threshold=None,
                 bj_exclude=None, enable_limit_filter=True,
                 limit_up_days=5,   # 近N日涨停过滤（Round2新增）
                 ):
        if db_path is None:
            db_path = str(Path(__file__).resolve().parent.parent.parent.parent / "quantweave.db")
        self.db_path = db_path
        self.initial_cash = initial_cash
        self.max_positions = max_positions
        self.top_n = top_n
        self.commission = commission
        self.slippage_default = slippage if slippage is not None else SLIPPAGE_LARGE
        self.scan_interval = scan_interval
        self.stop_loss = stop_loss if stop_loss is not None else UNIVERSAL_STOP_LOSS
        self.max_hold_days = max_hold_days if max_hold_days is not None else MAX_HOLD_DAYS
        self.stamp_tax = stamp_tax if stamp_tax is not None else STAMP_TAX
        self.limit_up_threshold = limit_up_threshold if limit_up_threshold is not None else LIMIT_UP_THRESHOLD
        self.bj_exclude = bj_exclude if bj_exclude is not None else BJ_EXCLUDE
        self.enable_limit_filter = enable_limit_filter
        self.limit_up_days = limit_up_days  # 近N日涨停过滤窗口
        # 实例变量：在run()里由_preload_all_data填充
        self.limit_up_dates: dict = {}  # {ts_code: set(涨停日期str)}

    def _get_slippage(self, price, shares):
        """根据持仓市值动态返回滑点"""
        total_market_value = price * shares
        if total_market_value < SMALL_CAP_THRESHOLD:
            return SLIPPAGE_SMALL
        elif total_market_value < MID_CAP_THRESHOLD:
            return SLIPPAGE_MID
        else:
            return SLIPPAGE_LARGE

    @staticmethod
    def _is_limit_up(dp_entry, threshold=None):
        """判断信号日是否涨停（收盘=最高 且 涨幅>=阈值）"""
        if threshold is None:
            threshold = LIMIT_UP_THRESHOLD
        close = dp_entry.get("close", 0)
        high = dp_entry.get("high", 0)
        prev_close = dp_entry.get("prev_close", 0)
        if prev_close <= 0 or high <= 0:
            return False
        # 方法1：涨幅判断
        change_pct = (close - prev_close) / prev_close * 100
        if change_pct >= threshold:
            return True
        # 方法2：收盘=最高（封板）
        if abs(close - high) < close * 0.001 and change_pct >= 9.5:
            return True
        return False

    # ================================================================
    # 主入口
    # ================================================================

    def run(self, start_date: str, end_date: str) -> dict:
        logger.info(f"🚀 一键选股回测: {start_date} → {end_date}")
        t0 = time.time()

        # 1. 预加载
        stock_data, stock_info = self._preload_all_data(start_date, end_date)
        if not stock_data:
            return {"error": "无可用股票数据"}
        logger.info(f"  加载 {len(stock_data)} 只, {time.time()-t0:.1f}s")

        # 1.5 预加载风控数据（夜间快照 + ST兜底）
        risk_snapshots, st_codes = self._preload_risk_data(start_date, end_date)
        has_risk = bool(risk_snapshots)
        logger.info(
            f"  风控数据: {'✅' if has_risk else '⚠️无快照，用ST兜底'}"
            f" | 快照天数={len(risk_snapshots)} | ST={len(st_codes)}只"
        )

        # 2. 交易日
        trading_dates = self._get_trading_dates(start_date, end_date)
        if not trading_dates:
            return {"error": "无可用交易日"}
        logger.info(f"  交易日 {len(trading_dates)} 天")

        # 3. 预计算信号
        t1 = time.time()
        all_signals = self._precompute_signals(stock_data)
        buy_idx, sell_idx = self._build_signal_index(all_signals)
        logger.info(f"  信号预计算完成, {time.time()-t1:.1f}s")

        # 3.5 预构建日期→行情索引（大幅加速每日查询）
        t15 = time.time()
        date_price_map = self._build_date_price_map(stock_data)
        logger.info(f"  行情索引构建完成, {time.time()-t15:.1f}s")

        # 4. 主循环
        cash = self.initial_cash
        positions = {}
        trades = []
        equity_curve = []
        daily_returns = []
        daily_pos_count = []

        for day_i, cur_date in enumerate(trading_dates):
            ds = cur_date.strftime("%Y%m%d")
            dp = date_price_map.get(ds, {})
            if not dp:
                continue

            # --- 退出检查 ---
            to_close = []
            for tc, pos in list(positions.items()):
                if tc not in dp:
                    continue
                p = dp[tc]["close"]
                h = dp[tc]["high"]
                pnl = (p - pos["cost"]) / pos["cost"]
                hold = day_i - pos["entry_day"]
                reason = self._check_exit(tc, pos, p, h, pnl, hold, ds, sell_idx)
                if reason:
                    to_close.append((tc, reason, pnl))

            for tc, reason, pnl in to_close:
                pos = positions[tc]
                actual_slip = pos.get("actual_slip", self.slippage_default)
                price = dp[tc]["close"] * (1 - actual_slip)  # 动态滑点
                amt = pos["shares"] * price
                comm = amt * self.commission
                # Round 1: 印花税单独计算（卖出时）
                stamp = amt * self.stamp_tax
                profit = amt - pos["cost"] * pos["shares"] - comm - stamp
                cash += amt - comm - stamp
                trades.append({
                    "date": ds, "direction": "sell", "ts_code": tc,
                    "stock_name": stock_info.get(tc, ""),
                    "price": round(price, 2), "volume": pos["shares"],
                    "amount": round(amt, 2), "commission": round(comm, 2),
                    "stamp_tax": round(stamp, 2),
                    "profit": round(profit, 2),
                    "signal": f"{reason} ({pnl*100:+.1f}%)",
                })
                del positions[tc]

            # --- 扫描建仓 ---
            if day_i % self.scan_interval == 0 and len(positions) < self.max_positions:
                cands = self._scan_and_score(
                    ds, day_i, buy_idx, stock_data, stock_info, positions,
                    risk_snapshots=risk_snapshots, st_codes=st_codes,
                )
                slots = self.max_positions - len(positions)
                for c in cands[:slots]:
                    tc = c["ts_code"]
                    if tc not in dp:
                        continue

                    # === Round 1: 北交所排除 ===
                    if self.bj_exclude and tc.startswith("bj"):
                        logger.info(f"  [过滤] {tc} 为北交所，排除")
                        continue

                    # === Round 1: 涨停板过滤 ===
                    entry_price, entry_date, limit_filtered = None, ds, False
                    if self.enable_limit_filter:
                        dp_entry = dp[tc]
                        if self._is_limit_up(dp_entry, self.limit_up_threshold):
                            # 涨停 → 跳过，次日开盘买入
                            # 尝试从下一交易日获取开盘价
                            next_date = trading_dates[day_i + 1].strftime("%Y%m%d") if day_i + 1 < len(trading_dates) else None
                            if next_date and next_date in date_price_map and tc in date_price_map[next_date]:
                                next_dp = date_price_map[next_date][tc]
                                # 次日若高开超过3%则放弃（追高风险太大）
                                open_price = next_dp["open"]
                                change_next = (open_price - dp_entry["close"]) / dp_entry["close"] * 100
                                if change_next > 3.0:
                                    logger.info(f"  [涨停跳过] {tc} 次日高开+{change_next:.1f}%，放弃")
                                    continue
                                entry_price = open_price * (1 + SLIPPAGE_MID)  # 次日开盘用中等滑点
                                entry_date = next_date
                                limit_filtered = True
                            else:
                                logger.info(f"  [涨停跳过] {tc} 信号日涨停{ds}，无次日数据，放弃")
                                continue

                    if entry_price is None:
                        # 正常情况：收盘价买入 + 分级滑点（先用默认大市值，待确认）
                        close_p = dp[tc]["close"]
                        entry_price = close_p * (1 + self.slippage_default)

                    budget = cash / max(slots, 1) * 0.95
                    shares = int(budget / entry_price / 100) * 100
                    if shares <= 0:
                        continue
                    cost = shares * entry_price
                    comm = cost * self.commission
                    if cost + comm > cash:
                        continue
                    cash -= cost + comm
                    # 实际滑点（分级）
                    actual_slip = self._get_slippage(entry_price, shares)
                    positions[tc] = {
                        "shares": shares, "cost": entry_price, "entry_day": day_i,
                        "entry_date": entry_date, "strategy": c.get("strategy", "dual_ma"),
                        "peak_price": entry_price, "score": c.get("score", 0),
                        "limit_filtered": limit_filtered, "actual_slip": actual_slip,
                    }
                    trades.append({
                        "date": entry_date, "direction": "buy", "ts_code": tc,
                        "stock_name": stock_info.get(tc, ""),
                        "price": round(entry_price, 2), "volume": shares,
                        "amount": round(cost, 2), "commission": round(comm, 2),
                        "signal": f"{c.get('strategy_name','')} 评分={c.get('score',0):.0f}" +
                                  (" [涨停次日开盘]" if limit_filtered else ""),
                    })

            # 更新峰值
            for tc, pos in positions.items():
                if tc in dp:
                    pos["peak_price"] = max(pos["peak_price"], dp[tc]["high"])

            # 净值
            mv = sum(positions[tc]["shares"] * dp.get(tc, {}).get("close", 0)
                     for tc in positions if tc in dp)
            tv = cash + mv
            equity_curve.append({"date": ds, "value": tv})
            daily_pos_count.append(len(positions))
            dr = (tv - equity_curve[-2]["value"]) / equity_curve[-2]["value"] if len(equity_curve) > 1 else 0
            daily_returns.append({"date": ds, "return": dr})

            if day_i % 50 == 0:
                logger.info(f"  {day_i}/{len(trading_dates)} 持仓={len(positions)} 净值={tv:,.0f}")

        # 强制平仓
        fds = trading_dates[-1].strftime("%Y%m%d")
        fp = date_price_map.get(fds, {})
        for tc, pos in list(positions.items()):
            if tc in fp:
                actual_slip = pos.get("actual_slip", self.slippage_default)
                price = fp[tc]["close"] * (1 - actual_slip)
                amt = pos["shares"] * price
                comm = amt * self.commission
                stamp = amt * self.stamp_tax
                profit = amt - pos["cost"] * pos["shares"] - comm - stamp
                cash += amt - comm - stamp
                pnl = price / pos["cost"] - 1
                trades.append({
                    "date": fds, "direction": "sell", "ts_code": tc,
                    "stock_name": stock_info.get(tc, ""),
                    "price": round(price, 2), "volume": pos["shares"],
                    "amount": round(amt, 2), "commission": round(comm, 2),
                    "stamp_tax": round(stamp, 2),
                    "profit": round(profit, 2),
                    "signal": f"回测结束平仓 ({pnl*100:+.1f}%)",
                })
        positions.clear()
        final_value = cash
        equity_curve[-1]["value"] = final_value

        # 指标
        result = self._calculate_metrics(trades, equity_curve, daily_returns, len(trading_dates), daily_pos_count)
        result["strategy_name"] = "一键选股（双均线+回调企稳）"
        result["start_date"] = start_date
        result["end_date"] = end_date
        result["max_positions"] = self.max_positions
        result["top_n"] = self.top_n
        result["risk_filter_mode"] = "snapshot" if has_risk else "st_fallback"
        result["risk_snapshot_days"] = len(risk_snapshots)
        result["risk_st_count"] = len(st_codes)
        logger.info(
            f"✅ 回测完成: 收益={result['total_return']:.2f}% 年化={result['annual_return']:.2f}% "
            f"回撤={result['max_drawdown']:.2f}% 夏普={result['sharpe_ratio']:.3f} "
            f"胜率={result['win_rate']:.1f}% 交易={result['total_trades']}次 {time.time()-t0:.1f}s"
        )
        return result

    # ================================================================
    # 数据加载
    # ================================================================

    def _preload_all_data(self, start_date, end_date):
        conn = sqlite3.connect(self.db_path)
        try:
            stocks_df = pd.read_sql("SELECT ts_code, name FROM stocks WHERE is_active = 1", conn)
            stock_info = dict(zip(stocks_df["ts_code"], stocks_df["name"]))

            # 提前250个交易日加载历史数据（策略需要MA60窗口 + prev_close计算）
            from datetime import datetime, timedelta
            sd = datetime.strptime(start_date, "%Y%m%d") - timedelta(days=250)
            hist_start = sd.strftime("%Y%m%d")

            all_daily = pd.read_sql(
                f"SELECT ts_code, trade_date, open, high, low, close, vol, "
                f"COALESCE(change_pct, 0) as change_pct "
                f"FROM stock_daily "
                f"WHERE trade_date >= '{hist_start}' AND trade_date <= '{end_date}' "
                f"ORDER BY ts_code, trade_date", conn
            )
            if all_daily.empty:
                return {}, stock_info

            # 计算 prev_close（Round1：涨停过滤依赖前收）
            for tc in all_daily["ts_code"].unique():
                mask = all_daily["ts_code"] == tc
                all_daily.loc[mask, "prev_close"] = all_daily.loc[mask, "close"].shift(1)

            # 建立涨停日期索引（Round2：近N日涨停过滤）
            limit_up_dates = {}
            for tc, grp in all_daily.groupby("ts_code"):
                dates = set(grp.loc[grp["change_pct"] >= 9.5, "trade_date"].astype(str).tolist())
                if dates:
                    limit_up_dates[tc] = dates
            self.limit_up_dates = limit_up_dates

            stock_data = {}
            for tc, grp in all_daily.groupby("ts_code"):
                df = grp.sort_values("trade_date").reset_index(drop=True)
                if len(df) >= 80:
                    stock_data[tc] = df
            return stock_data, stock_info
        finally:
            conn.close()

    def _preload_risk_data(self, start_date, end_date):
        """
        预加载风控数据：
          1. 从 stock_risk_flags 表加载回测期间内的所有风控快照
          2. 从 stocks 表加载当前 ST 股票集合（兜底方案）

        Returns:
            (risk_snapshots, st_codes)
            - risk_snapshots: {date_str: {ts_code: risk_level}}
            - st_codes: set of ST stock codes
        """
        risk_snapshots = {}
        st_codes = set()

        try:
            conn = sqlite3.connect(self.db_path)
            try:
                # 加载回测期间内的风控快照（由夜间批量扫描生成）
                rows = conn.execute(
                    "SELECT flag_date, ts_code, risk_level FROM stock_risk_flags "
                    "WHERE flag_date >= ? AND flag_date <= ?",
                    (start_date, end_date),
                ).fetchall()
                for flag_date, ts_code, risk_level in rows:
                    risk_snapshots.setdefault(flag_date, {})[ts_code] = risk_level

                # 加载当前 ST 股票（兜底）
                st_rows = conn.execute(
                    "SELECT ts_code FROM stocks WHERE is_active = 1 "
                    "AND (name LIKE '%ST%' OR name LIKE '%st%')"
                ).fetchall()
                st_codes = {r[0] for r in st_rows}
            finally:
                conn.close()
        except Exception as e:
            logger.warning(f"风控数据加载失败（跳过风控过滤）: {e}")

        return risk_snapshots, st_codes

    def _get_trading_dates(self, start_date, end_date):
        from datetime import datetime
        conn = sqlite3.connect(self.db_path)
        try:
            rows = conn.execute(
                f"SELECT DISTINCT trade_date FROM stock_daily "
                f"WHERE trade_date >= '{start_date}' AND trade_date <= '{end_date}' "
                f"ORDER BY trade_date"
            ).fetchall()
            return [datetime.strptime(r[0], "%Y%m%d") for r in rows]
        finally:
            conn.close()

    @staticmethod
    def _get_date_prices(stock_data, date_str):
        result = {}
        for tc, df in stock_data.items():
            mask = df["trade_date"].astype(str) == date_str
            if mask.any():
                row = df[mask].iloc[0]
                result[tc] = {
                    "open": float(row["open"]), "high": float(row["high"]),
                    "low": float(row["low"]), "close": float(row["close"]),
                    "vol": float(row["vol"]),
                }
        return result

    @staticmethod
    def _build_date_price_map(stock_data):
        """预构建日期→行情索引，避免每日遍历所有股票"""
        date_map = {}
        for tc, df in stock_data.items():
            for _, row in df.iterrows():
                ds = str(row["trade_date"])
                if ds not in date_map:
                    date_map[ds] = {}
                date_map[ds][tc] = {
                    "open": float(row["open"]), "high": float(row["high"]),
                    "low": float(row["low"]), "close": float(row["close"]),
                    "vol": float(row["vol"]),
                    "prev_close": float(row["prev_close"]) if "prev_close" in row and not pd.isna(row["prev_close"]) else float(row["close"]),
                }
        return date_map

    # ================================================================
    # 信号预计算
    # ================================================================

    def _precompute_signals(self, stock_data):
        all_signals = {}
        total = len(stock_data)
        for idx, (tc, df) in enumerate(stock_data.items()):
            if idx % 500 == 0:
                logger.info(f"  信号进度: {idx}/{total}")
            sigs = {}
            close = df["close"].values.astype(float)
            dates = df["trade_date"].astype(str).tolist()
            for key, cfg in ACTIVE_STRATEGIES.items():
                try:
                    if cfg["needs_full"]:
                        high = df["high"].values.astype(float)
                        low = df["low"].values.astype(float)
                        vol = df["vol"].values.astype(float)
                        open_ = df["open"].values.astype(float)
                        sigs[key] = cfg["func"](close, high, low, vol, open_, dates, cfg["params"])
                    else:
                        sigs[key] = cfg["func"](close, dates, cfg["params"])
                except Exception:
                    sigs[key] = {}
            all_signals[tc] = sigs
        return all_signals

    @staticmethod
    def _build_signal_index(all_signals):
        buy_idx, sell_idx = {}, {}
        for tc, stock_sigs in all_signals.items():
            for sk, signals in stock_sigs.items():
                for ds, st in signals.items():
                    if st == "buy":
                        buy_idx.setdefault(ds, {}).setdefault(tc, []).append(sk)
                    elif st == "sell":
                        sell_idx.setdefault(ds, {}).setdefault(tc, []).append(sk)
        return buy_idx, sell_idx

    # ================================================================
    # 评分选股
    # ================================================================

    def _scan_and_score(self, date_str, day_idx, buy_idx, stock_data, stock_info,
                        cur_positions, risk_snapshots=None, st_codes=None):
        day_buys = buy_idx.get(date_str, {})
        if not day_buys:
            return []

        # 风控过滤：获取当日快照，无快照则用ST兜底
        day_risk = risk_snapshots.get(date_str, {}) if risk_snapshots else {}
        use_st_fallback = not day_risk

        candidates = []
        for tc, strats_hit in day_buys.items():
            if tc in cur_positions:
                continue

            # === 风控过滤 ===
            if day_risk:
                # 有快照数据，用完整风控
                rl = day_risk.get(tc, "safe")
                if rl in ("block", "blocked"):
                    continue
            elif st_codes and tc in st_codes:
                # 无快照，ST兜底
                continue

            # === Round2: 近N日涨停过滤（追高风险）===
            # 信号日之前N个自然日内有涨停（非信号日本身）→ 检查是否有充分回调
            if self.limit_up_days > 0:
                lu_dates = self.limit_up_dates.get(tc, set())
                if lu_dates and date_str not in lu_dates:  # 信号日涨停由买入阶段处理
                    from datetime import datetime, timedelta
                    signal_dt = datetime.strptime(date_str, "%Y%m%d")
                    window_dates = set()
                    for delta in range(1, self.limit_up_days + 1):
                        d = signal_dt - timedelta(days=delta)
                        window_dates.add(d.strftime("%Y%m%d"))
                    recent_limit = lu_dates & window_dates
                    if recent_limit:
                        # 近N日有涨停 → 检查回调幅度
                        # 找最近涨停日，计算该日至今的最低点
                        # 若最低点比涨停价低>=2%，认为有回调，可以买；否则跳过
                        df_check = stock_data.get(tc)
                        if df_check is not None:
                            df_sub = df_check[df_check["trade_date"].astype(str) <= date_str].copy()
                            if len(df_sub) >= 5:
                                recent_low = df_sub.tail(self.limit_up_days)["low"].min()
                                limit_price = None
                                for _, row in df_sub.iloc[::-1].iterrows():
                                    pct = row.get("change_pct", 0) or 0
                                    if pct >= 9.5:
                                        limit_price = row["close"]
                                        break
                                if limit_price and recent_low >= limit_price * 0.98:
                                    # 无充分回调（最低价距涨停价<2%），排除
                                    continue

            df = stock_data.get(tc)
            if df is None:
                continue
            df_slice = df[df["trade_date"].astype(str) <= date_str].copy()
            if len(df_slice) < 60:
                continue

            score_data = _calc_score(df_slice, "")
            total_score = score_data.get("total", 0)
            if len(strats_hit) >= 2:
                total_score += 10

            candidates.append({
                "ts_code": tc,
                "name": stock_info.get(tc, ""),
                "score": total_score,
                "strategy": strats_hit[0],
                "strategy_name": ", ".join(ACTIVE_STRATEGIES.get(s, {}).get("name", s) for s in strats_hit),
                "resonance": len(strats_hit) >= 2,
            })

        candidates.sort(key=lambda x: x["score"], reverse=True)
        return candidates[:self.top_n]

    # ================================================================
    # 退出检查
    # ================================================================

    def _check_exit(self, tc, pos, cur_price, high_price, pnl_pct, hold_days, date_str, sell_idx):
        strategy = pos.get("strategy", "dual_ma")
        exit_cfg = ACTIVE_STRATEGIES.get(strategy, {}).get("exit_config", {})
        peak = pos.get("peak_price", pos["cost"])

        # 1. 止损
        if pnl_pct <= self.stop_loss:
            return f"止损"

        # 2. 超时
        if hold_days >= self.max_hold_days:
            return f"超时({hold_days}天)"

        # 3. 策略止盈
        et = exit_cfg.get("type", "fixed")
        if et == "fixed":
            if pnl_pct >= exit_cfg.get("take_profit_pct", 0.15):
                return "止盈"
        elif et == "trailing":
            tiers = exit_cfg.get("tiers", [])
            min_profit = exit_cfg.get("min_profit_pct", 0.03)
            peak_pnl = (peak - pos["cost"]) / pos["cost"]
            if peak_pnl >= min_profit:
                trail_pct = 0.05
                for tier in sorted(tiers, key=lambda t: t["profit_pct"]):
                    if peak_pnl >= tier["profit_pct"]:
                        trail_pct = tier["trail_pct"]
                dd = (peak - cur_price) / peak if peak > 0 else 0
                if dd >= trail_pct:
                    return "移动止盈"

        # 4. 策略卖出信号
        day_sells = sell_idx.get(date_str, {})
        if tc in day_sells:
            return "策略卖出"

        return None

    # ================================================================
    # 指标计算
    # ================================================================

    def _calculate_metrics(self, trades, equity_curve, daily_returns, trading_days, daily_pos_count):
        fv = equity_curve[-1]["value"] if equity_curve else self.initial_cash
        tr = (fv - self.initial_cash) / self.initial_cash * 100
        tdpy = 244
        ar = ((1 + tr / 100) ** (tdpy / max(trading_days, 1)) - 1) * 100 if trading_days > 0 else 0

        vals = [e["value"] for e in equity_curve]
        pk = vals[0] if vals else self.initial_cash
        mdd = 0
        for v in vals:
            if v > pk:
                pk = v
            dd = (pk - v) / pk * 100 if pk > 0 else 0
            if dd > mdd:
                mdd = dd

        rets = [d["return"] for d in daily_returns]
        sharpe = np.mean(rets) / np.std(rets) * np.sqrt(tdpy) if len(rets) > 1 and np.std(rets) > 0 else 0

        sells = [t for t in trades if t["direction"] == "sell" and "profit" in t]
        wins = [t for t in sells if t["profit"] > 0]
        losses = [t for t in sells if t["profit"] <= 0]
        wr = len(wins) / len(sells) * 100 if sells else 0
        aw = np.mean([t["profit"] for t in wins]) if wins else 0
        al = abs(np.mean([t["profit"] for t in losses])) if losses else 1
        plr = aw / al if al > 0 else 0

        # 卖出原因统计
        reason_stats = {}
        for t in sells:
            sig = t.get("signal", "")
            if "止损" in sig:
                reason_stats["止损"] = reason_stats.get("止损", 0) + 1
            elif "移动止盈" in sig:
                reason_stats["移动止盈"] = reason_stats.get("移动止盈", 0) + 1
            elif "止盈" in sig:
                reason_stats["固定止盈"] = reason_stats.get("固定止盈", 0) + 1
            elif "超时" in sig:
                reason_stats["超时平仓"] = reason_stats.get("超时平仓", 0) + 1
            elif "策略卖出" in sig:
                reason_stats["策略卖出"] = reason_stats.get("策略卖出", 0) + 1
            else:
                reason_stats["其他"] = reason_stats.get("其他", 0) + 1

        # 持仓天数
        hold_days = []
        pairs = {}
        for t in trades:
            if t["direction"] == "buy":
                pairs[t["ts_code"]] = t["date"]
            elif t["direction"] == "sell" and t["ts_code"] in pairs:
                try:
                    from datetime import datetime
                    d1 = datetime.strptime(pairs[t["ts_code"]], "%Y%m%d")
                    d2 = datetime.strptime(t["date"], "%Y%m%d")
                    hold_days.append((d2 - d1).days)
                except Exception:
                    pass
                del pairs[t["ts_code"]]

        return {
            "total_return": round(tr, 2),
            "annual_return": round(ar, 2),
            "max_drawdown": round(mdd, 2),
            "sharpe_ratio": round(sharpe, 3),
            "win_rate": round(wr, 2),
            "profit_loss_ratio": round(plr, 2),
            "total_trades": len(trades),
            "initial_cash": self.initial_cash,
            "final_value": round(fv, 2),
            "trades": trades,
            "equity_curve": equity_curve,
            "daily_returns": daily_returns,
            "avg_positions": round(np.mean(daily_pos_count), 1) if daily_pos_count else 0,
            "max_positions_held": max(daily_pos_count) if daily_pos_count else 0,
            "avg_hold_days": round(np.mean(hold_days), 1) if hold_days else 0,
            "sell_reason_stats": reason_stats,
        }


# ================================================================
# 综合评分函数（独立，避免依赖 QuickPicksService）
# ================================================================

def _calc_score(df: pd.DataFrame, industry: str = "") -> dict:
    """综合评分: 技术30% + 基本面25% + 消息面20% + 资金面15%"""
    if len(df) < 60:
        return {"total": 0, "advice": "数据不足"}

    closes = df["close"].values.astype(float)
    vols = df["vol"].values.astype(float)
    changes = df["change_pct"].values.astype(float)
    last = closes[-1]

    # 技术面
    ts = 50
    ma5, ma10, ma20, ma60 = (np.mean(closes[-n:]) for n in (5, 10, 20, 60))
    if ma5 > ma10 > ma20 > ma60: ts += 15
    elif ma5 > ma10 > ma20: ts += 10
    elif ma5 > ma10: ts += 5

    # MACD
    e12, e26 = float(closes[0]), float(closes[0])
    difs = []
    for c in closes:
        e12 = c * 2 / 13 + e12 * 11 / 13
        e26 = c * 2 / 27 + e26 * 25 / 27
        difs.append(e12 - e26)
    da = np.array(difs)
    dea = np.zeros(len(da))
    for i in range(1, len(da)):
        dea[i] = da[i] * 2 / 10 + dea[i - 1] * 8 / 10
    if da[-1] > dea[-1]: ts += 10
    mb = (da - dea) * 2
    if len(mb) >= 3 and mb[-1] < mb[-2] and da[-1] > dea[-1]: ts -= 5

    # RSI
    d = np.diff(closes[-15:])
    g = np.where(d > 0, d, 0)
    lo = np.where(d < 0, -d, 0)
    ag, al_ = np.mean(g[-14:]), np.mean(lo[-14:])
    rsi = 100 - (100 / (1 + ag / al_)) if al_ > 0 else 100
    if 40 <= rsi <= 60: ts += 10
    elif 30 <= rsi <= 70: ts += 5
    elif rsi > 80: ts -= 10
    elif rsi > 70: ts -= 5

    # 量比
    v5, v20 = np.mean(vols[-5:]), np.mean(vols[-20:])
    vr = v5 / v20 if v20 > 0 else 1
    if 0.8 <= vr <= 1.5: ts += 10
    elif vr > 2: ts -= 5

    # MA60偏离
    md = (last / ma60 - 1) * 100
    if abs(md) < 5: ts += 5
    elif md > 15: ts -= 10
    ts = min(100, max(0, ts))

    # 基本面
    bs = 50
    dr = changes[-30:] if len(changes) >= 30 else changes
    vol = np.std(dr) if len(dr) > 0 else 0
    if vol < 1.5: bs += 15
    elif vol < 2.5: bs += 10
    elif vol >= 4: bs -= 10

    h60, l60 = max(closes[-60:]), min(closes[-60:])
    pp = (last - l60) / (h60 - l60) * 100 if h60 != l60 else 50
    if 30 <= pp <= 70: bs += 15
    elif pp > 85: bs -= 10
    elif pp < 20: bs += 10

    y = closes[-20:]
    sl = np.polyfit(np.arange(len(y)), y, 1)[0] / last * 100
    if 0 < sl < 0.3: bs += 10
    elif sl >= 0.3: bs += 5
    elif -0.1 < sl <= 0: bs += 5
    else: bs -= 5
    bs = min(100, max(0, bs))

    # 消息面
    ns = 50
    hot = ["半导体", "人工智能", "软件", "通信", "新能源", "军工", "医药", "机器人"]
    if any(h in (industry or "") for h in hot): ns += 15
    c5 = (last / closes[-6] - 1) * 100 if len(closes) >= 6 else 0
    if 0 < c5 < 5: ns += 15
    elif c5 >= 5: ns += 5
    elif -2 < c5 <= 0: ns += 5
    elif c5 <= -5: ns -= 10
    ns = min(100, max(0, ns))

    # 资金面
    fs = 50
    if vr > 1.5: fs += 15
    elif vr > 1: fs += 10
    elif vr <= 0.7: fs -= 5
    tc_ = changes[-1] if len(changes) > 0 else 0
    if 0 < tc_ < 3: fs += 15
    elif 3 <= tc_ < 6: fs += 10
    elif -1 < tc_ <= 0: fs += 5
    elif tc_ <= -1: fs -= 10
    fs = min(100, max(0, fs))

    total = round(ts * 0.30 + bs * 0.25 + ns * 0.20 + fs * 0.15, 1)
    if total >= 80: adv = "强烈买入"
    elif total >= 65: adv = "买入/加仓"
    elif total >= 50: adv = "持有观望"
    elif total >= 35: adv = "减仓"
    else: adv = "卖出"

    return {"total": total, "tech": ts, "base": bs, "news": ns, "fund": fs, "advice": adv}
