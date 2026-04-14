"""
QuantWeave - 智能选股引擎
全市场扫描 + 多策略筛选 + 综合评分
"""
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from loguru import logger
from typing import Dict, List, Optional
from sqlalchemy.orm import Session

from ...models.models import Stock, StockDaily
from ..data.data_service import DataService
from ..strategy.strategy_service import (
    STRATEGY_REGISTRY, SignalType, get_strategy
)


class ScreeningService:
    """选股引擎 — 多策略全市场扫描"""

    # 预定义选股模板
    SCREENING_PRESETS = {
        "aggressive": {
            "name": "激进型（锋芒爆发）",
            "strategies": ["vol_breakout", "first_yin", "chip"],
            "description": "适合短线爆发，高风险高收益",
        },
        "moderate": {
            "name": "稳健型（趋势跟踪）",
            "strategies": ["trend_ma", "macd", "enhanced_chip", "pullback_stable"],
            "description": "适合波段操作，中等风险",
        },
        "conservative": {
            "name": "保守型（均值回归）",
            "strategies": ["bollinger", "rsi", "dual_ma"],
            "description": "适合低吸高抛，低风险",
        },
        "all": {
            "name": "全策略扫描",
            "strategies": list(STRATEGY_REGISTRY.keys()),
            "description": "所有策略同时扫描，综合评分",
        },
    }

    def __init__(self, db: Session, data_service: DataService):
        self.db = db
        self.data_service = data_service

    def get_stock_list(self, market: str = "all") -> List[dict]:
        """获取股票列表"""
        query = self.db.query(Stock).filter(Stock.is_active == True)
        if market == "sh":
            query = query.filter(Stock.ts_code.endswith(".SH"))
        elif market == "sz":
            query = query.filter(Stock.ts_code.endswith(".SZ"))
        stocks = query.limit(6000).all()
        return [
            {"ts_code": s.ts_code, "name": s.name, "industry": s.industry}
            for s in stocks
        ]

    def scan_market(
        self,
        strategy_keys: List[str] = None,
        stock_codes: List[str] = None,
        days: int = 120,
        preset: str = "all",
        top_n: int = 20,
    ) -> List[dict]:
        """
        全市场选股扫描
        
        Args:
            strategy_keys: 策略列表，None则用preset
            stock_codes: 指定股票池，None则全市场
            days: 回看天数
            preset: 预设模板名称
            top_n: 返回前N只
        
        Returns:
            选中的股票列表，含评分和信号
        """
        if strategy_keys is None:
            preset_cfg = self.SCREENING_PRESETS.get(preset, self.SCREENING_PRESETS["all"])
            strategy_keys = preset_cfg["strategies"]

        # 获取股票池
        if stock_codes:
            stocks = [{"ts_code": c, "name": ""} for c in stock_codes]
        else:
            stocks = self.get_stock_list()

        if not stocks:
            logger.warning("股票池为空，请先同步股票列表")
            return []

        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")

        logger.info(f"🔍 开始选股扫描: {len(stocks)}只股票 × {len(strategy_keys)}个策略")

        results = []
        for idx, stock in enumerate(stocks):
            ts_code = stock["ts_code"]
            stock_name = stock.get("name", "")
            if idx % 50 == 0:
                logger.info(f"  扫描进度: {idx}/{len(stocks)}")

            try:
                # 获取行情数据
                df = self.data_service.fetch_daily(ts_code, start_date, end_date)
                if df.empty or len(df) < 30:
                    continue

                # 用每个策略扫描
                stock_signals = []
                for sk in strategy_keys:
                    if sk not in STRATEGY_REGISTRY:
                        continue
                    try:
                        strategy = get_strategy(sk)
                        signals = strategy.generate_signals(df, ts_code)
                        # 只关注最近5个交易日的买入信号
                        recent_dates = df["trade_date"].astype(str).tail(5).tolist()
                        recent_buys = [
                            s for s in signals
                            if s.signal_type == SignalType.BUY and s.date in recent_dates
                        ]
                        stock_signals.extend(recent_buys)
                    except Exception as e:
                        logger.debug(f"  {ts_code} {sk} 策略异常: {e}")
                        continue

                if stock_signals:
                    # 计算综合评分
                    score = self._calculate_score(stock_signals, df)
                    latest = df.iloc[-1]
                    results.append({
                        "ts_code": ts_code,
                        "name": stock_name,
                        "close": float(latest["close"]),
                        "change_pct": float(latest.get("change_pct", 0)),
                        "signals": [s.to_dict() for s in stock_signals],
                        "signal_count": len(stock_signals),
                        "score": score,
                        "strategies_hit": list({s.reason.split()[0] if s.reason else "" for s in stock_signals}),
                    })

            except Exception as e:
                logger.debug(f"  {ts_code} 扫描异常: {e}")
                continue

        # 按评分排序
        results.sort(key=lambda x: x["score"], reverse=True)
        logger.info(f"✅ 选股完成: 发现 {len(results)} 只候选股")
        return results[:top_n]

    def analyze_stock(self, ts_code: str, days: int = 250) -> dict:
        """
        单只股票深度分析
        
        Returns:
            包含技术指标、各策略信号、综合评级的分析报告
        """
        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")

        df = self.data_service.fetch_daily(ts_code, start_date, end_date)
        if df.empty:
            return {"error": "数据不足", "ts_code": ts_code}

        df = self.data_service.calculate_ma(df)
        latest = df.iloc[-1]

        # 各策略信号
        all_signals = {}
        for key in STRATEGY_REGISTRY:
            try:
                strategy = get_strategy(key)
                signals = strategy.generate_signals(df, ts_code)
                # 最近10个交易日信号
                recent_dates = df["trade_date"].astype(str).tail(10).tolist()
                recent = [s.to_dict() for s in signals if s.date in recent_dates]
                if recent:
                    all_signals[key] = recent
            except Exception:
                continue

        # 技术指标汇总
        close = df["close"]
        analysis = {
            "ts_code": ts_code,
            "latest": {
                "date": str(latest.get("trade_date", "")),
                "close": float(latest["close"]),
                "change_pct": float(latest.get("change_pct", 0)),
                "vol": float(latest.get("vol", 0)),
                "amount": float(latest.get("amount", 0)),
            },
            "ma": {},
            "signals": all_signals,
            "recommendation": self._generate_recommendation(all_signals, df),
        }

        # 均线数据
        for p in [5, 10, 20, 60]:
            col = f"ma{p}"
            if col in df.columns and not pd.isna(latest.get(col)):
                analysis["ma"][f"ma{p}"] = float(latest[col])

        # RSI
        try:
            delta = close.diff()
            gain = delta.where(delta > 0, 0.0)
            loss = -delta.where(delta < 0, 0.0)
            avg_gain = gain.ewm(alpha=1.0 / 14, adjust=False).mean()
            avg_loss = loss.ewm(alpha=1.0 / 14, adjust=False).mean()
            rsi = 100 - (100 / (1 + avg_gain / avg_loss))
            analysis["rsi"] = round(float(rsi.iloc[-1]), 1)
        except Exception:
            pass

        return analysis

    def _calculate_score(self, signals, df: pd.DataFrame) -> float:
        """计算综合评分"""
        score = 0.0
        for s in signals:
            # 基础分 = 置信度 × 100
            score += s.confidence * 100

            # 多策略共振加分
        if len(set(s.reason.split()[0] for s in signals)) > 1:
            score += 20

        # 趋势加分: 价格在均线上方
        if len(df) >= 20:
            close = df["close"].iloc[-1]
            ma20 = df["close"].rolling(20).mean().iloc[-1]
            if not pd.isna(ma20) and close > ma20:
                score += 10

        return round(score, 1)

    def _generate_recommendation(self, signals: dict, df: pd.DataFrame) -> dict:
        """生成操作建议"""
        buy_strategies = []
        sell_strategies = []

        for key, sigs in signals.items():
            for s in sigs:
                if s.get("signal") == "buy":
                    buy_strategies.append(key)
                elif s.get("signal") == "sell":
                    sell_strategies.append(key)

        close = float(df["close"].iloc[-1])
        # 简单止损止盈建议
        stop_loss = round(close * 0.92, 2)  # -8%
        take_profit = round(close * 1.20, 2)  # +20%

        if buy_strategies:
            action = "buy"
            level = "强烈买入" if len(buy_strategies) >= 3 else "建议买入"
            reason = f"{len(buy_strategies)}个策略触发买入信号"
        elif sell_strategies:
            action = "sell"
            level = "建议卖出"
            reason = f"{len(sell_strategies)}个策略触发卖出信号"
        else:
            action = "hold"
            level = "观望"
            reason = "当前无明确信号"

        return {
            "action": action,
            "level": level,
            "reason": reason,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "buy_strategies": buy_strategies,
            "sell_strategies": sell_strategies,
        }
