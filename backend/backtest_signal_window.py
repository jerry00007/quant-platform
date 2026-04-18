#!/usr/bin/env python3
"""
QuantWeave — 信号窗口对比回测（1天 vs 2天 vs 3天 vs 5天）

验证信号窗口对收益的影响。不改动核心代码，仅做对比分析。
"""
import sqlite3, numpy as np, json, sys
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent / 'app' / 'services' / 'strategy'))
from core_signals import (
    CORE_STRATEGIES, signals_dual_ma, signals_pullback_stable,
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
COMMISSION = 0.001

EXIT_CONFIGS = {
    'dual_ma': {'type': 'fixed', 'take_profit_pct': 0.15},
    'pullback_stable': {
        'type': 'trailing',
        'tiers': [
            {'profit_pct': 0.05, 'trail_pct': 0.05},
            {'profit_pct': 0.15, 'trail_pct': 0.03},
            {'profit_pct': 0.30, 'trail_pct': 0.02},
        ],
        'min_profit_pct': 0.03,
    },
}

STRATEGIES = {
    'dual_ma': {
        'func': signals_dual_ma,
        'params': dict(CORE_STRATEGIES['dual_ma']['default_params']),
        'needs_full': False,
    },
    'pullback_stable': {
        'func': signals_pullback_stable,
        'params': dict(CORE_STRATEGIES['pullback_stable']['default_params']),
        'needs_full': True,
    },
}


def _adapter_close_only(func):
    def wrapper(sd, dates, params=None):
        close, _, _, _, _ = _sd_to_arrays(sd, dates)
        return func(close, dates, params)
    return wrapper

def _adapter_full(func):
    def wrapper(sd, dates, params=None):
        close, high, low, vol, open_ = _sd_to_arrays(sd, dates)
        return func(close, high, low, vol, open_, dates, params)
    return wrapper


def load_data():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT ts_code, trade_date, open, high, low, close, vol, amount "
        f"FROM stock_daily WHERE trade_date>='{START_DATE}' AND trade_date<='{END_DATE}' "
        "ORDER BY ts_code, trade_date"
    ).fetchall()
    # 过滤ST股
    stock_names = {}
    cur = conn.cursor()
    cur.execute("SELECT ts_code, name FROM stocks")
    for r in cur.fetchall():
        stock_names[r[0]] = r[1]
    conn.close()

    all_data = defaultdict(dict)
    date_set = set()
    for ts_code, trade_date, op, hi, lo, cl, vol, amt in rows:
        name = stock_names.get(ts_code, '')
        if name.startswith('ST') or name.startswith('*ST'):
            continue
        if not cl or cl <= 0:
            continue
        all_data[ts_code][trade_date] = {
            'open': float(op) if op else float(cl),
            'high': float(hi) if hi else float(cl),
            'low': float(lo) if lo else float(cl),
            'close': float(cl),
            'vol': float(vol) if vol else 0,
            'amount': float(amt) if amt else 0,
        }
        date_set.add(trade_date)
    return all_data, sorted(date_set)


def _sd_to_arrays(sd, dates):
    """将 stock_data dict 转为 numpy arrays"""
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


def backtest_with_window(all_data, dates, signal_func, params, name, needs_full=False, window_days=1):
    """回测，支持信号窗口参数"""
    stock_list = list(all_data.keys())

    # 1. 生成信号
    all_sigs = {}
    # 包装信号函数
    wrapped_func = _adapter_full(signal_func) if needs_full else _adapter_close_only(signal_func)
    for code in stock_list:
        sigs = wrapped_func(all_data[code], dates, params)
        if sigs:
            all_sigs[code] = sigs

    # 2. 构建信号索引：code -> {date: True} 表示该天有信号
    #    window_days>1 时，信号在 T, T+1, ..., T+(window-1) 都有效
    sig_valid = defaultdict(dict)  # sig_valid[code][date] = True
    date_index = {d: i for i, d in enumerate(dates)}

    for code, sigs in all_sigs.items():
        for sig_date, sig_type in sigs.items():
            if sig_type == 'buy' and sig_date in date_index:
                base_idx = date_index[sig_date]
                for offset in range(window_days):
                    idx = base_idx + offset
                    if idx < len(dates):
                        sig_valid[code][dates[idx]] = True

    # 3. 回测
    cash = INITIAL_CAPITAL
    positions = {}
    pv = INITIAL_CAPITAL
    equity = []
    trades = []
    exit_cfg = EXIT_CONFIGS.get(name, {'type': 'fixed', 'take_profit_pct': TAKE_PROFIT})

    for date in dates:
        # 卖出检查
        to_sell = []
        for code, pos in list(positions.items()):
            if code in all_data and date in all_data[code]:
                pr = all_data[code][date]['close']
                pnl = (pr - pos['cp']) / pos['cp']
                if pr > pos.get('peak', pos['cp']):
                    pos['peak'] = pr
                if pnl <= STOP_LOSS:
                    to_sell.append((code, pr, '止损'))
                elif exit_cfg['type'] == 'trailing':
                    profit_pct = (pr - pos['cp']) / pos['cp']
                    peak = pos.get('peak', pos['cp'])
                    drawdown_pct = (peak - pr) / peak if peak > 0 else 0
                    active_tier = None
                    for tier in sorted(exit_cfg['tiers'], key=lambda t: -t['profit_pct']):
                        if profit_pct >= tier['profit_pct']:
                            active_tier = tier
                            break
                    if active_tier and drawdown_pct >= active_tier['trail_pct']:
                        min_p = exit_cfg.get('min_profit_pct', 0.03)
                        if profit_pct >= min_p:
                            to_sell.append((code, pr, '跟踪止盈'))
                else:
                    tp_pct = exit_cfg.get('take_profit_pct', TAKE_PROFIT)
                    if pnl >= tp_pct:
                        to_sell.append((code, pr, '止盈'))

        for code, pr, reason in to_sell:
            pos = positions.pop(code)
            sa = pos['shares'] * pr * (1 - SLIPPAGE)
            cm = sa * COMMISSION
            cash += sa - cm
            profit = (pr - pos['cp']) * pos['shares'] - cm - pos['shares'] * pos['cp'] * COMMISSION
            trades.append({'dir': 'S', 'code': code, 'price': pr, 'vol': pos['shares'],
                           'profit': profit, 'reason': reason, 'date': date})

        # 买入（用信号窗口）
        ne = MAX_POSITIONS - len(positions)
        if ne > 0:
            cands = []
            for code in stock_list:
                if code in positions:
                    continue
                # 用窗口检查是否有有效信号
                if code in sig_valid and date in sig_valid[code]:
                    if code in all_data and date in all_data[code]:
                        pr = all_data[code][date]['close']
                        if pr > 0:
                            cands.append((code, pr))
            for code, pr in cands[:ne]:
                inv = pv * POSITION_PER_STOCK
                sh = int(inv / (pr * (1 + SLIPPAGE)) / 100) * 100
                if sh <= 0:
                    sh = 100
                cost = sh * pr * (1 + SLIPPAGE)
                cm = cost * COMMISSION
                if cash >= cost + cm:
                    cash -= cost + cm
                    positions[code] = {'shares': sh, 'cp': pr, 'bd': date, 'peak': pr}
                    trades.append({'dir': 'B', 'code': code, 'price': pr, 'vol': sh,
                                   'profit': 0, 'reason': '策略信号', 'date': date})

        # 策略卖出
        for code in list(positions.keys()):
            if code in all_sigs and date in all_sigs[code] and all_sigs[code][date] == 'sell':
                if code in all_data and date in all_data[code]:
                    pr = all_data[code][date]['close']
                    pos = positions.pop(code)
                    sa = pos['shares'] * pr * (1 - SLIPPAGE)
                    cm = sa * COMMISSION
                    cash += sa - cm
                    profit = (pr - pos['cp']) * pos['shares'] - cm
                    trades.append({'dir': 'S', 'code': code, 'price': pr, 'vol': pos['shares'],
                                   'profit': profit, 'reason': '策略卖出', 'date': date})

        posv = sum(
            pos['shares'] * all_data[code][date]['close']
            for code, pos in positions.items()
            if code in all_data and date in all_data[code]
        )
        pv = cash + posv
        equity.append({'date': date, 'value': round(pv, 2)})

    # 期末清仓
    ld = dates[-1]
    for code, pos in positions.items():
        if code in all_data and ld in all_data[code]:
            pr = all_data[code][ld]['close']
            sa = pos['shares'] * pr * (1 - SLIPPAGE)
            cm = sa * COMMISSION
            cash += sa - cm
            profit = (pr - pos['cp']) * pos['shares'] - cm
            trades.append({'dir': 'S', 'code': code, 'price': pr, 'vol': pos['shares'],
                           'profit': profit, 'reason': '期末清仓', 'date': ld})
    pv = cash

    # 统计
    total_return = (pv - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100
    peak = INITIAL_CAPITAL
    mdd = 0
    for e in equity:
        if e['value'] > peak:
            peak = e['value']
        dd = (peak - e['value']) / peak
        if dd > mdd:
            mdd = dd
    mdd *= 100

    sharpe = 0
    if len(equity) > 1:
        rets = np.array([(equity[i]['value'] - equity[i - 1]['value']) / equity[i - 1]['value']
                         for i in range(1, len(equity))])
        if np.std(rets) > 0:
            sharpe = (np.mean(rets) * 252 - 0.03) / (np.std(rets) * np.sqrt(252))

    sells = [t for t in trades if t['dir'] == 'S']
    wins = [t for t in sells if t.get('profit', 0) > 0]
    win_rate = len(wins) / len(sells) * 100 if sells else 0
    buys = [t for t in trades if t['dir'] == 'B']
    total_trades = len(buys)

    reason_counts = defaultdict(int)
    for t in sells:
        reason_counts[t.get('reason', '未知')] += 1

    return {
        'name': name,
        'window': window_days,
        'total_return': round(total_return, 2),
        'mdd': round(mdd, 2),
        'sharpe': round(sharpe, 3),
        'win_rate': round(win_rate, 1),
        'trades': total_trades,
        'reasons': dict(reason_counts),
    }


def main():
    print("Loading data...")
    all_data, dates = load_data()
    print(f"Loaded {len(all_data)} stocks, {len(dates)} trading days")
    print()

    windows = [1, 2, 3, 5]
    all_results = []

    for strat_name, strat_info in STRATEGIES.items():
        print(f"=== {strat_name} ===")
        for w in windows:
            label = f"{strat_name} (窗口={w}天)"
            print(f"  Running {label}...")
            result = backtest_with_window(
                all_data, dates,
                strat_info['func'], strat_info['params'],
                strat_name, needs_full=strat_info.get('needs_full', False),
                window_days=w
            )
            result['label'] = label
            all_results.append(result)
            print(f"    -> 收益:{result['total_return']:+.2f}% "
                  f"夏普:{result['sharpe']:.3f} "
                  f"回撤:{result['mdd']:.2f}% "
                  f"交易:{result['trades']}笔 "
                  f"胜率:{result['win_rate']:.1f}%")
        print()

    # 汇总表
    print("=" * 80)
    print(f"{'策略':<12} {'窗口':>4} {'收益%':>8} {'夏普':>6} {'回撤%':>6} {'交易数':>6} {'胜率%':>6} {'卖出原因'}")
    print("-" * 80)
    for r in all_results:
        reasons_str = ' | '.join(f"{k}:{v}" for k, v in r['reasons'].items())
        print(f"{r['name']:<12} {r['window']:>4}天 {r['total_return']:>+8.2f} {r['sharpe']:>6.3f} "
              f"{r['mdd']:>6.2f} {r['trades']:>6} {r['win_rate']:>6.1f} {reasons_str}")

    print()
    print("结论：")
    # 找每个策略的最优窗口
    for strat_name in STRATEGIES:
        strat_results = [r for r in all_results if r['name'] == strat_name]
        best = max(strat_results, key=lambda x: x['total_return'])
        print(f"  {strat_name}: 最优窗口={best['window']}天 (收益{best['total_return']:+.2f}%)")


if __name__ == '__main__':
    main()
