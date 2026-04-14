"""
QuantWeave - 每日信号服务
生成次日操作建议：买入/卖出/止损/止盈
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


class SignalService:
    """每日信号服务 — 生成次日操作建议"""

    def __init__(self, db: Session, data_service: DataService):
        self.db = db
        self.data_service = data_service

    def generate_daily_signals(
        self,
        stock_codes: List[str] = None,
        strategy_keys: List[str] = None,
        watchlist_only: bool = False,
    ) -> dict:
        """
        生成每日操作信号
        
        Returns:
            {
                "date": "生成日期",
                "next_trade_day": "下一交易日",
                "signals": [
                    {
                        "ts_code": "...",
                        "name": "...",
                        "action": "buy/sell/hold",
                        "strategies": [...],
                        "price": 当前价,
                        "stop_loss": 止损价,
                        "take_profit": 止盈价,
                        "reason": "...",
                        "urgency": "high/medium/low"
                    }
                ],
                "summary": {...}
            }
        """
        today = datetime.now().strftime("%Y%m%d")
        
        # 如果没有指定股票池，使用默认关注列表
        if stock_codes is None:
            stock_codes = self._get_default_watchlist()

        if strategy_keys is None:
            strategy_keys = list(STRATEGY_REGISTRY.keys())

        if not stock_codes:
            return {
                "date": today,
                "next_trade_day": self._get_next_trade_day(today),
                "signals": [],
                "summary": {"total": 0, "buy": 0, "sell": 0, "hold": 0},
                "message": "关注列表为空，请先添加股票到关注列表",
            }

        end_date = today
        start_date = (datetime.now() - timedelta(days=250)).strftime("%Y%m%d")

        logger.info(f"📡 生成每日信号: {len(stock_codes)}只 × {len(strategy_keys)}个策略")

        all_signals = []
        for ts_code in stock_codes:
            try:
                stock_name = self._get_stock_name(ts_code)
                df = self.data_service.fetch_daily(ts_code, start_date, end_date)
                if df.empty or len(df) < 30:
                    continue

                latest = df.iloc[-1]
                latest_close = float(latest["close"])
                latest_date = str(latest["trade_date"])

                # 各策略信号扫描
                buy_reasons = []
                sell_reasons = []
                strategy_details = []

                for sk in strategy_keys:
                    if sk not in STRATEGY_REGISTRY:
                        continue
                    try:
                        strategy = get_strategy(sk)
                        signals = strategy.generate_signals(df, ts_code)

                        # 最近3个交易日的信号
                        recent_dates = df["trade_date"].astype(str).tail(3).tolist()
                        for s in signals:
                            if s.date in recent_dates:
                                if s.signal_type == SignalType.BUY:
                                    buy_reasons.append({
                                        "strategy": sk,
                                        "reason": s.reason,
                                        "confidence": s.confidence,
                                    })
                                elif s.signal_type == SignalType.SELL:
                                    sell_reasons.append({
                                        "strategy": sk,
                                        "reason": s.reason,
                                        "confidence": s.confidence,
                                    })
                    except Exception:
                        continue

                # 生成操作建议
                signal = self._build_signal(
                    ts_code, stock_name, latest_close, latest_date,
                    buy_reasons, sell_reasons, df
                )
                if signal:
                    all_signals.append(signal)

            except Exception as e:
                logger.debug(f"  {ts_code} 信号生成异常: {e}")
                continue

        # 排序: 买入优先，然后按紧急度
        urgency_order = {"high": 0, "medium": 1, "low": 2}
        action_order = {"buy": 0, "sell": 1, "hold": 2}
        all_signals.sort(
            key=lambda x: (action_order.get(x["action"], 3), urgency_order.get(x["urgency"], 3))
        )

        summary = {
            "total": len(all_signals),
            "buy": sum(1 for s in all_signals if s["action"] == "buy"),
            "sell": sum(1 for s in all_signals if s["action"] == "sell"),
            "hold": sum(1 for s in all_signals if s["action"] == "hold"),
        }

        result = {
            "date": today,
            "next_trade_day": self._get_next_trade_day(today),
            "signals": all_signals,
            "summary": summary,
        }

        logger.info(f"✅ 信号生成完成: 买入{summary['buy']} 卖出{summary['sell']} 观望{summary['hold']}")
        return result

    def _build_signal(
        self,
        ts_code: str,
        stock_name: str,
        close: float,
        latest_date: str,
        buy_reasons: list,
        sell_reasons: list,
        df: pd.DataFrame,
    ) -> Optional[dict]:
        """构建单只股票的信号"""

        if not buy_reasons and not sell_reasons:
            return None

        # 确定主要动作
        if len(buy_reasons) > len(sell_reasons):
            action = "buy"
            reasons = buy_reasons
        elif len(sell_reasons) > len(buy_reasons):
            action = "sell"
            reasons = sell_reasons
        else:
            # 买卖信号数相同，观望
            action = "hold"
            reasons = buy_reasons + sell_reasons

        # 计算止损止盈
        atr = self._calculate_atr(df)
        if action == "buy":
            stop_loss = round(close - 2.5 * atr, 2)
            take_profit = round(close + 3.0 * atr, 2)
            # 限制止损不超过-8%
            if (stop_loss - close) / close < -0.08:
                stop_loss = round(close * 0.92, 2)
        elif action == "sell":
            stop_loss = None
            take_profit = None
        else:
            stop_loss = round(close - 2.5 * atr, 2)
            take_profit = round(close + 3.0 * atr, 2)

        # 紧急度
        max_confidence = max((r["confidence"] for r in reasons), default=0.5)
        if max_confidence >= 0.85 and len(reasons) >= 2:
            urgency = "high"
        elif max_confidence >= 0.75:
            urgency = "medium"
        else:
            urgency = "low"

        return {
            "ts_code": ts_code,
            "name": stock_name,
            "action": action,
            "price": close,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "reasons": reasons,
            "strategies": list({r["strategy"] for r in reasons}),
            "urgency": urgency,
            "date": latest_date,
        }

    def generate_morning_brief(self, stock_codes: List[str] = None) -> str:
        """生成早盘提醒文本（用于微信通知）"""
        result = self.generate_daily_signals(stock_codes=stock_codes)
        if not result.get("signals"):
            return "📊 QuantWeave 早盘提醒\n\n今日无操作信号，继续观望。"

        lines = ["📊 QuantWeave 早盘提醒", f"📅 {result['date']}", ""]

        # 买入建议
        buys = [s for s in result["signals"] if s["action"] == "buy"]
        if buys:
            lines.append("🟢 建议买入:")
            for s in buys[:5]:
                strategies_str = ",".join(s["strategies"][:3])
                lines.append(
                    f"  • {s['name']}({s['ts_code']}) "
                    f"现价:{s['price']:.2f} "
                    f"止损:{s['stop_loss']:.2f} "
                    f"止盈:{s['take_profit']:.2f}"
                )
                lines.append(f"    策略: {strategies_str}")
            lines.append("")

        # 卖出建议
        sells = [s for s in result["signals"] if s["action"] == "sell"]
        if sells:
            lines.append("🔴 建议卖出:")
            for s in sells[:5]:
                strategies_str = ",".join(s["strategies"][:3])
                lines.append(
                    f"  • {s['name']}({s['ts_code']}) "
                    f"现价:{s['price']:.2f}"
                )
                lines.append(f"    策略: {strategies_str}")
            lines.append("")

        # 统计
        summary = result["summary"]
        lines.append(f"📈 总计: 买入{summary['buy']} 卖出{summary['sell']} 观望{summary['hold']}")

        return "\n".join(lines)

    def _calculate_atr(self, df: pd.DataFrame, period: int = 14) -> float:
        """计算ATR"""
        if len(df) < period + 1:
            return float(df["close"].iloc[-1] * 0.03)  # 默认3%
        high = df["high"]
        low = df["low"]
        close = df["close"]
        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(period).mean().iloc[-1]
        return float(atr) if not pd.isna(atr) else float(close.iloc[-1] * 0.03)

    def _get_default_watchlist(self) -> List[str]:
        """获取默认关注列表"""
        # 从数据库读取已配置的股票池
        stocks = self.db.query(Stock).filter(Stock.is_active == True).limit(50).all()
        if stocks:
            return [s.ts_code for s in stocks]
        # 默认蓝筹股
        return [
            "600519.SH", "000858.SZ", "601318.SH", "600036.SH",
            "000001.SZ", "000333.SZ", "601398.SH", "000651.SZ",
        ]

    def _get_stock_name(self, ts_code: str) -> str:
        """获取股票名称"""
        stock = self.db.query(Stock).filter(Stock.ts_code == ts_code).first()
        return stock.name if stock else ts_code

    def _get_next_trade_day(self, date_str: str) -> str:
        """简单估算下一交易日（跳过周末）"""
        dt = datetime.strptime(date_str, "%Y%m%d")
        next_dt = dt + timedelta(days=1)
        while next_dt.weekday() >= 5:  # 周六日
            next_dt += timedelta(days=1)
        return next_dt.strftime("%Y%m%d")
