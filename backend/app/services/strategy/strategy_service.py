"""
QuantWeave - 策略引擎
内置策略：双均线交叉、布林带突破、RSI超买超卖、MACD金叉死叉
"""
import pandas as pd
import numpy as np
from loguru import logger
from typing import Dict, List, Optional, Tuple
from enum import Enum


class SignalType(str, Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


class Signal:
    """交易信号"""
    def __init__(self, signal_type: SignalType, ts_code: str, price: float,
                 reason: str = "", confidence: float = 1.0, date: str = ""):
        self.signal_type = signal_type
        self.ts_code = ts_code
        self.price = price
        self.reason = reason
        self.confidence = confidence  # 0.0 ~ 1.0
        self.date = date

    def to_dict(self):
        return {
            "signal": self.signal_type.value,
            "ts_code": self.ts_code,
            "price": self.price,
            "reason": self.reason,
            "confidence": self.confidence,
            "date": self.date,
        }


class StrategyBase:
    """策略基类"""
    
    name: str = "BaseStrategy"
    description: str = ""
    params: dict = {}

    def __init__(self, params: dict = None):
        if params:
            self.params = {**self.params, **params}

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算技术指标（子类实现）"""
        raise NotImplementedError

    def generate_signals(self, df: pd.DataFrame, ts_code: str = "") -> List[Signal]:
        """生成交易信号（子类实现）"""
        raise NotImplementedError


class DualMAStrategy(StrategyBase):
    """双均线交叉策略"""
    name = "双均线交叉"
    description = "短期均线上穿长期均线买入，下穿卖出"
    params = {
        "short_period": 5,
        "long_period": 40,  # 网格搜索最优（原默认20）
    }

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.sort_values("trade_date").copy()
        short = self.params["short_period"]
        long = self.params["long_period"]
        df["ma_short"] = df["close"].rolling(window=short).mean()
        df["ma_long"] = df["close"].rolling(window=long).mean()
        return df

    def generate_signals(self, df: pd.DataFrame, ts_code: str = "") -> List[Signal]:
        df = self.calculate_indicators(df)
        signals = []
        for i in range(1, len(df)):
            prev = df.iloc[i - 1]
            curr = df.iloc[i]
            
            if pd.isna(curr["ma_short"]) or pd.isna(curr["ma_long"]):
                continue
            
            # 金叉买入
            if prev["ma_short"] <= prev["ma_long"] and curr["ma_short"] > curr["ma_long"]:
                signals.append(Signal(
                    signal_type=SignalType.BUY,
                    ts_code=ts_code,
                    price=float(curr["close"]),
                    reason=f"MA{self.params['short_period']}上穿MA{self.params['long_period']}（金叉）",
                    confidence=0.8,
                    date=str(curr["trade_date"]),
                ))
            # 死叉卖出
            elif prev["ma_short"] >= prev["ma_long"] and curr["ma_short"] < curr["ma_long"]:
                signals.append(Signal(
                    signal_type=SignalType.SELL,
                    ts_code=ts_code,
                    price=float(curr["close"]),
                    reason=f"MA{self.params['short_period']}下穿MA{self.params['long_period']}（死叉）",
                    confidence=0.8,
                    date=str(curr["trade_date"]),
                ))
        return signals


class BollingerBreakStrategy(StrategyBase):
    """布林带突破策略"""
    name = "布林带突破"
    description = "价格突破布林带上轨卖出，突破下轨买入"
    params = {
        "period": 25,      # 网格搜索最优（原默认20）
        "std_dev": 2.5,    # 网格搜索最优（原默认2.0）
    }

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.sort_values("trade_date").copy()
        period = self.params["period"]
        std_dev = self.params["std_dev"]
        df["mid"] = df["close"].rolling(window=period).mean()
        df["std"] = df["close"].rolling(window=period).std()
        df["upper"] = df["mid"] + std_dev * df["std"]
        df["lower"] = df["mid"] - std_dev * df["std"]
        return df

    def generate_signals(self, df: pd.DataFrame, ts_code: str = "") -> List[Signal]:
        df = self.calculate_indicators(df)
        signals = []
        for i in range(1, len(df)):
            curr = df.iloc[i]
            prev = df.iloc[i - 1]
            
            if pd.isna(curr["lower"]):
                continue
            
            # 突破下轨买入
            if prev["close"] > prev["lower"] and curr["close"] <= curr["lower"]:
                signals.append(Signal(
                    signal_type=SignalType.BUY,
                    ts_code=ts_code,
                    price=float(curr["close"]),
                    reason="突破布林带下轨，超卖反弹",
                    confidence=0.7,
                    date=str(curr["trade_date"]),
                ))
            # 突破上轨卖出
            elif prev["close"] < prev["upper"] and curr["close"] >= curr["upper"]:
                signals.append(Signal(
                    signal_type=SignalType.SELL,
                    ts_code=ts_code,
                    price=float(curr["close"]),
                    reason="突破布林带上轨，超买回落",
                    confidence=0.7,
                    date=str(curr["trade_date"]),
                ))
        return signals


class RSIStrategy(StrategyBase):
    """RSI超买超卖策略"""
    name = "RSI超买超卖"
    description = "RSI低于25买入（超卖），高于80卖出（超买）"
    params = {
        "period": 12,       # 网格搜索最优（原默认14）
        "oversold": 25,     # 网格搜索最优（原默认30）
        "overbought": 80,   # 网格搜索最优（原默认70）
    }

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.sort_values("trade_date").copy()
        period = self.params["period"]
        delta = df["close"].diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)
        # Wilder's EMA (alpha = 1/period)
        avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
        rs = avg_gain / avg_loss
        df["rsi"] = 100 - (100 / (1 + rs))
        return df

    def generate_signals(self, df: pd.DataFrame, ts_code: str = "") -> List[Signal]:
        df = self.calculate_indicators(df)
        signals = []
        for i in range(1, len(df)):
            curr = df.iloc[i]
            if pd.isna(curr["rsi"]):
                continue

            # 超卖买入
            if curr["rsi"] < self.params["oversold"]:
                signals.append(Signal(
                    signal_type=SignalType.BUY,
                    ts_code=ts_code,
                    price=float(curr["close"]),
                    reason=f"RSI={curr['rsi']:.1f}，超卖区域",
                    confidence=0.75,
                    date=str(curr["trade_date"]),
                ))
            # 超买卖出
            elif curr["rsi"] > self.params["overbought"]:
                signals.append(Signal(
                    signal_type=SignalType.SELL,
                    ts_code=ts_code,
                    price=float(curr["close"]),
                    reason=f"RSI={curr['rsi']:.1f}，超买区域",
                    confidence=0.75,
                    date=str(curr["trade_date"]),
                ))
        return signals


class MACDStrategy(StrategyBase):
    """MACD金叉死叉策略"""
    name = "MACD金叉死叉"
    description = "MACD金叉买入，死叉卖出"
    params = {
        "fast_period": 15,     # 网格搜索最优（原默认12）
        "slow_period": 26,
        "signal_period": 13,   # 网格搜索最优（原默认9）
    }

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.sort_values("trade_date").copy()
        fast = self.params["fast_period"]
        slow = self.params["slow_period"]
        signal_p = self.params["signal_period"]
        
        ema_fast = df["close"].ewm(span=fast, adjust=False).mean()
        ema_slow = df["close"].ewm(span=slow, adjust=False).mean()
        df["dif"] = ema_fast - ema_slow
        df["dea"] = df["dif"].ewm(span=signal_p, adjust=False).mean()
        df["macd"] = 2 * (df["dif"] - df["dea"])
        return df

    def generate_signals(self, df: pd.DataFrame, ts_code: str = "") -> List[Signal]:
        df = self.calculate_indicators(df)
        signals = []
        for i in range(1, len(df)):
            prev = df.iloc[i - 1]
            curr = df.iloc[i]
            
            if pd.isna(curr["dif"]) or pd.isna(curr["dea"]):
                continue
            
            # MACD金叉
            if prev["dif"] <= prev["dea"] and curr["dif"] > curr["dea"]:
                signals.append(Signal(
                    signal_type=SignalType.BUY,
                    ts_code=ts_code,
                    price=float(curr["close"]),
                    reason="MACD金叉",
                    confidence=0.8,
                    date=str(curr["trade_date"]),
                ))
            # MACD死叉
            elif prev["dif"] >= prev["dea"] and curr["dif"] < curr["dea"]:
                signals.append(Signal(
                    signal_type=SignalType.SELL,
                    ts_code=ts_code,
                    price=float(curr["close"]),
                    reason="MACD死叉",
                    confidence=0.8,
                    date=str(curr["trade_date"]),
                ))
        return signals


# 策略注册表
from .chip_strategy import ChipStrategy, EnhancedChipStrategy, PullbackStableStrategy
from .fengmang_strategy import VolumeBreakoutStrategy, DragonFirstYinStrategy, TrendMAStrategy
from .top_bottom_strategy import TopBottomStrategy

STRATEGY_REGISTRY = {
    "dual_ma": DualMAStrategy,
    "bollinger": BollingerBreakStrategy,
    "rsi": RSIStrategy,
    "macd": MACDStrategy,
    "chip": ChipStrategy,
    "enhanced_chip": EnhancedChipStrategy,
    "pullback_stable": PullbackStableStrategy,
    "vol_breakout": VolumeBreakoutStrategy,
    "first_yin": DragonFirstYinStrategy,
    "trend_ma": TrendMAStrategy,
    "top_bottom": TopBottomStrategy,
}


def get_strategy(strategy_type: str, params: dict = None) -> StrategyBase:
    """获取策略实例"""
    cls = STRATEGY_REGISTRY.get(strategy_type)
    if not cls:
        raise ValueError(f"未知策略类型: {strategy_type}，可选: {list(STRATEGY_REGISTRY.keys())}")
    return cls(params=params)
