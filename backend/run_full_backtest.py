#!/usr/bin/env python3
"""
QuantWeave 全市场全策略回测 - 11策略独立回测
输出 JSON 供可视化使用
"""
import sys, os, json, time, sqlite3
import pandas as pd
import numpy as np
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app.services.strategy.strategy_service import SignalType, get_strategy, STRATEGY_REGISTRY

# ============ 配置 ============
DB_PATH = os.path.join(os.path.dirname(__file__), "quantweave.db")
START_DATE = "20240415"
END_DATE = "20260414"
INITIAL_CASH = 1000000.0
COMMISSION = 0.0003
SLIPPAGE = 0.001
MAX_POSITIONS = 10
POSITION_PER_STOCK = 0.2
STOP_LOSS_PCT = -0.08
TAKE_PROFIT_PCT = 0.15
MIN_DATA_DAYS = 60
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "reports")

ALL_STRATEGIES = list(STRATEGY_REGISTRY.keys())
STRATEGY_NAMES = {
    "dual_ma": "双均线交叉", "bollinger": "布林带突破", "rsi": "RSI超买超卖",
    "macd": "MACD金叉死叉", "chip": "主力筹码", "enhanced_chip": "增强筹码",
    "pullback_stable": "强势股回调企稳", "vol_breakout": "爆量突破",
    "first_yin": "龙头首阴反抽", "trend_ma": "均线趋势跟踪", "top_bottom": "顶底图",
}


def load_stock_names(conn):
    df = pd.read_sql("SELECT ts_code, name FROM stocks", conn)
    return dict(zip(df["ts_code"], df["name"]))


def load_all_data(conn):
    print("  加载日线数据...")
    df = pd.read_sql(
        f"SELECT ts_code, trade_date, open, high, low, close, vol, amount "
        f"FROM stock_daily WHERE trade_date >= '{START_DATE}' AND trade_date <= '{END_DATE}' "
        f"ORDER BY ts_code, trade_date", conn
    )
    print(f"  总记录: {len(df)}")
    grouped = {}
    for ts_code, group in df.groupby("ts_code"):
        g = group.sort_values("trade_date").reset_index(drop=True)
        if len(g) >= MIN_DATA_DAYS:
            grouped[ts_code] = g
    print(f"  有效股票: {len(grouped)} (≥{MIN_DATA_DAYS}天)")
    return grouped


def get_trading_dates(all_data):
    dates = set()
    for df in all_data.values():
        dates.update(df["trade_date"].tolist())
    return sorted(dates)


def run_single_backtest(strategy_key, all_data, trading_dates, stock_names):
    """运行单策略全市场回测"""
    strategy_name = STRATEGY_NAMES.get(strategy_key, strategy_key)
    strategy = get_strategy(strategy_key)
    print(f"\n{'='*50}\n  策略: {strategy_name} ({strategy_key})\n{'='*50}")

    # 预计算每只股票的每日价格索引（加速）
    price_index = {}
    for ts_code, sdf in all_data.items():
        price_index[ts_code] = dict(zip(sdf["trade_date"].tolist(), sdf["close"].tolist()))

    cash = INITIAL_CASH
    positions = {}
    trades = []
    equity_curve = []
    daily_returns = []
    total_dates = len(trading_dates)
    t0 = time.time()

    for day_idx, current_date in enumerate(trading_dates):
        # 当日价格
        date_prices = {}
        for ts_code, pidx in price_index.items():
            if current_date in pidx:
                date_prices[ts_code] = pidx[current_date]

        if not date_prices:
            continue

        # 1. 止损止盈检查
        for ts_code, pos in list(positions.items()):
            if ts_code not in date_prices:
                continue
            cp = date_prices[ts_code]
            pnl = (cp - pos["cost"]) / pos["cost"]
            if pnl <= STOP_LOSS_PCT:
                reason, pnl_s = "止损", pnl
            elif pnl >= TAKE_PROFIT_PCT:
                reason, pnl_s = "止盈", pnl
            else:
                continue
            # 卖出
            price = cp * (1 - SLIPPAGE)
            amount = pos["shares"] * price
            comm = amount * COMMISSION
            profit = amount - (pos["cost"] * pos["shares"]) - comm
            cash += amount - comm
            trades.append({
                "date": current_date, "dir": "S",
                "code": ts_code, "name": stock_names.get(ts_code, ts_code),
                "price": round(price, 2), "vol": pos["shares"],
                "amount": round(amount, 2), "comm": round(comm, 2),
                "profit": round(profit, 2), "pnl_pct": round(pnl_s*100, 2),
                "reason": f"{reason} {pnl_s*100:+.1f}%"
            })
            del positions[ts_code]

        # 2. 扫描买入候选
        if len(positions) < MAX_POSITIONS:
            candidates = []
            for ts_code, sdf in all_data.items():
                if ts_code in positions or ts_code not in date_prices:
                    continue
                data_before = sdf[sdf["trade_date"] <= current_date]
                if len(data_before) < 30:
                    continue
                try:
                    signals = strategy.generate_signals(data_before, ts_code)
                    buys = [s for s in signals if s.signal_type == SignalType.BUY and s.date == current_date]
                    if buys:
                        candidates.append((ts_code, buys[0].confidence * 100, buys[0].reason))
                except Exception:
                    continue

            candidates.sort(key=lambda x: x[1], reverse=True)
            slots = MAX_POSITIONS - len(positions)
            for ts_code, score, sig_reason in candidates[:slots]:
                price = date_prices[ts_code] * (1 + SLIPPAGE)
                budget = cash * POSITION_PER_STOCK
                shares = int(budget / price / 100) * 100
                if shares <= 0:
                    continue
                cost = shares * price
                comm = cost * COMMISSION
                if cost + comm > cash:
                    continue
                cash -= cost + comm
                positions[ts_code] = {"shares": shares, "cost": price, "buy_date": current_date}
                trades.append({
                    "date": current_date, "dir": "B",
                    "code": ts_code, "name": stock_names.get(ts_code, ts_code),
                    "price": round(price, 2), "vol": shares,
                    "amount": round(cost, 2), "comm": round(comm, 2),
                    "profit": 0, "pnl_pct": 0,
                    "reason": sig_reason
                })

        # 3. 计算净值
        mv = sum(positions[c]["shares"] * date_prices.get(c, positions[c]["cost"])
                 for c in positions)
        tv = cash + mv
        equity_curve.append({"date": current_date, "value": round(tv, 2)})
        dr = (tv - equity_curve[-2]["value"]) / equity_curve[-2]["value"] if len(equity_curve) > 1 else 0
        daily_returns.append({"date": current_date, "return": dr})

        if (day_idx + 1) % 50 == 0 or day_idx == total_dates - 1:
            print(f"    [{day_idx+1}/{total_dates}] 持仓{len(positions)} 净值{tv:,.0f} 耗时{time.time()-t0:.0f}s")

    # 4. 强制平仓
    last_date = trading_dates[-1]
    for ts_code, pos in list(positions.items()):
        price = (date_prices.get(ts_code) or pos["cost"]) * (1 - SLIPPAGE)
        amount = pos["shares"] * price
        comm = amount * COMMISSION
        profit = amount - (pos["cost"] * pos["shares"]) - comm
        pnl = (price - pos["cost"]) / pos["cost"]
        cash += amount - comm
        trades.append({
            "date": last_date, "dir": "S",
            "code": ts_code, "name": stock_names.get(ts_code, ts_code),
            "price": round(price, 2), "vol": pos["shares"],
            "amount": round(amount, 2), "comm": round(comm, 2),
            "profit": round(profit, 2), "pnl_pct": round(pnl*100, 2),
            "reason": "强制平仓"
        })
    positions.clear()
    final_value = cash
    if equity_curve:
        equity_curve[-1]["value"] = round(final_value, 2)

    # 5. 指标计算
    total_ret = (final_value - INITIAL_CASH) / INITIAL_CASH * 100
    td = len(trading_dates)
    annual_ret = ((1 + total_ret/100) ** (244/max(td,1)) - 1) * 100 if td > 0 else 0
    vals = [e["value"] for e in equity_curve]
    peak, max_dd = vals[0] if vals else INITIAL_CASH, 0
    for v in vals:
        if v > peak: peak = v
        dd = (peak - v) / peak * 100 if peak > 0 else 0
        if dd > max_dd: max_dd = dd
    rets = [d["return"] for d in daily_returns]
    sharpe = np.mean(rets) / np.std(rets) * np.sqrt(244) if len(rets) > 1 and np.std(rets) > 0 else 0
    sells = [t for t in trades if t["dir"] == "S" and "profit" in t]
    wins = [t for t in sells if t["profit"] > 0]
    wr = len(wins) / len(sells) * 100 if sells else 0
    aw = np.mean([t["profit"] for t in wins]) if wins else 0
    al = abs(np.mean([t["profit"] for t in sells if t["profit"] <= 0])) if any(t["profit"] <= 0 for t in sells) else 1
    plr = aw / al if al > 0 else 0

    print(f"  => 收益={total_ret:.2f}% 回撤={max_dd:.2f}% 夏普={sharpe:.3f} 交易{len(trades)}次")
    return {
        "key": strategy_key, "name": strategy_name,
        "total_return": round(total_ret, 2), "annual_return": round(annual_ret, 2),
        "max_drawdown": round(max_dd, 2), "sharpe_ratio": round(sharpe, 3),
        "win_rate": round(wr, 2), "profit_loss_ratio": round(plr, 2),
        "total_trades": len(trades), "buys": len([t for t in trades if t["dir"]=="B"]),
        "sells": len([t for t in trades if t["dir"]=="S"]),
        "initial_cash": INITIAL_CASH, "final_value": round(final_value, 2),
        "equity_curve": equity_curve, "trades": trades,
    }


def main():
    print("=" * 50)
    print("  QuantWeave 全市场全策略回测")
    print(f"  区间: {START_DATE} ~ {END_DATE}")
    print(f"  策略: {len(ALL_STRATEGIES)} 个")
    print("=" * 50)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    stock_names = load_stock_names(conn)
    all_data = load_all_data(conn)
    trading_dates = get_trading_dates(all_data)
    conn.close()
    print(f"  交易日: {len(trading_dates)} ({trading_dates[0]}~{trading_dates[-1]})")

    results = {}
    for sk in ALL_STRATEGIES:
        r = run_single_backtest(sk, all_data, trading_dates, stock_names)
        results[sk] = r

    # 保存 JSON
    json_path = os.path.join(OUTPUT_DIR, "full_backtest_results.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False)
    print(f"\n  JSON 已保存: {json_path}")

    # 汇总表
    print("\n" + "=" * 80)
    print(f"  {'策略':<14} {'收益%':>8} {'年化%':>8} {'回撤%':>8} {'夏普':>6} {'胜率%':>6} {'盈亏比':>6} {'交易':>5}")
    print("-" * 80)
    for k, r in sorted(results.items(), key=lambda x: x[1]["total_return"], reverse=True):
        n = STRATEGY_NAMES.get(k, k)[:6]
        print(f"  {n:<14} {r['total_return']:>8.2f} {r['annual_return']:>8.2f} "
              f"{r['max_drawdown']:>8.2f} {r['sharpe_ratio']:>6.3f} "
              f"{r['win_rate']:>6.1f} {r['profit_loss_ratio']:>6.2f} {r['total_trades']:>5}")
    print("=" * 80)


if __name__ == "__main__":
    main()
