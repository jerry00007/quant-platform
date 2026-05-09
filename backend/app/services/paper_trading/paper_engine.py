"""
QuantWeave — 超短线模拟盘引擎

完全独立于核心策略（dual_ma / pullback_stable），零耦合。
复用 ultra_short_engine.py 的信号函数 find_mode1/2/3 + calc_score + pos_pct。

使用方式:
    from app.services.paper_trading.paper_engine import PaperEngine

    engine = PaperEngine()
    engine.scan_and_buy()   # 扫描+买入（14:50 执行）
    engine.check_and_sell() # 卖出检测（09:35 执行）
    engine.status()         # 当前状态
"""
import os
import sys
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from loguru import logger

# 确保可以 import 同级模块
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

# 复用超短线回测引擎的信号函数（纯函数，无副作用）
from scripts.ultra_short_engine import (
    find_mode1, find_mode2, find_mode3,
    calc_score, pos_pct, recent_limit_up,
    is_bj, limit_threshold, is_20cm, _f,
    LIMIT_UP_THRESHOLD_MAIN, LIMIT_UP_THRESHOLD_20CM,
)

# 雪球实时行情
try:
    from app.services.data.xueqiu_data import (
        get_realtime_quote, batch_realtime_quotes, get_index_quotes
    )
    _HAS_XUEQIU = True
except ImportError:
    _HAS_XUEQIU = False

DB_PATH = Path(__file__).resolve().parent.parent.parent.parent / "quantweave.db"

# 模拟盘参数
INITIAL_CAPITAL = 700_000.0  # 70万初始资金
COMMISSION = 0.0003          # 佣金万三
STAMP_TAX = 0.001            # 印花税千一
SLIPPAGE = 0.0001            # 滑点万分之一
STOP_LOSS = -0.05            # -5% 硬止损
MAX_HOLD_DAYS = 2            # 最长持有2天
MAX_POSITIONS = 3            # 最多同时持有3只
MAX_TOTAL_POS = 0.50         # 总仓位不超过50%


class PaperEngine:
    """超短线模拟盘引擎"""

    def __init__(self, db_path: str = None):
        self.db_path = db_path or str(DB_PATH)
        self._ensure_tables()

    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _ensure_tables(self):
        """确保模拟盘表存在"""
        conn = self._conn()
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS paper_account (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE DEFAULT 'ultra_short',
                    total_assets REAL NOT NULL DEFAULT 700000.0,
                    cash_balance REAL NOT NULL DEFAULT 700000.0,
                    initial_capital REAL NOT NULL DEFAULT 700000.0,
                    total_profit REAL DEFAULT 0.0,
                    total_profit_pct REAL DEFAULT 0.0,
                    max_drawdown REAL DEFAULT 0.0,
                    peak_assets REAL DEFAULT 700000.0,
                    total_trades INTEGER DEFAULT 0,
                    win_trades INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS paper_positions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts_code TEXT NOT NULL,
                    name TEXT,
                    volume INTEGER NOT NULL,
                    avg_cost REAL NOT NULL,
                    current_price REAL,
                    market_value REAL,
                    profit REAL DEFAULT 0.0,
                    profit_pct REAL DEFAULT 0.0,
                    mode TEXT NOT NULL,
                    mode_name TEXT,
                    score INTEGER DEFAULT 0,
                    limit_up_close REAL DEFAULT 0.0,
                    limit_up_low REAL DEFAULT 0.0,
                    peak_price REAL,
                    partial_sold INTEGER DEFAULT 0,
                    entry_date TEXT,
                    hold_days INTEGER DEFAULT 0,
                    is_active INTEGER DEFAULT 1,
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS paper_trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts_code TEXT NOT NULL,
                    name TEXT,
                    direction TEXT NOT NULL,
                    price REAL NOT NULL,
                    volume INTEGER NOT NULL,
                    amount REAL,
                    commission REAL DEFAULT 0.0,
                    tax REAL DEFAULT 0.0,
                    net_amount REAL,
                    profit REAL,
                    profit_pct REAL,
                    mode TEXT,
                    mode_name TEXT,
                    score INTEGER,
                    reason TEXT,
                    trade_date TEXT,
                    created_at TEXT DEFAULT (datetime('now'))
                );
            """)
            # 初始化账户（如果不存在）
            row = conn.execute("SELECT COUNT(*) FROM paper_account").fetchone()
            if row[0] == 0:
                conn.execute("""
                    INSERT INTO paper_account (name, total_assets, cash_balance, initial_capital, peak_assets)
                    VALUES ('ultra_short', ?, ?, ?, ?)
                """, (INITIAL_CAPITAL, INITIAL_CAPITAL, INITIAL_CAPITAL, INITIAL_CAPITAL))
            conn.commit()
        finally:
            conn.close()

    def _get_account(self, conn) -> dict:
        """获取账户信息"""
        row = conn.execute("SELECT * FROM paper_account WHERE name='ultra_short'").fetchone()
        if not row:
            return {}
        cols = ["id", "name", "total_assets", "cash_balance", "initial_capital",
                "total_profit", "total_profit_pct", "max_drawdown", "peak_assets",
                "total_trades", "win_trades", "created_at", "updated_at"]
        return dict(zip(cols, row))

    def _update_account(self, conn, cash_change: float = 0, trade_profit: float = None):
        """更新账户资金"""
        acc = self._get_account(conn)
        if not acc:
            return

        new_cash = acc["cash_balance"] + cash_change

        # 计算持仓市值
        positions = conn.execute(
            "SELECT volume, avg_cost, current_price FROM paper_positions WHERE is_active=1"
        ).fetchall()
        mv = 0
        for vol, cost, price in positions:
            mv += vol * (price if price and price > 0 else cost)

        new_total = new_cash + mv
        new_profit = new_total - acc["initial_capital"]
        new_profit_pct = new_profit / acc["initial_capital"] * 100 if acc["initial_capital"] else 0
        new_peak = max(acc["peak_assets"], new_total)
        dd = (new_peak - new_total) / new_peak * 100 if new_peak else 0
        max_dd = max(acc["max_drawdown"], dd)

        # 更新胜率统计
        new_total_trades = acc["total_trades"]
        new_win_trades = acc["win_trades"]
        if trade_profit is not None:
            new_total_trades += 1
            if trade_profit > 0:
                new_win_trades += 1

        conn.execute("""
            UPDATE paper_account SET
                total_assets=?, cash_balance=?, total_profit=?, total_profit_pct=?,
                max_drawdown=?, peak_assets=?, total_trades=?, win_trades=?,
                updated_at=datetime('now')
            WHERE name='ultra_short'
        """, (new_total, new_cash, new_profit, new_profit_pct,
              max_dd, new_peak, new_total_trades, new_win_trades))

    def _get_stock_name(self, ts_code: str, conn) -> str:
        """获取股票名称"""
        row = conn.execute("SELECT name FROM stocks WHERE ts_code=?", (ts_code,)).fetchone()
        return row[0] if row and row[0] else ts_code

    # ============================================================
    # 数据加载（复用 ultra_short_engine 的逻辑）
    # ============================================================

    def _load_stock_data(self, lookback_days=180):
        """加载全市场行情数据，计算均线"""
        conn = self._conn()
        try:
            # 获取最新交易日
            latest = conn.execute(
                "SELECT MAX(trade_date) FROM stock_daily"
            ).fetchone()[0]
            if not latest:
                return {}, {}, latest

            hs = (datetime.strptime(latest, "%Y%m%d") - timedelta(lookback_days)).strftime("%Y%m%d")
            ad = pd.read_sql(
                f"SELECT ts_code, trade_date, open, high, low, close, vol, "
                f"COALESCE(change_pct,0) as change_pct "
                f"FROM stock_daily WHERE trade_date >= '{hs}' AND trade_date <= '{latest}' "
                f"ORDER BY ts_code, trade_date", conn)

            if ad.empty:
                return {}, {}, latest

            sdf = pd.read_sql("SELECT ts_code, name FROM stocks WHERE is_active = 1", conn)
            sinfo = dict(zip(sdf["ts_code"], sdf["name"]))

            sd2 = {}
            for tc, g in ad.groupby("ts_code"):
                g2 = g.sort_values("trade_date").reset_index(drop=True)
                if len(g2) < 60:
                    continue
                for w, name in [(5, "ma5"), (10, "ma10"), (20, "ma20"), (60, "ma60")]:
                    g2[name] = g2["close"].rolling(w, min_periods=w).mean()
                sd2[tc] = g2

            return sd2, sinfo, latest
        finally:
            conn.close()

    def _get_recent_dates(self, n=10):
        """获取最近n个交易日"""
        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT DISTINCT trade_date FROM stock_daily ORDER BY trade_date DESC LIMIT ?", (n,)
            ).fetchall()
            return [r[0] for r in reversed(rows)]
        finally:
            conn.close()

    def _build_date_index(self, all_dates):
        """构建日期索引"""
        adi = {d: i for i, d in enumerate(all_dates)}
        return adi

    # ============================================================
    # 1. 扫描 + 买入（14:50 执行）
    # ============================================================

    def scan_and_buy(self) -> str:
        """扫描信号并模拟买入"""
        logger.info("📝 [模拟盘] 开始扫描超短线信号...")
        t0 = time.time()

        sdata, sinfo, latest_date = self._load_stock_data()
        if not sdata:
            msg = "📝 [模拟盘] 无行情数据，跳过扫描"
            logger.warning(msg)
            return msg

        # 构建日期索引
        all_dates = []
        for tc, df in sdata.items():
            all_dates.extend(df["trade_date"].tolist())
            break  # 只需要一只股的日期列表
        if not all_dates:
            # 用数据库直接查
            conn2 = self._conn()
            try:
                rows = conn2.execute(
                    "SELECT DISTINCT trade_date FROM stock_daily ORDER BY trade_date"
                ).fetchall()
                all_dates = [r[0] for r in rows]
            finally:
                conn2.close()

        adi = self._build_date_index(all_dates)
        ds = latest_date

        # 构建 didx
        idx = adi.get(ds)
        if idx is None:
            msg = f"📝 [模拟盘] 无法定位日期索引: {ds}"
            logger.warning(msg)
            return msg

        didx = {"date": ds}
        for n in range(1, 11):
            if idx >= n:
                didx[f"prev_{n}_date"] = all_dates[idx - n]

        # 三模式扫描
        candidates = []
        candidates.extend(find_mode1(ds, didx, sdata, sinfo))
        candidates.extend(find_mode2(ds, didx, sdata, sinfo))
        candidates.extend(find_mode3(ds, didx, sdata, sinfo))

        # 去重（同股票取最高分）
        seen = {}
        for c in candidates:
            tc = c["ts_code"]
            if tc not in seen or c["score"] > seen[tc]["score"]:
                seen[tc] = c
        candidates = sorted(seen.values(), key=lambda x: -x["score"])

        logger.info(f"📝 [模拟盘] 扫描完成: {len(candidates)}只候选, {time.time()-t0:.1f}s")

        # 模拟买入
        conn = self._conn()
        try:
            acc = self._get_account(conn)
            active_positions = conn.execute(
                "SELECT ts_code, volume, avg_cost FROM paper_positions WHERE is_active=1"
            ).fetchall()
            active_codes = {r[0] for r in active_positions}

            # 当前持仓市值
            existing_mv = sum(r[1] * r[2] for r in active_positions)

            bought = []
            for c in candidates:
                if len(active_codes) >= MAX_POSITIONS:
                    break
                tc = c["ts_code"]
                if tc in active_codes:
                    continue

                pp = pos_pct(c["score"])
                if pp <= 0:
                    continue

                tgt_val = acc["initial_capital"] * pp
                if (existing_mv + tgt_val) / acc["initial_capital"] > MAX_TOTAL_POS:
                    continue

                # 获取实时价格（买入用实时价）
                buy_price = None
                if _HAS_XUEQIU:
                    q = get_realtime_quote(tc)
                    if q and q.get("current", 0) > 0:
                        buy_price = q["current"]

                # 无实时价格则用收盘价
                if not buy_price:
                    buy_price = c["close"]

                buy_price *= (1 + SLIPPAGE)  # 滑点

                budget = min(tgt_val, acc["cash_balance"] * 0.95)
                shares = int(budget / buy_price / 100) * 100
                if shares <= 0:
                    continue

                cost = shares * buy_price
                total_cost = cost * (1 + COMMISSION)
                if total_cost > acc["cash_balance"]:
                    continue

                # 记录买入
                name = self._get_stock_name(tc, conn)
                conn.execute("""
                    INSERT INTO paper_positions
                    (ts_code, name, volume, avg_cost, current_price, market_value,
                     mode, mode_name, score, limit_up_close, limit_up_low,
                     peak_price, partial_sold, entry_date, hold_days, is_active)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, 0, 1)
                """, (tc, name, shares, buy_price, buy_price, cost,
                      c["mode"], c.get("mode_name", c["mode"]), c["score"],
                      c.get("limit_up_close", 0), c.get("limit_up_low", 0),
                      buy_price, ds))

                conn.execute("""
                    INSERT INTO paper_trades
                    (ts_code, name, direction, price, volume, amount, commission, tax,
                     net_amount, mode, mode_name, score, reason, trade_date)
                    VALUES (?, ?, 'buy', ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?)
                """, (tc, name, buy_price, shares, cost, cost * COMMISSION,
                      cost * (1 + COMMISSION), c["mode"], c.get("mode_name", c["mode"]),
                      c["score"], f"{c.get('mode_name', c['mode'])} 评分={c['score']}", ds))

                self._update_account(conn, cash_change=-total_cost)
                conn.commit()

                active_codes.add(tc)
                existing_mv += cost
                bought.append({
                    "ts_code": tc, "name": name, "price": buy_price,
                    "shares": shares, "mode": c.get("mode_name", c["mode"]),
                    "score": c["score"]
                })
                logger.info(f"📝 [模拟盘] 买入 {name}({tc}) {shares}股 @{buy_price:.2f} "
                            f"| {c.get('mode_name', c['mode'])} 评分={c['score']}")

            # 生成报告
            report_lines = [
                "=" * 45,
                f"📝 [模拟盘] 超短线扫描 | {ds}",
                "=" * 45,
                "",
                f"📊 扫描结果: {len(candidates)}只候选",
            ]

            if bought:
                report_lines.append(f"✅ 今日买入: {len(bought)}只")
                for b in bought:
                    arrow = "🔴"
                    report_lines.append(
                        f"  {arrow} {b['name']}({b['ts_code']}) "
                        f"@{b['price']:.2f} ×{b['shares']}股 "
                        f"| {b['mode']} 评分={b['score']}"
                    )
            else:
                report_lines.append("⚪ 今日无符合条件的新买入")

            report_lines.append("")
            report_lines.append(f"💰 账户资金: {acc['cash_balance']:.0f}元")
            report_lines.append(f"📋 持仓: {len(active_codes)}只")
            report_lines.append("")
            report_lines.append("⚠️ 模拟盘交易，仅供验证策略")

            text = "\n".join(report_lines)
            logger.info(f"📝 [模拟盘] 扫描完成: 买入{len(bought)}只, {time.time()-t0:.1f}s")
            return text

        finally:
            conn.close()

    # ============================================================
    # 2. 卖出检测（09:35 执行）
    # ============================================================

    def check_and_sell(self) -> str:
        """检测持仓的卖出信号并执行"""
        logger.info("📝 [模拟盘] 开始卖出检测...")
        t0 = time.time()

        conn = self._conn()
        try:
            positions = conn.execute(
                "SELECT id, ts_code, name, volume, avg_cost, current_price, mode, mode_name, "
                "score, limit_up_close, limit_up_low, peak_price, partial_sold, "
                "entry_date, hold_days "
                "FROM paper_positions WHERE is_active=1"
            ).fetchall()

            if not positions:
                return "📝 [模拟盘] 无持仓，跳过卖出检测"

            today = datetime.now().strftime("%Y%m%d")

            # 批量获取实时行情
            codes = [p[1] for p in positions]
            quotes = {}
            if _HAS_XUEQIU:
                try:
                    quotes = batch_realtime_quotes(codes)
                except Exception:
                    pass

            sold = []
            for pos in positions:
                (pid, tc, name, vol, avg_cost, cur_price, mode, mode_name,
                 score, lul_close, lul_low, peak_price, partial_sold,
                 entry_date, hold_days) = pos

                # 获取实时价格
                q = quotes.get(tc, {})
                rt_price = q.get("current", 0) if q else 0
                if rt_price <= 0:
                    rt_price = cur_price or avg_cost

                # 用实时价中的 high/low（雪球有当日高低）
                rt_high = q.get("high", rt_price) if q else rt_price
                rt_low = q.get("low", rt_price) if q else rt_price

                # 计算盈亏
                pnl = (rt_price - avg_cost) / avg_cost
                new_hold_days = hold_days + 1
                new_peak = max(peak_price or rt_price, rt_high)

                # 更新持仓的实时价格和天数
                conn.execute("""
                    UPDATE paper_positions SET
                        current_price=?, market_value=?, profit=?, profit_pct=?,
                        peak_price=?, hold_days=?, updated_at=datetime('now')
                    WHERE id=?
                """, (rt_price, vol * rt_price, vol * (rt_price - avg_cost),
                      pnl * 100, new_peak, new_hold_days, pid))

                # 检查卖出条件
                reason = self._check_exit(
                    pnl, rt_low, lul_low, partial_sold, new_hold_days, new_peak, avg_cost
                )

                if reason:
                    sell_price = rt_price * (1 - SLIPPAGE)
                    gross = vol * sell_price
                    commission = gross * COMMISSION
                    tax = gross * STAMP_TAX
                    net = gross - commission - tax
                    profit = net - avg_cost * vol
                    profit_pct = profit / (avg_cost * vol) * 100

                    # 记录卖出
                    conn.execute("""
                        INSERT INTO paper_trades
                        (ts_code, name, direction, price, volume, amount, commission, tax,
                         net_amount, profit, profit_pct, mode, mode_name, score, reason, trade_date)
                        VALUES (?, ?, 'sell', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (tc, name, sell_price, vol, gross, commission, tax,
                          net, profit, profit_pct, mode, mode_name, score,
                          f"{reason} ({pnl*100:+.1f}%)", today))

                    # 平仓
                    conn.execute("UPDATE paper_positions SET is_active=0 WHERE id=?", (pid,))

                    self._update_account(conn, cash_change=net, trade_profit=profit)
                    conn.commit()

                    sold.append({
                        "ts_code": tc, "name": name, "price": sell_price,
                        "profit": profit, "profit_pct": profit_pct,
                        "reason": reason, "mode": mode_name
                    })
                    logger.info(f"📝 [模拟盘] 卖出 {name}({tc}) {vol}股 @{sell_price:.2f} "
                                f"| 盈亏{profit:+.0f}元({profit_pct:+.1f}%) | {reason}")
                else:
                    conn.commit()

            # 生成报告
            report_lines = [
                "=" * 45,
                f"📝 [模拟盘] 卖出检测 | {today}",
                "=" * 45,
                "",
                f"📋 持仓检查: {len(positions)}只",
            ]

            if sold:
                report_lines.append(f"⚡ 执行卖出: {len(sold)}只")
                for s in sold:
                    arrow = "🔴" if s["profit"] > 0 else "🟢"
                    report_lines.append(
                        f"  {arrow} {s['name']}({s['ts_code']}) "
                        f"@{s['price']:.2f} {s['profit']:+.0f}元({s['profit_pct']:+.1f}%) "
                        f"| {s['reason']}"
                    )
            else:
                report_lines.append("✅ 无触发卖出，继续持有")

            # 显示剩余持仓
            remaining = conn.execute(
                "SELECT ts_code, name, volume, avg_cost, current_price, profit_pct, hold_days "
                "FROM paper_positions WHERE is_active=1"
            ).fetchall()
            if remaining:
                report_lines.append("")
                report_lines.append(f"📊 剩余持仓: {len(remaining)}只")
                for r in remaining:
                    arrow = "🔴" if (r[5] or 0) > 0 else "🟢"
                    report_lines.append(
                        f"  {arrow} {r[1]}({r[0]}) {r[4]:.2f} "
                        f"成本{r[3]:.2f} {arrow}{r[5]:+.1f}% 持{r[6]}天"
                    )

            report_lines.append("")
            report_lines.append("⚠️ 模拟盘交易，仅供验证策略")

            text = "\n".join(report_lines)
            logger.info(f"📝 [模拟盘] 卖出检测完成: 卖出{len(sold)}只, {time.time()-t0:.1f}s")
            return text

        finally:
            conn.close()

    def _check_exit(self, pnl, low, lul_low, partial_sold, hold_days, peak_price, avg_cost):
        """检查卖出条件（与回测引擎一致）"""
        # 硬止损
        if pnl <= STOP_LOSS:
            return "止损"
        # 破涨停低点
        if lul_low > 0 and low < lul_low:
            return "破涨停低点"
        # 分段止盈
        if not partial_sold:
            if pnl >= 0.08:
                return "止盈+8%"
            if pnl >= 0.05:
                return "止盈+5%(部分)"
            if pnl >= 0.03:
                return "止盈+3%(部分)"
        else:
            if pnl >= 0.08:
                return "止盈+8%"
            if pnl >= 0.05:
                return "止盈+5%(剩余)"
        # 移动止盈：从峰值回落3%
        if peak_price and avg_cost:
            peak_pnl = (peak_price - avg_cost) / avg_cost
            if peak_pnl >= 0.05 and (peak_price - low) / peak_price >= 0.03:
                return "移动止盈"
        # 超时
        if hold_days >= MAX_HOLD_DAYS:
            return f"超时{hold_days}天"
        return None

    # ============================================================
    # 3. 状态查询
    # ============================================================

    def status(self) -> str:
        """获取模拟盘当前状态"""
        conn = self._conn()
        try:
            acc = self._get_account(conn)
            if not acc:
                return "📝 [模拟盘] 账户未初始化"

            positions = conn.execute(
                "SELECT ts_code, name, volume, avg_cost, current_price, profit_pct, "
                "mode_name, score, hold_days FROM paper_positions WHERE is_active=1"
            ).fetchall()

            # 今日交易
            today = datetime.now().strftime("%Y%m%d")
            today_trades = conn.execute(
                "SELECT ts_code, name, direction, price, volume, profit, reason "
                "FROM paper_trades WHERE trade_date=?", (today,)
            ).fetchall()

            # 统计
            total_return = acc["total_profit_pct"]
            wr = acc["win_trades"] / acc["total_trades"] * 100 if acc["total_trades"] else 0

            lines = [
                "=" * 45,
                f"📝 [模拟盘] 账户概览 | {datetime.now().strftime('%Y-%m-%d')}",
                "=" * 45,
                "",
                f"💰 初始资金: {acc['initial_capital']/10000:.1f}万",
                f"📊 总资产: {acc['total_assets']/10000:.2f}万",
                f"💵 可用现金: {acc['cash_balance']/10000:.2f}万",
                f"📈 累计收益: {total_return:+.2f}%",
                f"📉 最大回撤: {acc['max_drawdown']:.2f}%",
                f"🎯 胜率: {wr:.1f}% ({acc['win_trades']}/{acc['total_trades']}笔)",
                "",
            ]

            if positions:
                lines.append(f"📋 当前持仓: {len(positions)}只")
                # 获取实时行情
                quotes = {}
                if _HAS_XUEQIU:
                    try:
                        codes = [p[0] for p in positions]
                        quotes = batch_realtime_quotes(codes)
                    except Exception:
                        pass

                for p in positions:
                    tc, name, vol, cost, cur, pnl_pct, mode_name, score, hold = p
                    q = quotes.get(tc, {})
                    rt_price = q.get("current", cur or cost)
                    chg = q.get("percent", 0)
                    real_pnl = (rt_price - cost) / cost * 100 if cost else 0
                    arrow = "🔴" if real_pnl > 0 else "🟢"
                    lines.append(
                        f"  {arrow} {name}({tc}) {rt_price:.2f}({chg:+.2f}%) "
                        f"成本{cost:.2f} {arrow}{real_pnl:+.1f}% "
                        f"| {mode_name} 评分{score} 持{hold}天"
                    )
                lines.append("")
            else:
                lines.append("📋 当前无持仓")
                lines.append("")

            if today_trades:
                lines.append(f"📊 今日交易: {len(today_trades)}笔")
                for t in today_trades:
                    tc, name, direction, price, vol, profit, reason = t
                    d = "买入" if direction == "buy" else "卖出"
                    profit_str = f" 盈亏{profit:+.0f}元" if profit else ""
                    lines.append(f"  • {d} {name}({tc}) @{price:.2f} ×{vol}{profit_str}")
                lines.append("")

            lines.append("⚠️ 模拟盘交易，仅供验证策略")
            return "\n".join(lines)

        finally:
            conn.close()

    def get_status_data(self) -> dict:
        """获取模拟盘状态数据（供API调用）"""
        conn = self._conn()
        try:
            acc = self._get_account(conn)
            positions = conn.execute(
                "SELECT ts_code, name, volume, avg_cost, current_price, profit_pct, "
                "mode_name, score, hold_days, entry_date "
                "FROM paper_positions WHERE is_active=1"
            ).fetchall()

            # 最近交易
            recent_trades = conn.execute(
                "SELECT ts_code, name, direction, price, volume, profit, profit_pct, "
                "mode_name, reason, trade_date "
                "FROM paper_trades ORDER BY id DESC LIMIT 20"
            ).fetchall()

            return {
                "account": acc,
                "positions": [
                    {
                        "ts_code": p[0], "name": p[1], "volume": p[2],
                        "avg_cost": p[3], "current_price": p[4], "profit_pct": p[5],
                        "mode_name": p[6], "score": p[7], "hold_days": p[8],
                        "entry_date": p[9]
                    }
                    for p in positions
                ],
                "recent_trades": [
                    {
                        "ts_code": t[0], "name": t[1], "direction": t[2],
                        "price": t[3], "volume": t[4], "profit": t[5],
                        "profit_pct": t[6], "mode_name": t[7], "reason": t[8],
                        "trade_date": t[9]
                    }
                    for t in recent_trades
                ]
            }
        finally:
            conn.close()


# ============================================================
# CLI 直接运行
# ============================================================

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="超短线模拟盘")
    parser.add_argument("--scan", action="store_true", help="扫描+买入")
    parser.add_argument("--sell", action="store_true", help="卖出检测")
    parser.add_argument("--status", action="store_true", help="查看状态")
    parser.add_argument("--db", default=str(DB_PATH), help="数据库路径")
    args = parser.parse_args()

    engine = PaperEngine(args.db)

    if args.scan:
        text = engine.scan_and_buy()
        print(text)
        try:
            from app.utils.wechat_notify import send_trading_report
            send_trading_report("📝模拟盘扫描", text)
        except Exception:
            pass
    elif args.sell:
        text = engine.check_and_sell()
        print(text)
        try:
            from app.utils.wechat_notify import send_trading_report
            send_trading_report("📝模拟盘卖出", text)
        except Exception:
            pass
    elif args.status:
        print(engine.status())
    else:
        parser.print_help()
