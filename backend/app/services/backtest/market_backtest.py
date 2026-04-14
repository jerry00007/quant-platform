"""
QuantWeave - 全市场动态选股回测引擎
每日全市场扫描，动态调仓
"""
import pandas as pd
import numpy as np
from loguru import logger
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from collections import defaultdict

from ..strategy.strategy_service import Signal, SignalType, get_strategy, STRATEGY_REGISTRY
from ..data.data_service import DataService
from ...models.models import Stock


class MarketBacktestEngine:
    """全市场动态选股回测引擎"""
    
    def __init__(self, data_service: DataService, initial_cash: float = 1000000.0,
                 commission: float = 0.0003, slippage: float = 0.001,
                 max_positions: int = 10,
                 position_per_stock: float = 0.2,
                 rebalance_interval: int = 1,
                 stop_loss_pct: float = -0.08,
                 take_profit_pct: float = 0.15):
        """
        Args:
            initial_cash: 初始资金
            commission: 手续费率
            slippage: 滑点
            max_positions: 最大持仓数
            position_per_stock: 单只股票仓位比例
            rebalance_interval: 调仓间隔（天数）
            stop_loss_pct: 止损比例
            take_profit_pct: 止盈比例
        """
        self.data_service = data_service
        self.initial_cash = initial_cash
        self.commission = commission
        self.slippage = slippage
        self.max_positions = max_positions
        self.position_per_stock = position_per_stock
        self.rebalance_interval = rebalance_interval
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
    
    def run(self, strategy_types: List[str],
            start_date: str, end_date: str,
            stock_limit: int = 200) -> dict:
        """
        执行全市场动态回测
        
        Args:
            strategy_types: 策略列表
            start_date: 开始日期
            end_date: 结束日期
            stock_limit: 每日扫描的股票数量限制
        
        Returns:
            回测结果
        """
        logger.info(f"开始全市场动态回测: {strategy_types} | {start_date}-{end_date}")
        
        # 1. 获取交易日列表
        trading_dates = self._get_trading_dates(start_date, end_date)
        if not trading_dates:
            return {"error": "无可用交易日数据"}
        logger.info(f"共 {len(trading_dates)} 个交易日")
        
        # 2. 获取股票列表
        stocks = self._get_stock_list(limit=stock_limit)
        logger.info(f"股票池: {len(stocks)} 只")
        
        # 3. 预加载所有股票数据（提高性能）
        logger.info("预加载股票数据...")
        stock_data_cache = self._preload_stock_data(stocks, start_date, end_date)
        
        # 4. 初始化状态
        cash = self.initial_cash
        positions = {}  # {ts_code: {"shares": int, "cost": float}}
        trades = []
        equity_curve = []
        daily_returns = []
        daily_positions_count = []
        
        # 5. 逐日回测
        for day_idx, current_date in enumerate(trading_dates):
            date_str = current_date.strftime("%Y%m%d")
            
            # 获取当日行情
            date_data = self._get_date_data(stock_data_cache, date_str)
            if not date_data:
                continue
            
            # 调仓检查（每日或止损止盈）
            need_rebalance = (day_idx % self.rebalance_interval == 0)
            
            # 检查持仓股票的止损止盈
            positions_to_close = []
            for ts_code, pos in list(positions.items()):
                if ts_code not in date_data:
                    continue
                current_price = date_data[ts_code]["close"]
                cost = pos["cost"]
                pnl_pct = (current_price - cost) / cost
                
                # 止损
                if pnl_pct <= self.stop_loss_pct:
                    positions_to_close.append((ts_code, "止损", pnl_pct))
                # 止盈
                elif pnl_pct >= self.take_profit_pct:
                    positions_to_close.append((ts_code, "止盈", pnl_pct))
            
            # 执行卖出（止损止盈）
            for ts_code, reason, pnl_pct in positions_to_close:
                pos = positions[ts_code]
                price = date_data[ts_code]["close"] * (1 - self.slippage)
                amount = pos["shares"] * price
                comm = amount * self.commission
                profit = amount - (pos["cost"] * pos["shares"]) - comm
                
                cash += (amount - comm)
                trades.append({
                    "date": date_str,
                    "direction": "sell",
                    "ts_code": ts_code,
                    "price": round(price, 2),
                    "volume": pos["shares"],
                    "amount": round(amount, 2),
                    "commission": round(comm, 2),
                    "profit": round(profit, 2),
                    "signal": f"{reason} {pnl_pct*100:+.1f}%",
                })
                del positions[ts_code]
                logger.debug(f"[{date_str}] {ts_code} {reason}, 卖出 {pos['shares']}股")
            
            # 调仓：选出新的买入标的
            if need_rebalance and len(positions) < self.max_positions:
                candidates = self._scan_candidates(
                    stock_data_cache, date_str, strategy_types
                )
                
                # 排除已有持仓
                candidates = [c for c in candidates if c["ts_code"] not in positions]
                
                # 买入新标的
                slots = self.max_positions - len(positions)
                for candidate in candidates[:slots]:
                    ts_code = candidate["ts_code"]
                    if ts_code not in date_data:
                        continue
                    
                    price = date_data[ts_code]["close"] * (1 + self.slippage)
                    buy_budget = cash * self.position_per_stock
                    shares = int(buy_budget / price / 100) * 100
                    
                    if shares <= 0:
                        continue
                    
                    cost = shares * price
                    comm = cost * self.commission
                    total_cost = cost + comm
                    
                    if total_cost > cash:
                        continue
                    
                    cash -= total_cost
                    positions[ts_code] = {"shares": shares, "cost": price}
                    trades.append({
                        "date": date_str,
                        "direction": "buy",
                        "ts_code": ts_code,
                        "price": round(price, 2),
                        "volume": shares,
                        "amount": round(cost, 2),
                        "commission": round(comm, 2),
                        "signal": candidate.get("signal", "选股信号"),
                    })
                    logger.debug(f"[{date_str}] 买入 {ts_code} {shares}股 @ {price:.2f}")
            
            # 计算当日净值
            market_value = sum(
                positions[ts_code]["shares"] * date_data.get(ts_code, {}).get("close", 0)
                for ts_code in positions
            )
            total_value = cash + market_value
            equity_curve.append({"date": date_str, "value": total_value})
            daily_positions_count.append(len(positions))
            
            # 当日收益率
            if len(equity_curve) > 1:
                daily_ret = (total_value - equity_curve[-2]["value"]) / equity_curve[-2]["value"]
            else:
                daily_ret = 0
            daily_returns.append({"date": date_str, "return": daily_ret})
            
            if day_idx % 20 == 0:
                logger.info(f"  进度: {day_idx}/{len(trading_dates)}, 持仓: {len(positions)}, 净值: {total_value:.0f}")
        
        # 6. 计算最终资产（强制平仓）
        final_date = trading_dates[-1].strftime("%Y%m%d")
        final_data = self._get_date_data(stock_data_cache, final_date)
        
        for ts_code, pos in list(positions.items()):
            if final_data and ts_code in final_data:
                price = final_data[ts_code]["close"] * (1 - self.slippage)
                amount = pos["shares"] * price
                comm = amount * self.commission
                profit = amount - (pos["cost"] * pos["shares"]) - comm
                
                cash += (amount - comm)
                trades.append({
                    "date": final_date,
                    "direction": "sell",
                    "ts_code": ts_code,
                    "price": round(price, 2),
                    "volume": pos["shares"],
                    "amount": round(amount, 2),
                    "commission": round(comm, 2),
                    "profit": round(profit, 2),
                    "signal": "强制平仓",
                })
        positions.clear()
        
        final_value = cash
        equity_curve[-1]["value"] = final_value
        
        # 7. 计算指标
        result = self._calculate_metrics(
            trades, equity_curve, daily_returns, 
            len(trading_dates), daily_positions_count
        )
        
        result["strategy_name"] = f"全市场动态选股({','.join(strategy_types)})"
        result["start_date"] = start_date
        result["end_date"] = end_date
        
        logger.info(
            f"全市场回测完成: 收益={result['total_return']:.2f}%, 回撤={result['max_drawdown']:.2f}%, "
            f"夏普={result['sharpe_ratio']:.3f}, 交易={result['total_trades']}次"
        )
        return result
    
    def _get_trading_dates(self, start_date: str, end_date: str) -> List[datetime]:
        """获取交易日列表（从数据库获取）"""
        dates = []
        try:
            from sqlalchemy import distinct, cast, String
            from ...models.models import StockDaily
            session = self.data_service.db
            
            # 确保日期是字符串格式
            start_str = str(start_date)
            end_str = str(end_date)
            
            logger.info(f"查询交易日: {start_str} - {end_str}")
            
            # 直接用字符串比较
            query = session.query(StockDaily.trade_date).filter(
                StockDaily.trade_date >= start_str,
                StockDaily.trade_date <= end_str
            ).distinct().order_by(StockDaily.trade_date)
            
            logger.info(f"SQL: {query}")
            
            for row in query:
                date_val = row[0]
                if isinstance(date_val, str):
                    dates.append(datetime.strptime(date_val, "%Y%m%d"))
                else:
                    dates.append(date_val)
                    
            logger.info(f"找到 {len(dates)} 个交易日")
        except Exception as e:
            logger.warning(f"获取交易日失败: {e}")
            import traceback
            traceback.print_exc()
        return dates
    
    def _get_stock_list(self, limit: int = 200) -> List[dict]:
        """获取股票列表"""
        try:
            session = self.data_service.db
            stocks = session.query(Stock).filter(
                Stock.is_active == True
            ).limit(limit).all()
            return [{"ts_code": s.ts_code, "name": s.name} for s in stocks]
        except Exception as e:
            logger.warning(f"获取股票列表失败: {e}")
            return []
    
    def _preload_stock_data(self, stocks: List[dict], start_date: str, end_date: str) -> dict:
        """预加载所有股票数据"""
        cache = {}
        for stock in stocks:
            ts_code = stock["ts_code"]
            try:
                df = self.data_service.fetch_daily(ts_code, start_date, end_date)
                if not df.empty:
                    cache[ts_code] = df
            except Exception:
                continue
        return cache
    
    def _get_date_data(self, stock_data_cache: dict, date_str: str) -> dict:
        """获取指定日期所有股票的价格数据"""
        date_data = {}
        for ts_code, df in stock_data_cache.items():
            df_dates = df["trade_date"].astype(str)
            mask = df_dates == date_str
            if mask.any():
                row = df[mask].iloc[0]
                date_data[ts_code] = {
                    "close": float(row["close"]),
                    "open": float(row.get("open", row["close"])),
                    "high": float(row.get("high", row["close"])),
                    "low": float(row.get("low", row["close"])),
                    "vol": float(row.get("vol", 0)),
                }
        return date_data
    
    def _scan_candidates(self, stock_data_cache: dict, date_str: str, 
                         strategy_types: List[str]) -> List[dict]:
        """扫描候选股票"""
        candidates = []
        
        for ts_code, df in stock_data_cache.items():
            df_dates = df["trade_date"].astype(str)
            if date_str not in df_dates.values:
                continue
            
            # 获取该日之前的数据用于信号生成
            df_before = df[df_dates <= date_str]
            if len(df_before) < 30:
                continue
            
            try:
                # 使用第一个策略生成信号
                strategy = get_strategy(strategy_types[0])
                signals = strategy.generate_signals(df_before, ts_code)
                
                # 检查当日是否有买入信号
                buy_signals = [s for s in signals if s.signal_type == SignalType.BUY and s.date == date_str]
                
                if buy_signals:
                    score = buy_signals[0].confidence * 100
                    row = df[df_dates == date_str].iloc[0]
                    candidates.append({
                        "ts_code": ts_code,
                        "score": score,
                        "price": float(row["close"]),
                        "signal": buy_signals[0].reason,
                    })
            except Exception:
                continue
        
        # 按评分排序
        candidates.sort(key=lambda x: x["score"], reverse=True)
        return candidates[:20]
    
    def _calculate_metrics(self, trades: List[dict], equity_curve: List[dict],
                          daily_returns: List[dict], trading_days: int,
                          daily_positions_count: List[int]) -> dict:
        """计算回测指标"""
        final_value = equity_curve[-1]["value"] if equity_curve else self.initial_cash
        total_return = (final_value - self.initial_cash) / self.initial_cash * 100
        
        # 年化收益
        trading_days_per_year = 244
        annual_return = ((1 + total_return / 100) ** (trading_days_per_year / max(trading_days, 1)) - 1) * 100 if trading_days > 0 else 0
        
        # 最大回撤
        values = [e["value"] for e in equity_curve]
        peak = values[0]
        max_dd = 0
        for v in values:
            if v > peak:
                peak = v
            dd = (peak - v) / peak * 100 if peak > 0 else 0
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
        
        return {
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
            "avg_positions": round(np.mean(daily_positions_count), 1) if daily_positions_count else 0,
            "max_positions": max(daily_positions_count) if daily_positions_count else 0,
        }