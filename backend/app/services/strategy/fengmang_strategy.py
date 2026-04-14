"""
QuantWeave - 锋芒实战策略集
包含：爆量突破、龙头首阴反抽、均线趋势跟踪
来源：锋芒爆点盈利系统 / 波段实战课程
"""
import numpy as np
import pandas as pd
from loguru import logger
from typing import List, Optional, Set
from .strategy_service import StrategyBase, Signal, SignalType


class VolumeBreakoutStrategy(StrategyBase):
    """爆量突破 — 锋芒爆点盈利系统
    
    核心逻辑：低位横盘后爆量突破20日高点，换手率放大
    
    买入条件:
      1. 20日波动率 < 15%（横盘整理）
      2. 今日成交量 > 2倍20日均量（爆量）
      3. 收盘价突破20日最高价（突破）
      4. 价格在20日均线上方（趋势确认）
    
    卖出条件:
      1. 止损: -8%
      2. 止盈: +20%
      3. 移动止盈: 盈利>10%后回撤5%
    """
    name = "爆量突破(锋芒)"
    description = "低位横盘后爆量突破20日高点，捕捉主力启动信号"
    params = {
        "box_days": 20,
        "vol_mult": 2.0,
        "stop_loss_pct": -0.08,
        "take_profit_pct": 0.20,
        "trail_start": 0.10,
        "trail_pct": 0.05,
    }

    def __init__(self, params: dict = None):
        super().__init__(params)
        self.position = None
        self.entry_price = None
        self.trailing_stop = None

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.sort_values("trade_date").copy()
        bd = self.params["box_days"]
        close = df["close"]
        high = df["high"]
        vol = df["vol"] if "vol" in df.columns else pd.Series(0, index=df.index)

        df["ma20"] = close.rolling(bd).mean()
        df["avg_vol"] = vol.rolling(bd).mean()
        # 20日年化波动率
        df["volatility"] = close.pct_change().rolling(bd).std() * np.sqrt(bd)
        # 20日最高价（不包含当日）
        df["high20"] = high.rolling(bd).max().shift(1)
        return df

    def generate_signals(self, df: pd.DataFrame, ts_code: str = "") -> List[Signal]:
        if df.empty or len(df) < 30:
            return []

        df = self.calculate_indicators(df)
        close = df["close"]
        vol = df["vol"] if "vol" in df.columns else pd.Series(0, index=df.index)

        bd = self.params["box_days"]
        vm = self.params["vol_mult"]

        is_box = df["volatility"] < 0.15
        is_vol = vol > df["avg_vol"] * vm
        is_break = close > df["high20"]
        above_ma = close > df["ma20"]

        buy_cond = is_box & is_vol & is_break & above_ma

        self.position = None
        self.entry_price = None
        self.trailing_stop = None
        signals = []

        for i in range(bd, len(df)):
            row = df.iloc[i]
            p = close.iloc[i]
            dt = str(row["trade_date"])

            if self.position is None:
                if buy_cond.iloc[i]:
                    vol_ratio = vol.iloc[i] / max(df["avg_vol"].iloc[i], 1)
                    signals.append(Signal(
                        signal_type=SignalType.BUY,
                        ts_code=ts_code,
                        price=float(p),
                        reason=f"爆量突破 量比{vol_ratio:.1f} 突破{df['high20'].iloc[i]:.2f}",
                        confidence=0.80,
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
                        confidence=0.80,
                        date=dt,
                    ))
                    self.position = None
                    self.entry_price = None
                    self.trailing_stop = None

        return signals


class DragonFirstYinStrategy(StrategyBase):
    """龙头首阴反抽 — 锋芒爆点盈利系统
    
    核心逻辑：连续涨停后首次收大阴线，次日低吸博弈反抽
    
    买入条件:
      1. 连续涨停 >= 2天
      2. 首日收阴线（跌幅>3%，收盘<开盘）
      3. 次日低吸买入
    
    卖出条件:
      1. 止损: -5%
      2. 止盈: +10%
      3. 持仓超过3天保利出局
    """
    name = "龙头首阴反抽(锋芒)"
    description = "连续涨停后首阴次日低吸，博弈龙头反抽"
    params = {
        "limit_pct": 0.095,
        "min_limits": 2,
        "yin_pct": -0.03,
        "stop_loss_pct": -0.05,
        "take_profit_pct": 0.10,
        "max_hold_days": 3,
    }

    def __init__(self, params: dict = None):
        super().__init__(params)

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.sort_values("trade_date").copy()
        pct = df["pct_chg"] if "pct_chg" in df.columns else df["close"].pct_change() * 100
        df["pct"] = pct

        lp = self.params["limit_pct"] * 100
        is_limit = pct > lp

        # 统计连续涨停天数
        limit_streak = pd.Series(0, index=df.index)
        streak = 0
        for i in range(len(df)):
            if is_limit.iloc[i]:
                streak += 1
                limit_streak.iloc[i] = streak
            else:
                streak = 0
        df["limit_streak"] = limit_streak

        # 首阴: 昨日连续涨停>=N，今日收阴且跌幅>3%
        ml = self.params["min_limits"]
        yp = self.params["yin_pct"] * 100
        df["first_yin"] = (
            (limit_streak.shift(1) >= ml) &
            (pct < yp) &
            (df["close"] < df["open"])
        )
        # 次日买入信号
        df["buy_signal"] = df["first_yin"].shift(1).fillna(False)

        return df

    def generate_signals(self, df: pd.DataFrame, ts_code: str = "") -> List[Signal]:
        if df.empty or len(df) < 30:
            return []

        df = self.calculate_indicators(df)
        close = df["close"]

        mh = self.params["max_hold_days"]
        signals = []
        in_pos = False
        entry_price = 0
        hold_days = 0

        for i in range(30, len(df)):
            row = df.iloc[i]
            p = close.iloc[i]
            dt = str(row["trade_date"])

            if not in_pos and df["buy_signal"].iloc[i]:
                signals.append(Signal(
                    signal_type=SignalType.BUY,
                    ts_code=ts_code,
                    price=float(p),
                    reason="首阴次日低吸",
                    confidence=0.75,
                    date=dt,
                ))
                in_pos = True
                entry_price = p
                hold_days = 0
            elif in_pos:
                hold_days += 1
                pnl = (p - entry_price) / entry_price
                sell = False
                reason = ""

                if pnl <= self.params["stop_loss_pct"]:
                    sell = True
                    reason = f"止损 {pnl*100:+.1f}%"
                elif pnl >= self.params["take_profit_pct"]:
                    sell = True
                    reason = f"止盈 {pnl*100:+.1f}%"
                elif hold_days >= mh:
                    sell = True
                    reason = f"持仓{mh}日保利 {pnl*100:+.1f}%"

                if sell:
                    signals.append(Signal(
                        signal_type=SignalType.SELL,
                        ts_code=ts_code,
                        price=float(p),
                        reason=reason,
                        confidence=0.75,
                        date=dt,
                    ))
                    in_pos = False

        return signals


class TrendMAStrategy(StrategyBase):
    """均线趋势跟踪 — 锋芒波段实战
    
    三阶段均线系统：酝势→起势→趋势
    
    买入条件:
      1. MA5 > MA10 > MA20 > MA30 多头排列首次形成（起势信号）
    
    卖出条件:
      1. 固定止损: -5%
      2. 浮动保利: 盈利>5%后回撤3%
      3. 趋势保利: 多头排列破位（收盘破5均）
    """
    name = "均线趋势跟踪(锋芒)"
    description = "三阶段均线系统，捕捉酝势→起势→趋势完整波段"
    params = {
        "ma_periods": [5, 10, 20, 30],
        "stop_loss_pct": -0.05,
        "trail_start": 0.05,
        "trail_pct": 0.03,
    }

    def __init__(self, params: dict = None):
        super().__init__(params)
        self.position = None
        self.entry_price = None
        self.trailing_stop = None
        self.prev_bull = False

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.sort_values("trade_date").copy()
        close = df["close"]
        ms = self.params["ma_periods"]

        for m in ms:
            df[f"ma{m}"] = close.rolling(m).mean()

        # 多头排列: MA5 > MA10 > MA20 > MA30
        bull = pd.Series(True, index=df.index)
        for j in range(len(ms) - 1):
            bull = bull & (df[f"ma{ms[j]}"] > df[f"ma{ms[j+1]}"])
        df["bull_align"] = bull.astype(int)

        # 首次多头: 之前非多头，今天多头
        df["first_bull"] = bull & ~bull.shift(1).fillna(False)

        return df

    def generate_signals(self, df: pd.DataFrame, ts_code: str = "") -> List[Signal]:
        if df.empty or len(df) < 40:
            return []

        df = self.calculate_indicators(df)
        close = df["close"]
        ms = self.params["ma_periods"]
        bull = df["bull_align"].astype(bool)
        first_bull = df["first_bull"]

        self.position = None
        self.entry_price = None
        self.trailing_stop = None
        self.prev_bull = False
        signals = []

        for i in range(max(ms), len(df)):
            row = df.iloc[i]
            p = close.iloc[i]
            dt = str(row["trade_date"])

            if self.position is None:
                if first_bull.iloc[i]:
                    signals.append(Signal(
                        signal_type=SignalType.BUY,
                        ts_code=ts_code,
                        price=float(p),
                        reason="均线起势(多头排列)",
                        confidence=0.80,
                        date=dt,
                    ))
                    self.position = "buy"
                    self.entry_price = p
                    self.trailing_stop = None
                    self.prev_bull = bool(bull.iloc[i])
            else:
                pnl = (p - self.entry_price) / self.entry_price
                sell = False
                reason = ""

                if pnl <= self.params["stop_loss_pct"]:
                    sell = True
                    reason = f"止损 {pnl*100:+.1f}%"
                elif pnl > self.params["trail_start"]:
                    trail_price = p * (1 - self.params["trail_pct"])
                    if self.trailing_stop is None or trail_price > self.trailing_stop:
                        self.trailing_stop = trail_price
                    if p <= self.trailing_stop:
                        sell = True
                        reason = f"浮动保利 {pnl*100:+.1f}%"
                elif not bull.iloc[i] and self.prev_bull:
                    sell = True
                    reason = f"趋势破位 {pnl*100:+.1f}%"

                self.prev_bull = bool(bull.iloc[i])

                if sell:
                    signals.append(Signal(
                        signal_type=SignalType.SELL,
                        ts_code=ts_code,
                        price=float(p),
                        reason=reason,
                        confidence=0.80,
                        date=dt,
                    ))
                    self.position = None
                    self.entry_price = None
                    self.trailing_stop = None

        return signals
