#!/usr/bin/env python3
"""
QuantWeave Parameter Optimizer - 策略参数网格搜索优化器
对全市场动态选股策略进行参数调优，找到最优参数组合
"""
import sqlite3
import numpy as np
import json
import time
import sys
from itertools import product
from datetime import datetime

DB_PATH = 'quantweave.db'
START_DATE = '20240415'
END_DATE = '20260414'
INITIAL_CAPITAL = 1000000
MAX_POSITIONS = 10
POSITION_PER_STOCK = 0.2
STOP_LOSS = -0.08
TAKE_PROFIT = 0.15
SLIPPAGE = 0.001
COMMISSION = 0.0003
OUTPUT_PATH = 'reports/optimization_results.json'

# ============================================================
# Data Loading
# ============================================================
def load_all_data():
    """Load all stock daily data, return {ts_code: {date: {open,high,low,close,vol}}"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    cur.execute("SELECT ts_code, trade_date, open, high, low, close, vol, amount FROM stock_daily "
                f"WHERE trade_date >= '{START_DATE}' AND trade_date <= '{END_DATE}' "
                "ORDER BY ts_code, trade_date")
    rows = cur.fetchall()
    conn.close()
    
    data = {}
    stock_names = {}
    
    # Get stock names
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT ts_code, name FROM stocks")
    for r in cur.fetchall():
        stock_names[r[0]] = r[1]
    conn.close()
    
    for r in rows:
        ts_code, trade_date, open_p, high, low, close, vol, amount = r
        if ts_code not in data:
            data[ts_code] = {}
        if close and close > 0:
            data[ts_code][trade_date] = {
                'open': float(open_p) if open_p else float(close),
                'high': float(high) if high else float(close),
                'low': float(low) if low else float(close),
                'close': float(close),
                'vol': float(vol) if vol else 0,
                'amount': float(amount) if amount else 0,
            }
    
    # Filter out ST stocks
    filtered = {}
    for code, days in data.items():
        name = stock_names.get(code, '')
        if name.startswith('ST') or name.startswith('*ST'):
            continue
        filtered[code] = days
    
    print(f"Loaded {len(filtered)} stocks, {sum(len(v) for v in filtered.values())} records")
    return filtered, stock_names

# ============================================================
# Strategy Signal Generators
# ============================================================
def calc_ma(closes, period):
    """Calculate MA for array"""
    if len(closes) < period:
        return None
    return float(np.mean(closes[-period:]))

def calc_std(closes, period):
    if len(closes) < period:
        return None
    return float(np.std(closes[-period:], ddof=0))

def calc_rsi(closes, period):
    if len(closes) < period + 1:
        return None
    deltas = np.diff(closes[-(period+1):])
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    avg_gain = np.mean(gains)
    avg_loss = np.mean(losses)
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))

def calc_ema(values, period):
    if len(values) < period:
        return None
    ema = float(np.mean(values[:period]))
    multiplier = 2.0 / (period + 1)
    for v in values[period:]:
        ema = (v - ema) * multiplier + ema
    return ema

def generate_bollinger_signals(stock_data, dates, params):
    """Generate Bollinger Band signals"""
    period = params.get('period', 25)
    std_mult = params.get('std_mult', 2.5)
    
    signals = {}  # date -> 'buy' or 'sell'
    closes_arr = []
    
    for d in dates:
        if d not in stock_data:
            closes_arr.append(None)
            continue
        closes_arr.append(stock_data[d]['close'])
    
    for i in range(period, len(closes_arr)):
        if closes_arr[i] is None:
            continue
        window = [c for c in closes_arr[i-period:i] if c is not None]
        if len(window) < period:
            continue
        
        ma = np.mean(window)
        std = np.std(window, ddof=0)
        upper = ma + std_mult * std
        lower = ma - std_mult * std
        
        close = closes_arr[i]
        prev_close = closes_arr[i-1] if i > 0 and closes_arr[i-1] else None
        
        # Buy: breakout above upper band
        if close > upper and prev_close and prev_close <= (ma + std_mult * np.std([c for c in closes_arr[i-period-1:i-1] if c is not None], ddof=0)):
            signals[dates[i]] = 'buy'
        # Sell: below lower band or MA
        elif close < lower:
            signals[dates[i]] = 'sell'
        elif prev_close and prev_close < ma and close >= ma:
            pass  # neutral
        elif prev_close and prev_close > ma and close <= ma:
            signals[dates[i]] = 'sell'  # cross down MA
    
    return signals

def generate_pullback_signals(stock_data, dates, params):
    """Generate Pullback Stable signals"""
    ma_short = params.get('ma_short', 5)
    ma_mid = params.get('ma_mid', 10)
    ma_long = params.get('ma_long', 20)
    near_pct = params.get('near_pct', 0.03)
    
    signals = {}
    closes_arr = []
    opens_arr = []
    vols_arr = []
    
    for d in dates:
        if d not in stock_data:
            closes_arr.append(None)
            opens_arr.append(None)
            vols_arr.append(None)
            continue
        closes_arr.append(stock_data[d]['close'])
        opens_arr.append(stock_data[d]['open'])
        vols_arr.append(stock_data[d]['vol'])
    
    for i in range(ma_long + 5, len(closes_arr)):
        if closes_arr[i] is None:
            continue
        
        window_c = [c for c in closes_arr[i-ma_long-5:i+1] if c is not None]
        window_v = [v for v in vols_arr[i-ma_long-5:i+1] if v is not None]
        
        if len(window_c) < ma_long:
            continue
        
        closes = np.array(window_c)
        vols = np.array(window_v) if window_v else np.array([1])
        
        ma_s = np.mean(closes[-ma_short:])
        ma_m = np.mean(closes[-ma_mid:])
        ma_l = np.mean(closes[-ma_long:])
        prev_ma_l = np.mean(closes[-ma_long-5:-5]) if len(closes) >= ma_long + 5 else ma_l
        
        close = closes[-1]
        open_p = opens_arr[i] if opens_arr[i] else close
        
        # Bullish structure: MA_short > MA_mid > MA_long, MA20 rising
        bullish = ma_s > ma_m > ma_l and ma_l > prev_ma_l
        near_ma = abs(close - ma_m) / ma_m < near_pct
        today_up = close >= open_p
        vol_shrink = vols[-1] < np.mean(vols[-10:]) if len(vols) >= 10 else False
        
        if bullish and near_ma and today_up:
            signals[dates[i]] = 'buy'
        elif close < ma_l:  # below MA_long, sell
            signals[dates[i]] = 'sell'
    
    return signals

def generate_dual_ma_signals(stock_data, dates, params):
    """Generate Dual MA crossover signals"""
    fast = params.get('fast', 5)
    slow = params.get('slow', 40)
    
    signals = {}
    closes_arr = []
    for d in dates:
        if d in stock_data:
            closes_arr.append((d, stock_data[d]['close']))
    
    for i in range(slow + 1, len(closes_arr)):
        window = [c for _, c in closes_arr[i-slow-1:i+1]]
        if len(window) < slow + 1:
            continue
        
        fast_ma = np.mean(window[-fast:])
        slow_ma = np.mean(window[-slow:])
        prev_fast = np.mean(window[-fast-1:-1])
        prev_slow = np.mean(window[-slow-1:-1])
        
        # Golden cross
        if prev_fast <= prev_slow and fast_ma > slow_ma:
            signals[closes_arr[i][0]] = 'buy'
        # Death cross
        elif prev_fast >= prev_slow and fast_ma < slow_ma:
            signals[closes_arr[i][0]] = 'sell'
    
    return signals

def generate_rsi_signals(stock_data, dates, params):
    """Generate RSI signals"""
    period = params.get('period', 12)
    oversold = params.get('oversold', 25)
    overbought = params.get('overbought', 80)
    
    signals = {}
    closes_arr = []
    for d in dates:
        if d in stock_data:
            closes_arr.append((d, stock_data[d]['close']))
    
    for i in range(period + 1, len(closes_arr)):
        window = np.array([c for _, c in closes_arr[i-period-1:i+1]])
        if len(window) < period + 1:
            continue
        
        rsi = calc_rsi(window, period)
        if rsi is None:
            continue
        
        if rsi < oversold:
            signals[closes_arr[i][0]] = 'buy'
        elif rsi > overbought:
            signals[closes_arr[i][0]] = 'sell'
    
    return signals

def generate_macd_signals(stock_data, dates, params):
    """Generate MACD signals"""
    fast = params.get('fast', 15)
    slow = params.get('slow', 26)
    signal_period = params.get('signal', 13)
    
    signals = {}
    closes_arr = []
    for d in dates:
        if d in stock_data:
            closes_arr.append((d, stock_data[d]['close']))
    
    # Need at least slow + signal_period data points
    if len(closes_arr) < slow + signal_period:
        return signals
    
    # Calculate MACD series
    all_closes = np.array([c for _, c in closes_arr])
    
    for i in range(slow + signal_period, len(all_closes)):
        window = all_closes[:i+1]
        
        fast_ema = calc_ema(window, fast)
        slow_ema = calc_ema(window, slow)
        if fast_ema is None or slow_ema is None:
            continue
        
        macd_line = fast_ema - slow_ema
        
        # Signal line
        if i < slow + signal_period:
            continue
        
        # Simple approximation: use recent MACD values
        macd_vals = []
        for j in range(slow, i+1):
            w = all_closes[:j+1]
            f = calc_ema(w, fast)
            s = calc_ema(w, slow)
            if f is not None and s is not None:
                macd_vals.append(f - s)
        
        if len(macd_vals) < signal_period:
            continue
        
        signal_line = np.mean(macd_vals[-signal_period:])
        prev_macd = macd_vals[-2] if len(macd_vals) >= 2 else 0
        
        # Golden cross: MACD crosses above signal
        if prev_macd <= signal_line and macd_line > signal_line:
            signals[closes_arr[i][0]] = 'buy'
        # Death cross: MACD crosses below signal
        elif prev_macd >= signal_line and macd_line < signal_line:
            signals[closes_arr[i][0]] = 'sell'
    
    return signals

# ============================================================
# Backtest Engine
# ============================================================
def backtest_strategy(all_data, dates, signal_func, params, strategy_name=""):
    """
    Full market dynamic backtest with given strategy parameters
    Returns metrics dict
    """
    # Pre-generate all signals
    stock_list = list(all_data.keys())
    
    # Batch compute signals for all stocks
    print(f"  Computing signals for {len(stock_list)} stocks with {strategy_name}...")
    all_signals = {}
    for idx, code in enumerate(stock_list):
        stock_data = all_data[code]
        signals = signal_func(stock_data, dates, params)
        if signals:
            all_signals[code] = signals
        if (idx + 1) % 1000 == 0:
            print(f"    ... {idx+1}/{len(stock_list)} done")
    
    # Simulate trading
    cash = INITIAL_CAPITAL
    positions = {}  # code -> {shares, cost_price, buy_date}
    portfolio_value = INITIAL_CAPITAL
    equity_curve = []
    trades = []
    
    trading_dates = sorted(dates)
    
    for di, date in enumerate(trading_dates):
        # Check stop loss / take profit for existing positions
        to_sell = []
        for code, pos in list(positions.items()):
            if code in all_data and date in all_data[code]:
                price = all_data[code][date]['close']
                pnl_pct = (price - pos['cost_price']) / pos['cost_price']
                
                if pnl_pct <= STOP_LOSS:
                    to_sell.append((code, price, '止损'))
                elif pnl_pct >= TAKE_PROFIT:
                    to_sell.append((code, price, '止盈'))
        
        for code, price, reason in to_sell:
            pos = positions.pop(code)
            sell_amount = pos['shares'] * price * (1 - SLIPPAGE)
            comm = sell_amount * COMMISSION
            cash += sell_amount - comm
            profit = (price - pos['cost_price']) * pos['shares'] - comm - pos['shares'] * pos['cost_price'] * COMMISSION
            trades.append({'dir': 'S', 'code': code, 'price': price, 'vol': pos['shares'],
                          'amount': sell_amount, 'comm': comm, 'profit': profit, 'reason': reason})
        
        # Scan for new buys if we have room
        num_empty = MAX_POSITIONS - len(positions)
        if num_empty > 0:
            candidates = []
            for code in stock_list:
                if code in positions:
                    continue
                if code in all_signals and date in all_signals[code]:
                    if all_signals[code][date] == 'buy':
                        if code in all_data and date in all_data[code]:
                            price = all_data[code][date]['close']
                            if price > 0:
                                candidates.append((code, price))
            
            # Sort by... just pick first N
            for code, price in candidates[:num_empty]:
                invest = portfolio_value * POSITION_PER_STOCK
                shares = int(invest / (price * (1 + SLIPPAGE)) / 100) * 100
                if shares <= 0:
                    shares = 100
                cost = shares * price * (1 + SLIPPAGE)
                comm = cost * COMMISSION
                if cash >= cost + comm:
                    cash -= cost + comm
                    positions[code] = {'shares': shares, 'cost_price': price, 'buy_date': date}
                    trades.append({'dir': 'B', 'code': code, 'price': price, 'vol': shares,
                                  'amount': cost, 'comm': comm, 'reason': '策略信号'})
        
        # Check sell signals for existing positions
        for code in list(positions.keys()):
            if code in all_signals and date in all_signals[code]:
                if all_signals[code][date] == 'sell':
                    if code in all_data and date in all_data[code]:
                        price = all_data[code][date]['close']
                        pos = positions.pop(code)
                        sell_amount = pos['shares'] * price * (1 - SLIPPAGE)
                        comm = sell_amount * COMMISSION
                        cash += sell_amount - comm
                        profit = (price - pos['cost_price']) * pos['shares'] - comm
                        trades.append({'dir': 'S', 'code': code, 'price': price, 'vol': pos['shares'],
                                      'amount': sell_amount, 'comm': comm, 'profit': profit, 'reason': '策略卖出'})
        
        # Calculate portfolio value
        pos_value = sum(
            pos['shares'] * all_data[code][date]['close']
            for code, pos in positions.items()
            if code in all_data and date in all_data[code]
        )
        portfolio_value = cash + pos_value
        equity_curve.append({'date': date, 'value': round(portfolio_value, 2)})
    
    # Force liquidation at end
    last_date = trading_dates[-1]
    for code, pos in positions.items():
        if code in all_data and last_date in all_data[code]:
            price = all_data[code][last_date]['close']
            sell_amount = pos['shares'] * price * (1 - SLIPPAGE)
            comm = sell_amount * COMMISSION
            cash += sell_amount - comm
            profit = (price - pos['cost_price']) * pos['shares'] - comm
            trades.append({'dir': 'S', 'code': code, 'price': price, 'vol': pos['shares'],
                          'amount': sell_amount, 'comm': comm, 'profit': profit, 'reason': '期末清仓'})
    
    portfolio_value = cash
    
    # Calculate metrics
    total_return = (portfolio_value - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100
    num_days = len(trading_dates)
    annual_return = total_return / (num_days / 252) if num_days > 0 else 0
    
    # Max drawdown
    peak = INITIAL_CAPITAL
    max_dd = 0
    for e in equity_curve:
        if e['value'] > peak:
            peak = e['value']
        dd = (peak - e['value']) / peak
        if dd > max_dd:
            max_dd = dd
    max_dd *= 100
    
    # Sharpe ratio
    if len(equity_curve) > 1:
        returns = []
        for i in range(1, len(equity_curve)):
            r = (equity_curve[i]['value'] - equity_curve[i-1]['value']) / equity_curve[i-1]['value']
            returns.append(r)
        returns = np.array(returns)
        sharpe = (np.mean(returns) * 252 - 0.03) / (np.std(returns) * np.sqrt(252)) if np.std(returns) > 0 else 0
    else:
        sharpe = 0
    
    # Win rate
    sell_trades = [t for t in trades if t['dir'] == 'S']
    wins = [t for t in sell_trades if t.get('profit', 0) > 0]
    win_rate = len(wins) / len(sell_trades) * 100 if sell_trades else 0
    
    # Profit/Loss ratio
    win_profits = [t['profit'] for t in sell_trades if t.get('profit', 0) > 0]
    loss_profits = [-t['profit'] for t in sell_trades if t.get('profit', 0) < 0]
    avg_win = np.mean(win_profits) if win_profits else 0
    avg_loss = np.mean(loss_profits) if loss_profits else 1
    pl_ratio = avg_win / avg_loss if avg_loss > 0 else 0
    
    return {
        'name': strategy_name,
        'params': {k: v for k, v in params.items()},
        'total_return': round(total_return, 2),
        'annual_return': round(annual_return, 2),
        'max_drawdown': round(max_dd, 2),
        'sharpe_ratio': round(float(sharpe), 4),
        'win_rate': round(win_rate, 1),
        'profit_loss_ratio': round(float(pl_ratio), 2),
        'total_trades': len(trades),
        'final_value': round(portfolio_value, 2),
    }

# ============================================================
# Grid Search Runner
# ============================================================
def grid_search(all_data, dates, strategy_name, signal_func, param_grid, max_combos=50):
    """Run grid search over parameter space"""
    keys = list(param_grid.keys())
    values = list(param_grid.values())
    combos = list(product(*values))
    
    if len(combos) > max_combos:
        # Subsample to keep it manageable
        step = len(combos) // max_combos
        combos = combos[::step][:max_combos]
    
    print(f"\n{'='*60}")
    print(f"Optimizing: {strategy_name} | {len(combos)} parameter combinations")
    print(f"{'='*60}")
    
    results = []
    for i, combo in enumerate(combos):
        params = dict(zip(keys, combo))
        label = str(params)
        print(f"\n[{i+1}/{len(combos)}] {label}")
        
        result = backtest_strategy(all_data, dates, signal_func, params, strategy_name)
        result['params_str'] = label
        results.append(result)
        
        print(f"  Return: {result['total_return']:+.2f}% | Sharpe: {result['sharpe_ratio']:.3f} | DD: {result['max_drawdown']:.2f}% | Trades: {result['total_trades']}")
        sys.stdout.flush()
    
    # Sort by Sharpe ratio (primary), then return (secondary)
    results.sort(key=lambda x: (-x['sharpe_ratio'], -x['total_return']))
    
    return results

# ============================================================
# Main
# ============================================================
if __name__ == '__main__':
    print("QuantWeave Parameter Optimizer")
    print(f"Period: {START_DATE} ~ {END_DATE}")
    print(f"Loading data...")
    
    all_data, stock_names = load_all_data()
    
    # Get trading dates
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(f"SELECT DISTINCT trade_date FROM stock_daily WHERE trade_date >= '{START_DATE}' AND trade_date <= '{END_DATE}' ORDER BY trade_date")
    dates = [r[0] for r in cur.fetchall()]
    conn.close()
    print(f"Trading dates: {len(dates)}")
    
    all_results = {}
    
    # ---- 1. Bollinger Band Optimization ----
    print("\n\n" + "="*60)
    print("PHASE 1: Bollinger Band Optimization")
    print("="*60)
    boll_grid = {
        'period': [15, 20, 25, 30],
        'std_mult': [1.5, 2.0, 2.5, 3.0],
    }
    boll_results = grid_search(all_data, dates, "布林带突破", generate_bollinger_signals, boll_grid, max_combos=16)
    all_results['bollinger'] = boll_results
    
    # Show top 5
    print(f"\nTop 5 Bollinger params:")
    for i, r in enumerate(boll_results[:5]):
        print(f"  {i+1}. {r['params_str']} => Return:{r['total_return']:+.2f}% Sharpe:{r['sharpe_ratio']:.3f} DD:{r['max_drawdown']:.2f}%")
    
    # ---- 2. Pullback Stable Optimization ----
    print("\n\n" + "="*60)
    print("PHASE 2: Pullback Stable Optimization")
    print("="*60)
    pull_grid = {
        'ma_short': [3, 5, 7],
        'ma_mid': [8, 10, 12, 15],
        'ma_long': [15, 20, 25, 30],
        'near_pct': [0.02, 0.03, 0.05],
    }
    pull_results = grid_search(all_data, dates, "强势股回调企稳", generate_pullback_signals, pull_grid, max_combos=36)
    all_results['pullback'] = pull_results
    
    print(f"\nTop 5 Pullback params:")
    for i, r in enumerate(pull_results[:5]):
        print(f"  {i+1}. {r['params_str']} => Return:{r['total_return']:+.2f}% Sharpe:{r['sharpe_ratio']:.3f} DD:{r['max_drawdown']:.2f}%")
    
    # ---- 3. Dual MA Optimization ----
    print("\n\n" + "="*60)
    print("PHASE 3: Dual MA Crossover Optimization")
    print("="*60)
    dma_grid = {
        'fast': [3, 5, 7, 10],
        'slow': [20, 30, 40, 50, 60],
    }
    dma_results = grid_search(all_data, dates, "双均线交叉", generate_dual_ma_signals, dma_grid, max_combos=20)
    all_results['dual_ma'] = dma_results
    
    print(f"\nTop 5 Dual MA params:")
    for i, r in enumerate(dma_results[:5]):
        print(f"  {i+1}. {r['params_str']} => Return:{r['total_return']:+.2f}% Sharpe:{r['sharpe_ratio']:.3f} DD:{r['max_drawdown']:.2f}%")
    
    # ---- 4. RSI Optimization ----
    print("\n\n" + "="*60)
    print("PHASE 4: RSI Optimization")
    print("="*60)
    rsi_grid = {
        'period': [6, 9, 12, 14, 21],
        'oversold': [15, 20, 25, 30],
        'overbought': [70, 75, 80, 85],
    }
    rsi_results = grid_search(all_data, dates, "RSI超买超卖", generate_rsi_signals, rsi_grid, max_combos=40)
    all_results['rsi'] = rsi_results
    
    print(f"\nTop 5 RSI params:")
    for i, r in enumerate(rsi_results[:5]):
        print(f"  {i+1}. {r['params_str']} => Return:{r['total_return']:+.2f}% Sharpe:{r['sharpe_ratio']:.3f} DD:{r['max_drawdown']:.2f}%")
    
    # ---- 5. MACD Optimization ----
    print("\n\n" + "="*60)
    print("PHASE 5: MACD Optimization (slow, skipping most combos)")
    print("="*60)
    macd_grid = {
        'fast': [8, 12, 15],
        'slow': [20, 26, 30],
        'signal': [7, 9, 13],
    }
    macd_results = grid_search(all_data, dates, "MACD金叉死叉", generate_macd_signals, macd_grid, max_combos=9)
    all_results['macd'] = macd_results
    
    print(f"\nTop 5 MACD params:")
    for i, r in enumerate(macd_results[:5]):
        print(f"  {i+1}. {r['params_str']} => Return:{r['total_return']:+.2f}% Sharpe:{r['sharpe_ratio']:.3f} DD:{r['max_drawdown']:.2f}%")
    
    # ---- Summary ----
    print("\n\n" + "="*60)
    print("OPTIMIZATION COMPLETE - SUMMARY")
    print("="*60)
    
    summary = {}
    for strategy, results in all_results.items():
        if results:
            best = results[0]
            summary[strategy] = best
            print(f"\n{strategy} BEST:")
            print(f"  Params: {best['params_str']}")
            print(f"  Return: {best['total_return']:+.2f}% | Sharpe: {best['sharpe_ratio']:.3f} | DD: {best['max_drawdown']:.2f}%")
            print(f"  Win Rate: {best['win_rate']:.1f}% | P/L Ratio: {best['profit_loss_ratio']:.2f} | Trades: {best['total_trades']}")
    
    # Save
    # Convert params to serializable
    for strategy, results in all_results.items():
        for r in results:
            for k, v in r['params'].items():
                if isinstance(v, (np.integer,)):
                    r['params'][k] = int(v)
                elif isinstance(v, (np.floating,)):
                    r['params'][k] = float(v)
    
    with open(OUTPUT_PATH, 'w') as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nResults saved to {OUTPUT_PATH}")
