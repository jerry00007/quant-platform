"""
QuantWeave — 交易跟踪池服务

核心功能：
1. 选股信号自动入池
2. 每日卖出信号检测 + 提醒
3. 个股操作指南生成（买入位/止损位/止盈位）
4. 跟踪池生命周期管理
5. 选股胜率统计闭环

数据流：
  选股信号 → 入池 → 每日检测卖出信号 → 出池
                    ↓
              操作指南（止损/止盈/持有周期）
                    ↓
              胜率统计 → 反馈到策略权重
"""
import sqlite3
import json
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from loguru import logger

# 雪球实时行情（可选依赖，不可用时不影响收盘价逻辑）
try:
    from app.services.data.xueqiu_data import get_realtime_quote, batch_realtime_quotes
    _HAS_XUEQIU = True
except ImportError:
    _HAS_XUEQIU = False


# ============================================================
# 数据模型（直接用 SQLite，与 quantweave.db 统一）
# ============================================================

TRACKING_POOL_DDL = """
CREATE TABLE IF NOT EXISTS tracking_pool (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_code TEXT NOT NULL,
    stock_name TEXT DEFAULT '',
    strategy TEXT NOT NULL,
    signal_date TEXT NOT NULL,
    signal_price REAL NOT NULL,
    status TEXT DEFAULT 'tracking',
    stop_loss_price REAL DEFAULT 0,
    take_profit_price REAL DEFAULT 0,
    buy_suggestion_price REAL DEFAULT 0,
    hold_days_suggest TEXT DEFAULT '',
    reason TEXT DEFAULT '',
    topic_tags TEXT DEFAULT '',
    actual_buy_price REAL DEFAULT 0,
    actual_buy_date TEXT DEFAULT '',
    actual_sell_price REAL DEFAULT 0,
    actual_sell_date TEXT DEFAULT '',
    sell_reason TEXT DEFAULT '',
    max_profit_pct REAL DEFAULT 0,
    max_loss_pct REAL DEFAULT 0,
    current_price REAL DEFAULT 0,
    current_pnl_pct REAL DEFAULT 0,
    exit_type TEXT DEFAULT 'fixed',
    exit_config_json TEXT DEFAULT '',
    peak_price REAL DEFAULT 0,
    notes TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    UNIQUE(ts_code, strategy, signal_date)
);

CREATE INDEX IF NOT EXISTS idx_tp_status ON tracking_pool(status);
CREATE INDEX IF NOT EXISTS idx_tp_signal_date ON tracking_pool(signal_date);
CREATE INDEX IF NOT EXISTS idx_tp_ts_code ON tracking_pool(ts_code);

CREATE TABLE IF NOT EXISTS tracking_daily_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tracking_id INTEGER NOT NULL,
    log_date TEXT NOT NULL,
    close_price REAL DEFAULT 0,
    high_price REAL DEFAULT 0,
    low_price REAL DEFAULT 0,
    pnl_pct REAL DEFAULT 0,
    signal TEXT DEFAULT '',
    note TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS tracking_performance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy TEXT NOT NULL,
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    total_signals INTEGER DEFAULT 0,
    total_tracked INTEGER DEFAULT 0,
    win_count INTEGER DEFAULT 0,
    loss_count INTEGER DEFAULT 0,
    win_rate REAL DEFAULT 0,
    avg_profit_pct REAL DEFAULT 0,
    avg_loss_pct REAL DEFAULT 0,
    avg_hold_days REAL DEFAULT 0,
    best_trade_pct REAL DEFAULT 0,
    worst_trade_pct REAL DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);
"""


class TrackingPoolService:
    """交易跟踪池服务"""

    def __init__(self, db_path: str = "quantweave.db"):
        self.db_path = db_path
        self._ensure_tables()

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _ensure_tables(self):
        conn = self._get_conn()
        conn.executescript(TRACKING_POOL_DDL)
        conn.close()

    # ============================================================
    # 1. 入池 — 选股信号自动加入跟踪池
    # ============================================================

    def add_to_pool(
        self,
        ts_code: str,
        strategy: str,
        signal_date: str,
        signal_price: float,
        stock_name: str = "",
        reason: str = "",
        topic_tags: str = "",
    ) -> int:
        """将选股信号加入跟踪池，同时生成操作指南"""
        conn = self._get_conn()

        # 检查是否已在池中（同策略同日期）
        existing = conn.execute(
            "SELECT id FROM tracking_pool WHERE ts_code=? AND strategy=? AND signal_date=?",
            (ts_code, strategy, signal_date),
        ).fetchone()
        if existing:
            conn.close()
            return existing[0]

        # 生成操作指南
        guide = self._generate_operation_guide(ts_code, signal_price, strategy, conn)

        conn.execute(
            """INSERT INTO tracking_pool
               (ts_code, stock_name, strategy, signal_date, signal_price,
                stop_loss_price, take_profit_price, buy_suggestion_price,
                hold_days_suggest, reason, topic_tags, status,
                exit_type, exit_config_json, peak_price)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'tracking', ?, ?, ?)""",
            (
                ts_code, stock_name, strategy, signal_date, signal_price,
                guide["stop_loss"], guide["take_profit"], guide["buy_price"],
                guide["hold_days"], reason, topic_tags,
                guide.get("exit_type", "fixed"), guide.get("exit_config", "{}"),
                signal_price,  # 初始 peak = 信号价
            ),
        )
        pool_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()
        conn.close()

        logger.info(f"📥 入池: {ts_code} | 策略:{strategy} | 止损:{guide['stop_loss']:.2f} | 止盈:{guide['take_profit']:.2f}")
        return pool_id

    def batch_add_signals(
        self, signals: List[Dict], signal_date: str
    ) -> Dict[str, int]:
        """批量将选股信号入池"""
        result = {"added": 0, "skipped": 0, "errors": 0}
        for sig in signals:
            try:
                pool_id = self.add_to_pool(
                    ts_code=sig["code"],
                    strategy=sig.get("strategy", "unknown"),
                    signal_date=signal_date,
                    signal_price=sig.get("close", 0),
                    stock_name=sig.get("name", ""),
                    reason=sig.get("reason", ""),
                    topic_tags=sig.get("topic_tags", ""),
                )
                if pool_id:
                    result["added"] += 1
                else:
                    result["skipped"] += 1
            except Exception as e:
                logger.warning(f"入池失败 {sig.get('code', '?')}: {e}")
                result["errors"] += 1
        return result

    # ============================================================
    # 2. 操作指南生成
    # ============================================================

    def _generate_operation_guide(
        self, ts_code: str, current_price: float, strategy: str, conn
    ) -> Dict:
        """根据策略类型和技术指标生成操作指南"""
        # 获取最近60天数据
        df = pd.read_sql(
            "SELECT trade_date, open, high, low, close, vol FROM stock_daily "
            "WHERE ts_code=? ORDER BY trade_date DESC LIMIT 60",
            conn,
            params=(ts_code,),
        )
        if df.empty or len(df) < 10:
            return {
                "buy_price": round(current_price, 2),
                "stop_loss": round(current_price * 0.93, 2),
                "take_profit": round(current_price * 1.15, 2),
                "hold_days": "3-10天",
            }

        df = df.sort_values("trade_date").reset_index(drop=True)
        closes = df["close"].values.astype(float)
        highs = df["high"].values.astype(float)
        lows = df["low"].values.astype(float)

        # 计算关键均线
        ma5 = np.mean(closes[-5:]) if len(closes) >= 5 else current_price
        ma10 = np.mean(closes[-10:]) if len(closes) >= 10 else current_price
        ma20 = np.mean(closes[-20:]) if len(closes) >= 20 else current_price
        ma60 = np.mean(closes[-60:]) if len(closes) >= 60 else current_price

        # ATR(14)
        atr = self._calc_atr(highs, lows, closes, 14)

        # 根据策略类型确定止损止盈逻辑
        # 止盈配置来自 core_signals.CORE_STRATEGIES.exit_config（回测验证最优）
        if strategy in ("pullback_stable", "回调企稳"):
            # 回调企稳：宽幅移动止盈v3（回测+99.55%/夏普1.591）
            stop_loss = round(min(current_price * 0.93, ma10 * 0.97), 2)
            take_profit = round(current_price * 1.30, 2)  # 目标价（移动止盈的参考上限）
            buy_price = round(max(ma5, current_price * 0.98), 2)
            hold_days = "5-15天（波段）"
            exit_type = "trailing"
            exit_config = json.dumps({
                "tiers": [
                    {"profit_pct": 0.05, "trail_pct": 0.05},
                    {"profit_pct": 0.15, "trail_pct": 0.03},
                    {"profit_pct": 0.30, "trail_pct": 0.02},
                ],
                "min_profit_pct": 0.03,
            })
        elif strategy in ("dual_ma", "双均线交叉"):
            # 双均线：固定+15%止盈最优（回测+101.44%，移动止盈反降）
            stop_loss = round(max(current_price * 0.93, ma5 * 0.97), 2)
            take_profit = round(current_price * 1.15, 2)
            buy_price = round(current_price, 2)
            hold_days = "10-30天（趋势）"
            exit_type = "fixed"
            exit_config = json.dumps({"take_profit_pct": 0.15})
        elif strategy in ("bollinger_upper", "布林带上轨突破"):
            stop_loss = round(current_price - 2.0 * atr, 2)
            take_profit = round(current_price + 2.5 * atr, 2)
            buy_price = round(current_price * 0.99, 2)
            hold_days = "3-7天（短线）"
            exit_type = "fixed"
            exit_config = json.dumps({"take_profit_pct": 0.15})
        elif strategy in ("trend_ma", "均线趋势跟踪"):
            stop_loss = round(max(current_price * 0.93, ma20 * 0.97), 2)
            take_profit = round(current_price * 1.15, 2)
            buy_price = round(current_price, 2)
            hold_days = "10-30天（趋势跟踪）"
            exit_type = "fixed"
            exit_config = json.dumps({"take_profit_pct": 0.15})
        elif strategy in ("enhanced_chip", "增强筹码"):
            stop_loss = round(current_price - 2.0 * atr, 2)
            take_profit = round(current_price + 2.5 * atr, 2)
            buy_price = round(max(ma5, current_price * 0.99), 2)
            hold_days = "5-10天（波段）"
            exit_type = "fixed"
            exit_config = json.dumps({"take_profit_pct": 0.15})
        else:
            # 默认
            stop_loss = round(current_price * 0.93, 2)
            take_profit = round(current_price * 1.15, 2)
            buy_price = round(current_price, 2)
            hold_days = "3-10天"
            exit_type = "fixed"
            exit_config = json.dumps({"take_profit_pct": 0.15})

        # 止损保底：不超过-8%
        if stop_loss > current_price * 0.92:
            stop_loss = round(current_price * 0.92, 2)

        return {
            "buy_price": buy_price,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "hold_days": hold_days,
            "exit_type": exit_type,
            "exit_config": exit_config,
        }

    def _calc_atr(self, high, low, close, period=14):
        """计算ATR"""
        n = len(close)
        if n < period + 1:
            return float(close[-1] * 0.03)
        tr = np.zeros(n)
        for i in range(1, n):
            tr[i] = max(
                high[i] - low[i],
                abs(high[i] - close[i - 1]),
                abs(low[i] - close[i - 1]),
            )
        atr = np.mean(tr[-period:])
        return float(atr) if atr > 0 else float(close[-1] * 0.03)

    # ============================================================
    # 3. 每日卖出信号检测
    # ============================================================

    def detect_sell_signals(self, trade_date: str = None, use_realtime: bool = True) -> List[Dict]:
        """检测跟踪池中所有 tracking 状态股票的卖出信号

        Args:
            trade_date: 交易日期
            use_realtime: 是否使用雪球实时价格（盘中=True，盘后=False）
        """
        if not trade_date:
            trade_date = datetime.now().strftime("%Y%m%d")

        conn = self._get_conn()
        pool = conn.execute(
            "SELECT id, ts_code, stock_name, strategy, signal_date, signal_price, "
            "stop_loss_price, take_profit_price, exit_type, exit_config_json, peak_price "
            "FROM tracking_pool WHERE status='tracking' AND actual_buy_price > 0"
        ).fetchall()
        conn.close()

        # 批量获取实时行情（减少请求次数）
        realtime_prices = {}
        if use_realtime and _HAS_XUEQIU and pool:
            try:
                codes = [item[1] for item in pool]
                realtime_quotes = batch_realtime_quotes(codes)
                realtime_prices = {
                    tc: float(q["current"])
                    for tc, q in realtime_quotes.items()
                    if q.get("current") and q.get("is_trade")
                }
                logger.info(f"📡 雪球实时行情获取成功: {len(realtime_prices)}/{len(pool)}只")
            except Exception as e:
                logger.warning(f"批量实时行情失败，fallback到收盘价: {e}")

        sell_signals = []
        for item in pool:
            pool_id, ts_code, stock_name, strategy, sig_date, sig_price, sl, tp, exit_type, exit_config_str, peak_price = item

            # 优先使用实时价格，fallback到数据库
            if ts_code in realtime_prices:
                current = realtime_prices[ts_code]
            else:
                current = self._get_latest_price(ts_code, use_realtime=False)
            if current <= 0:
                continue

            pnl_pct = round((current - sig_price) / sig_price * 100, 2)

            # 更新 peak_price（跟踪最高价）
            if current > peak_price:
                conn2 = self._get_conn()
                conn2.execute(
                    "UPDATE tracking_pool SET peak_price=? WHERE id=?",
                    (current, pool_id),
                )
                conn2.commit()
                conn2.close()
                peak_price = current

            # 检查卖出条件
            sell_reason = ""

            # 条件1：触发止损
            if current <= sl:
                sell_reason = f"触发止损：当前{current:.2f} <= 止损位{sl:.2f}"

            # 条件2：止盈判断（根据 exit_type 区分）
            elif exit_type == "trailing":
                # 移动止盈逻辑
                sell_reason = self._check_trailing_stop(
                    sig_price, current, peak_price, exit_config_str
                )
            elif current >= tp:
                # 固定止盈
                sell_reason = f"触发止盈：当前{current:.2f} >= 止盈位{tp:.2f}"

            # 条件3：策略卖出信号
            if not sell_reason:
                strategy_sell = self._check_strategy_sell(ts_code, strategy, current)
                if strategy_sell:
                    sell_reason = strategy_sell

            # 条件4：超过最大持有天数（15个交易日）
            hold_days = self._calc_trading_days(sig_date, trade_date)
            if hold_days >= 15 and pnl_pct < 3:
                sell_reason = f"超时止损：持有{hold_days}天，收益仅{pnl_pct}%"

            if sell_reason:
                sell_signals.append({
                    "pool_id": pool_id,
                    "ts_code": ts_code,
                    "stock_name": stock_name,
                    "strategy": strategy,
                    "signal_date": sig_date,
                    "signal_price": sig_price,
                    "current_price": current,
                    "pnl_pct": pnl_pct,
                    "sell_reason": sell_reason,
                    "stop_loss": sl,
                    "take_profit": tp,
                    "hold_days": hold_days,
                })

            # 更新当前价格和盈亏
            self._update_pool_price(pool_id, current, pnl_pct, conn=None)

        if sell_signals:
            logger.info(f"🔴 检测到 {len(sell_signals)} 个卖出信号")
        return sell_signals

    def _check_trailing_stop(
        self, buy_price: float, current_price: float, peak_price: float,
        exit_config_str: str
    ) -> str:
        """移动止盈检查（宽幅跟踪止盈v3）

        Args:
            buy_price: 买入价（信号价）
            current_price: 当前价
            peak_price: 持有期间最高价
            exit_config_str: JSON配置字符串

        Returns:
            卖出原因（空字符串表示不触发）
        """
        try:
            config = json.loads(exit_config_str) if exit_config_str else {}
        except (json.JSONDecodeError, TypeError):
            return ""

        tiers = config.get("tiers", [])
        min_profit_pct = config.get("min_profit_pct", 0.03)

        if not tiers:
            return ""

        # 当前盈利百分比
        profit_pct = (current_price - buy_price) / buy_price
        # 从最高点回撤百分比
        if peak_price > buy_price:
            drawdown_from_peak = (peak_price - current_price) / (peak_price - buy_price)
        else:
            drawdown_from_peak = 0

        # 找到当前所在的止盈等级（从高到低匹配）
        active_tier = None
        for tier in sorted(tiers, key=lambda t: -t["profit_pct"]):
            if profit_pct >= tier["profit_pct"]:
                active_tier = tier
                break

        if active_tier is None:
            return ""  # 还没达到第一级止盈门槛

        trail_pct = active_tier["trail_pct"]
        # 计算跟踪止盈价 = 买入价 * (1 + 当前最高利润 * (1 - 回撤容许比例))
        # 简化：当从 peak 回撤超过 trail_pct 时卖出
        drawdown_pct = (peak_price - current_price) / peak_price if peak_price > 0 else 0

        if drawdown_pct >= trail_pct:
            # 确保最低锁定 min_profit_pct
            locked_profit = (current_price - buy_price) / buy_price
            if locked_profit >= min_profit_pct:
                tier_desc = f"赚{active_tier['profit_pct']*100:.0f}%级"
                return (
                    f"跟踪止盈({tier_desc}，回撤{drawdown_pct*100:.1f}% ≥ {trail_pct*100:.0f}%)："
                    f"买入{buy_price:.2f} → 最高{peak_price:.2f} → 当前{current_price:.2f}，"
                    f"锁定盈利{locked_profit*100:.1f}%"
                )

        return ""

    def _check_strategy_sell(
        self, ts_code: str, strategy: str, current_price: float
    ) -> str:
        """检查策略自身的卖出信号"""
        conn = self._get_conn()
        df = pd.read_sql(
            "SELECT trade_date, open, high, low, close, vol FROM stock_daily "
            "WHERE ts_code=? ORDER BY trade_date",
            conn,
            params=(ts_code,),
        )
        conn.close()

        if df.empty or len(df) < 30:
            return ""

        df = df.sort_values("trade_date").reset_index(drop=True)
        dates = df["trade_date"].astype(str).tolist()
        closes = df["close"].values.astype(float)

        # 根据策略类型检查卖出条件
        try:
            if strategy in ("dual_ma", "双均线交叉"):
                # 死叉检测
                ma7 = pd.Series(closes).rolling(7).mean().values
                ma60 = pd.Series(closes).rolling(60).mean().values
                if len(ma7) >= 2 and not np.isnan(ma7[-1]) and not np.isnan(ma60[-1]):
                    if ma7[-2] >= ma60[-2] and ma7[-1] < ma60[-1]:
                        return "双均线死叉：MA7下穿MA60"

            elif strategy in ("pullback_stable", "回调企稳"):
                # ZLCMQ < 20 或跌破MA60
                ma60 = pd.Series(closes).rolling(60).mean().values
                if not np.isnan(ma60[-1]) and current_price < ma60[-1]:
                    return f"趋势破位：收盘价{current_price:.2f}跌破MA60={ma60[-1]:.2f}"

            elif strategy in ("bollinger_upper", "布林带上轨突破"):
                # 回到布林中轨以下
                ma25 = pd.Series(closes).rolling(25).mean().values
                if not np.isnan(ma25[-1]) and current_price < ma25[-1]:
                    return f"布林回归：收盘价{current_price:.2f}跌破中轨={ma25[-1]:.2f}"

            elif strategy in ("trend_ma", "均线趋势跟踪"):
                # 跌破MA15
                ma15 = pd.Series(closes).rolling(15).mean().values
                if not np.isnan(ma15[-1]) and current_price < ma15[-1]:
                    return f"趋势破位：收盘价{current_price:.2f}跌破MA15={ma15[-1]:.2f}"
        except Exception:
            pass

        return ""

    def _get_latest_price(self, ts_code: str, use_realtime: bool = True) -> float:
        """获取最新价格，优先使用雪球实时行情，fallback到数据库收盘价

        Args:
            ts_code: 股票代码
            use_realtime: 是否尝试获取实时价格（盘中场景用True）
        """
        # 优先尝试雪球实时行情
        if use_realtime and _HAS_XUEQIU:
            try:
                q = get_realtime_quote(ts_code, use_cache=True)
                if q and q.get("current") and q.get("is_trade"):
                    return float(q["current"])
            except Exception:
                pass

        # fallback: 数据库最新收盘价
        conn = self._get_conn()
        row = conn.execute(
            "SELECT close FROM stock_daily WHERE ts_code=? ORDER BY trade_date DESC LIMIT 1",
            (ts_code,),
        ).fetchone()
        conn.close()
        return float(row[0]) if row else 0

    def _calc_trading_days(self, start_date: str, end_date: str) -> int:
        """计算两个日期间的交易日数"""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT COUNT(*) FROM stock_daily WHERE ts_code='000001.SZ' "
            "AND trade_date >= ? AND trade_date <= ?",
            (start_date, end_date),
        ).fetchone()
        conn.close()
        return int(row[0]) if row else 0

    def _update_pool_price(
        self, pool_id: int, current_price: float, pnl_pct: float, conn=None
    ):
        """更新跟踪池中股票的当前价格和盈亏"""
        own_conn = conn is None
        if own_conn:
            conn = self._get_conn()
        try:
            conn.execute(
                "UPDATE tracking_pool SET current_price=?, current_pnl_pct=?, "
                "max_profit_pct=MAX(max_profit_pct, ?), max_loss_pct=MIN(max_loss_pct, ?), "
                "updated_at=datetime('now') WHERE id=?",
                (current_price, pnl_pct, pnl_pct, pnl_pct, pool_id),
            )
            conn.commit()
        finally:
            if own_conn:
                conn.close()

    def execute_sell(self, pool_id: int, sell_price: float, sell_reason: str, sell_date: str = None):
        """执行卖出（更新跟踪池状态）"""
        if not sell_date:
            sell_date = datetime.now().strftime("%Y%m%d")

        conn = self._get_conn()
        conn.execute(
            "UPDATE tracking_pool SET status='sold', actual_sell_price=?, "
            "actual_sell_date=?, sell_reason=?, updated_at=datetime('now') WHERE id=?",
            (sell_price, sell_date, sell_reason, pool_id),
        )
        conn.commit()
        conn.close()
        logger.info(f"📤 卖出: pool_id={pool_id} | 价格:{sell_price:.2f} | 原因:{sell_reason}")

    # ============================================================
    # 4. 查询 & 报告
    # ============================================================

    def get_tracking_pool(self, status: str = "tracking") -> List[Dict]:
        """获取跟踪池中的股票"""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT id, ts_code, stock_name, strategy, signal_date, signal_price, "
            "stop_loss_price, take_profit_price, buy_suggestion_price, "
            "hold_days_suggest, reason, current_price, current_pnl_pct, "
            "max_profit_pct, max_loss_pct, topic_tags "
            "FROM tracking_pool WHERE status=? ORDER BY signal_date DESC",
            (status,),
        ).fetchall()
        conn.close()

        result = []
        for r in rows:
            result.append({
                "id": r[0],
                "ts_code": r[1],
                "stock_name": r[2],
                "strategy": r[3],
                "signal_date": r[4],
                "signal_price": r[5],
                "stop_loss": r[6],
                "take_profit": r[7],
                "buy_price": r[8],
                "hold_days_suggest": r[9],
                "reason": r[10],
                "current_price": r[11],
                "current_pnl_pct": r[12],
                "max_profit_pct": r[13],
                "max_loss_pct": r[14],
                "topic_tags": r[15],
            })
        return result

    def generate_daily_report(self, trade_date: str = None) -> str:
        """生成每日跟踪池报告"""
        if not trade_date:
            trade_date = datetime.now().strftime("%Y%m%d")

        tracking = self.get_tracking_pool("tracking")
        sell_signals = self.detect_sell_signals(trade_date)

        lines = [
            "=" * 50,
            f"📊 QuantWeave 跟踪池日报 | {trade_date}",
            "=" * 50,
            "",
        ]

        # 卖出提醒（最紧急）
        if sell_signals:
            lines.append("🔴 卖出提醒（今日需操作）")
            lines.append("")
            for s in sell_signals[:10]:
                pnl_color = "🟢" if s["pnl_pct"] > 0 else "🔴"
                lines.append(
                    f"  {pnl_color} {s['stock_name']}({s['ts_code']}) | "
                    f"策略:{s['strategy']}"
                )
                lines.append(
                    f"     信号价:{s['signal_price']:.2f} → 当前:{s['current_price']:.2f} "
                    f"({s['pnl_pct']:+.2f}%)"
                )
                lines.append(f"     原因: {s['sell_reason']}")
                lines.append(f"     持有{s['hold_days']}天 | 止损:{s['stop_loss']:.2f} 止盈:{s['take_profit']:.2f}")
                lines.append("")
        else:
            lines.append("✅ 今日无卖出信号")
            lines.append("")

        # 跟踪池概况
        lines.append(f"📋 跟踪池概况（{len(tracking)}只）")
        lines.append("")
        for t in tracking[:20]:
            pnl_color = "🟢" if t["current_pnl_pct"] > 0 else "🔴" if t["current_pnl_pct"] < 0 else "⚪"
            lines.append(
                f"  {pnl_color} {t['stock_name']}({t['ts_code']}) | "
                f"{t['strategy']} | 入池:{t['signal_date']}"
            )
            if t["current_price"] > 0:
                lines.append(
                    f"     信号价:{t['signal_price']:.2f} → 当前:{t['current_price']:.2f} "
                    f"({t['current_pnl_pct']:+.2f}%)"
                )
            lines.append(
                f"     建议买入:{t['buy_price']:.2f} | 止损:{t['stop_loss']:.2f} | "
                f"止盈:{t['take_profit']:.2f} | {t['hold_days_suggest']}"
            )
            lines.append("")

        if len(tracking) > 20:
            lines.append(f"  ... 共{len(tracking)}只")
            lines.append("")

        # 统计
        total = len(tracking)
        profit_count = sum(1 for t in tracking if t["current_pnl_pct"] > 0)
        lines.append(f"📈 统计: 跟踪中{total}只 | 盈利{profit_count}只 | 亏损{total-profit_count}只")
        lines.append("")

        return "\n".join(lines)

    def generate_operation_guide_report(self, ts_code: str) -> str:
        """生成单只股票的详细操作指南"""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT ts_code, stock_name, strategy, signal_date, signal_price, "
            "stop_loss_price, take_profit_price, buy_suggestion_price, "
            "hold_days_suggest, reason, current_price, current_pnl_pct, "
            "exit_type, exit_config_json, peak_price "
            "FROM tracking_pool WHERE ts_code=? AND status='tracking' "
            "ORDER BY signal_date DESC LIMIT 1",
            (ts_code,),
        ).fetchone()

        # 获取技术面数据
        df = pd.read_sql(
            "SELECT trade_date, close, high, low, vol FROM stock_daily "
            "WHERE ts_code=? ORDER BY trade_date DESC LIMIT 30",
            conn,
            params=(ts_code,),
        )
        conn.close()

        if not row:
            return f"⚠️ {ts_code} 不在跟踪池中"

        ts_code, name, strategy, sig_date, sig_price, sl, tp, buy_price, hold_days, reason, cur_price, pnl, exit_type, exit_config_str, peak_price = row

        # 构建止盈说明
        exit_desc = ""
        if exit_type == "trailing":
            try:
                cfg = json.loads(exit_config_str) if exit_config_str else {}
                tiers = cfg.get("tiers", [])
                min_p = cfg.get("min_profit_pct", 0.03) * 100
                tier_descs = [f"赚{t['profit_pct']*100:.0f}%后回撤{t['trail_pct']*100:.0f}%卖" for t in tiers]
                exit_desc = "移动止盈: " + " → ".join(tier_descs) + f" | 最低锁定+{min_p:.0f}%"
            except (json.JSONDecodeError, TypeError):
                exit_desc = f"止盈价: {tp:.2f}（+{(tp-sig_price)/sig_price*100:.1f}%）"
        else:
            exit_desc = f"止盈价: {tp:.2f}（固定+{(tp-sig_price)/sig_price*100:.1f}%）"

        lines = [
            f"📝 操作指南: {name}({ts_code})",
            "",
            f"📊 策略: {strategy} | 信号日期: {sig_date}",
            f"💰 信号价: {sig_price:.2f} | 当前价: {cur_price:.2f} ({pnl:+.2f}%)",
            "",
            "🎯 操作建议:",
            f"  建议买入价: {buy_price:.2f}（接近此价位可建仓）",
            f"  止损价: {sl:.2f}（跌破必须卖出，亏损{(sl-sig_price)/sig_price*100:.1f}%）",
            f"  {exit_desc}",
            f"  建议持有: {hold_days}",
            "",
        ]

        # 技术面参考
        if not df.empty:
            closes = df["close"].values.astype(float)
            ma5 = np.mean(closes[:5]) if len(closes) >= 5 else 0
            ma10 = np.mean(closes[:10]) if len(closes) >= 10 else 0
            ma20 = np.mean(closes[:20]) if len(closes) >= 20 else 0

            lines.append("📐 技术参考:")
            lines.append(f"  MA5: {ma5:.2f}")
            lines.append(f"  MA10: {ma10:.2f}")
            lines.append(f"  MA20: {ma20:.2f}")

            if cur_price > ma5:
                lines.append("  ✅ 站上5日均线（短期偏多）")
            else:
                lines.append("  ⚠️ 跌破5日均线（短期偏弱）")

            if ma5 > ma10 > ma20:
                lines.append("  ✅ 多头排列（趋势向上）")
            elif ma5 < ma10 < ma20:
                lines.append("  ⚠️ 空头排列（趋势向下）")

        lines.append("")
        lines.append(f"📋 入池原因: {reason}")

        return "\n".join(lines)

    # ============================================================
    # 5. 胜率统计闭环
    # ============================================================

    def calculate_strategy_performance(self, strategy: str = None) -> List[Dict]:
        """计算策略胜率和表现"""
        conn = self._get_conn()

        where = "WHERE status IN ('sold', 'expired')" + (
            f" AND strategy='{strategy}'" if strategy else ""
        )

        rows = conn.execute(
            f"SELECT strategy, signal_price, actual_sell_price, signal_date, actual_sell_date "
            f"FROM tracking_pool {where} ORDER BY signal_date DESC"
        ).fetchall()
        conn.close()

        if not rows:
            return []

        # 按策略分组统计
        stats = {}
        for r in rows:
            strat, sig_p, sell_p, sig_d, sell_d = r
            if strat not in stats:
                stats[strat] = {"wins": 0, "losses": 0, "profits": [], "hold_days": []}

            if sell_p and sig_p:
                pnl = (sell_p - sig_p) / sig_p * 100
                stats[strat]["profits"].append(pnl)
                if pnl > 0:
                    stats[strat]["wins"] += 1
                else:
                    stats[strat]["losses"] += 1

                # 计算持有天数
                days = self._calc_trading_days(sig_d, sell_d) if sell_d else 0
                stats[strat]["hold_days"].append(days)

        result = []
        for strat, s in stats.items():
            total = s["wins"] + s["losses"]
            if total == 0:
                continue
            avg_profit = np.mean(s["profits"]) if s["profits"] else 0
            result.append({
                "strategy": strat,
                "total_trades": total,
                "win_rate": round(s["wins"] / total * 100, 1),
                "avg_profit_pct": round(avg_profit, 2),
                "avg_hold_days": round(np.mean(s["hold_days"]), 1) if s["hold_days"] else 0,
                "best_trade": round(max(s["profits"]), 2) if s["profits"] else 0,
                "worst_trade": round(min(s["profits"]), 2) if s["profits"] else 0,
            })

        return sorted(result, key=lambda x: x["avg_profit_pct"], reverse=True)
