"""
涨停洗盘 & 高窄旗形 参数扫描脚本（优化版）
数据只加载一次，参数变体共享预计算结果。
运行方式: cd backend && python run_param_sweep.py
"""

import sys
import json
import time
from pathlib import Path
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from loguru import logger

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / "app" / "services" / "strategy"))

from core_signals import CORE_STRATEGIES

DB_PATH = str(Path(__file__).resolve().parent / "quantweave.db")
STAMP_TAX = 0.001

LIMIT_UP_VARIANTS = {
    "v0-original": {
        "label": "原版（涨停9.5%/放量2x/跌破2%/7天）— 0信号基准",
        "params": {"limit_up_pct": 0.095, "vol_surge_mult": 2.0, "max_break_pct": 0.02, "hold_days": 7, "stop_loss_pct": 0.05},
        "bp": {"max_hold_days": 7, "stop_loss": -0.05},
    },
    "v1-relax-vol": {
        "label": "放量1.2x+跌破3%（降低放量门槛）",
        "params": {"limit_up_pct": 0.095, "vol_surge_mult": 1.2, "max_break_pct": 0.03, "hold_days": 7, "stop_loss_pct": 0.05},
        "bp": {"max_hold_days": 7, "stop_loss": -0.05},
    },
    "v2-big-yang": {
        "label": "大阳5%+放量1.0x+跌破5%/10天",
        "params": {"limit_up_pct": 0.05, "vol_surge_mult": 1.0, "max_break_pct": 0.05, "hold_days": 10, "stop_loss_pct": 0.06},
        "bp": {"max_hold_days": 10, "stop_loss": -0.06},
    },
    "v3-aggressive": {
        "label": "大阳7%+放量1.0x+跌破3%/5天/5仓",
        "params": {"limit_up_pct": 0.07, "vol_surge_mult": 1.0, "max_break_pct": 0.03, "hold_days": 5, "stop_loss_pct": 0.04},
        "bp": {"max_positions": 5, "top_n": 3, "max_hold_days": 5, "stop_loss": -0.04},
    },
    "v4-moderate": {
        "label": "大阳8%+放量1.0x+跌破4%/10天",
        "params": {"limit_up_pct": 0.08, "vol_surge_mult": 1.0, "max_break_pct": 0.04, "hold_days": 10, "stop_loss_pct": 0.05},
        "bp": {"max_hold_days": 10, "stop_loss": -0.05},
    },
}

FLAG_VARIANTS = {
    "v0-original": {
        "label": "原版（40日涨60%/10日收敛15%）— 0信号基准",
        "params": {"momentum_period": 40, "momentum_pct": 0.60, "flag_period": 10, "flag_pct": 0.15, "support_pct": 0.80, "vol_period": 20, "vol_shrink_pct": 0.6},
        "bp": {"max_hold_days": 15, "stop_loss": -0.08},
    },
    "v1-moderate": {
        "label": "30日涨30%/10日收敛20%/缩量0.8",
        "params": {"momentum_period": 30, "momentum_pct": 0.30, "flag_period": 10, "flag_pct": 0.20, "support_pct": 0.78, "vol_period": 15, "vol_shrink_pct": 0.8},
        "bp": {"max_hold_days": 15, "stop_loss": -0.08},
    },
    "v2-short": {
        "label": "15日涨15%/5日收敛10%/缩量0.9/5仓",
        "params": {"momentum_period": 15, "momentum_pct": 0.15, "flag_period": 5, "flag_pct": 0.10, "support_pct": 0.80, "vol_period": 10, "vol_shrink_pct": 0.9},
        "bp": {"max_positions": 5, "top_n": 3, "max_hold_days": 10, "stop_loss": -0.06},
    },
    "v3-ultra-relaxed": {
        "label": "10日涨10%/5日收敛8%/缩量0.9/5仓/30天",
        "params": {"momentum_period": 10, "momentum_pct": 0.10, "flag_period": 5, "flag_pct": 0.08, "support_pct": 0.80, "vol_period": 10, "vol_shrink_pct": 0.9},
        "bp": {"max_positions": 5, "top_n": 3, "max_hold_days": 30, "stop_loss": -0.08},
    },
    "v4-trend-follow": {
        "label": "20日涨20%/10日收敛15%/缩量0.8/5仓/20天",
        "params": {"momentum_period": 20, "momentum_pct": 0.20, "flag_period": 10, "flag_pct": 0.15, "support_pct": 0.78, "vol_period": 15, "vol_shrink_pct": 0.8},
        "bp": {"max_positions": 5, "top_n": 3, "max_hold_days": 20, "stop_loss": -0.08},
    },
}


def load_data(start_date, end_date):
    import sqlite3
    conn = sqlite3.connect(DB_PATH)
    try:
        stocks_df = pd.read_sql("SELECT ts_code, name FROM stocks WHERE is_active = 1", conn)
        stock_info = dict(zip(stocks_df["ts_code"], stocks_df["name"]))

        sd = datetime.strptime(start_date, "%Y%m%d") - timedelta(days=250)
        hist_start = sd.strftime("%Y%m%d")

        all_daily = pd.read_sql(
            f"SELECT ts_code, trade_date, open, high, low, close, vol, "
            f"COALESCE(change_pct, 0) as change_pct "
            f"FROM stock_daily "
            f"WHERE trade_date >= '{hist_start}' AND trade_date <= '{end_date}' "
            f"ORDER BY ts_code, trade_date", conn
        )

        for tc in all_daily["ts_code"].unique():
            mask = all_daily["ts_code"] == tc
            all_daily.loc[mask, "prev_close"] = all_daily.loc[mask, "close"].shift(1)

        limit_up_dates = {}
        for tc, grp in all_daily.groupby("ts_code"):
            dates = set(grp.loc[grp["change_pct"] >= 9.5, "trade_date"].astype(str).tolist())
            if dates:
                limit_up_dates[tc] = dates

        st_codes = set()
        try:
            st_rows = conn.execute(
                "SELECT ts_code FROM stocks WHERE is_active = 1 AND (name LIKE '%ST%' OR name LIKE '%st%')"
            ).fetchall()
            st_codes = {r[0] for r in st_rows}
        except Exception:
            pass

        stock_data = {}
        for tc, grp in all_daily.groupby("ts_code"):
            df = grp.sort_values("trade_date").reset_index(drop=True)
            if len(df) >= 80:
                stock_data[tc] = df

        rows = conn.execute(
            f"SELECT DISTINCT trade_date FROM stock_daily "
            f"WHERE trade_date >= '{start_date}' AND trade_date <= '{end_date}' ORDER BY trade_date"
        ).fetchall()
        trading_dates = [datetime.strptime(r[0], "%Y%m%d") for r in rows]

        return stock_data, stock_info, trading_dates, limit_up_dates, st_codes
    finally:
        conn.close()


def precompute_signals(stock_data, strategy_key, strategy_params):
    entry = CORE_STRATEGIES[strategy_key]
    func = entry["func"]
    needs_full = len(entry.get("needs", ["close"])) > 1
    all_signals = {}
    for tc, df in stock_data.items():
        close = df["close"].values.astype(float)
        dates = df["trade_date"].astype(str).tolist()
        try:
            if needs_full:
                sigs = func(close, df["high"].values.astype(float), df["low"].values.astype(float),
                           df["vol"].values.astype(float), df["open"].values.astype(float), dates, strategy_params)
            else:
                sigs = func(close, dates, strategy_params)
        except Exception:
            sigs = {}
        all_signals[tc] = {strategy_key: sigs}
    return all_signals


def build_signal_index(all_signals):
    buy_idx, sell_idx = {}, {}
    for tc, stock_sigs in all_signals.items():
        for sk, signals in stock_sigs.items():
            for ds, st in signals.items():
                if st == "buy":
                    buy_idx.setdefault(ds, {}).setdefault(tc, []).append(sk)
                elif st == "sell":
                    sell_idx.setdefault(ds, {}).setdefault(tc, []).append(sk)
    return buy_idx, sell_idx


def build_date_price_map(stock_data):
    date_map = {}
    for tc, df in stock_data.items():
        for _, row in df.iterrows():
            ds = str(row["trade_date"])
            if ds not in date_map:
                date_map[ds] = {}
            date_map[ds][tc] = {
                "open": float(row["open"]), "high": float(row["high"]),
                "low": float(row["low"]), "close": float(row["close"]),
                "vol": float(row["vol"]),
                "prev_close": float(row["prev_close"]) if "prev_close" in row and not pd.isna(row["prev_close"]) else float(row["close"]),
            }
    return date_map


def is_limit_up(dp_entry, threshold=9.8):
    close = dp_entry.get("close", 0)
    high = dp_entry.get("high", 0)
    prev_close = dp_entry.get("prev_close", 0)
    if prev_close <= 0 or high <= 0:
        return False
    change_pct = (close - prev_close) / prev_close * 100
    return change_pct >= threshold or (abs(close - high) < close * 0.001 and change_pct >= 9.5)


def run_variant(stock_data, trading_dates, date_price_map, limit_up_dates, st_codes,
                strategy_key, variant_id, config):
    params = config["params"]
    bp = config["bp"]
    max_positions = bp.get("max_positions", 3)
    max_hold_days = bp.get("max_hold_days", 15)
    stop_loss = bp.get("stop_loss", -0.08)

    all_signals = precompute_signals(stock_data, strategy_key, params)
    buy_idx, sell_idx = build_signal_index(all_signals)

    total_buy = sum(len(v) for v in buy_idx.values())
    logger.info(f"    {variant_id}: {total_buy} 买入信号")

    cash = 1_000_000.0
    positions = {}
    trades = []
    equity_curve = []
    daily_returns = []

    for day_i, cur_date in enumerate(trading_dates):
        ds = cur_date.strftime("%Y%m%d")
        dp = date_price_map.get(ds, {})
        if not dp:
            continue

        for tc, pos in list(positions.items()):
            if tc not in dp:
                continue
            p = dp[tc]["close"]
            pnl = (p - pos["cost"]) / pos["cost"]
            hold = day_i - pos["entry_day"]
            reason = None
            if pnl <= stop_loss:
                reason = "止损"
            elif hold >= max_hold_days:
                reason = "超期"
            elif tc in sell_idx.get(ds, {}):
                reason = "信号卖出"
            if reason:
                price = dp[tc]["close"] * 0.999
                amt = pos["shares"] * price
                comm = amt * 0.0003
                stamp = amt * STAMP_TAX
                profit = amt - pos["cost"] * pos["shares"] - comm - stamp
                cash += amt - comm - stamp
                trades.append({"direction": "sell", "profit": profit, "pnl": pnl})
                del positions[tc]

        if day_i % 2 == 0 and len(positions) < max_positions:
            candidates = []
            for tc in buy_idx.get(ds, {}):
                if tc in positions or tc.startswith("bj") or tc in st_codes:
                    continue
                dp_entry = dp.get(tc)
                if not dp_entry or is_limit_up(dp_entry):
                    continue
                recent_limit = any(
                    (cur_date - timedelta(days=o)).strftime("%Y%m%d") in limit_up_dates.get(tc, set())
                    for o in range(1, 6)
                )
                if recent_limit:
                    continue
                candidates.append({"ts_code": tc, "price": dp_entry["close"]})

            candidates = candidates[:max_positions]
            slots = max_positions - len(positions)
            for c in candidates[:slots]:
                tc = c["ts_code"]
                if tc not in dp:
                    continue
                price = dp[tc]["close"] * 1.001
                alloc = cash / max(max_positions - len(positions), 1)
                shares = int(alloc / price / 100) * 100
                if shares <= 0:
                    continue
                cost = price * shares
                if cost + cost * 0.0003 > cash:
                    continue
                cash -= cost + cost * 0.0003
                positions[tc] = {"cost": price, "shares": shares, "entry_day": day_i}

        pos_value = sum(dp.get(tc, {}).get("close", pos["cost"]) * pos["shares"] for tc, pos in positions.items())
        equity = cash + pos_value
        equity_curve.append(equity)
        prev_eq = equity_curve[-2] if len(equity_curve) >= 2 else 1_000_000
        daily_returns.append((equity - prev_eq) / prev_eq if prev_eq > 0 else 0)

    for tc, pos in list(positions.items()):
        for d in reversed(trading_dates):
            ds_check = d.strftime("%Y%m%d")
            if tc in date_price_map.get(ds_check, {}):
                p = date_price_map[ds_check][tc]["close"]
                pnl = (p - pos["cost"]) / pos["cost"]
                price = p * 0.999
                amt = pos["shares"] * price
                comm = amt * 0.0003
                stamp = amt * STAMP_TAX
                profit = amt - pos["cost"] * pos["shares"] - comm - stamp
                cash += amt - comm - stamp
                trades.append({"direction": "sell", "profit": profit, "pnl": pnl})
                break
    positions.clear()

    final = cash
    total_return = (final - 1_000_000) / 1_000_000
    sells = [t for t in trades if t["direction"] == "sell"]
    total_trades = len(sells)
    winning = len([t for t in sells if t.get("profit", 0) > 0])
    win_rate = winning / total_trades if total_trades > 0 else 0

    peak = 1_000_000
    max_dd = 0
    for eq in equity_curve:
        if eq > peak:
            peak = eq
        dd = (eq - peak) / peak
        if dd < max_dd:
            max_dd = dd

    daily_arr = np.array(daily_returns)
    sharpe = float(np.mean(daily_arr) / np.std(daily_arr) * np.sqrt(252)) if np.std(daily_arr) > 0 else 0

    return {
        "variant": variant_id,
        "label": config["label"],
        "total_return": round(total_return * 100, 1),
        "sharpe": round(sharpe, 3),
        "max_drawdown": round(max_dd * 100, 1),
        "total_trades": total_trades,
        "win_rate": round(win_rate * 100, 1),
    }


def main():
    START = "20240101"
    END = "20260401"

    print("🔬 QuantWeave 参数扫描")
    print(f"   区间: {START} → {END} | 基准: resonance-v1 = +41.6% / 夏普0.978 / 回撤12.1%\n")

    t0 = time.time()
    print("📦 加载数据...")
    stock_data, stock_info, trading_dates, limit_up_dates, st_codes = load_data(START, END)
    print(f"   {len(stock_data)} 只, {len(trading_dates)} 天, {time.time()-t0:.0f}s")

    print("🏗️ 构建行情索引...")
    t1 = time.time()
    date_price_map = build_date_price_map(stock_data)
    print(f"   完成, {time.time()-t1:.0f}s")

    all_results = {}
    for strategy_key, variants, icon in [
        ("limit_up_shakeout", LIMIT_UP_VARIANTS, "🔥"),
        ("high_tight_flag", FLAG_VARIANTS, "🚩"),
    ]:
        name = CORE_STRATEGIES[strategy_key]["name"]
        print(f"\n{icon} {name}:")
        results = []
        for vid, cfg in variants.items():
            t2 = time.time()
            r = run_variant(stock_data, trading_dates, date_price_map, limit_up_dates, st_codes,
                           strategy_key, vid, cfg)
            results.append(r)
            print(f"  {vid:<20} 收益={r['total_return']:+.1f}% 夏普={r['sharpe']:.3f} 回撤={r['max_drawdown']:.1f}% 交易={r['total_trades']} 胜率={r['win_rate']:.1f}% ({time.time()-t2:.0f}s)")
        all_results[strategy_key] = results

    print(f"\n{'='*80}")
    print("📊 汇总 (基准: resonance-v1 = +41.6% / 夏普0.978 / 回撤12.1%)")
    print(f"{'='*80}")
    for strategy_key, results in all_results.items():
        icon = "🔥" if strategy_key == "limit_up_shakeout" else "🚩"
        print(f"\n{icon} {CORE_STRATEGIES[strategy_key]['name']}:")
        print(f"  {'变体':<20} {'收益':>8} {'夏普':>8} {'回撤':>8} {'交易':>6} {'胜率':>8}")
        for r in results:
            print(f"  {r['variant']:<20} {r['total_return']:>+7.1f}% {r['sharpe']:>8.3f} {r['max_drawdown']:>7.1f}% {r['total_trades']:>6} {r['win_rate']:>7.1f}%")

    output = {
        "start": START, "end": END,
        "baseline": {"total_return": 41.6, "sharpe": 0.978, "max_drawdown": -12.1},
        "limit_up_shakeout": all_results.get("limit_up_shakeout", []),
        "high_tight_flag": all_results.get("high_tight_flag", []),
    }
    out_path = Path(__file__).resolve().parent.parent / "data_cache" / "param_sweep_results.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2))
    print(f"\n💾 保存: {out_path}")
    print(f"⏱️ 总耗时: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
