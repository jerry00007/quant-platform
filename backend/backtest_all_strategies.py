#!/usr/bin/env python3
"""
QuantWeave — 全量策略2年回测（引用共用策略模块）

4大策略：布林带上轨突破 + 双均线交叉 + 增强筹码 + 强势股回调企稳
策略逻辑统一由 core_signals.py 提供

使用方式:
    cd /Users/liujianyu/WorkBuddy/Claw/quant-platform/backend
    /opt/anaconda3/envs/quant-platform/bin/python backtest_all_strategies.py
"""
import sqlite3, numpy as np, json, sys
from datetime import datetime
from pathlib import Path

# 引用共用策略模块
sys.path.insert(0, str(Path(__file__).parent / 'app' / 'services' / 'strategy'))
from core_signals import (
    CORE_STRATEGIES,
    signals_bollinger_upper,
    signals_dual_ma,
    signals_enhanced_chip,
    signals_pullback_stable,
)

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


def _sd_to_arrays(sd, dates):
    """将 stock_data dict 转为 numpy arrays（适配 core_signals 接口）"""
    close = np.array([sd.get(d, {}).get('close') for d in dates], dtype=float)
    # 把 None 转为 NaN
    close = np.where(close == None, np.nan, close)  # noqa: E711
    high = np.array([sd.get(d, {}).get('high') for d in dates], dtype=float)
    high = np.where(high == None, np.nan, high)
    low = np.array([sd.get(d, {}).get('low') for d in dates], dtype=float)
    low = np.where(low == None, np.nan, low)
    vol = np.array([sd.get(d, {}).get('vol') for d in dates], dtype=float)
    vol = np.where(vol == None, np.nan, vol)
    open_ = np.array([sd.get(d, {}).get('open') for d in dates], dtype=float)
    open_ = np.where(open_ == None, np.nan, open_)
    return close, high, low, vol, open_


# ============================================================
# 适配器：将 core_signals 函数包装为回测引擎可用的接口
# ============================================================

def _adapter_close_only(func):
    """包装仅需 close 的策略（布林带、双均线）"""
    def wrapper(sd, dates, params=None):
        close, _, _, _, _ = _sd_to_arrays(sd, dates)
        return func(close, dates, params)
    return wrapper

def _adapter_full(func):
    """包装需要全部字段的策略（增强筹码、回调企稳）"""
    def wrapper(sd, dates, params=None):
        close, high, low, vol, open_ = _sd_to_arrays(sd, dates)
        return func(close, high, low, vol, open_, dates, params)
    return wrapper


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
# Main — 策略配置引用 CORE_STRATEGIES 注册表
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

    # 从共用模块读取策略配置，适配器包装
    STRATEGY_LIST = [
        ('bollinger_upper', _adapter_close_only(signals_bollinger_upper)),
        ('dual_ma',         _adapter_close_only(signals_dual_ma)),
        ('enhanced_chip',   _adapter_full(signals_enhanced_chip)),
        ('pullback_stable', _adapter_full(signals_pullback_stable)),
    ]

    results = {}
    for key, func in STRATEGY_LIST:
        cfg = CORE_STRATEGIES[key]
        name = cfg['name']
        params = cfg['default_params']
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
