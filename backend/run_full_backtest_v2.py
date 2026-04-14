#!/usr/bin/env python3
"""
QuantWeave 全市场全策略回测 V2（优化版）
核心优化：先批量预计算所有股票信号，再逐日模拟交易
"""
import sys, os, json, time, sqlite3
import pandas as pd
import numpy as np
from datetime import datetime
from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing as mp

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


def load_data():
    """从 SQLite 加载所有数据"""
    print("  加载数据...")
    conn = sqlite3.connect(DB_PATH)
    names_df = pd.read_sql("SELECT ts_code, name FROM stocks", conn)
    stock_names = dict(zip(names_df["ts_code"], names_df["name"]))

    df = pd.read_sql(
        f"SELECT ts_code, trade_date, open, high, low, close, vol, amount "
        f"FROM stock_daily WHERE trade_date >= '{START_DATE}' AND trade_date <= '{END_DATE}' "
        f"ORDER BY ts_code, trade_date", conn
    )
    conn.close()
    print(f"  总记录: {len(df)}")

    # 分组为 dict
    all_data = {}
    for ts_code, group in df.groupby("ts_code"):
        g = group.sort_values("trade_date").reset_index(drop=True)
        if len(g) >= MIN_DATA_DAYS:
            all_data[ts_code] = g

    trading_dates = sorted(df["trade_date"].unique().tolist())
    print(f"  有效股票: {len(all_data)} | 交易日: {len(trading_dates)}")
    return all_data, trading_dates, stock_names


def precompute_signals_for_stock(args):
    """为单只股票计算某策略的所有买入信号（用于多进程）"""
    ts_code, df_dict, strategy_key = args
    try:
        strategy = get_strategy(strategy_key)
        df = pd.DataFrame(df_dict)
        signals = strategy.generate_signals(df, ts_code)
        buy_dates = set()
        best_signals = {}
        for s in signals:
            if s.signal_type == SignalType.BUY and s.date:
                buy_dates.add(s.date)
                if s.date not in best_signals or s.confidence > best_signals[s.date]["score"]:
                    best_signals[s.date] = {
                        "score": s.confidence * 100,
                        "reason": s.reason,
                    }
        return ts_code, buy_dates, best_signals
    except Exception:
        return ts_code, set(), {}


def precompute_strategy_signals(strategy_key, all_data):
    """预计算某策略所有股票的买入信号"""
    strategy_name = STRATEGY_NAMES.get(strategy_key, strategy_key)
    print(f"  预计算信号: {strategy_name} ({strategy_key})...")

    # 转换 DataFrame 为 dict 用于序列化
    stock_args = []
    for ts_code, df in all_data.items():
        stock_args.append((ts_code, df.to_dict('list'), strategy_key))

    # 单进程版（避免多进程序列化开销）
    buy_signals = {}  # {ts_code: {date: {score, reason}}}
    buy_dates_map = {}  # {date: [ts_code1, ts_code2, ...]}

    t0 = time.time()
    for idx, (ts_code, df_dict, sk) in enumerate(stock_args):
        tc, dates, sigs = precompute_signals_for_stock((ts_code, df_dict, sk))
        if dates:
            buy_signals[tc] = sigs
            for d in dates:
                if d not in buy_dates_map:
                    buy_dates_map[d] = []
                buy_dates_map[d].append((tc, sigs[d]["score"]))

        if (idx + 1) % 500 == 0:
            print(f"    [{idx+1}/{len(stock_args)}] 耗时{time.time()-t0:.0f}s")

    print(f"    完成: {len(buy_signals)}只股票有买入信号, {len(buy_dates_map)}个交易日有信号, 耗时{time.time()-t0:.0f}s")
    return buy_signals, buy_dates_map


def simulate_trading(strategy_key, all_data, trading_dates, stock_names,
                     buy_signals, buy_dates_map):
    """基于预计算信号模拟交易"""
    strategy_name = STRATEGY_NAMES.get(strategy_key, strategy_key)
    print(f"  模拟交易: {strategy_name}...")

    # 预计算价格索引
    price_idx = {}
    for ts_code, sdf in all_data.items():
        price_idx[ts_code] = dict(zip(sdf["trade_date"].tolist(), sdf["close"].tolist()))

    cash = INITIAL_CASH
    positions = {}
    trades = []
    equity_curve = []
    daily_returns = []

    for day_idx, current_date in enumerate(trading_dates):
        # 当日价格
        date_prices = {}
        for ts_code, pidx in price_idx.items():
            if current_date in pidx:
                date_prices[ts_code] = pidx[current_date]
        if not date_prices:
            continue

        # 1. 止损止盈
        for ts_code, pos in list(positions.items()):
            if ts_code not in date_prices:
                continue
            cp = date_prices[ts_code]
            pnl = (cp - pos["cost"]) / pos["cost"]
            if pnl <= STOP_LOSS_PCT:
                reason = f"止损 {pnl*100:+.1f}%"
            elif pnl >= TAKE_PROFIT_PCT:
                reason = f"止盈 {pnl*100:+.1f}%"
            else:
                continue
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
                "profit": round(profit, 2), "pnl_pct": round(pnl*100, 2),
                "reason": reason
            })
            del positions[ts_code]

        # 2. 买入候选（从预计算信号中查找）
        if len(positions) < MAX_POSITIONS and current_date in buy_dates_map:
            candidates = [
                (tc, score) for tc, score in buy_dates_map[current_date]
                if tc not in positions and tc in date_prices
            ]
            candidates.sort(key=lambda x: x[1], reverse=True)
            slots = MAX_POSITIONS - len(positions)
            for tc, score in candidates[:slots]:
                price = date_prices[tc] * (1 + SLIPPAGE)
                budget = cash * POSITION_PER_STOCK
                shares = int(budget / price / 100) * 100
                if shares <= 0:
                    continue
                cost = shares * price
                comm = cost * COMMISSION
                if cost + comm > cash:
                    continue
                cash -= cost + comm
                positions[tc] = {"shares": shares, "cost": price, "buy_date": current_date}
                sig = buy_signals.get(tc, {}).get(current_date, {})
                trades.append({
                    "date": current_date, "dir": "B",
                    "code": tc, "name": stock_names.get(tc, tc),
                    "price": round(price, 2), "vol": shares,
                    "amount": round(cost, 2), "comm": round(comm, 2),
                    "profit": 0, "pnl_pct": 0,
                    "reason": sig.get("reason", "选股信号")
                })

        # 3. 净值
        mv = sum(positions[c]["shares"] * date_prices.get(c, positions[c]["cost"]) for c in positions)
        tv = cash + mv
        equity_curve.append({"date": current_date, "value": round(tv, 2)})
        dr = (tv - equity_curve[-2]["value"]) / equity_curve[-2]["value"] if len(equity_curve) > 1 else 0
        daily_returns.append({"date": current_date, "return": dr})

    # 4. 强制平仓
    last_date = trading_dates[-1]
    for ts_code, pos in list(positions.items()):
        cp = date_prices.get(ts_code, pos["cost"])
        price = cp * (1 - SLIPPAGE)
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

    # 5. 指标
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

    print(f"    收益={total_ret:.2f}% 回撤={max_dd:.2f}% 夏普={sharpe:.3f} 交易{len(trades)}次")
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
    t_all = time.time()
    print("=" * 50)
    print("  QuantWeave 全市场全策略回测 V2")
    print(f"  区间: {START_DATE} ~ {END_DATE}")
    print(f"  策略: {len(ALL_STRATEGIES)} 个")
    print("=" * 50)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    all_data, trading_dates, stock_names = load_data()

    results = {}
    for sk in ALL_STRATEGIES:
        print(f"\n{'='*50}")
        t1 = time.time()
        buy_signals, buy_dates_map = precompute_strategy_signals(sk, all_data)
        t2 = time.time()
        r = simulate_trading(sk, all_data, trading_dates, stock_names, buy_signals, buy_dates_map)
        t3 = time.time()
        print(f"  总耗时: 信号预计算{t2-t1:.0f}s + 交易模拟{t3-t2:.0f}s = {t3-t1:.0f}s")
        results[sk] = r

    # 保存 JSON
    json_path = os.path.join(OUTPUT_DIR, "full_backtest_results.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False)
    print(f"\n  JSON 已保存: {json_path}")

    # 汇总
    print("\n" + "=" * 80)
    print(f"  {'策略':<14} {'收益%':>8} {'年化%':>8} {'回撤%':>8} {'夏普':>6} {'胜率%':>6} {'盈亏比':>6} {'交易':>5} {'最终资产':>14}")
    print("-" * 80)
    for k, r in sorted(results.items(), key=lambda x: x[1]["total_return"], reverse=True):
        n = STRATEGY_NAMES.get(k, k)[:6]
        print(f"  {n:<14} {r['total_return']:>8.2f} {r['annual_return']:>8.2f} "
              f"{r['max_drawdown']:>8.2f} {r['sharpe_ratio']:>6.3f} "
              f"{r['win_rate']:>6.1f} {r['profit_loss_ratio']:>6.2f} {r['total_trades']:>5} "
              f"¥{r['final_value']:>14,.0f}")
    print("=" * 80)
    print(f"\n  全部完成，总耗时: {(time.time()-t_all)/60:.1f} 分钟")


if __name__ == "__main__":
    main()
