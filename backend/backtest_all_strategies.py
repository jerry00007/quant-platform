#!/usr/bin/env python3
"""
QuantWeave — 全量策略2年回测
4大策略：布林带上轨突破 + 双均线交叉 + 增强筹码 + 强势股回调企稳

使用方式:
    cd /Users/liujianyu/WorkBuddy/Claw/quant-platform/backend
    /opt/anaconda3/envs/quant-platform/bin/python backtest_all_strategies.py
"""
import sqlite3, numpy as np, json
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
REPORT_DIR = 'reports'
REPORT_HTML = f'{REPORT_DIR}/all_strategies_backtest.html'
REPORT_JSON = f'{REPORT_DIR}/all_strategies_backtest.json'

def load_all_data():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(f"SELECT ts_code, trade_date, open, high, low, close, vol, amount "
                f"FROM stock_daily WHERE trade_date >= '{START_DATE}' AND trade_date <= '{END_DATE}' "
                f"ORDER BY ts_code, trade_date")
    rows = cur.fetchall()
    stock_names = {}
    cur.execute("SELECT ts_code, name FROM stocks")
    for r in cur.fetchall():
        stock_names[r[0]] = r[1]
    conn.close()
    data = {}
    for ts_code, trade_date, op, hi, lo, cl, vol, amt in rows:
        name = stock_names.get(ts_code, '')
        if name.startswith('ST') or name.startswith('*ST'):
            continue
        if not cl or cl <= 0:
            continue
        if ts_code not in data:
            data[ts_code] = {}
        data[ts_code][trade_date] = {
            'open': float(op) if op else float(cl), 'high': float(hi) if hi else float(cl),
            'low': float(lo) if lo else float(cl), 'close': float(cl),
            'vol': float(vol) if vol else 0, 'amount': float(amt) if amt else 0,
        }
    print(f"Loaded {len(data)} stocks, {sum(len(v) for v in data.values())} records")
    return data, stock_names

def tdx_sma(x, n, m):
    y = np.empty(len(x)); y[0] = x[0]
    for i in range(1, len(x)):
        y[i] = (m * x[i] + (n - m) * y[i - 1]) / n
    return y

def _calc_zlcmq(closes, highs, lows, idx):
    """计算第idx天的ZLCMQ值和窗口"""
    c_arr = np.array([c for c in closes[:idx+1] if c is not None])
    h_arr = np.array([h for h in highs[:idx+1] if h is not None])
    l_arr = np.array([l for l in lows[:idx+1] if l is not None])
    if len(c_arr) < 75:
        return None, c_arr
    lo75 = np.min(l_arr[-75:]); hi75 = np.max(h_arr[-75:])
    var7 = (hi75 - lo75) / 100.0
    if var7 < 1e-10:
        return None, c_arr
    raw = np.nan_to_num((c_arr[-75:] - lo75) / var7, nan=0.0)
    var8 = tdx_sma(raw, 20, 1); var8s = tdx_sma(var8, 15, 1)
    vara = 3.0 * var8 - 2.0 * var8s
    zlcmq = 100.0 - vara
    return zlcmq, c_arr

# ============================================================
# 4个策略信号函数
# ============================================================
def signals_bollinger_upper(sd, dates, params=None):
    p = params or {}
    period = p.get('period', 25); std_mult = p.get('std_mult', 2.0); near_pct = p.get('near_pct', 0.02)
    signals = {}
    closes = [sd.get(d, {}).get('close') for d in dates]
    for i in range(period+1, len(closes)):
        if closes[i] is None: continue
        w = [c for c in closes[i-period:i] if c is not None]
        if len(w) < period: continue
        ma = np.mean(w); std = np.std(w, ddof=0)
        upper = ma + std_mult*std; lower = ma - std_mult*std
        if closes[i-1] is None: continue
        if closes[i-1] <= upper and closes[i] > upper: signals[dates[i]] = 'buy'
        elif (upper - closes[i]) / upper < near_pct and closes[i] > ma: signals[dates[i]] = 'buy'
        if closes[i-1] >= ma and closes[i] < ma: signals[dates[i]] = 'sell'
        elif closes[i] < lower: signals[dates[i]] = 'sell'
    return signals

def signals_dual_ma(sd, dates, params=None):
    p = params or {}
    sp = p.get('short_period', 7); lp = p.get('long_period', 40)
    signals = {}
    closes = [sd.get(d, {}).get('close') for d in dates]
    ms = []; ml = []
    for i in range(len(closes)):
        if closes[i] is None: ms.append(None); ml.append(None); continue
        ws = [c for c in closes[max(0,i-sp+1):i+1] if c is not None]
        ms.append(np.mean(ws) if len(ws) >= sp else None)
        wl = [c for c in closes[max(0,i-lp+1):i+1] if c is not None]
        ml.append(np.mean(wl) if len(wl) >= lp else None)
    for i in range(1, len(closes)):
        if any(x is None for x in [closes[i], ms[i], ml[i], ms[i-1], ml[i-1]]): continue
        if ms[i-1] <= ml[i-1] and ms[i] > ml[i]: signals[dates[i]] = 'buy'
        elif ms[i-1] >= ml[i-1] and ms[i] < ml[i]: signals[dates[i]] = 'sell'
    return signals

def signals_enhanced_chip(sd, dates, params=None):
    p = params or {}
    n_days = p.get('n_days', 5); min_high = p.get('min_high', 98); min_fall = p.get('min_fall', 5)
    chip_exit = p.get('chip_exit', 15); vol_mult = p.get('vol_surge_mult', 1.5)
    signals = {}
    closes = [sd.get(d, {}).get('close') for d in dates]
    opens = [sd.get(d, {}).get('open') for d in dates]
    highs = [sd.get(d, {}).get('high') for d in dates]
    lows = [sd.get(d, {}).get('low') for d in dates]
    vols = [sd.get(d, {}).get('vol') for d in dates]
    for i in range(75, len(closes)):
        if closes[i] is None: continue
        zlcmq, c_arr = _calc_zlcmq(closes, highs, lows, i)
        if zlcmq is None: continue
        cur_z = zlcmq[-1]; prev_z = zlcmq[-2] if len(zlcmq)>1 else cur_z
        zw = zlcmq[-n_days:] if len(zlcmq)>=n_days else zlcmq
        zq_high = np.max(zw)
        if zq_high < min_high: continue
        if zq_high - cur_z < min_fall: continue
        if not (prev_z >= 95 and cur_z < 95): continue
        if opens[i] is None: continue
        is_stable = (closes[i]>opens[i]) or (i>0 and closes[i-1] is not None and closes[i]>closes[i-1])
        if not is_stable: continue
        if vols[i] and vols[i] > 0:
            rv = [v for v in vols[max(0,i-20):i] if v]
            if rv and vols[i] < np.mean(rv)*vol_mult: continue
        else: continue
        ma60w = [c for c in closes[max(0,i-59):i+1] if c is not None]
        if len(ma60w) >= 30 and closes[i] < np.mean(ma60w)*0.98: continue
        signals[dates[i]] = 'buy'
        if cur_z < chip_exit and prev_z < chip_exit: signals[dates[i]] = 'sell'
    return signals

def signals_pullback_stable(sd, dates, params=None):
    p = params or {}
    n_days = p.get('n_days', 8); min_high = p.get('min_high', 95); min_fall = p.get('min_fall', 5)
    stable_thr = p.get('stable_threshold', 3)
    signals = {}
    closes = [sd.get(d, {}).get('close') for d in dates]
    opens = [sd.get(d, {}).get('open') for d in dates]
    lows = [sd.get(d, {}).get('low') for d in dates]
    vols = [sd.get(d, {}).get('vol') for d in dates]
    for i in range(75, len(closes)):
        if closes[i] is None: continue
        zlcmq, c_arr = _calc_zlcmq(closes,
            [sd.get(d, {}).get('high') for d in dates], lows, i)
        if zlcmq is None: continue
        cur_z = zlcmq[-1]
        zw = zlcmq[-n_days:] if len(zlcmq)>=n_days else zlcmq
        if np.max(zw) < min_high: continue
        if np.max(zw) - cur_z < min_fall: continue
        cl = closes[i]; op = opens[i] if opens[i] else cl
        sc = 0
        if cl > op: sc += 1
        if i>0 and closes[i-1] is not None and cl > closes[i-1]: sc += 1
        if i>0 and lows[i] and lows[i-1] and lows[i] > lows[i-1]: sc += 1
        if vols[i]:
            rv = [v for v in vols[max(0,i-5):i] if v]
            if rv and vols[i] < np.mean(rv): sc += 1
        m5 = [c for c in closes[max(0,i-5):i] if c is not None]
        if m5 and cl > np.mean(m5): sc += 1
        if sc >= stable_thr: signals[dates[i]] = 'buy'
        if cur_z < 20: signals[dates[i]] = 'sell'
        elif len(c_arr) >= 60:
            ma60 = np.mean(c_arr[-60:])
            if i>0 and closes[i-1] is not None and closes[i-1]>=ma60 and cl<ma60:
                signals[dates[i]] = 'sell'
    return signals

# ============================================================
# Backtest Engine
# ============================================================
def backtest_strategy(all_data, dates, signal_func, params, name=""):
    stock_list = list(all_data.keys())
    print(f"  [{name}] 扫描 {len(stock_list)} 只...")
    all_sigs = {}
    for idx, code in enumerate(stock_list):
        sigs = signal_func(all_data[code], dates, params)
        if sigs: all_sigs[code] = sigs
        if (idx+1) % 1000 == 0: print(f"    ... {idx+1}/{len(stock_list)}")

    cash = INITIAL_CAPITAL; positions = {}; pv = INITIAL_CAPITAL
    equity = []; trades = []
    for date in sorted(dates):
        to_sell = []
        for code, pos in list(positions.items()):
            if code in all_data and date in all_data[code]:
                pr = all_data[code][date]['close']
                pnl = (pr - pos['cp']) / pos['cp']
                if pnl <= STOP_LOSS: to_sell.append((code, pr, '止损'))
                elif pnl >= TAKE_PROFIT: to_sell.append((code, pr, '止盈'))
        for code, pr, reason in to_sell:
            pos = positions.pop(code)
            sa = pos['shares']*pr*(1-SLIPPAGE); cm = sa*COMMISSION; cash += sa-cm
            profit = (pr-pos['cp'])*pos['shares']-cm-pos['shares']*pos['cp']*COMMISSION
            trades.append({'dir':'S','code':code,'price':pr,'vol':pos['shares'],'profit':profit,'reason':reason,'date':date})
        ne = MAX_POSITIONS - len(positions)
        if ne > 0:
            cands = []
            for code in stock_list:
                if code in positions: continue
                if code in all_sigs and date in all_sigs[code] and all_sigs[code][date]=='buy':
                    if code in all_data and date in all_data[code]:
                        pr = all_data[code][date]['close']
                        if pr > 0: cands.append((code, pr))
            for code, pr in cands[:ne]:
                inv = pv*POSITION_PER_STOCK
                sh = int(inv/(pr*(1+SLIPPAGE))/100)*100
                if sh <= 0: sh = 100
                cost = sh*pr*(1+SLIPPAGE); cm = cost*COMMISSION
                if cash >= cost+cm:
                    cash -= cost+cm; positions[code] = {'shares':sh,'cp':pr,'bd':date}
                    trades.append({'dir':'B','code':code,'price':pr,'vol':sh,'profit':0,'reason':'策略信号','date':date})
        for code in list(positions.keys()):
            if code in all_sigs and date in all_sigs[code] and all_sigs[code][date]=='sell':
                if code in all_data and date in all_data[code]:
                    pr = all_data[code][date]['close']
                    pos = positions.pop(code)
                    sa = pos['shares']*pr*(1-SLIPPAGE); cm = sa*COMMISSION; cash += sa-cm
                    profit = (pr-pos['cp'])*pos['shares']-cm
                    trades.append({'dir':'S','code':code,'price':pr,'vol':pos['shares'],'profit':profit,'reason':'策略卖出','date':date})
        posv = sum(pos['shares']*all_data[code][date]['close'] for code,pos in positions.items() if code in all_data and date in all_data[code])
        pv = cash + posv
        equity.append({'date':date,'value':round(pv,2)})

    ld = sorted(dates)[-1]
    for code, pos in positions.items():
        if code in all_data and ld in all_data[code]:
            pr = all_data[code][ld]['close']; sa = pos['shares']*pr*(1-SLIPPAGE); cm = sa*COMMISSION; cash += sa-cm
            profit = (pr-pos['cp'])*pos['shares']-cm
            trades.append({'dir':'S','code':code,'price':pr,'vol':pos['shares'],'profit':profit,'reason':'期末清仓','date':ld})
    pv = cash

    tr = (pv-INITIAL_CAPITAL)/INITIAL_CAPITAL*100
    nd = len(dates); ar = tr/(nd/252) if nd else 0
    peak = INITIAL_CAPITAL; mdd = 0; dd_curve = []
    for e in equity:
        if e['value']>peak: peak = e['value']
        dd = (peak-e['value'])/peak; dd_curve.append({'date':e['date'],'dd':round(dd*100,2)})
        if dd>mdd: mdd = dd
    mdd *= 100
    sharpe = 0
    if len(equity)>1:
        rets = np.array([(equity[i]['value']-equity[i-1]['value'])/equity[i-1]['value'] for i in range(1,len(equity))])
        if np.std(rets)>0: sharpe = (np.mean(rets)*252-0.03)/(np.std(rets)*np.sqrt(252))
    sells = [t for t in trades if t['dir']=='S']
    wins = [t for t in sells if t.get('profit',0)>0]
    wr = len(wins)/len(sells)*100 if sells else 0
    wp = [t['profit'] for t in sells if t.get('profit',0)>0]
    lp = [-t['profit'] for t in sells if t.get('profit',0)<0]
    aw = np.mean(wp) if wp else 0; al = np.mean(lp) if lp else 1
    plr = aw/al if al>0 else 0

    print(f"  => 收益:{tr:+.2f}% 夏普:{sharpe:.3f} 回撤:{mdd:.2f}% 交易:{len(trades)} 胜率:{wr:.1f}%")
    return {'name':name,'params':dict(params) if params else {},
            'total_return':round(tr,2),'annual_return':round(ar,2),'max_drawdown':round(mdd,2),
            'sharpe_ratio':round(float(sharpe),4),'win_rate':round(wr,1),
            'profit_loss_ratio':round(float(plr),2),'total_trades':len(trades),
            'final_value':round(pv,2),'equity_curve':equity,'dd_curve':dd_curve,'trades':trades}

# ============================================================
# HTML Report
# ============================================================
def generate_html_report(results, stock_names):
    from bt_html import build_html
    html = build_html(results, stock_names, START_DATE, END_DATE, INITIAL_CAPITAL, MAX_POSITIONS, STOP_LOSS, TAKE_PROFIT)
    Path(REPORT_DIR).mkdir(parents=True, exist_ok=True)
    with open(REPORT_HTML, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"\n📊 HTML报告: {REPORT_HTML}")

# ============================================================
# Main
# ============================================================
if __name__ == '__main__':
    print("=" * 60)
    print("📊 QuantWeave — 全量策略2年回测")
    print(f"区间: {START_DATE} ~ {END_DATE}")
    print("=" * 60)

    all_data, stock_names = load_all_data()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(f"SELECT DISTINCT trade_date FROM stock_daily WHERE trade_date>='{START_DATE}' AND trade_date<='{END_DATE}' ORDER BY trade_date")
    dates = [r[0] for r in cur.fetchall()]
    conn.close()
    print(f"交易日数: {len(dates)}\n")

    STRATEGIES = [
        ('bollinger_upper', '布林带上轨突破', signals_bollinger_upper, {'period':25,'std_mult':2.0,'near_pct':0.02}),
        ('dual_ma', '双均线交叉', signals_dual_ma, {'short_period':7,'long_period':40}),
        ('enhanced_chip', '增强筹码策略', signals_enhanced_chip, {'n_days':5,'min_high':98,'min_fall':5,'chip_exit':15,'vol_surge_mult':1.5,'trend_ma_period':60}),
        ('pullback_stable', '强势股回调企稳', signals_pullback_stable, {'n_days':8,'min_high':95,'min_fall':5,'stable_threshold':3}),
    ]

    results = {}
    for key, name, func, params in STRATEGIES:
        print(f"\n{'='*60}\n策略: {name}\n{'='*60}")
        results[key] = backtest_strategy(all_data, dates, func, params, name)

    # 汇总打印
    print(f"\n{'='*60}\n📊 全量策略回测汇总\n{'='*60}")
    print(f"{'策略':<20} {'收益':>10} {'年化':>10} {'夏普':>8} {'回撤':>8} {'胜率':>8} {'交易':>6}")
    print("-" * 70)
    for key, r in results.items():
        print(f"{r['name']:<20} {r['total_return']:>+9.2f}% {r['annual_return']:>+9.2f}% {r['sharpe_ratio']:>8.3f} {r['max_drawdown']:>7.2f}% {r['win_rate']:>7.1f}% {r['total_trades']:>6}")

    # 保存JSON
    summary = {}
    for k, v in results.items():
        summary[k] = {kk: vv for kk, vv in v.items() if kk not in ('equity_curve','dd_curve','trades')}
    Path(REPORT_DIR).mkdir(parents=True, exist_ok=True)
    with open(REPORT_JSON, 'w') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n💾 JSON: {REPORT_JSON}")

    # 生成HTML
    generate_html_report(results, stock_names)
