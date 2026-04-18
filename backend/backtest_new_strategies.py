#!/usr/bin/env python3
"""
QuantWeave — 三个新策略2年回测
策略一：筹码低位密集
策略二：资金流主动买入（量价近似）
策略三：拉升段跟庄

cd /Users/liujianyu/WorkBuddy/Claw/quant-platform/backend
/opt/anaconda3/envs/quant-platform/bin/python backtest_new_strategies.py
"""
import sqlite3, numpy as np, json, sys
from pathlib import Path

DB_PATH = 'quantweave.db'
START_DATE = '20240415'
END_DATE = '20260414'
INITIAL_CAPITAL = 1000000
MAX_POSITIONS = 10
POSITION_PER_STOCK = 0.2
SLIPPAGE = 0.001
COMMISSION = 0.0003

EXIT_CONFIGS = {
    'chip_low': {'stop_loss': -0.10, 'exit': {'type': 'fixed', 'tp': 0.30}, 'max_hold': 30, 'min_profit': 0.15},
    'money_flow': {'stop_loss': -0.08, 'exit': {'type': 'fixed', 'tp': 0.25}, 'max_hold': 20, 'min_profit': 0},
    'pulling_phase': {'stop_loss': -0.15, 'exit': {'type': 'trail_peak', 'tp': 0.15}, 'max_hold': 20, 'min_profit': 0},
}


def _sd_to_arrays(sd, dates):
    close = np.array([sd.get(d, {}).get('close') for d in dates], dtype=float)
    close = np.where(close == None, np.nan, close)
    high = np.array([sd.get(d, {}).get('high') for d in dates], dtype=float)
    high = np.where(high == None, np.nan, high)
    low = np.array([sd.get(d, {}).get('low') for d in dates], dtype=float)
    low = np.where(low == None, np.nan, low)
    vol = np.array([sd.get(d, {}).get('vol') for d in dates], dtype=float)
    vol = np.where(vol == None, np.nan, vol)
    open_ = np.array([sd.get(d, {}).get('open') for d in dates], dtype=float)
    open_ = np.where(open_ == None, np.nan, open_)
    return close, high, low, vol, open_


def load_all_data():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(f"""SELECT ts_code, trade_date, open, high, low, close, vol, amount
                FROM stock_daily WHERE trade_date >= '{START_DATE}' AND trade_date <= '{END_DATE}'
                ORDER BY ts_code, trade_date""")
    rows = cur.fetchall()
    stock_names = {}
    cur.execute("SELECT ts_code, name FROM stocks")
    for r in cur.fetchall():
        stock_names[r[0]] = r[1]
    conn.close()
    data = {}
    for ts_code, trade_date, op, hi, lo, cl, v, amt in rows:
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
            'vol': float(v) if v else 0, 'amount': float(amt) if amt else 0,
        }
    print(f"Loaded {len(data)} stocks, {sum(len(v) for v in data.values())} records")
    return data, stock_names


# ============================================================
# 策略一：筹码低位密集
# ============================================================
def signals_chip_low(close, high, low, vol, open_, dates, params=None):
    """用价格-成交量分布近似CYQ，找低位密集+横盘+突破"""
    p = params or {}
    lookback = p.get('lookback', 30)
    width_thresh = p.get('width_thresh', 0.25)
    peak_pos_min = p.get('peak_pos_min', 0.85)
    sideways_days = p.get('sideways_days', 10)
    sideways_range = p.get('sideways_range', 0.12)

    signals = {}
    n = len(close)
    for i in range(lookback + sideways_days + 1, n):
        if np.isnan(close[i]):
            continue
        wc = close[i-lookback:i+1]; wv = vol[i-lookback:i+1]
        wh = high[i-lookback:i+1]; wl = low[i-lookback:i+1]
        valid = ~(np.isnan(wc)|np.isnan(wv)|(wv<=0))
        if valid.sum()<lookback*0.5: continue
        pc, pv, ph, pl = wc[valid], wv[valid], wh[valid], wl[valid]
        if len(pc)<10 or pv.sum()==0: continue

        p_min, p_max = pl.min(), ph.max()
        if p_max<=p_min: continue
        bins = np.linspace(p_min, p_max, 16)
        bin_vols = np.zeros(15)
        for j in range(len(pc)):
            lo_j, hi_j = pl[j], ph[j]
            for b in range(15):
                overlap = max(0, min(hi_j, bins[b+1]) - max(lo_j, bins[b]))
                if overlap>0: bin_vols[b] += pv[j]*overlap/(hi_j-lo_j+1e-10)
        tv = bin_vols.sum()
        if tv==0: continue
        bp = bin_vols/tv

        peak_bin = np.argmax(bp)
        peak_price = (bins[peak_bin]+bins[peak_bin+1])/2
        sig_bins = np.where(bp>0.04)[0]
        if len(sig_bins)<2: continue
        conc_w = (bins[sig_bins[-1]+1]-bins[sig_bins[0]])/close[i]
        peak_pos = peak_price/close[i]

        # 横盘
        rc = close[i-sideways_days:i+1]
        vr = rc[~np.isnan(rc)]
        if len(vr)<sideways_days: continue
        rr = (vr.max()-vr.min())/np.mean(vr)

        # 突破
        prev_hi = np.max(vr[:-1]) if len(vr)>1 else vr[0]
        breakout = close[i]>prev_hi*1.02

        # 量能正常
        rv = vol[i-sideways_days:i+1]; pv2 = vol[i-lookback:i-sideways_days]
        rv2 = rv[(~np.isnan(rv))&(rv>0)]; pv3 = pv2[(~np.isnan(pv2))&(pv2>0)]
        if len(rv2)==0 or len(pv3)==0: continue
        vr2 = np.mean(rv2)/np.mean(pv3)

        if conc_w<width_thresh and peak_pos>=peak_pos_min and rr<sideways_range and 0.5<=vr2<=2.0 and breakout and bp[peak_bin]>0.08:
            signals[dates[i]] = 'buy'

        # 卖出：筹码上移分散
        if peak_pos>1.2 and bp[peak_bin]<0.03:
            signals[dates[i]] = 'sell'
    return signals


# ============================================================
# 策略二：资金流主动买入（量价近似）
# ============================================================
def signals_money_flow(close, high, low, vol, open_, dates, params=None):
    """用量价关系近似主力资金：主动买入力 = (C-O)/(H-L+eps)*V"""
    p = params or {}
    flow_days = p.get('flow_days', 5)
    surge_days = p.get('surge_days', 3)
    vol_mult = p.get('vol_mult', 1.5)

    signals = {}
    n = len(close)
    # 计算每日买入力
    bf = np.full(n, np.nan)
    for i in range(1, n):
        if np.isnan(close[i]) or np.isnan(vol[i]) or vol[i]<=0: continue
        hl = high[i]-low[i]
        if hl<=0: continue
        bf[i] = (close[i]-open_[i])/hl * vol[i]

    for i in range(flow_days+surge_days+21, n):
        if np.isnan(close[i]) or np.isnan(vol[i]): continue

        # 5日累计净买入力
        bfr = bf[i-flow_days+1:i+1]
        vb = bfr[~np.isnan(bfr)]
        if len(vb)<flow_days*0.5: continue
        net_flow = np.sum(vb)
        if len(vb)>=3:
            fh = np.mean(vb[:len(vb)//2]); sh = np.mean(vb[len(vb)//2:])
            rising = sh>fh
        else: rising=False

        # 连续正流入
        bs = bf[i-surge_days+1:i+1]
        vs = bs[~np.isnan(bs)]
        consec_pos = all(v>0 for v in vs) if len(vs)>=surge_days else False

        # 放量上涨
        avg20 = np.nanmean(vol[i-20:i])
        if np.isnan(avg20) or avg20<=0: continue
        surge_up = vol[i]>avg20*vol_mult and close[i]>open_[i] and (close[i]-close[i-1])/close[i-1]>0.03

        # 突破20日新高
        rh = high[i-20:i]; vh2 = rh[~np.isnan(rh)]
        if len(vh2)==0: continue
        is_break = close[i]>np.max(vh2)

        if net_flow>0 and rising and consec_pos and surge_up and is_break:
            signals[dates[i]] = 'buy'

        # 卖出：连续5日负流入
        if i>=5:
            bs2 = bf[i-4:i+1]; vs2 = bs2[~np.isnan(bs2)]
            if len(vs2)>=5 and all(v<0 for v in vs2):
                signals[dates[i]] = 'sell'
    return signals


# ============================================================
# 策略三：拉升段跟庄
# ============================================================
def signals_pulling_phase(close, high, low, vol, open_, dates, params=None):
    """只做拉升段：低位涨20-80%+洗盘结束+放量启动+MACD金叉+涨停基因"""
    p = params or {}
    rise_min = p.get('rise_min', 0.20)
    rise_max = p.get('rise_max', 0.80)
    launch_vol = p.get('launch_vol', 2.0)
    limit_pct = p.get('limit_pct', 0.095)

    signals = {}
    n = len(close)

    # MACD
    a12, a26, a9 = 2/13, 2/27, 2/10
    e12 = np.full(n, np.nan); e26 = np.full(n, np.nan)
    dif = np.full(n, np.nan); dea = np.full(n, np.nan)
    e12[0]=close[0]; e26[0]=close[0]
    for i in range(1, n):
        if np.isnan(close[i]):
            e12[i]=e12[i-1]; e26[i]=e26[i-1]
        else:
            e12[i] = a12*close[i]+(1-a12)*(e12[i-1] if not np.isnan(e12[i-1]) else close[i])
            e26[i] = a26*close[i]+(1-a26)*(e26[i-1] if not np.isnan(e26[i-1]) else close[i])
    for i in range(n):
        if not np.isnan(e12[i]) and not np.isnan(e26[i]): dif[i]=e12[i]-e26[i]
    dea[0] = 0
    for i in range(1, n):
        if np.isnan(dif[i]): dea[i]=dea[i-1]
        else: dea[i] = a9*dif[i]+(1-a9)*(dea[i-1] if not np.isnan(dea[i-1]) else dif[i])

    for i in range(61, n):
        if np.isnan(close[i]) or np.isnan(vol[i]): continue

        # 拉升阶段
        rl = np.nanmin(low[i-60:i+1])
        if np.isnan(rl) or rl<=0: continue
        rise = (close[i]-rl)/rl
        if not (rise_min<=rise<=rise_max): continue

        # 站上MA20
        mc = close[i-19:i+1]; vm = mc[~np.isnan(mc)]
        if len(vm)<15: continue
        if close[i]<=np.mean(vm): continue

        # 放量启动
        av5 = np.nanmean(vol[max(0,i-5):i])
        if np.isnan(av5) or av5<=0: continue
        launch = vol[i]>av5*launch_vol and close[i]>open_[i]
        if not launch: continue

        # MACD金叉
        gc = (not np.isnan(dif[i]) and not np.isnan(dea[i]) and
              not np.isnan(dif[i-1]) and not np.isnan(dea[i-1]) and
              dif[i-1]<=dea[i-1] and dif[i]>dea[i])
        if not gc: continue

        # 涨停基因
        has_limit = False
        for j in range(max(0,i-30), i):
            if np.isnan(close[j]) or j==0 or np.isnan(close[j-1]): continue
            if close[j-1]>0 and (close[j]-close[j-1])/close[j-1]>=limit_pct:
                has_limit=True; break
        if not has_limit: continue

        signals[dates[i]] = 'buy'

        # 卖出：高位放量大阴线
        if (close[i]<open_[i] and (open_[i]-close[i])/open_[i]>0.07 and vol[i]>av5*2):
            signals[dates[i]] = 'sell'
    return signals


# ============================================================
# 回测引擎
# ============================================================
def backtest_strategy(all_data, dates, signal_func, params, name, exit_key):
    stock_list = list(all_data.keys())
    print(f"  [{name}] 扫描 {len(stock_list)} 只...")

    all_sigs = {}
    for idx, code in enumerate(stock_list):
        sd = all_data[code]
        c, h, l, v, o = _sd_to_arrays(sd, dates)
        sigs = signal_func(c, h, l, v, o, dates, params)
        if sigs: all_sigs[code] = sigs
        if (idx+1)%1000==0: print(f"    ... {idx+1}/{len(stock_list)}")

    ecfg = EXIT_CONFIGS[exit_key]
    sl = ecfg['stop_loss']; ex = ecfg['exit']; mxh = ecfg['max_hold']; mnp = ecfg['min_profit']

    cash=INITIAL_CAPITAL; positions={}; pv=INITIAL_CAPITAL; equity=[]; trades=[]
    for date in sorted(dates):
        to_sell = []
        for code, pos in list(positions.items()):
            if code not in all_data or date not in all_data[code]: continue
            pr = all_data[code][date]['close']
            pnl = (pr-pos['cp'])/pos['cp']
            if pr>pos.get('peak',pos['cp']): pos['peak']=pr
            hd = pos.get('hold_days',0)+1; pos['hold_days']=hd
            reason = None

            # 止损
            if ex['type']=='trail_peak':
                dd = (pos.get('peak',pos['cp'])-pr)/pos.get('peak',pos['cp'])
                if dd>=ex['tp']: reason='回落止损'
            elif pnl<=sl: reason='止损'

            # 止盈
            if not reason:
                if ex['type']=='fixed' and pnl>=ex['tp']: reason='止盈'
                elif ex['type']=='trail_peak' and reason!='回落止损' and pnl>0:
                    pass  # 已在上面处理

            # 超时
            if not reason and hd>=mxh and pnl<mnp: reason='超时换股'
            if reason: to_sell.append((code,pr,reason))

        for code,pr,reason in to_sell:
            pos=positions.pop(code)
            sa=pos['shares']*pr*(1-SLIPPAGE); cm=sa*COMMISSION; cash+=sa-cm
            profit=(pr-pos['cp'])*pos['shares']-cm-pos['shares']*pos['cp']*COMMISSION
            trades.append({'dir':'S','code':code,'price':pr,'vol':pos['shares'],'profit':profit,'reason':reason,'date':date})

        ne=MAX_POSITIONS-len(positions)
        if ne>0:
            cands=[]
            for code in stock_list:
                if code in positions: continue
                if code in all_sigs and date in all_sigs[code] and all_sigs[code][date]=='buy':
                    if code in all_data and date in all_data[code]:
                        pr=all_data[code][date]['close']
                        if pr>0: cands.append((code,pr))
            for code,pr in cands[:ne]:
                inv=pv*POSITION_PER_STOCK; sh=int(inv/(pr*(1+SLIPPAGE))/100)*100
                if sh<=0: sh=100
                cost=sh*pr*(1+SLIPPAGE); cm=cost*COMMISSION
                if cash>=cost+cm:
                    cash-=cost+cm; positions[code]={'shares':sh,'cp':pr,'bd':date,'peak':pr,'hold_days':0}
                    trades.append({'dir':'B','code':code,'price':pr,'vol':sh,'profit':0,'reason':'策略信号','date':date})

        for code in list(positions.keys()):
            if code in all_sigs and date in all_sigs[code] and all_sigs[code][date]=='sell':
                if code in all_data and date in all_data[code]:
                    pr=all_data[code][date]['close']; pos=positions.pop(code)
                    sa=pos['shares']*pr*(1-SLIPPAGE); cm=sa*COMMISSION; cash+=sa-cm
                    profit=(pr-pos['cp'])*pos['shares']-cm
                    trades.append({'dir':'S','code':code,'price':pr,'vol':pos['shares'],'profit':profit,'reason':'策略卖出','date':date})

        posv=sum(pos['shares']*all_data[code][date]['close'] for code,pos in positions.items() if code in all_data and date in all_data[code])
        pv=cash+posv; equity.append({'date':date,'value':round(pv,2)})

    ld=sorted(dates)[-1]
    for code,pos in positions.items():
        if code in all_data and ld in all_data[code]:
            pr=all_data[code][ld]['close']; sa=pos['shares']*pr*(1-SLIPPAGE); cm=sa*COMMISSION; cash+=sa-cm
            profit=(pr-pos['cp'])*pos['shares']-cm
            trades.append({'dir':'S','code':code,'price':pr,'vol':pos['shares'],'profit':profit,'reason':'期末清仓','date':ld})
    pv=cash

    tr=(pv-INITIAL_CAPITAL)/INITIAL_CAPITAL*100; nd=len(dates); ar=tr/(nd/252) if nd else 0
    pk=INITIAL_CAPITAL; mdd=0; dd_curve=[]
    for e in equity:
        if e['value']>pk: pk=e['value']
        dd=(pk-e['value'])/pk; dd_curve.append({'date':e['date'],'dd':round(dd*100,2)})
        if dd>mdd: mdd=dd
    mdd*=100
    sharpe=0
    if len(equity)>1:
        rets=np.array([(equity[i]['value']-equity[i-1]['value'])/equity[i-1]['value'] for i in range(1,len(equity))])
        if np.std(rets)>0: sharpe=(np.mean(rets)*252-0.03)/(np.std(rets)*np.sqrt(252))
    sells=[t for t in trades if t['dir']=='S' and t['reason']!='期末清仓']
    wins=[t for t in sells if t.get('profit',0)>0]
    wr=len(wins)/len(sells)*100 if sells else 0
    wp=[t['profit'] for t in sells if t.get('profit',0)>0]; lp2=[-t['profit'] for t in sells if t.get('profit',0)<0]
    aw=np.mean(wp) if wp else 0; al=np.mean(lp2) if lp2 else 1
    plr=aw/al if al>0 else 0
    sr={}
    for t in sells: sr[t['reason']]=sr.get(t['reason'],0)+1

    print(f"  => 收益:{tr:+.2f}% 夏普:{sharpe:.3f} 回撤:{mdd:.2f}% 交易:{len(trades)} 胜率:{wr:.1f}% 卖出:{sr}")
    return {'name':name,'total_return':round(tr,2),'annual_return':round(ar,2),'max_drawdown':round(mdd,2),
            'sharpe_ratio':round(float(sharpe),4),'win_rate':round(wr,1),'profit_loss_ratio':round(float(plr),2),
            'total_trades':len(trades),'sell_reasons':sr,'final_value':round(pv,2),
            'equity_curve':equity,'dd_curve':dd_curve,'trades':trades}


# ============================================================
# Main
# ============================================================
if __name__ == '__main__':
    print("=" * 60)
    print("📊 QuantWeave — 三个新策略2年回测")
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
        ('chip_low', '筹码低位密集', signals_chip_low,
         {'lookback':30,'width_thresh':0.25,'peak_pos_min':0.85,'sideways_days':10,'sideways_range':0.12}),
        ('money_flow', '资金流主动买入', signals_money_flow,
         {'flow_days':5,'surge_days':3,'vol_mult':1.5}),
        ('pulling_phase', '拉升段跟庄', signals_pulling_phase,
         {'rise_min':0.20,'rise_max':0.80,'launch_vol':2.0,'limit_pct':0.095}),
    ]

    results = {}
    for key, name, func, params in STRATEGIES:
        print(f"\n{'='*60}\n策略: {name}\n{'='*60}")
        results[key] = backtest_strategy(all_data, dates, func, params, name, key)

    # 汇总
    print(f"\n{'='*60}\n📊 新策略回测汇总\n{'='*60}")
    print(f"{'策略':<16} {'收益':>10} {'年化':>10} {'夏普':>8} {'回撤':>8} {'胜率':>8} {'交易':>6}")
    print("-" * 70)
    for key, r in results.items():
        print(f"{r['name']:<16} {r['total_return']:>+9.2f}% {r['annual_return']:>+9.2f}% {r['sharpe_ratio']:>8.3f} {r['max_drawdown']:>7.2f}% {r['win_rate']:>7.1f}% {r['total_trades']:>6}")

    # JSON
    Path('reports').mkdir(parents=True, exist_ok=True)
    summary = {}
    for k, v in results.items():
        summary[k] = {kk: vv for kk, vv in v.items() if kk not in ('equity_curve','dd_curve','trades')}
    with open('reports/new_strategies_backtest.json', 'w') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n💾 JSON: reports/new_strategies_backtest.json")
