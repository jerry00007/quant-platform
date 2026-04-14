"""
QuantWeave - 回测引擎
模拟策略在历史数据上的表现，计算收益率、最大回撤、夏普比率等指标
"""
import pandas as pd
import numpy as np
from loguru import logger
from typing import Dict, List, Optional
from datetime import datetime

from ..strategy.strategy_service import Signal, SignalType, get_strategy
from ..data.data_service import DataService


class BacktestEngine:
    """回测引擎（支持仓位管理、移动止损、ATR止损）"""

    def __init__(self, data_service: DataService, initial_cash: float = 1000000.0,
                 commission: float = 0.0003, slippage: float = 0.001,
                 position_ratio: float = 1.0,
                 stop_loss_pct: float = None,
                 take_profit_pct: float = None,
                 trailing_stop_pct: float = None):
        """
        Args:
            position_ratio: 仓位比例（0.0~1.0），1.0=全仓，0.3=30%仓位
            stop_loss_pct: 固定止损比例（如 -0.08 表示-8%止损），None=不限
            take_profit_pct: 固定止盈比例（如 0.15 表示+15%止盈），None=不限
            trailing_stop_pct: 移动止损回撤比例（如 0.05 表示盈利后回撤5%止盈），None=不限
        """
        self.data_service = data_service
        self.initial_cash = initial_cash
        self.commission = commission
        self.slippage = slippage
        self.position_ratio = max(0.1, min(1.0, position_ratio))
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        self.trailing_stop_pct = trailing_stop_pct

    def run(self, strategy_type: str, ts_code: str,
            start_date: str, end_date: str,
            strategy_params: dict = None) -> dict:
        """
        执行回测
        
        Returns:
            {
                "total_return": 总收益率%,
                "annual_return": 年化收益率%,
                "max_drawdown": 最大回撤%,
                "sharpe_ratio": 夏普比率,
                "win_rate": 胜率%,
                "profit_loss_ratio": 盈亏比,
                "total_trades": 总交易次数,
                "final_value": 最终资产,
                "trades": [交易记录],
                "equity_curve": [净值曲线],
                "daily_returns": [每日收益率],
            }
        """
        logger.info(f"开始回测: {strategy_type} | {ts_code} | {start_date}-{end_date}")

        # 1. 获取数据
        df = self.data_service.fetch_daily(ts_code, start_date, end_date)
        if df.empty:
            logger.error("获取数据为空")
            return {"error": "获取数据为空，请检查股票代码和日期"}
        df = df.sort_values("trade_date").reset_index(drop=True)
        logger.info(f"获取到 {len(df)} 条数据")

        # 2. 生成信号
        strategy = get_strategy(strategy_type, strategy_params)
        signals = strategy.generate_signals(df, ts_code)
        logger.info(f"生成 {len(signals)} 个交易信号")

        # 3. 模拟交易（支持仓位管理 + 通用止损止盈）
        cash = self.initial_cash
        position = 0  # 持仓数量
        entry_price = 0.0  # 买入价格
        highest_since_buy = 0.0  # 买入后最高价（用于移动止损）
        trades = []
        equity_curve = []
        daily_returns = []

        for i, row in df.iterrows():
            date = str(row["trade_date"])
            price = float(row["close"])

            # 匹配当日信号
            day_signals = [s for s in signals if s.date == date]

            for signal in day_signals:
                if signal.signal_type == SignalType.BUY and position == 0:
                    # 买入：按仓位比例（不再全仓）
                    buy_price = price * (1 + self.slippage)
                    buy_budget = cash * self.position_ratio  # 按比例分配
                    shares = int(buy_budget / buy_price / 100) * 100  # 整百股
                    if shares <= 0:
                        continue
                    cost = shares * buy_price
                    comm = cost * self.commission
                    cash -= (cost + comm)
                    position = shares
                    entry_price = buy_price
                    highest_since_buy = buy_price
                    trades.append({
                        "date": date, "direction": "buy",
                        "price": buy_price, "volume": shares,
                        "amount": cost, "commission": comm,
                        "position_ratio": self.position_ratio,
                        "signal": signal.reason,
                    })
                    logger.debug(f"[{date}] 买入 {shares}股 @ {buy_price:.2f} (仓位{self.position_ratio*100:.0f}%)")

                elif signal.signal_type == SignalType.SELL and position > 0:
                    # 卖出：清仓
                    sell_price = price * (1 - self.slippage)
                    amount = position * sell_price
                    comm = amount * self.commission
                    profit = amount - trades[-1]["amount"] if trades else 0
                    cash += (amount - comm)
                    trades.append({
                        "date": date, "direction": "sell",
                        "price": sell_price, "volume": position,
                        "amount": amount, "commission": comm,
                        "profit": profit,
                        "signal": signal.reason,
                    })
                    logger.debug(f"[{date}] 卖出 {position}股 @ {sell_price:.2f}, 盈亏={profit:.2f}")
                    position = 0
                    entry_price = 0.0
                    highest_since_buy = 0.0

            # 通用止损止盈检查（持仓状态下每日检查）
            if position > 0 and price > 0:
                highest_since_buy = max(highest_since_buy, price)
                pnl_ratio = (price - entry_price) / entry_price

                should_sell = False
                sell_reason = ""

                # 固定止损
                if self.stop_loss_pct is not None and pnl_ratio <= self.stop_loss_pct:
                    should_sell = True
                    sell_reason = f"引擎止损 {pnl_ratio*100:+.1f}%"

                # 固定止盈
                elif self.take_profit_pct is not None and pnl_ratio >= self.take_profit_pct:
                    should_sell = True
                    sell_reason = f"引擎止盈 {pnl_ratio*100:+.1f}%"

                # 移动止盈（盈利后回撤）
                elif self.trailing_stop_pct is not None and entry_price > 0:
                    peak_pnl = (highest_since_buy - entry_price) / entry_price
                    if peak_pnl > 0.05:  # 至少盈利5%才启动
                        drawdown = (highest_since_buy - price) / highest_since_buy
                        if drawdown >= self.trailing_stop_pct:
                            should_sell = True
                            sell_reason = f"移动止盈 峰值盈利{peak_pnl*100:.1f}% 回撤{drawdown*100:.1f}%"

                if should_sell:
                    sell_price = price * (1 - self.slippage)
                    amount = position * sell_price
                    comm = amount * self.commission
                    profit = amount - (entry_price * position)
                    cash += (amount - comm)
                    trades.append({
                        "date": date, "direction": "sell",
                        "price": sell_price, "volume": position,
                        "amount": amount, "commission": comm,
                        "profit": profit,
                        "signal": sell_reason,
                    })
                    logger.debug(f"[{date}] {sell_reason}, 卖出 {position}股")
                    position = 0
                    entry_price = 0.0
                    highest_since_buy = 0.0

            # 计算当日净值
            market_value = position * price
            total_value = cash + market_value
            equity_curve.append({"date": date, "value": total_value})

            # 当日收益率
            if i > 0 and equity_curve[-2]["value"] > 0:
                daily_ret = (total_value - equity_curve[-2]["value"]) / equity_curve[-2]["value"]
            else:
                daily_ret = 0
            daily_returns.append({"date": date, "return": daily_ret})

        # 4. 计算指标
        final_value = equity_curve[-1]["value"] if equity_curve else self.initial_cash
        total_return = (final_value - self.initial_cash) / self.initial_cash * 100

        # 年化收益
        days = len(df)
        trading_days_per_year = 244
        annual_return = ((1 + total_return / 100) ** (trading_days_per_year / max(days, 1)) - 1) * 100 if days > 0 else 0

        # 最大回撤
        values = [e["value"] for e in equity_curve]
        peak = values[0]
        max_dd = 0
        for v in values:
            if v > peak:
                peak = v
            dd = (peak - v) / peak * 100
            if dd > max_dd:
                max_dd = dd

        # 夏普比率
        rets = [d["return"] for d in daily_returns]
        sharpe = 0
        if len(rets) > 1 and np.std(rets) > 0:
            sharpe = np.mean(rets) / np.std(rets) * np.sqrt(trading_days_per_year)

        # 胜率 & 盈亏比
        sell_trades = [t for t in trades if t["direction"] == "sell" and "profit" in t]
        wins = [t for t in sell_trades if t["profit"] > 0]
        win_rate = len(wins) / len(sell_trades) * 100 if sell_trades else 0
        avg_win = np.mean([t["profit"] for t in wins]) if wins else 0
        avg_loss = abs(np.mean([t["profit"] for t in sell_trades if t["profit"] <= 0])) if sell_trades else 1
        pl_ratio = avg_win / avg_loss if avg_loss > 0 else 0

        result = {
            "total_return": round(total_return, 2),
            "annual_return": round(annual_return, 2),
            "max_drawdown": round(max_dd, 2),
            "sharpe_ratio": round(sharpe, 3),
            "win_rate": round(win_rate, 2),
            "profit_loss_ratio": round(pl_ratio, 2),
            "total_trades": len(trades),
            "initial_cash": self.initial_cash,
            "final_value": round(final_value, 2),
            "trades": trades,
            "equity_curve": equity_curve,
            "daily_returns": daily_returns,
            "strategy_name": strategy.name,
            "ts_code": ts_code,
            "start_date": start_date,
            "end_date": end_date,
        }

        logger.info(
            f"回测完成: 收益={total_return:.2f}%, 回撤={max_dd:.2f}%, "
            f"夏普={sharpe:.3f}, 胜率={win_rate:.1f}%, 交易={len(trades)}次"
        )
        return result
