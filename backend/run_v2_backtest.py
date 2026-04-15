"""
QuantWeave V2 Optimized Full Backtest
"""
import sqlite3, json, time, sys
import numpy as np
import pandas as pd
from collections import defaultdict

DB = 'quantweave.db'
START_DATE = '20240415'
END_DATE = '20260414'
INITIAL_CAPITAL = 1000000
MAX_POSITIONS = 10
POSITION_PCT = 0.2
STOP_LOSS = -0.08
TAKE_PROFIT = 0.15
COMMISSION = 0.0003
SLIPPAGE = 0.001

sys.path.insert(0, '.')
from app.services.strategy.strategy_service import (
    DualMAStrategy, BollingerBreakStrategy, RSIStrategy, MACDStrategy
)
from app.services.strategy.chip_strategy import ChipStrategy, EnhancedChipStrategy, PullbackStableStrategy
from app.services.strategy.fengmang_strategy import VolumeBreakoutStrategy, DragonFirstYinStrategy, TrendMAStrategy
from app.services.strategy.top_bottom_strategy import TopBottomStrategy

STRATEGIES = [
    DualMAStrategy, BollingerBreakStrategy, RSIStrategy, MACDStrategy,
    ChipStrategy, EnhancedChipStrategy, PullbackStableStrategy,
    VolumeBreakoutStrategy, DragonFirstYinStrategy, TrendMAStrategy,
    TopBottomStrategy,
]

print("=" * 70)
print("QuantWeave V2 Optimized Full Backtest")
print(f"Period: {START_DATE} ~ {END_DATE}")
print("=" * 70)

# Load data
t0 = time.time()
conn = sqlite3.connect(DB)
cur = conn.cursor()

cur.execute(f"SELECT ts_code, trade_date, open, high, low, close, vol, amount FROM stock_daily WHERE trade_date BETWEEN '{START_DATE}' AND '{END_DATE}' ORDER BY ts_code, trade_date")
raw = cur.fetchall()

cur.execute("SELECT ts_code, name FROM stocks")
name_map = {r[0]: r[1] for r in cur.fetchall()}
conn.close()

stock_data = defaultdict(list)
for r in raw:
    stock_data[r[0]].append(r)

stock_dfs = {}
for ts_code, rows in stock_data.items():
    df = pd.DataFrame(rows, columns=['ts_code','trade_date','open','high','low','close','vol','amount'])
    for col in ['open','high','low','close','vol','amount']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    df = df.sort_values('trade_date').reset_index(drop=True)
    stock_dfs[ts_code] = df

print(f"Loaded {len(stock_dfs)} stocks, {len(raw)} records in {time.time()-t0:.1f}s")

# Get trading dates
dates_set = set()
for df in stock_dfs.values():
    for d in df['trade_date'].values:
        if START_DATE <= str(d) <= END_DATE:
            dates_set.add(str(d))
trading_dates = sorted(dates_set)
print(f"Trading dates: {len(trading_dates)}")

# Build price lookup: (ts_code, date) -> {open, high, low, close, vol}
price_lookup = {}
for ts_code, df in stock_dfs.items():
    for _, row in df.iterrows():
        price_lookup[(ts_code, str(row['trade_date']))] = {
            'open': row['open'], 'high': row['high'], 'low': row['low'],
            'close': row['close'], 'vol': row['vol']
        }

results = {}
for strat_cls in STRATEGIES:
    strategy = strat_cls()
    t1 = time.time()
    print(f"\n{'='*60}")
    print(f"[{strategy.name}] Computing signals...")
    
    # Pre-compute all signals
    all_signals = []
    done = 0
    for ts_code, df in stock_dfs.items():
        if len(df) < 30:
            continue
        name = name_map.get(ts_code, ts_code)
        if name.startswith('ST') or name.startswith('*ST'):
            continue
        try:
            signals = strategy.generate_signals(df, ts_code)
            for s in signals:
                if START_DATE <= s.date <= END_DATE:
                    all_signals.append({
                        'date': s.date, 'type': s.signal_type.value,
                        'code': ts_code, 'name': name,
                        'price': s.price, 'reason': s.reason[:40]
                    })
        except:
            pass
        done += 1
        if done % 1000 == 0:
            print(f"    ... {done}/{len(stock_dfs)} done")
    
    print(f"  Total signals: {len(all_signals)} in {time.time()-t1:.1f}s")
    
    # Group by date
    buy_by_date = defaultdict(list)
    for s in all_signals:
        if s['type'] == 'buy':
            buy_by_date[s['date']].append(s)
    
    # Quick simulation using pre-computed signals
    t2 = time.time()
    positions = {}
    cash = INITIAL_CAPITAL
    equity = []
    trades = []
    
    for date in trading_dates:
        # Check exits for existing positions
        to_sell = []
        for code, pos in positions.items():
            p = price_lookup.get((code, date))
            if p is None:
                continue
            price = float(p['close'])
            pnl = (price - pos['entry_price']) / pos['entry_price']
            if pnl <= STOP_LOSS or pnl >= TAKE_PROFIT:
                reason = f"止损{pnl*100:+.1f}%" if pnl <= STOP_LOSS else f"止盈{pnl*100:+.1f}%"
                to_sell.append((code, price, reason))
        
        for code, price, reason in to_sell:
            pos = positions.pop(code)
            sell_price = price * (1 - SLIPPAGE)
            amount = sell_price * pos['shares']
            comm = amount * COMMISSION
            cash += amount - comm
            profit = (sell_price - pos['entry_price']) * pos['shares'] - comm
            trades.append({
                'date': date, 'dir': 'S', 'code': code, 'name': pos['name'],
                'price': round(sell_price, 2), 'vol': pos['shares'],
                'amount': round(amount, 0), 'comm': round(comm, 0),
                'profit': round(profit, 0), 'reason': reason
            })
        
        # Process sell signals for held positions
        for s in all_signals:
            if s['date'] == date and s['type'] == 'sell' and s['code'] in positions:
                pos = positions.pop(s['code'])
                sell_price = s['price'] * (1 - SLIPPAGE)
                amount = sell_price * pos['shares']
                comm = amount * COMMISSION
                cash += amount - comm
                profit = (sell_price - pos['entry_price']) * pos['shares'] - comm
                trades.append({
                    'date': date, 'dir': 'S', 'code': s['code'], 'name': s['name'],
                    'price': round(sell_price, 2), 'vol': pos['shares'],
                    'amount': round(amount, 0), 'comm': round(comm, 0),
                    'profit': round(profit, 0), 'reason': s['reason'][:30]
                })
        
        # Buy from signals
        candidates = buy_by_date.get(date, [])
        for s in candidates:
            if len(positions) >= MAX_POSITIONS:
                break
            if s['code'] in positions:
                continue
            buy_price = s['price'] * (1 + SLIPPAGE)
            invest = INITIAL_CAPITAL * POSITION_PCT
            shares = int(invest / buy_price / 100) * 100
            if shares <= 0:
                continue
            amount = buy_price * shares
            comm = amount * COMMISSION
            if cash >= amount + comm:
                cash -= amount + comm
                positions[s['code']] = {
                    'name': s['name'], 'entry_price': buy_price,
                    'shares': shares, 'entry_date': date
                }
                trades.append({
                    'date': date, 'dir': 'B', 'code': s['code'], 'name': s['name'],
                    'price': round(buy_price, 2), 'vol': shares,
                    'amount': round(amount, 0), 'comm': round(comm, 0),
                    'profit': 0, 'reason': s['reason'][:30]
                })
        
        # Calculate equity
        pos_value = 0
        for code, pos in positions.items():
            p = price_lookup.get((code, date))
            if p:
                pos_value += float(p['close']) * pos['shares']
            else:
                pos_value += pos['entry_price'] * pos['shares']
        equity.append({'date': date, 'value': round(cash + pos_value, 0)})
    
    # Force close remaining
    for code, pos in list(positions.items()):
        p = price_lookup.get((code, END_DATE))
        price = float(p['close']) if p else pos['entry_price']
        sell_price = price * (1 - SLIPPAGE)
        amount = sell_price * pos['shares']
        comm = amount * COMMISSION
        cash += amount - comm
        profit = (sell_price - pos['entry_price']) * pos['shares'] - comm
        trades.append({
            'date': END_DATE, 'dir': 'S', 'code': code, 'name': pos['name'],
            'price': round(sell_price, 2), 'vol': pos['shares'],
            'amount': round(amount, 0), 'comm': round(comm, 0),
            'profit': round(profit, 0), 'reason': '到期清仓'
        })
    positions.clear()
    
    # Metrics
    final_value = cash
    total_return = (final_value - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100
    years = len(trading_dates) / 242
    annual_return = ((final_value / INITIAL_CAPITAL) ** (1/years) - 1) * 100 if years > 0 else 0
    
    peak = INITIAL_CAPITAL
    max_dd = 0
    for e in equity:
        if e['value'] > peak: peak = e['value']
        dd = (peak - e['value']) / peak
        if dd > max_dd: max_dd = dd
    
    if len(equity) > 1:
        daily_ret = [(equity[i]['value'] - equity[i-1]['value']) / equity[i-1]['value'] for i in range(1, len(equity))]
        sharpe = (np.mean(daily_ret) - 0.03/242) / np.std(daily_ret) * np.sqrt(242) if np.std(daily_ret) > 0 else 0
    else:
        sharpe = 0
    
    sells = [t for t in trades if t['dir'] == 'S']
    wins = [t for t in sells if t['profit'] > 0]
    win_rate = len(wins) / len(sells) * 100 if sells else 0
    w = [t['profit'] for t in sells if t['profit'] > 0]
    l = [-t['profit'] for t in sells if t['profit'] < 0]
    pl_ratio = (np.mean(w) / np.mean(l)) if l and np.mean(l) > 0 else 0
    
    results[strategy.name] = {
        'name': strategy.name,
        'total_return': round(total_return, 2),
        'annual_return': round(annual_return, 2),
        'max_drawdown': round(max_dd * 100, 2),
        'sharpe_ratio': round(float(sharpe), 3),
        'win_rate': round(win_rate, 1),
        'profit_loss_ratio': round(float(pl_ratio), 2),
        'total_trades': len(trades),
        'final_value': round(final_value, 0),
        'equity_curve': equity,
        'trades': trades,
    }
    
    print(f"  Simulation: {time.time()-t2:.1f}s")
    print(f"  >>> Return: {total_return:+.2f}% | Sharpe: {sharpe:.3f} | DD: {max_dd*100:.2f}% | Trades: {len(trades)}")

# Save
with open('../reports/full_backtest_v2_results.json', 'w') as f:
    json.dump(results, f, ensure_ascii=False)

# Summary
print(f"\n{'='*70}")
print("V2 OPTIMIZED BACKTEST RESULTS")
print(f"{'='*70}")
sorted_r = sorted(results.items(), key=lambda x: x[1]['total_return'], reverse=True)
for i, (k, r) in enumerate(sorted_r):
    m = ['1st','2nd','3rd'][i] if i < 3 else str(i+1)
    print(f"  {m}. {r['name']:<14} Return:{r['total_return']:+8.2f}% Sharpe:{r['sharpe_ratio']:.3f} DD:{r['max_drawdown']:6.2f}% Trades:{r['total_trades']}")

print(f"\nTotal time: {time.time()-t0:.1f}s")
print(f"Saved to reports/full_backtest_v2_results.json")
