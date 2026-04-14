"""
QuantWeave - 网格仓位管理系统
基于锋芒课程第八章"网格体系"，结合顶底图评分动态调整仓位。

核心逻辑：
1. 顶底图评分 → 仓位等级（极低/偏低/中性/偏高/极高）
2. 仓位等级 → 建议仓位比例（0%~100%）
3. 单只股票上限20%，分散5只
4. 支持滚动调仓（定期重新评估）

锋芒网格体系：
- 90分（极低）→ 满仓进攻
- 60-90分 → 半仓滚动
- <60分 → 空仓观望
"""
import numpy as np
import pandas as pd
from loguru import logger
from typing import Dict, List, Optional, Tuple
from enum import Enum
from dataclasses import dataclass, field


class PositionLevel(str, Enum):
    """仓位等级"""
    EXTREMELY_LOW = "极低位"   # 顶底图评分 ≥ 90，满仓
    LOW = "偏低"               # 75-90，重仓
    NEUTRAL = "中性"           # 60-75，半仓
    HIGH = "偏高"              # 40-60，轻仓
    EXTREMELY_HIGH = "极高"    # < 40，空仓


@dataclass
class PositionAdvice:
    """仓位建议"""
    score: float                    # 顶底图评分（0-100）
    level: PositionLevel            # 仓位等级
    total_position_pct: float       # 总仓位百分比（0.0~1.0）
    single_stock_pct: float         # 单只股票仓位（默认0.2 = 20%）
    max_stocks: int                 # 建议持仓数量
    action: str                     # 操作建议
    reason: str                     # 原因说明


class TopBottomScorer:
    """顶底图评分计算器
    
    基于TopBottomStrategy的指标计算，给出0-100的综合评分。
    评分越高代表市场越处于低位（越适合买入）。
    """
    
    def __init__(self, params: dict = None):
        self.params = params or {}
        self.var1 = self.params.get("var1", 1.0)
        self.winner_lookback = self.params.get("winner_lookback", 250)
    
    @staticmethod
    def _tdx_sma(x, n, m):
        """通达信 SMA(X, N, M)"""
        y = np.empty(len(x))
        y[0] = x[0]
        for i in range(1, len(x)):
            y[i] = (m * x[i] + (n - m) * y[i - 1]) / n
        return y
    
    def _winner(self, price: pd.Series, lookback: int = None) -> pd.Series:
        """简化版 WINNER 计算"""
        if lookback is None:
            lookback = self.winner_lookback
        if len(price) < lookback:
            lookback = len(price)
        winner_values = np.ones(len(price))
        for i in range(len(price)):
            start = max(0, i - lookback + 1)
            window = price.iloc[start:i+1]
            if len(window) < 2:
                winner_values[i] = 0.5
            else:
                rank = (window <= price.iloc[i]).sum()
                winner_values[i] = rank / len(window)
        return pd.Series(winner_values, index=price.index)
    
    def calculate_score(self, df: pd.DataFrame) -> float:
        """计算顶底图综合评分（0-100）
        
        评分逻辑：
        - 基于fight(髑战)、sanpang(三胖)、qieshou(切手)的综合位置
        - 低位 = 高分（适合买入）
        - 高位 = 低分（应该减仓）
        """
        if df.empty or len(df) < 100:
            return 50.0  # 默认中性
        
        df = df.sort_values("trade_date").copy()
        close = df["close"]
        high = df["high"]
        low = df["low"]
        open_ = df["open"]
        volume = df["vol"] if "vol" in df.columns else pd.Series(1000000, index=df.index)
        capital = df["vol"] * df["close"] * 10 if "vol" in df.columns else pd.Series(1e9, index=df.index)
        
        var1 = self.var1
        
        # VAR3 = MA(CLOSE,13)
        var3 = close.rolling(13, min_periods=1).mean()
        # VAR4
        var4 = 100 - np.abs((close - var3) / np.where(var3 > 1e-10, var3, 1e-10) * 100)
        
        # fight(髑战) 简化计算
        var5 = low.rolling(75, min_periods=1).min()
        var6 = high.rolling(75, min_periods=1).max()
        var7 = (var6 - var5) / 100.0
        raw_var8 = np.where(var7 > 1e-10, (close - var5) / var7, 0.0)
        var8 = self._tdx_sma(raw_var8, 20, 1)
        var8_sma = self._tdx_sma(var8, 15, 1)
        vara = 3.0 * var8 - 2.0 * var8_sma
        fight = (100 - vara) * var1
        
        # sanpang(三胖)
        winner_close_95 = self._winner(close * 0.95)
        sanpang_raw = winner_close_95 * 100
        sanpang = sanpang_raw.rolling(3, min_periods=1).mean() * var1
        
        # qieshou(切手)
        winner_close = self._winner(close)
        var2 = 1.0 / np.where(winner_close > 1e-10, winner_close, 1e-10)
        cond1 = var2 > 5
        cond2 = var2 < 100
        val_if = np.where(cond1, np.where(cond2, var2, var4 - 10), 0)
        qieshou = (100 - val_if) * var1
        
        # 取最新值
        idx = -1
        fight_val = float(fight.iloc[idx])
        sanpang_val = float(sanpang.iloc[idx])
        qieshou_val = float(qieshou.iloc[idx])
        
        # VAR20 红色柱条件（简化版）
        var12 = close - close.shift(1)
        var13 = np.maximum(var12, 0)
        var14 = np.abs(var12)
        var13_sma = self._tdx_sma(var13.values, 7, 1)
        var14_sma = self._tdx_sma(var14.values, 7, 1)
        var15 = np.where(var14_sma > 1e-10, var13_sma / var14_sma * 100, 50)
        var13_sma13 = self._tdx_sma(var13.values, 13, 1)
        var14_sma13 = self._tdx_sma(var14.values, 13, 1)
        var16 = np.where(var14_sma13 > 1e-10, var13_sma13 / var14_sma13 * 100, 50)
        var17 = pd.Series(range(1, len(close)+1), index=close.index)
        
        var18_numer = self._tdx_sma(np.maximum(var12, 0).values, 6, 1)
        var18_denom = self._tdx_sma(np.abs(var12).values, 6, 1)
        var18 = np.where(var18_denom > 1e-10, var18_numer / var18_denom * 100, 50)
        
        hhv_60 = high.rolling(60, min_periods=1).max()
        llv_60 = low.rolling(60, min_periods=1).min()
        var19 = (-200) * (hhv_60 - close) / np.where((hhv_60 - llv_60) > 1e-10, hhv_60 - llv_60, 1e-10) + 100
        
        is_red_bar = bool(
            var18[idx] <= 25 and
            var19[idx] < -95 and
            var17.iloc[idx] > 50 and
            var15[idx] < 22 and
            var16[idx] < 28
        )
        
        # === 综合评分算法 ===
        # 1. 髑战(fight)位置评分（0-40分）：越低越好
        fight_score = max(0, min(40, (100 - fight_val) * 0.4))
        
        # 2. 切手(qieshou)位置评分（0-30分）：越低越好
        qieshou_score = max(0, min(30, (100 - qieshou_val) * 0.3))
        
        # 3. 三胖(sanpang)位置评分（0-20分）：中位最佳
        sanpang_score = max(0, min(20, sanpang_val * 0.2))
        
        # 4. 红色柱加分（0-10分）
        red_bar_score = 10.0 if is_red_bar else 0.0
        
        total_score = fight_score + qieshou_score + sanpang_score + red_bar_score
        total_score = max(0, min(100, total_score))
        
        logger.debug(
            f"顶底图评分: {total_score:.1f} "
            f"(fight={fight_val:.1f}→{fight_score:.1f}, "
            f"qieshou={qieshou_val:.1f}→{qieshou_score:.1f}, "
            f"sanpang={sanpang_val:.1f}→{sanpang_score:.1f}, "
            f"red_bar={'✅' if is_red_bar else '❌'}→{red_bar_score:.1f})"
        )
        
        return round(total_score, 1)


class GridPositionManager:
    """网格仓位管理器
    
    锋芒第八章网格体系实现：
    - 根据顶底图评分分配仓位
    - 90分（极低）→ 满仓
    - 75-90分 → 重仓（80%）
    - 60-75分 → 半仓（50%）
    - 40-60分 → 轻仓（30%）
    - <40分 → 空仓（0%）
    
    单只股票上限20%，分散5只
    """
    
    # 仓位等级对应参数
    POSITION_CONFIG = {
        PositionLevel.EXTREMELY_LOW: {
            "total_pct": 1.0,     # 满仓
            "single_pct": 0.20,   # 单只20%
            "max_stocks": 5,
            "action": "满仓进攻",
            "reason": "市场处于极低位，顶底图评分≥90，历史级别底部区域",
        },
        PositionLevel.LOW: {
            "total_pct": 0.8,     # 重仓
            "single_pct": 0.20,   # 单只20%
            "max_stocks": 4,
            "action": "重仓操作",
            "reason": "市场偏低，顶底图评分75-90，适合积极布局",
        },
        PositionLevel.NEUTRAL: {
            "total_pct": 0.5,     # 半仓
            "single_pct": 0.15,   # 单只15%
            "max_stocks": 4,
            "action": "半仓滚动",
            "reason": "市场中位，顶底图评分60-75，半仓操作降低风险",
        },
        PositionLevel.HIGH: {
            "total_pct": 0.3,     # 轻仓
            "single_pct": 0.10,   # 单只10%
            "max_stocks": 3,
            "action": "轻仓防守",
            "reason": "市场偏高，顶底图评分40-60，控制仓位等待回调",
        },
        PositionLevel.EXTREMELY_HIGH: {
            "total_pct": 0.0,     # 空仓
            "single_pct": 0.0,
            "max_stocks": 0,
            "action": "空仓观望",
            "reason": "市场处于极高位，顶底图评分<40，风险极大，建议空仓",
        },
    }
    
    def __init__(self, scorer: TopBottomScorer = None):
        self.scorer = scorer or TopBottomScorer()
    
    def _score_to_level(self, score: float) -> PositionLevel:
        """评分转仓位等级"""
        if score >= 90:
            return PositionLevel.EXTREMELY_LOW
        elif score >= 75:
            return PositionLevel.LOW
        elif score >= 60:
            return PositionLevel.NEUTRAL
        elif score >= 40:
            return PositionLevel.HIGH
        else:
            return PositionLevel.EXTREMELY_HIGH
    
    def get_position_advice(self, score: float) -> PositionAdvice:
        """根据评分获取仓位建议"""
        level = self._score_to_level(score)
        config = self.POSITION_CONFIG[level]
        
        return PositionAdvice(
            score=score,
            level=level,
            total_position_pct=config["total_pct"],
            single_stock_pct=config["single_pct"],
            max_stocks=config["max_stocks"],
            action=config["action"],
            reason=config["reason"],
        )
    
    def evaluate_market(self, df: pd.DataFrame) -> PositionAdvice:
        """评估市场并给出仓位建议
        
        Args:
            df: 包含OHLCV数据的DataFrame，建议用大盘指数（如沪深300）
        
        Returns:
            PositionAdvice: 仓位建议
        """
        score = self.scorer.calculate_score(df)
        return self.get_position_advice(score)
    
    def allocate_positions(
        self,
        total_cash: float,
        advice: PositionAdvice,
        stock_candidates: List[Dict],
    ) -> List[Dict]:
        """根据仓位建议分配资金到具体股票
        
        Args:
            total_cash: 总可用资金
            advice: 仓位建议
            stock_candidates: 候选股票列表 [{"ts_code": "xxx", "name": "xxx", "price": 10.5}, ...]
        
        Returns:
            分配结果列表 [{"ts_code": "xxx", "name": "xxx", "shares": 1000, "budget": 10500}, ...]
        """
        if advice.total_position_pct <= 0 or not stock_candidates:
            return []
        
        # 可用仓位资金
        position_cash = total_cash * advice.total_position_pct
        max_stocks = min(advice.max_stocks, len(stock_candidates))
        per_stock_budget = position_cash / max_stocks
        
        allocations = []
        for i, stock in enumerate(stock_candidates[:max_stocks]):
            price = stock.get("price", 0)
            if price <= 0:
                continue
            shares = int(per_stock_budget / price / 100) * 100  # 整百股
            budget = shares * price
            allocations.append({
                "ts_code": stock["ts_code"],
                "name": stock.get("name", ""),
                "shares": shares,
                "budget": round(budget, 2),
                "budget_pct": round(budget / total_cash * 100, 1),
            })
        
        logger.info(
            f"仓位分配: 总资金{total_cash:,.0f} → 仓位{advice.total_position_pct*100:.0f}% "
            f"({position_cash:,.0f}) → {len(allocations)}只股票 "
            f"每只约{per_stock_budget:,.0f}"
        )
        
        return allocations
    
    def should_rebalance(
        self,
        current_score: float,
        previous_score: float,
        threshold: float = 10.0,
    ) -> Tuple[bool, str]:
        """判断是否需要调仓
        
        Args:
            current_score: 当前评分
            previous_score: 上次评分
            threshold: 调仓阈值（评分变化超过此值才调仓）
        
        Returns:
            (是否需要调仓, 原因说明)
        """
        diff = current_score - previous_score
        
        # 跨越等级阈值
        current_level = self._score_to_level(current_score)
        previous_level = self._score_to_level(previous_score)
        
        if current_level != previous_level:
            return True, (
                f"仓位等级变化: {previous_level.value}→{current_level.value} "
                f"(评分{previous_score:.1f}→{current_score:.1f})"
            )
        
        # 同等级内大幅波动
        if abs(diff) >= threshold:
            return True, f"评分大幅波动: {diff:+.1f} ({previous_score:.1f}→{current_score:.1f})"
        
        return False, f"评分变化不大: {diff:+.1f}，维持当前仓位"
    
    def get_portfolio_status(
        self,
        advice: PositionAdvice,
        current_positions: List[Dict],
        total_cash: float,
    ) -> Dict:
        """获取组合状态分析
        
        Args:
            advice: 仓位建议
            current_positions: 当前持仓 [{"ts_code": "xxx", "shares": 1000, "market_value": 10500}, ...]
            total_cash: 当前现金
        
        Returns:
            组合状态分析
        """
        current_total = total_cash + sum(p.get("market_value", 0) for p in current_positions)
        current_position_value = sum(p.get("market_value", 0) for p in current_positions)
        current_position_pct = current_position_value / current_total if current_total > 0 else 0
        
        target_position_value = current_total * advice.total_position_pct
        diff = target_position_value - current_position_value
        diff_pct = advice.total_position_pct - current_position_pct
        
        # 判断操作方向
        if abs(diff_pct) < 0.05:
            direction = "维持"
        elif diff_pct > 0:
            direction = "加仓"
        else:
            direction = "减仓"
        
        return {
            "score": advice.score,
            "level": advice.level.value,
            "action": advice.action,
            "reason": advice.reason,
            "current_total_assets": round(current_total, 2),
            "current_position_pct": round(current_position_pct * 100, 1),
            "target_position_pct": round(advice.total_position_pct * 100, 1),
            "diff_pct": round(diff_pct * 100, 1),
            "diff_amount": round(diff, 2),
            "direction": direction,
            "position_count": len(current_positions),
            "target_count": advice.max_stocks,
            "single_stock_limit_pct": round(advice.single_stock_pct * 100, 1),
        }
