#!/usr/bin/env python3
"""
Quant Daily Picks v2 — 新策略2年回测
对布林带上轨突破 + 强势股回调企稳(ZLCMQ) 进行全市场动态回测

使用方式:
    cd /Users/liujianyu/WorkBuddy/Claw/quant-platform/backend
    /opt/anaconda3/envs/quant-platform/bin/python backtest_daily_picks_v2.py
"""
import sqlite3
import numpy as np
import json
import sys
from datetime import datetime
from pathlib import Path

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
OUTPUT_PATH = 'reports/daily_picks_v2_backtest.json'

# ============================================================
# Data Loading
# ============================================================
def load_all_data():
    """Load all stock daily data, return {ts_code: {date: {open,high,low,close,vol}}}"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    cur.execute(f"SELECT ts_code, trade_date, open, high, low, close, vol, amount "
                f"FROM stock_daily WHERE trade_date >= '{START_DATE}' AND trade_date <= '{END_DATE}' "
                f"ORDER BY ts_code, trade_date")
    rows = cur.fetchall()
    conn.close()
    
    data = {}
    stock_names = {}
    
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
    
    # Filter ST stocks
    filtered = {}
    for code, days in data.items():
        name = stock_names.get(code, '')
        if name.startswith('ST') or name.startswith('*ST'):
            continue
        filtered[code] = days
    
    print(f"Loaded {len(filtered)} stocks, {sum(len(v) for v in filtered.values())} records")
    return filtered, stock_names


# ============================================================
# TDX SMA (通达信 SMA 函数)
# ============================================================
def tdx_sma(x, n, m):
    y = np.empty(len(x))
    y[0] = x[0]
    for i in range(1, len(x)):
        y[i] = (m * x[i] + (n - m) * y[i - 1]) / n
    return y


# ============================================================
# Strategy 1: 布林带上轨突破
# ============================================================
def generate_bollinger_upper_signals(stock_data, dates, params):
    """布林带上轨突破策略：股价接近或突破布林上轨时买入"""
    period = params.get('period', 25)
    std_mult = params.get('std_mult', 2.0)
    near_pct = params.get('near_pct', 0.02)  # 接近上轨的阈值
    
    signals = {}
    closes_arr = []
    
    for d in dates:
        if d not in stock_data:
            closes_arr.append(None)
            continue
        closes_arr.append(stock_data[d]['close'])
    
    for i in range(period + 1, len(closes_arr)):
        if closes_arr[i] is None:
            continue
        window = [c for c in closes_arr[i - period:i] if c is not None]
        if len(window) < period:
            continue
        
        ma = np.mean(window)
        std = np.std(window, ddof=0)
        upper = ma + std_mult * std
        
        close = closes_arr[i]
        prev_close = closes_arr[i - 1] if i > 0 and closes_arr[i - 1] else None
        
        if prev_close is None:
            continue
        
        # 买入: 突破上轨 or 接近上轨(< near_pct)
        if prev_close <= upper and close > upper:
            signals[dates[i]] = 'buy'
        elif (upper - close) / upper < near_pct and close > ma:
            signals[dates[i]] = 'buy'
        
        # 卖出: 跌破中轨 or 触及下轨
        lower = ma - std_mult * std
        if prev_close >= ma and close < ma:
            signals[dates[i]] = 'sell'
        elif close < lower:
            signals[dates[i]] = 'sell'
    
    return signals


# ============================================================
# Strategy 2: 强势股回调企稳 (ZLCMQ版，与 daily_picks.py 一致)
# ============================================================
def generate_zlcmq_pullback_signals(stock_data, dates, params):
    """强势股回调企稳策略(ZLCMQ)：ZLCMQ高位回落+企稳条件"""
    n_days = params.get('n_days', 8)
    min_high = params.get('min_high', 92)
    min_fall = params.get('min_fall', 3)
    stable_threshold = params.get('stable_threshold', 3)
    
    signals = {}
    closes_arr = []
    opens_arr = []
    highs_arr = []
    lows_arr = []
    vols_arr = []
    
    for d in dates:
        if d not in stock_data:
            closes_arr.append(None)
            opens_arr.append(None)
            highs_arr.append(None)
            lows_arr.append(None)
            vols_arr.append(None)
            continue
        closes_arr.append(stock_data[d]['close'])
        opens_arr.append(stock_data[d]['open'])
        highs_arr.append(stock_data[d]['high'])
        lows_arr.append(stock_data[d]['low'])
        vols_arr.append(stock_data[d]['vol'])
    
    # 需要至少75天数据来计算ZLCMQ
    for i in range(75, len(closes_arr)):
        if closes_arr[i] is None:
            continue
        
        # 计算 ZLCMQ（需要使用历史窗口）
        window_c = np.array([c for c in closes_arr[:i+1] if c is not None])
        window_h = np.array([h for h in highs_arr[:i+1] if h is not None])
        window_l = np.array([l for l in lows_arr[:i+1] if l is not None])
        
        if len(window_c) < 75:
            continue
        
        # 计算 ZLCMQ
        var5 = np.minimum.accumulate(window_l)[-75:]  # 75日最低
        var6 = np.maximum.accumulate(window_h)[-75:]  # 75日最高
        
        # 简化版ZLCMQ计算（用最近75日窗口）
        lo_75 = np.min(window_l[-75:])
        hi_75 = np.max(window_h[-75:])
        var7 = (hi_75 - lo_75) / 100.0
        
        if var7 < 1e-10:
            continue
        
        c_recent = window_c[-75:]
        h_recent = window_h[-75:]
        l_recent = window_l[-75:]
        
        raw = np.where(var7 > 1e-10, (c_recent - lo_75) / var7, 0.0)
        raw = np.nan_to_num(raw, nan=0.0)
        
        var8 = tdx_sma(raw, 20, 1)
        var8_s = tdx_sma(var8, 15, 1)
        vara = 3.0 * var8 - 2.0 * var8_s
        zlcmq = 100.0 - vara
        current_zlcmq = zlcmq[-1]
        
        # 检查 n_days 内是否有过高位
        zlcmq_window = zlcmq[-n_days:] if len(zlcmq) >= n_days else zlcmq
        zlcmq_high = np.max(zlcmq_window)
        
        # 条件1: n_days内ZLCMQ达到过 min_high
        if zlcmq_high < min_high:
            continue
        
        # 条件2: 从高位回落 >= min_fall
        fall = zlcmq_high - current_zlcmq
        if fall < min_fall:
            continue
        
        # 条件3: 企稳判断（5选3）
        close = closes_arr[i]
        open_p = opens_arr[i] if opens_arr[i] else close
        
        stable_count = 0
        # 1. 当日阳线
        if close > open_p:
            stable_count += 1
        # 2. 当日收涨
        if i > 0 and closes_arr[i-1] is not None and close > closes_arr[i-1]:
            stable_count += 1
        # 3. 低点抬高（对比前日）
        if i > 0 and lows_arr[i] is not None and lows_arr[i-1] is not None and lows_arr[i] > lows_arr[i-1]:
            stable_count += 1
        # 4. 缩量（对比5日均量）
        if vols_arr[i] is not None:
            recent_vols = [v for v in vols_arr[max(0,i-5):i] if v is not None]
            if recent_vols and np.mean(recent_vols) > 0:
                if vols_arr[i] < np.mean(recent_vols):
                    stable_count += 1
        # 5. 站上MA5
        ma5_window = [c for c in closes_arr[max(0,i-5):i] if c is not None]
        if ma5_window and close > np.mean(ma5_window):
            stable_count += 1
        
        if stable_count >= stable_threshold:
            signals[dates[i]] = 'buy'
        
        # 卖出: ZLCMQ < 20（筹码极度分散）或 跌破60日均线
        if current_zlcmq < 20:
            signals[dates[i]] = 'sell'
        elif len(window_c) >= 60:
            ma60 = np.mean(window_c[-60:])
            if i > 0 and closes_arr[i-1] is not None:
                if closes_arr[i-1] >= ma60 and close < ma60:
                    signals[dates[i]] = 'sell'
    
    return signals


# ============================================================
# Backtest Engine (from optimize_params.py)
# ============================================================
def backtest_strategy(all_data, dates, signal_func, params, strategy_name=""):
    """全市场动态回测"""
    stock_list = list(all_data.keys())
    
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
    positions = {}
    portfolio_value = INITIAL_CAPITAL
    equity_curve = []
    trades = []
    
    trading_dates = sorted(dates)
    
    for di, date in enumerate(trading_dates):
        # Check stop loss / take profit
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
        
        # Scan for new buys
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
        
        # Check sell signals
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
        
        # Portfolio value
        pos_value = sum(
            pos['shares'] * all_data[code][date]['close']
            for code, pos in positions.items()
            if code in all_data and date in all_data[code]
        )
        portfolio_value = cash + pos_value
        equity_curve.append({'date': date, 'value': round(portfolio_value, 2)})
    
    # Force liquidation
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
    
    # Metrics
    total_return = (portfolio_value - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100
    num_days = len(trading_dates)
    annual_return = total_return / (num_days / 252) if num_days > 0 else 0
    
    peak = INITIAL_CAPITAL
    max_dd = 0
    for e in equity_curve:
        if e['value'] > peak:
            peak = e['value']
        dd = (peak - e['value']) / peak
        if dd > max_dd:
            max_dd = dd
    max_dd *= 100
    
    if len(equity_curve) > 1:
        returns = []
        for i in range(1, len(equity_curve)):
            r = (equity_curve[i]['value'] - equity_curve[i-1]['value']) / equity_curve[i-1]['value']
            returns.append(r)
        returns = np.array(returns)
        sharpe = (np.mean(returns) * 252 - 0.03) / (np.std(returns) * np.sqrt(252)) if np.std(returns) > 0 else 0
    else:
        sharpe = 0
    
    sell_trades = [t for t in trades if t['dir'] == 'S']
    wins = [t for t in sell_trades if t.get('profit', 0) > 0]
    win_rate = len(wins) / len(sell_trades) * 100 if sell_trades else 0
    
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
        'equity_curve': equity_curve,
        'trades': trades,
    }


# ============================================================
# HTML Report Generator
# ============================================================
def generate_html_report(results, stock_names):
    """生成回测HTML报告"""
    import html as html_mod
    
    # 策略配色
    COLORS = {
        'bollinger_upper': '#3b82f6',
        'zlcmq_pullback': '#10b981',
        'bollinger_upper_best': '#6366f1',
        'zlcmq_pullback_best': '#f59e0b',
    }
    
    # 提取策略列表(排除 best 变体用于图表)
    chart_strategies = [(k, v) for k, v in results.items() 
                        if k in ('bollinger_upper', 'zlcmq_pullback')]
    
    best_strategies = [(k, v) for k, v in results.items() 
                       if k in ('bollinger_upper_best', 'zlcmq_pullback_best')]
    
    all_strategies = [(k, v) for k, v in results.items()]
    
    # 构建权益曲线JS数据
    equity_datasets = []
    for key, res in chart_strategies:
        curve = res.get('equity_curve', [])
        if not curve:
            continue
        data_str = ",".join(f'{{"x":"{e["date"]}", "y":{e["value"]}}}' for e in curve)
        equity_datasets.append(f'''{{
            label: "{res['name']}",
            borderColor: "{COLORS.get(key, '#999')}",
            backgroundColor: "rgba(0,0,0,0)",
            data: [{data_str}],
            borderWidth: 2,
            pointRadius: 0,
            tension: 0.1
        }}''')
    
    # 回撤曲线
    dd_datasets = []
    for key, res in chart_strategies:
        curve = res.get('equity_curve', [])
        if not curve:
            continue
        peak = INITIAL_CAPITAL
        dd_data = []
        for e in curve:
            if e['value'] > peak:
                peak = e['value']
            dd_pct = round((peak - e['value']) / peak * 100, 2)
            dd_data.append(f'{{"x":"{e["date"]}", "y":{dd_pct}}}')
        dd_datasets.append(f'''{{
            label: "{res['name']} 回撤",
            borderColor: "{COLORS.get(key, '#999')}",
            backgroundColor: "rgba(0,0,0,0)",
            data: [{",".join(dd_data)}],
            borderWidth: 1.5,
            pointRadius: 0,
            fill: true
        }}''')
    
    # 策略排名表
    ranked = sorted(all_strategies, key=lambda x: -x[1].get('sharpe_ratio', 0))
    rank_rows = ""
    for rank, (key, r) in enumerate(ranked, 1):
        medal = "🥇" if rank == 1 else ("🥈" if rank == 2 else ("🥉" if rank == 3 else f"{rank}"))
        ret_cls = "positive" if r['total_return'] > 0 else "negative"
        rank_rows += f'''<tr>
            <td>{medal}</td>
            <td>{r['name']}</td>
            <td class="{ret_cls}">{r['total_return']:+.2f}%</td>
            <td>{r['annual_return']:+.2f}%</td>
            <td>{r['sharpe_ratio']:.3f}</td>
            <td>{r['max_drawdown']:.2f}%</td>
            <td>{r['win_rate']:.1f}%</td>
            <td>{r['profit_loss_ratio']:.2f}</td>
            <td>{r['total_trades']}</td>
        </tr>'''
    
    # 交易明细表(取最佳策略的最近20笔)
    trade_table = ""
    for key, res in best_strategies:
        trades = res.get('trades', [])
        if not trades:
            continue
        recent = trades[-30:]
        for t in recent:
            name = stock_names.get(t['code'], t['code'])
            dir_cls = "buy" if t['dir'] == 'B' else "sell"
            dir_label = "买入" if t['dir'] == 'B' else "卖出"
            profit_str = f"{t.get('profit', 0):+.2f}" if t.get('profit') else "—"
            p_cls = "positive" if t.get('profit', 0) > 0 else ("negative" if t.get('profit', 0) and t.get('profit', 0) < 0 else "")
            trade_table += f'''<tr>
                <td>{res['name']}</td>
                <td class="{dir_cls}">{dir_label}</td>
                <td>{name}({t['code']})</td>
                <td>¥{t['price']:.2f}</td>
                <td>{t['vol']}</td>
                <td class="{p_cls}">{profit_str}</td>
                <td>{t.get('reason', '')}</td>
            </tr>'''
    
    html_content = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>QuantWeave v2 回测报告</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family: 'Plus Jakarta Sans', -apple-system, sans-serif; background:#f8fafc; color:#1e293b; }}
.header {{ background:linear-gradient(135deg,#0f172a 0%,#1e40af 100%); color:#fff; padding:40px; text-align:center; }}
.header h1 {{ font-size:2em; margin-bottom:8px; }}
.header .subtitle {{ opacity:0.8; font-size:1.1em; }}
.container {{ max-width:1200px; margin:0 auto; padding:20px; }}
.section {{ background:#fff; border-radius:12px; box-shadow:0 1px 3px rgba(0,0,0,0.1); padding:24px; margin-bottom:20px; }}
.section h2 {{ font-size:1.3em; margin-bottom:16px; color:#1e40af; border-bottom:2px solid #e2e8f0; padding-bottom:8px; }}
.cards {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(280px, 1fr)); gap:16px; margin-bottom:20px; }}
.card {{ background:#fff; border-radius:12px; padding:20px; box-shadow:0 1px 3px rgba(0,0,0,0.1); border-left:4px solid var(--accent,#3b82f6); }}
.card .label {{ font-size:0.85em; color:#64748b; margin-bottom:4px; }}
.card .value {{ font-size:1.8em; font-weight:700; }}
.card .sub {{ font-size:0.85em; color:#64748b; margin-top:4px; }}
.positive {{ color:#dc2626; }}
.negative {{ color:#16a34a; }}
.buy {{ color:#dc2626; font-weight:600; }}
.sell {{ color:#16a34a; font-weight:600; }}
table {{ width:100%; border-collapse:collapse; font-size:0.9em; }}
th {{ background:#f1f5f9; padding:10px 12px; text-align:left; font-weight:600; color:#475569; }}
td {{ padding:10px 12px; border-bottom:1px solid #f1f5f9; }}
.chart-box {{ position:relative; height:350px; }}
.footer {{ text-align:center; padding:20px; color:#94a3b8; font-size:0.85em; }}
</style>
</head>
<body>

<div class="header">
    <h1>📊 QuantWeave v2 回测报告</h1>
    <div class="subtitle">区间: {START_DATE} ~ {END_DATE} | 初始资金: ¥{INITIAL_CAPITAL:,} | 最大持仓: {MAX_POSITIONS}只</div>
</div>

<div class="container">
    <!-- 策略对比卡片 -->
    <div class="cards">'''
    
    # 动态生成策略卡片
    for key, res in all_strategies:
        ret = res['total_return']
        ret_cls = "positive" if ret > 0 else "negative"
        final_val = res.get('final_value', INITIAL_CAPITAL * (1 + ret/100))
        accent = COLORS.get(key, '#3b82f6')
        html_content += f'''
        <div class="card" style="--accent:{accent}">
            <div class="label">{res['name']}</div>
            <div class="value {ret_cls}">{ret:+.2f}%</div>
            <div class="sub">夏普 {res['sharpe_ratio']:.3f} | 回撤 {res['max_drawdown']:.2f}% | 胜率 {res['win_rate']:.1f}%</div>
            <div class="sub">终值 ¥{final_val:,.0f} | 交易 {res['total_trades']}笔</div>
        </div>'''
    
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M')
    equity_js = ",".join(equity_datasets)
    dd_js = ",".join(dd_datasets)
    sl_pct = f"{STOP_LOSS*100:.0f}"
    tp_pct = f"{TAKE_PROFIT*100:.0f}"
    
    html_content += f'''
    </div>

    <!-- 权益曲线 -->
    <div class="section">
        <h2>📈 权益曲线</h2>
        <div class="chart-box"><canvas id="equityChart"></canvas></div>
    </div>

    <!-- 回撤曲线 -->
    <div class="section">
        <h2>📉 最大回撤</h2>
        <div class="chart-box"><canvas id="drawdownChart"></canvas></div>
    </div>

    <!-- 策略排名 -->
    <div class="section">
        <h2>🏆 策略综合排名 (按夏普比率)</h2>
        <table>
            <thead><tr><th>#</th><th>策略</th><th>总收益</th><th>年化</th><th>夏普</th><th>最大回撤</th><th>胜率</th><th>盈亏比</th><th>交易数</th></tr></thead>
            <tbody>{rank_rows}</tbody>
        </table>
    </div>

    <!-- 交易明细 -->
    <div class="section">
        <h2>📋 最近交易明细 (最佳策略)</h2>
        <table>
            <thead><tr><th>策略</th><th>方向</th><th>股票</th><th>价格</th><th>数量</th><th>盈亏</th><th>原因</th></tr></thead>
            <tbody>{trade_table}</tbody>
        </table>
    </div>
</div>

<div class="footer">
    QuantWeave v2 · 回测引擎 · 止损{sl_pct}% / 止盈+{tp_pct}% · 生成时间: {now_str}
</div>

<script>
const dateConfig = {{
    type: 'time',
    time: {{ unit: 'month', displayFormats: {{ month: 'yyyy-MM' }} }},
    ticks: {{ maxTicksLimit: 12 }}
}};

new Chart(document.getElementById('equityChart'), {{
    type: 'line',
    data: {{ datasets: [{equity_js}] }},
    options: {{
        responsive: true,
        maintainAspectRatio: false,
        interaction: {{ intersect: false, mode: 'index' }},
        scales: {{ x: dateConfig, y: {{ ticks: {{ callback: v => '¥' + (v/10000).toFixed(1) + '万' }} }} }},
        plugins: {{
            legend: {{ position: 'top' }},
            tooltip: {{ callbacks: {{ label: ctx => ctx.dataset.label + ': ¥' + ctx.parsed.y.toLocaleString() }} }}
        }}
    }}
}});

new Chart(document.getElementById('drawdownChart'), {{
    type: 'line',
    data: {{ datasets: [{dd_js}] }},
    options: {{
        responsive: true,
        maintainAspectRatio: false,
        interaction: {{ intersect: false, mode: 'index' }},
        scales: {{ x: dateConfig, y: {{ ticks: {{ callback: v => v.toFixed(1) + '%' }} }} }},
        plugins: {{
            legend: {{ position: 'top' }},
            tooltip: {{ callbacks: {{ label: ctx => ctx.dataset.label + ': ' + ctx.parsed.y.toFixed(2) + '%' }} }}
        }}
    }}
}});
</script>
</body>
</html>'''
    
    output = 'reports/daily_picks_v2_backtest.html'
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    with open(output, 'w', encoding='utf-8') as f:
        f.write(html_content)
    print(f"📊 HTML报告已生成: {output}")


# ============================================================
# Main
# ============================================================
if __name__ == '__main__':
    print("=" * 60)
    print("📊 Daily Picks v2 — 新策略2年回测")
    print(f"区间: {START_DATE} ~ {END_DATE}")
    print("=" * 60)
    
    all_data, stock_names = load_all_data()
    
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(f"SELECT DISTINCT trade_date FROM stock_daily WHERE trade_date >= '{START_DATE}' AND trade_date <= '{END_DATE}' ORDER BY trade_date")
    dates = [r[0] for r in cur.fetchall()]
    conn.close()
    print(f"交易日数: {len(dates)}")
    
    results = {}
    
    # ---- 1. 布林带上轨突破 ----
    print("\n" + "=" * 60)
    print("PHASE 1: 布林带上轨突破 (Bollinger Upper Break)")
    print("=" * 60)
    
    boll_params = {'period': 25, 'std_mult': 2.0, 'near_pct': 0.02}
    boll_result = backtest_strategy(all_data, dates, generate_bollinger_upper_signals, boll_params, "布林带上轨突破")
    results['bollinger_upper'] = boll_result
    print(f"\n  收益: {boll_result['total_return']:+.2f}% | 夏普: {boll_result['sharpe_ratio']:.3f} | 回撤: {boll_result['max_drawdown']:.2f}% | 交易: {boll_result['total_trades']}")
    
    # 也跑一下不同参数看看效果
    boll_variants = [
        {'period': 20, 'std_mult': 2.0, 'near_pct': 0.02},
        {'period': 25, 'std_mult': 2.0, 'near_pct': 0.03},
        {'period': 20, 'std_mult': 1.5, 'near_pct': 0.02},
        {'period': 30, 'std_mult': 2.0, 'near_pct': 0.02},
        {'period': 25, 'std_mult': 1.5, 'near_pct': 0.03},
    ]
    
    boll_all = [boll_result]
    for bp in boll_variants:
        r = backtest_strategy(all_data, dates, generate_bollinger_upper_signals, bp, f"布林带上轨突破({bp})")
        boll_all.append(r)
        print(f"  收益: {r['total_return']:+.2f}% | 夏普: {r['sharpe_ratio']:.3f} | 回撤: {r['max_drawdown']:.2f}% | 交易: {r['total_trades']}")
    
    boll_all.sort(key=lambda x: (-x['sharpe_ratio'], -x['total_return']))
    results['bollinger_upper_best'] = boll_all[0]
    
    # ---- 2. 强势股回调企稳(ZLCMQ) ----
    print("\n" + "=" * 60)
    print("PHASE 2: 强势股回调企稳 (ZLCMQ Pullback)")
    print("=" * 60)
    
    pull_params = {'n_days': 8, 'min_high': 92, 'min_fall': 3, 'stable_threshold': 3}
    pull_result = backtest_strategy(all_data, dates, generate_zlcmq_pullback_signals, pull_params, "强势股回调企稳(ZLCMQ)")
    results['zlcmq_pullback'] = pull_result
    print(f"\n  收益: {pull_result['total_return']:+.2f}% | 夏普: {pull_result['sharpe_ratio']:.3f} | 回撤: {pull_result['max_drawdown']:.2f}% | 交易: {pull_result['total_trades']}")
    
    # 参数变体
    pull_variants = [
        {'n_days': 5, 'min_high': 90, 'min_fall': 3, 'stable_threshold': 3},
        {'n_days': 8, 'min_high': 95, 'min_fall': 5, 'stable_threshold': 3},
        {'n_days': 10, 'min_high': 92, 'min_fall': 3, 'stable_threshold': 3},
        {'n_days': 8, 'min_high': 92, 'min_fall': 3, 'stable_threshold': 4},
        {'n_days': 8, 'min_high': 90, 'min_fall': 5, 'stable_threshold': 3},
    ]
    
    pull_all = [pull_result]
    for pp in pull_variants:
        r = backtest_strategy(all_data, dates, generate_zlcmq_pullback_signals, pp, f"强势股回调企稳({pp})")
        pull_all.append(r)
        print(f"  收益: {r['total_return']:+.2f}% | 夏普: {r['sharpe_ratio']:.3f} | 回撤: {r['max_drawdown']:.2f}% | 交易: {r['total_trades']}")
    
    pull_all.sort(key=lambda x: (-x['sharpe_ratio'], -x['total_return']))
    results['zlcmq_pullback_best'] = pull_all[0]
    
    # ---- Summary ----
    print("\n" + "=" * 60)
    print("📊 回测结果汇总")
    print("=" * 60)
    
    # 与之前回测的对比
    prev_best = {
        '布林带突破(下轨)': {'return': 24.29, 'sharpe': 0.947, 'dd': 24.42},
        '增强筹码策略': {'return': 20.20, 'sharpe': 0.683, 'dd': 28.15},
        '双均线交叉': {'return': 11.76, 'sharpe': 0.442, 'dd': 20.33},
    }
    
    print("\n📊 旧策略(已测) vs 新策略:")
    print("-" * 70)
    print(f"{'策略':<25} {'收益':>10} {'夏普':>10} {'最大回撤':>10} {'交易数':>8}")
    print("-" * 70)
    for name, m in prev_best.items():
        print(f"{name:<25} {m['return']:>+9.2f}% {m['sharpe']:>10.3f} {m['dd']:>9.2f}% {'—':>8}")
    
    for key in ['bollinger_upper', 'zlcmq_pullback']:
        r = results[key]
        print(f"{r['name']:<25} {r['total_return']:>+9.2f}% {r['sharpe_ratio']:>10.3f} {r['max_drawdown']:>9.2f}% {r['total_trades']:>8}")
    
    print("-" * 70)
    print("\n最佳参数:")
    for key in ['bollinger_upper_best', 'zlcmq_pullback_best']:
        r = results[key]
        print(f"  {r['name']}: {r['params']} => 收益{r['total_return']:+.2f}% 夏普{r['sharpe_ratio']:.3f} 回撤{r['max_drawdown']:.2f}%")
    
    # Save JSON (summary only, no curves)
    summary = {}
    for k, v in results.items():
        if isinstance(v, dict):
            summary[k] = {kk: vv for kk, vv in v.items() if kk not in ('equity_curve', 'trades')}
            for pk, pv in v.get('params', {}).items():
                if isinstance(pv, (np.integer,)):
                    v['params'][pk] = int(pv)
                elif isinstance(pv, (np.floating,)):
                    v['params'][pk] = float(pv)
    
    Path(OUTPUT_PATH).parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, 'w') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n💾 结果已保存: {OUTPUT_PATH}")
    
    # ===== Generate HTML report =====
    generate_html_report(results, stock_names)
