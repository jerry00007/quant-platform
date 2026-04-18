"""
QuantWeave - 每日信号服务
生成次日操作建议：买入/卖出/止损/止盈
"""
import json
import sqlite3
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
from loguru import logger
from typing import Dict, List, Optional
from sqlalchemy.orm import Session

from ...models.models import Stock, StockDaily, Position
from ..data.data_service import DataService
from ..strategy.strategy_service import (
    STRATEGY_REGISTRY, SignalType, get_strategy
)

# 雪球实时行情（可选）
try:
    from ..data.xueqiu_data import batch_realtime_quotes
    _HAS_XUEQIU = True
except ImportError:
    _HAS_XUEQIU = False


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
        """生成早盘提醒文本（用于微信通知）
        
        信号来源：scan_results 表（一键选股结果），不是旧的 11 策略系统。
        """
        today_str = datetime.now().strftime("%Y%m%d")
        lines = ["📊 QuantWeave 早盘提醒", f"📅 {today_str}", ""]

        # 我的持仓（头部）
        self._append_portfolio_section(lines)

        # 从 scan_results 表读取最新一键选股结果
        scan_data = self._get_latest_scan_results()
        if scan_data:
            resonance = scan_data.get("resonance", [])
            strategy_signals = scan_data.get("strategy_signals", {})

            # 🔴 共振股推荐（Top5，按评分排序）
            if resonance:
                # 按评分降序
                sorted_res = sorted(resonance, key=lambda x: x.get("score", {}).get("total", 0), reverse=True)
                lines.append(f"🎯 共振股Top{min(len(sorted_res), 5)}:")
                for s in sorted_res[:5]:
                    score = s.get("score", {})
                    total_score = score.get("total", 0)
                    icon = score.get("icon", "⚪")
                    advice = score.get("advice", "—")
                    price = s.get("price", 0)
                    entry = s.get("entry_points", {})
                    stop_loss = entry.get("stop_loss", 0)
                    target = entry.get("target_1", 0)
                    strategies = ",".join(st.get("strategy", "") for st in s.get("strategies", [])[:3])
                    risk_level = s.get("risk_level", "safe")
                    risk_tag = " 🚫" if risk_level in ("block", "blocked") else (" ⚠️" if risk_level == "warning" else "")

                    lines.append(
                        f"  {icon} {s.get('name', '')}({s.get('ts_code', '')}) "
                        f"评分{total_score:.0f}({advice}){risk_tag}"
                    )
                    if price:
                        detail = f"    价:{price:.2f}"
                        if stop_loss:
                            detail += f" 止损:{stop_loss:.2f}"
                        if target:
                            detail += f" 目标:{target:.2f}"
                        lines.append(detail)
                    if strategies:
                        lines.append(f"    策略: {strategies}")
                lines.append("")

            # 各策略信号摘要
            if strategy_signals:
                lines.append("📋 策略信号:")
                for key, sigs in strategy_signals.items():
                    buy_count = sum(1 for s in sigs if s.get("signal", {}).get("signal") == "buy")
                    lines.append(f"  • {key}: {len(sigs)}只信号, {buy_count}只买入")
                lines.append("")

            # 统计
            total_res = len(resonance)
            total_signals = scan_data.get("total_signals", 0)
            total_stocks = scan_data.get("total_stocks", 0)
            scan_time = scan_data.get("scan_time", "")
            lines.append(
                f"📈 扫描{total_stocks}只, {total_signals}只信号, "
                f"{total_res}只共振 | 扫描时间:{scan_time}"
            )
        else:
            lines.append("⚠️ 暂无选股数据，请先执行一键选股。")

        return "\n".join(lines)

    def _get_latest_scan_results(self) -> Optional[Dict]:
        """从 scan_results 表读取最新一键选股结果"""
        try:
            db_path = Path(__file__).resolve().parent.parent.parent.parent / "quantweave.db"
            conn = sqlite3.connect(str(db_path))
            try:
                row = conn.execute(
                    "SELECT result_json FROM scan_results ORDER BY id DESC LIMIT 1"
                ).fetchone()
                if row and row[0]:
                    return json.loads(row[0])
            finally:
                conn.close()
        except Exception as e:
            logger.warning(f"读取 scan_results 失败: {e}")
        return None

    def _append_portfolio_section(self, lines: list):
        """在通知文本中追加持仓板块"""
        try:
            positions = (
                self.db.query(Position)
                .filter(Position.is_active == True)
                .all()
            )
            if not positions:
                return

            lines.append("💼 我的持仓:")
            total_mv = 0.0
            total_cost = 0.0
            pos_quotes = {}

            # 获取实时行情
            if _HAS_XUEQIU:
                try:
                    codes = [p.ts_code for p in positions]
                    pos_quotes = batch_realtime_quotes(codes) or {}
                except Exception as e:
                    logger.debug(f"持仓实时行情获取失败: {e}")

            for p in positions:
                q = pos_quotes.get(p.ts_code, {})
                cur_price = q.get("current", p.current_price or p.avg_cost)
                chg_pct = q.get("percent", 0)

                # 盈亏计算
                if cur_price and p.avg_cost:
                    pnl_pct = (cur_price - p.avg_cost) / p.avg_cost * 100
                    pnl_emoji = "🔴" if pnl_pct > 0 else "🟢"
                    chg_emoji = "🔴" if chg_pct >= 0 else "🟢"
                    lines.append(
                        f"  {chg_emoji} {p.name}({p.ts_code}) "
                        f"{cur_price:.2f} ({chg_pct:+.2f}%) | "
                        f"成本{p.avg_cost:.2f} {pnl_emoji}持仓{pnl_pct:+.2f}%"
                    )
                    total_mv += cur_price * p.volume
                    total_cost += p.avg_cost * p.volume
                else:
                    lines.append(f"  • {p.name}({p.ts_code}) {p.volume}股")

            if total_cost > 0:
                total_pnl = total_mv - total_cost
                total_pnl_pct = total_pnl / total_cost * 100
                pnl_emoji = "🔴" if total_pnl > 0 else "🟢"
                lines.append(f"  {'─' * 35}")
                lines.append(
                    f"  💰 总市值{total_mv / 10000:.2f}万 "
                    f"{pnl_emoji}总盈亏{total_pnl / 10000:+.2f}万({total_pnl_pct:+.2f}%)"
                )
            lines.append("")
        except Exception as e:
            logger.debug(f"持仓板块生成失败: {e}")

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
