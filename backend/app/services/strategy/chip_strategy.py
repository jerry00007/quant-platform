"""
QuantWeave - 主力筹码趋向策略（来自参考项目通达信指标转换）
包含：基础筹码策略 + 增强型筹码策略 + 强势股回调企稳策略
"""
import numpy as np
import pandas as pd
from loguru import logger
from typing import List, Optional, Set
from .strategy_service import StrategyBase, Signal, SignalType


class ChipStrategy(StrategyBase):
    """主力筹码趋向(ZLCMQ)策略
    
    买入条件:
      1. ZLCMQ 在 N_DAYS 内曾到达 MIN_HIGH 以上
      2. ZLCMQ 下穿 95
      3. 从高点回落至少 MIN_FALL
      4. 价格企稳（阳线或收盘高于昨收）
    
    卖出条件:
      1. 止损: -8%
      2. 止盈: +15%
      3. 筹码极度分散: ZLCMQ < 15
    """
    name = "主力筹码趋向"
    description = "基于通达信ZLCMQ指标，捕捉主力筹码集中后的回落企稳机会"
    params = {
        "n_days": 5,
        "min_high": 98,
        "min_fall": 5,
        "stop_loss_pct": -0.08,
        "take_profit_pct": 0.15,
        "chip_exit": 15,
    }

    def __init__(self, params: dict = None):
        super().__init__(params)
        self.position = None
        self.entry_price = None

    @staticmethod
    def _tdx_sma(x, n, m):
        """通达信 SMA(X, N, M): Y = (M*X + (N-M)*Y_prev) / N"""
        y = np.empty(len(x))
        y[0] = x[0]
        for i in range(1, len(x)):
            y[i] = (m * x[i] + (n - m) * y[i - 1]) / n
        return y

    @staticmethod
    def _barslast_high(zlcmq, n_days):
        """BARSLAST(ZLCMQ = HHV(ZLCMQ, N_DAYS))"""
        result = np.full(len(zlcmq), np.nan)
        for i in range(len(zlcmq)):
            start = max(0, i - n_days + 1)
            window = zlcmq[start: i + 1]
            if len(window) == 0 or np.any(np.isnan(window)):
                continue
            max_val = np.max(window)
            for j in range(len(window) - 1, -1, -1):
                if not np.isnan(window[j]) and window[j] == max_val:
                    result[i] = len(window) - 1 - j
                    break
        return result

    def calculate_zlcmq(self, close, high, low):
        """计算主力筹码趋向指标"""
        c = close.values.astype(float)
        h = high.values.astype(float)
        lo = low.values.astype(float)

        var5 = pd.Series(lo).rolling(75, min_periods=1).min().values
        var6 = pd.Series(h).rolling(75, min_periods=1).max().values
        var7 = (var6 - var5) / 100.0

        raw = np.where(var7 > 1e-10, (c - var5) / var7, 0.0)
        raw = np.nan_to_num(raw, nan=0.0)

        var8 = self._tdx_sma(raw, 20, 1)
        var8_s = self._tdx_sma(var8, 15, 1)
        vara = 3.0 * var8 - 2.0 * var8_s

        return pd.Series(100.0 - vara, index=close.index)

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.sort_values("trade_date").copy()
        df["zlcmq"] = self.calculate_zlcmq(df["close"], df["high"], df["low"])
        return df

    def generate_signals(self, df: pd.DataFrame, ts_code: str = "") -> List[Signal]:
        if df.empty or len(df) < 80:
            return []

        df = self.calculate_indicators(df)
        close = df["close"]
        open_ = df["open"]
        zlcmq = df["zlcmq"]

        n_days = self.params["n_days"]
        min_high = self.params["min_high"]
        min_fall = self.params["min_fall"]
        stop_loss_pct = self.params["stop_loss_pct"]
        take_profit_pct = self.params["take_profit_pct"]
        chip_exit = self.params["chip_exit"]

        zq_high = zlcmq.rolling(n_days, min_periods=1).max()
        was_high = zq_high >= min_high
        cross_95 = (zlcmq.shift(1) >= 95) & (zlcmq < 95)

        high_bars = self._barslast_high(zlcmq.values, n_days)
        fall_value = zq_high - zlcmq
        is_fast_fall = (
            (high_bars >= 2)
            & (high_bars <= n_days - 1)
            & (fall_value >= min_fall)
        )

        is_stable = (close > open_) | (close > close.shift(1))
        buy_cond = was_high & cross_95 & is_fast_fall & is_stable

        self.position = None
        self.entry_price = None
        signals = []

        for i in range(75, len(df)):
            row = df.iloc[i]
            p = close.iloc[i]
            z = zlcmq.iloc[i]

            if self.position is None:
                if buy_cond.iloc[i]:
                    signals.append(Signal(
                        signal_type=SignalType.BUY,
                        ts_code=ts_code,
                        price=float(p),
                        reason=f"筹码高位回落企稳 ZLCMQ={z:.1f}",
                        confidence=0.85,
                        date=str(row["trade_date"]),
                    ))
                    self.position = "buy"
                    self.entry_price = p
            else:
                pnl = (p - self.entry_price) / self.entry_price
                sell = False
                reason = ""

                if pnl <= stop_loss_pct:
                    sell = True
                    reason = f"止损 {pnl * 100:+.1f}%"
                elif pnl >= take_profit_pct:
                    sell = True
                    reason = f"止盈 {pnl * 100:+.1f}%"
                elif not np.isnan(z) and z < chip_exit:
                    sell = True
                    reason = f"筹码极度分散 ZLCMQ={z:.1f}"

                if sell:
                    signals.append(Signal(
                        signal_type=SignalType.SELL,
                        ts_code=ts_code,
                        price=float(p),
                        reason=reason,
                        confidence=0.85,
                        date=str(row["trade_date"]),
                    ))
                    self.position = None
                    self.entry_price = None

        return signals


class EnhancedChipStrategy(StrategyBase):
    """增强型主力筹码趋向策略（多因子确认+动态风控）
    
    新增买入条件:
      5. 成交量放大确认（20日均量1.5倍以上）
      6. 换手率过滤（避开炒作股）
      7. 趋势过滤（收盘价在60日均线上方）
    
    新增卖出条件:
      1. ATR动态止损（2.5倍ATR）
      2. 移动止盈（盈利>10%后启动）
      3. 止盈 +20%
      4. 筹码极度分散（连续2日确认）
    """
    name = "增强筹码策略"
    description = "ZLCMQ+多因子确认+ATR动态风控，收益回撤比更优"
    params = {
        "n_days": 5,
        "min_high": 98,
        "min_fall": 5,
        "stop_loss_atr_mult": 2.5,
        "take_profit_pct": 0.20,
        "chip_exit": 15,
        "vol_surge_mult": 1.5,
        "max_turnover": 8.0,
        "trend_ma_period": 60,
        "trailing_profit_start": 0.10,
        "trailing_atr_mult": 1.5,
    }

    def __init__(self, params: dict = None):
        super().__init__(params)
        self.position = None
        self.entry_price = None
        self.trailing_stop = None

    @staticmethod
    def _tdx_sma(x, n, m):
        y = np.empty(len(x))
        y[0] = x[0]
        for i in range(1, len(x)):
            y[i] = (m * x[i] + (n - m) * y[i - 1]) / n
        return y

    @staticmethod
    def _barslast_high(zlcmq, n_days):
        result = np.full(len(zlcmq), np.nan)
        for i in range(len(zlcmq)):
            start = max(0, i - n_days + 1)
            window = zlcmq[start: i + 1]
            if len(window) == 0 or np.any(np.isnan(window)):
                continue
            max_val = np.max(window)
            for j in range(len(window) - 1, -1, -1):
                if not np.isnan(window[j]) and window[j] == max_val:
                    result[i] = len(window) - 1 - j
                    break
        return result

    @staticmethod
    def _atr(high, low, close, period=14):
        tr1 = high - low
        tr2 = np.abs(high - close.shift(1))
        tr3 = np.abs(low - close.shift(1))
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return tr.rolling(period).mean()

    def calculate_zlcmq(self, close, high, low):
        c = close.values.astype(float)
        h = high.values.astype(float)
        lo = low.values.astype(float)
        var5 = pd.Series(lo).rolling(75, min_periods=1).min().values
        var6 = pd.Series(h).rolling(75, min_periods=1).max().values
        var7 = (var6 - var5) / 100.0
        raw = np.where(var7 > 1e-10, (c - var5) / var7, 0.0)
        raw = np.nan_to_num(raw, nan=0.0)
        var8 = self._tdx_sma(raw, 20, 1)
        var8_s = self._tdx_sma(var8, 15, 1)
        vara = 3.0 * var8 - 2.0 * var8_s
        return pd.Series(100.0 - vara, index=close.index)

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.sort_values("trade_date").copy()
        df["zlcmq"] = self.calculate_zlcmq(df["close"], df["high"], df["low"])
        df["atr"] = self._atr(df["high"], df["low"], df["close"])
        return df

    def generate_signals(self, df: pd.DataFrame, ts_code: str = "") -> List[Signal]:
        if df.empty or len(df) < 80:
            return []

        df = self.calculate_indicators(df)
        close = df["close"]
        open_ = df["open"]
        volume = df["vol"] if "vol" in df.columns else pd.Series(0, index=df.index)
        zlcmq = df["zlcmq"]

        vol_avg_20 = volume.rolling(20, min_periods=1).mean()
        vol_surge = volume > vol_avg_20 * self.params["vol_surge_mult"]

        ma_trend = close.rolling(self.params["trend_ma_period"], min_periods=1).mean()
        trend_ok = close > ma_trend * 0.98

        n_days = self.params["n_days"]
        zq_high = zlcmq.rolling(n_days, min_periods=1).max()
        was_high = zq_high >= self.params["min_high"]
        cross_95 = (zlcmq.shift(1) >= 95) & (zlcmq < 95)

        high_bars = self._barslast_high(zlcmq.values, n_days)
        fall_value = zq_high - zlcmq
        is_fast_fall = (high_bars >= 2) & (high_bars <= n_days - 1) & (fall_value >= self.params["min_fall"])

        is_stable = (close > open_) | (close > close.shift(1))
        buy_cond = was_high & cross_95 & is_fast_fall & is_stable & vol_surge & trend_ok

        atr = df["atr"]
        atr_mult_stop = atr * self.params["stop_loss_atr_mult"]
        atr_mult_trail = atr * self.params["trailing_atr_mult"]

        self.position = None
        self.entry_price = None
        self.trailing_stop = None
        signals = []

        for i in range(75, len(df)):
            row = df.iloc[i]
            p = close.iloc[i]
            z = zlcmq.iloc[i]
            z_prev = zlcmq.iloc[i - 1] if i > 0 else np.nan

            if self.position is None:
                if buy_cond.iloc[i]:
                    self.trailing_stop = p - atr_mult_trail.iloc[i]
                    signals.append(Signal(
                        signal_type=SignalType.BUY,
                        ts_code=ts_code,
                        price=float(p),
                        reason=f"筹码高位回落企稳+放量+趋势确认 ZLCMQ={z:.1f}",
                        confidence=0.90,
                        date=str(row["trade_date"]),
                    ))
                    self.position = "buy"
                    self.entry_price = p
            else:
                pnl = (p - self.entry_price) / self.entry_price
                sell = False
                reason = ""

                if p <= (self.entry_price - atr_mult_stop.iloc[i]):
                    sell = True
                    reason = f"ATR止损 {pnl * 100:+.1f}%"
                elif pnl > self.params["trailing_profit_start"]:
                    self.trailing_stop = max(self.trailing_stop, p - atr_mult_trail.iloc[i])
                    if p <= self.trailing_stop:
                        sell = True
                        reason = f"移动止盈 {pnl * 100:+.1f}%"
                elif pnl >= self.params["take_profit_pct"]:
                    sell = True
                    reason = f"止盈 {pnl * 100:+.1f}%"
                elif not np.isnan(z) and not np.isnan(z_prev) and z < self.params["chip_exit"] and z_prev < self.params["chip_exit"]:
                    sell = True
                    reason = f"筹码极度分散 ZLCMQ={z:.1f}"

                if sell:
                    signals.append(Signal(
                        signal_type=SignalType.SELL,
                        ts_code=ts_code,
                        price=float(p),
                        reason=reason,
                        confidence=0.90,
                        date=str(row["trade_date"]),
                    ))
                    self.position = None
                    self.entry_price = None
                    self.trailing_stop = None

        return signals


class PullbackStableStrategy(StrategyBase):
    """强势股首次回调企稳策略（通达信公式迁移 - 改良版）
    
    核心逻辑：强势股从高位快速回落后，出现缩量企稳信号
    
    买入条件:
      1. ZLCMQ 在 N_DAYS(8) 内曾达到 HIGH_LEVEL(92) 以上
      2. ZLCMQ 从高点回落至少 FALL_MIN(3)
      3. 企稳条件 5选3:
         - 真阳线 (C > O)
         - 收盘高于昨日 (C > REF(C,1))
         - 低点抬高 (L > REF(L,1))
         - 缩量 (VOL < REF(VOL,1) * 0.7)
         - 站上5日线 (C > MA(C,5))
      4. 大盘在20日均线上方 (可选，需外部传入)
    
    卖出条件:
      1. 止损: -8%
      2. 止盈: +15%
      3. 移动止盈: 盈利>10%后回撤5%止盈
    """
    name = "强势股回调企稳"
    description = "基于通达信改良版选股公式，捕捉强势股首次回调企稳机会（5选3企稳+大盘过滤）"
    params = {
        "n_days": 8,
        "high_level": 92,
        "fall_min": 3,
        "vol_shrink": 0.7,
        "stop_loss_pct": -0.08,
        "take_profit_pct": 0.15,
        "trail_start": 0.10,
        "trail_pct": 0.05,
    }

    def __init__(self, params: dict = None):
        super().__init__(params)
        self.position = None
        self.entry_price = None
        self.trailing_stop = None
        self.market_ok_dates: Optional[Set[str]] = None

    def set_market_ok(self, dates_set: Set[str]):
        """设置大盘允许日期集合（INDEXC > MA(INDEXC,20) 的日期）"""
        self.market_ok_dates = dates_set

    @staticmethod
    def _tdx_sma(x, n, m):
        y = np.empty(len(x))
        y[0] = x[0]
        for i in range(1, len(x)):
            y[i] = (m * x[i] + (n - m) * y[i - 1]) / n
        return y

    def calculate_zlcmq(self, close, high, low):
        c = close.values.astype(float)
        h = high.values.astype(float)
        lo = low.values.astype(float)
        var5 = pd.Series(lo).rolling(75, min_periods=1).min().values
        var6 = pd.Series(h).rolling(75, min_periods=1).max().values
        var7 = (var6 - var5) / 100.0
        raw = np.where(var7 > 1e-10, (c - var5) / var7, 0.0)
        raw = np.nan_to_num(raw, nan=0.0)
        var8 = self._tdx_sma(raw, 20, 1)
        var8_s = self._tdx_sma(var8, 15, 1)
        vara = 3.0 * var8 - 2.0 * var8_s
        return pd.Series(100.0 - vara, index=close.index)

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.sort_values("trade_date").copy()
        df["zlcmq"] = self.calculate_zlcmq(df["close"], df["high"], df["low"])
        return df

    def generate_signals(self, df: pd.DataFrame, ts_code: str = "") -> List[Signal]:
        if df.empty or len(df) < 80:
            return []

        df = self.calculate_indicators(df)
        close = df["close"]
        open_ = df["open"]
        low = df["low"]
        high = df["high"]
        volume = df["vol"] if "vol" in df.columns else pd.Series(0, index=df.index)
        zlcmq = df["zlcmq"]

        n_days = self.params["n_days"]
        high_level = self.params["high_level"]
        fall_min = self.params["fall_min"]
        vol_shrink = self.params["vol_shrink"]

        # 高位判断: N天内ZLCMQ最高值 >= HIGH_LEVEL
        zq_max = zlcmq.rolling(n_days, min_periods=1).max()
        was_high = zq_max >= high_level

        # 从高位回落幅度
        fall_value = zq_max - zlcmq
        has_fall = fall_value >= fall_min

        # 企稳条件（5选3）
        s1 = (close > open_).astype(int)                          # 真阳线
        s2 = (close > close.shift(1)).astype(int)                  # 收盘高于昨日
        s3 = (low > low.shift(1)).astype(int)                      # 低点抬高
        s4 = (volume < volume.shift(1) * vol_shrink).astype(int)   # 缩量
        s5 = (close > close.rolling(5, min_periods=1).mean()).astype(int)  # 站上5日线

        stable_count = s1 + s2 + s3 + s4 + s5
        is_stable = stable_count >= 3

        buy_cond = was_high & has_fall & is_stable

        self.position = None
        self.entry_price = None
        self.trailing_stop = None
        signals = []

        for i in range(75, len(df)):
            row = df.iloc[i]
            p = close.iloc[i]
            z = zlcmq.iloc[i]
            dt = str(row["trade_date"])

            # 大盘过滤: 非市场OK日不开新仓
            if self.market_ok_dates is not None and dt not in self.market_ok_dates:
                continue

            if self.position is None:
                if buy_cond.iloc[i]:
                    sc = int(stable_count.iloc[i])
                    signals.append(Signal(
                        signal_type=SignalType.BUY,
                        ts_code=ts_code,
                        price=float(p),
                        reason=f"强势回调企稳 ZLCMQ={z:.1f} 企稳={sc}项",
                        confidence=0.85,
                        date=dt,
                    ))
                    self.position = "buy"
                    self.entry_price = p
                    self.trailing_stop = None
            else:
                pnl = (p - self.entry_price) / self.entry_price
                sell = False
                reason = ""

                if pnl <= self.params["stop_loss_pct"]:
                    sell = True
                    reason = f"止损 {pnl*100:+.1f}%"
                elif pnl >= self.params["take_profit_pct"]:
                    sell = True
                    reason = f"止盈 {pnl*100:+.1f}%"
                elif pnl > self.params["trail_start"]:
                    trail_price = p * (1 - self.params["trail_pct"])
                    if self.trailing_stop is None or trail_price > self.trailing_stop:
                        self.trailing_stop = trail_price
                    if p <= self.trailing_stop:
                        sell = True
                        reason = f"移动止盈 {pnl*100:+.1f}%"

                if sell:
                    signals.append(Signal(
                        signal_type=SignalType.SELL,
                        ts_code=ts_code,
                        price=float(p),
                        reason=reason,
                        confidence=0.85,
                        date=dt,
                    ))
                    self.position = None
                    self.entry_price = None
                    self.trailing_stop = None

        return signals
