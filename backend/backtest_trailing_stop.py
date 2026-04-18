#!/usr/bin/env python3
"""
QuantWeave — 止盈方案对比回测

对比 2策略（双均线 + 回调企稳）在不同止盈方案下的表现：
  A. 基准：固定止盈+15%（当前方案）
  B. 移动止盈v1：赚5%启动跟踪（回撤3%卖）→ 赚10%（回撤2%）→ 赚20%（回撤1.5%）
  C. 移动止盈v2：赚3%启动跟踪（回撤2%卖）→ 赚8%（回撤1.5%）→ 赚15%（回撤1%）
  D. 移动止盈v3：赚5%启动（回撤5%卖）→ 赚15%（回撤3%）→ 赚30%（回撤2%）
  E. 无止盈（只靠止损-8%和策略卖出信号）

使用方式:
    cd /Users/liujianyu/WorkBuddy/Claw/quant-platform/backend
    /opt/anaconda3/envs/quant-platform/bin/python backtest_trailing_stop.py
"""
import sqlite3, numpy as np, json, sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / 'app' / 'services' / 'strategy'))
from core_signals import CORE_STRATEGIES, signals_dual_ma, signals_pullback_stable

DB_PATH = 'quantweave.db'
START_DATE = '20240415'
END_DATE = '20260414'
INITIAL_CAPITAL = 1000000
MAX_POSITIONS = 10
POSITION_PER_STOCK = 0.2
STOP_LOSS = -0.08
SLIPPAGE = 0.001
COMMISSION = 0.0003


# ============================================================
# 止盈方案定义
# ============================================================
class FixedTakeProfit:
    """方案A：固定止盈"""
    name = "A.固定止盈15%"
    def __init__(self, threshold=0.15):
        self.threshold = threshold
    def init_position(self, code, buy_price, buy_date):
        return {'peak_price': buy_price}
    def check_sell(self, pos, current_price, date):
        pnl = (current_price - pos['cp']) / pos['cp']
        if pnl >= self.threshold:
            return True, '止盈'
        if current_price > pos['state']['peak_price']:
            pos['state']['peak_price'] = current_price
        return False, None


class TrailingStop:
    """移动止盈（多级递进）"""
    def __init__(self, name, levels):
        """
        levels: [(profit_threshold, trailing_pct), ...]
        e.g. [(0.05, 0.03), (0.10, 0.02), (0.20, 0.015)]
        表示：赚5%后回撤3%卖 → 赚10%后回撤2%卖 → 赚20%后回撤1.5%卖
        """
        self._name = name
        self.levels = sorted(levels, key=lambda x: x[0])
        self.min_lock = self.levels[0][0]  # 最低锁定利润

    @property
    def name(self):
        return self._name

    def init_position(self, code, buy_price, buy_date):
        return {'peak_price': buy_price, 'activated': False, 'current_level': 0, 'trailing_stop_price': None}

    def check_sell(self, pos, current_price, date):
        pnl = (current_price - pos['cp']) / pos['cp']
        state = pos['state']

        # 更新最高价
        if current_price > state['peak_price']:
            state['peak_price'] = current_price

        # 找到当前适用的级别
        applicable_level = None
        for threshold, trailing_pct in self.levels:
            if pnl >= threshold:
                applicable_level = (threshold, trailing_pct)

        if applicable_level is None:
            return False, None

        threshold, trailing_pct = applicable_level

        # 计算跟踪止损价
        # 从最高价回撤 trailing_pct
        peak_pnl = (state['peak_price'] - pos['cp']) / pos['cp']
        # 跟踪止损价 = 最高价 * (1 - trailing_pct)
        trailing_price = state['peak_price'] * (1 - trailing_pct)

        # 最低保护价 = 买入价 * (1 + min_lock / 2)，至少锁定一半的最低级别利润
        protect_price = pos['cp'] * (1 + self.min_lock * 0.5)

        actual_stop = max(trailing_price, protect_price)

        if current_price <= actual_stop:
            reason = f'跟踪止盈(赚{pnl*100:.1f}%)'
            return True, reason

        return False, None


class NoTakeProfit:
    """方案E：无止盈，只靠止损和策略卖出"""
    name = "E.无止盈(仅止损+策略卖)"
    def init_position(self, code, buy_price, buy_date):
        return {'peak_price': buy_price}
    def check_sell(self, pos, current_price, date):
        if current_price > pos['state']['peak_price']:
            pos['state']['peak_price'] = current_price
        return False, None


# ============================================================
# 定义5种止盈方案
# ============================================================
PROFIT_SCHEMES = [
    FixedTakeProfit(0.15),
    TrailingStop("B.移动止盈v1(5%/3%→10%/2%→20%/1.5%)",
                 [(0.05, 0.03), (0.10, 0.02), (0.20, 0.015)]),
    TrailingStop("C.移动止盈v2(3%/2%→8%/1.5%→15%/1%)",
                 [(0.03, 0.02), (0.08, 0.015), (0.15, 0.01)]),
    TrailingStop("D.移动止盈v3(5%/5%→15%/3%→30%/2%)",
                 [(0.05, 0.05), (0.15, 0.03), (0.30, 0.02)]),
    NoTakeProfit(),
]


# ============================================================
# 数据加载
# ============================================================
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


# ============================================================
# 回测引擎（支持不同止盈方案）
# ============================================================
def backtest_with_scheme(all_data, dates, signal_func, params, scheme, name=""):
    stock_list = list(all_data.keys())
    all_sigs = {}
    for code in stock_list:
        sigs = signal_func(all_data[code], dates, params)
        if sigs: all_sigs[code] = sigs

    cash = INITIAL_CAPITAL
    positions = {}
    pv = INITIAL_CAPITAL
    equity = []
    trades = []

    for date in sorted(dates):
        # 检查卖出条件
        to_sell = []
        for code, pos in list(positions.items()):
            if code in all_data and date in all_data[code]:
                pr = all_data[code][date]['close']
                pnl = (pr - pos['cp']) / pos['cp']

                # 止损（固定-8%）
                if pnl <= STOP_LOSS:
                    to_sell.append((code, pr, '止损'))
                    continue

                # 止盈方案检查
                sold, reason = scheme.check_sell(pos, pr, date)
                if sold:
                    to_sell.append((code, pr, reason))

        # 执行卖出
        for code, pr, reason in to_sell:
            pos = positions.pop(code)
            sa = pos['shares'] * pr * (1 - SLIPPAGE)
            cm = sa * COMMISSION
            cash += sa - cm
            profit = (pr - pos['cp']) * pos['shares'] - cm - pos['shares'] * pos['cp'] * COMMISSION
            trades.append({'dir': 'S', 'code': code, 'price': pr, 'vol': pos['shares'],
                         'profit': profit, 'reason': reason, 'date': date})

        # 买入
        ne = MAX_POSITIONS - len(positions)
        if ne > 0:
            cands = []
            for code in stock_list:
                if code in positions:
                    continue
                if code in all_sigs and date in all_sigs[code] and all_sigs[code][date] == 'buy':
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
                    state = scheme.init_position(code, pr, date)
                    positions[code] = {'shares': sh, 'cp': pr, 'bd': date, 'state': state}
                    trades.append({'dir': 'B', 'code': code, 'price': pr, 'vol': sh,
                                 'profit': 0, 'reason': '策略信号', 'date': date})

        # 策略卖出信号
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

        # 净值
        posv = sum(pos['shares'] * all_data[code][date]['close']
                   for code, pos in positions.items()
                   if code in all_data and date in all_data[code])
        pv = cash + posv
        equity.append({'date': date, 'value': round(pv, 2)})

    # 期末清仓
    ld = sorted(dates)[-1]
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

    # 统计指标
    tr = (pv - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100
    nd = len(dates)
    ar = tr / (nd / 252) if nd else 0

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

    sells = [t for t in trades if t['dir'] == 'S' and t['reason'] != '期末清仓']
    wins = [t for t in sells if t.get('profit', 0) > 0]
    wr = len(wins) / len(sells) * 100 if sells else 0

    # 卖出原因统计
    sell_reasons = {}
    for t in sells:
        r = t['reason']
        if '跟踪止盈' in r:
            r = '跟踪止盈'
        sell_reasons[r] = sell_reasons.get(r, 0) + 1

    # 盈亏分布
    profits = [t['profit'] for t in sells]
    avg_profit = np.mean(profits) if profits else 0
    max_win = max(profits) if profits else 0
    max_loss = min(profits) if profits else 0

    wp = [t['profit'] for t in sells if t.get('profit', 0) > 0]
    lp = [-t['profit'] for t in sells if t.get('profit', 0) < 0]
    aw = np.mean(wp) if wp else 0
    al = np.mean(lp) if lp else 1
    plr = aw / al if al > 0 else 0

    return {
        'scheme': scheme.name,
        'total_return': round(tr, 2),
        'annual_return': round(ar, 2),
        'max_drawdown': round(mdd, 2),
        'sharpe_ratio': round(float(sharpe), 4),
        'win_rate': round(wr, 1),
        'profit_loss_ratio': round(float(plr), 2),
        'total_trades': len(trades),
        'sell_count': len(sells),
        'sell_reasons': sell_reasons,
        'avg_profit': round(float(avg_profit), 2),
        'max_win': round(float(max_win), 2),
        'max_loss': round(float(max_loss), 2),
        'final_value': round(pv, 2),
        'equity_curve': equity,
        'trades': trades,
    }


# ============================================================
# 生成对比报告
# ============================================================
def generate_report(all_results, stock_names):
    css = """body{font-family:'Plus Jakarta Sans',system-ui,sans-serif;background:#f8fafc;color:#1e293b;margin:0;padding:20px}
h1{text-align:center;color:#0f172a;margin-bottom:5px}
.subtitle{text-align:center;color:#64748b;margin-bottom:30px}
.card{background:white;border-radius:12px;padding:20px;margin:15px 0;box-shadow:0 1px 3px rgba(0,0,0,0.1)}
table{width:100%;border-collapse:collapse;margin:10px 0}
th{background:#f1f5f9;padding:10px;text-align:left;font-size:13px;color:#475569;border-bottom:2px solid #e2e8f0}
td{padding:8px 10px;border-bottom:1px solid #f1f5f9;font-size:13px}
tr:hover td{background:#f8fafc}
.best{background:#ecfdf5;font-weight:600;color:#059669}
.tag{display:inline-block;padding:2px 8px;border-radius:4px;font-size:11px;margin:2px}
.tag-stop{background:#fef2f2;color:#dc2626}
.tag-take{background:#ecfdf5;color:#059669}
.tag-strategy{background:#eff6ff;color:#2563eb}
.tag-trail{background:#fefce8;color:#ca8a04}
.bar{height:20px;border-radius:3px;display:flex;align-items:center;padding-left:8px;font-size:11px;color:white;font-weight:600}
.bar-green{background:linear-gradient(90deg,#059669,#10b981)}
.bar-red{background:linear-gradient(90deg,#dc2626,#ef4444)}"""

    html_parts = []
    html_parts.append(f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>QuantWeave 止盈方案对比回测</title>
<style>
{css}
</style>
</head>
<body>
<h1>📊 止盈方案对比回测</h1>
<div class="subtitle">双均线(7/60) + 回调企稳 | {START_DATE} ~ {END_DATE} | 100万初始资金</div>""")

    for strategy_name, scheme_results in all_results.items():
        html_parts.append(f'<div class="card"><h2>策略：{strategy_name}</h2>')

        # 汇总对比表
        html_parts.append("""<table>
<tr><th>止盈方案</th><th>总收益</th><th>年化</th><th>夏普</th><th>回撤</th><th>胜率</th>
<th>盈亏比</th><th>交易数</th><th>卖出次数</th></tr>""")

        # 找出每个指标的最佳值
        best_return = max(r['total_return'] for r in scheme_results)
        best_sharpe = max(r['sharpe_ratio'] for r in scheme_results)
        best_mdd = min(r['max_drawdown'] for r in scheme_results)
        best_wr = max(r['win_rate'] for r in scheme_results)

        for r in scheme_results:
            ret_cls = ' class="best"' if r['total_return'] == best_return else ''
            sh_cls = ' class="best"' if r['sharpe_ratio'] == best_sharpe else ''
            dd_cls = ' class="best"' if r['max_drawdown'] == best_mdd else ''
            wr_cls = ' class="best"' if r['win_rate'] == best_wr else ''

            html_parts.append(f"""<tr>
<td>{r['scheme']}</td>
<td{ret_cls}>{r['total_return']:+.2f}%</td>
<td>{r['annual_return']:+.2f}%</td>
<td{sh_cls}>{r['sharpe_ratio']:.3f}</td>
<td{dd_cls}>{r['max_drawdown']:.2f}%</td>
<td{wr_cls}>{r['win_rate']:.1f}%</td>
<td>{r['profit_loss_ratio']:.2f}</td>
<td>{r['total_trades']}</td>
<td>{r['sell_count']}</td>
</tr>""")
        html_parts.append("</table>")

        # 卖出原因对比
        html_parts.append('<h3>卖出原因分布</h3><table><tr><th>方案</th>')
        all_reasons = set()
        for r in scheme_results:
            all_reasons.update(r['sell_reasons'].keys())
        for reason in sorted(all_reasons):
            html_parts.append(f'<th>{reason}</th>')
        html_parts.append('</tr>')
        for r in scheme_results:
            html_parts.append(f'<tr><td>{r["scheme"]}</td>')
            for reason in sorted(all_reasons):
                cnt = r['sell_reasons'].get(reason, 0)
                cls = ''
                if '止盈' in reason or '跟踪' in reason:
                    cls = 'tag-take'
                elif '止损' in reason:
                    cls = 'tag-stop'
                elif '策略' in reason:
                    cls = 'tag-strategy'
                html_parts.append(f'<td><span class="tag {cls}">{cnt}</span></td>')
            html_parts.append('</tr>')
        html_parts.append('</table>')

        # 收益对比柱状图（CSS实现）
        html_parts.append('<h3>收益对比</h3>')
        max_ret = max(abs(r['total_return']) for r in scheme_results)
        for r in scheme_results:
            pct = abs(r['total_return']) / max_ret * 100 if max_ret > 0 else 0
            bar_cls = 'bar-green' if r['total_return'] >= 0 else 'bar-red'
            html_parts.append(
                f'<div style="margin:5px 0"><span style="font-size:12px;color:#64748b;width:280px;display:inline-block">'
                f'{r["scheme"]}</span>'
                f'<div class="bar {bar_cls}" style="width:{max(pct,5)}%">{r["total_return"]:+.2f}%</div></div>'
            )

        html_parts.append('</div>')

    html_parts.append('</body></html>')

    output = '\n'.join(html_parts)
    report_path = 'reports/trailing_stop_comparison.html'
    Path('reports').mkdir(parents=True, exist_ok=True)
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(output)
    return report_path


# ============================================================
# Main
# ============================================================
if __name__ == '__main__':
    print("=" * 70)
    print("📊 QuantWeave — 止盈方案对比回测")
    print(f"策略: 双均线(7/60) + 回调企稳(8/95/5)")
    print(f"区间: {START_DATE} ~ {END_DATE}")
    print(f"止盈方案: {len(PROFIT_SCHEMES)}种")
    print("=" * 70)

    all_data, stock_names = load_all_data()

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(f"SELECT DISTINCT trade_date FROM stock_daily WHERE trade_date>='{START_DATE}' AND trade_date<='{END_DATE}' ORDER BY trade_date")
    dates = [r[0] for r in cur.fetchall()]
    conn.close()
    print(f"交易日数: {len(dates)}\n")

    # 只测2个策略
    STRATEGIES = [
        ('dual_ma', '双均线交叉(7/60)', _adapter_close_only(signals_dual_ma)),
        ('pullback_stable', '强势股回调企稳(8/95/5)', _adapter_full(signals_pullback_stable)),
    ]

    all_results = {}

    for key, strat_name, signal_func in STRATEGIES:
        cfg = CORE_STRATEGIES[key]
        params = cfg['default_params']
        print(f"\n{'='*70}")
        print(f"策略: {strat_name}")
        print(f"{'='*70}")

        scheme_results = []
        for scheme in PROFIT_SCHEMES:
            print(f"\n  方案: {scheme.name}")
            result = backtest_with_scheme(all_data, dates, signal_func, params, scheme, strat_name)
            scheme_results.append(result)
            print(f"  => 收益:{result['total_return']:+.2f}% 夏普:{result['sharpe_ratio']:.3f} "
                  f"回撤:{result['max_drawdown']:.2f}% 交易:{result['total_trades']} "
                  f"胜率:{result['win_rate']:.1f}% 卖出:{result['sell_reasons']}")

        all_results[strat_name] = scheme_results

    # 汇总打印
    print(f"\n{'='*70}")
    print("📊 止盈方案对比汇总")
    print(f"{'='*70}")
    for strat_name, scheme_results in all_results.items():
        print(f"\n【{strat_name}】")
        print(f"{'方案':<40} {'收益':>10} {'夏普':>8} {'回撤':>8} {'胜率':>8} {'卖出原因'}")
        print("-" * 100)
        for r in scheme_results:
            reasons_str = ' | '.join(f'{k}:{v}' for k, v in r['sell_reasons'].items())
            print(f"{r['scheme']:<40} {r['total_return']:>+9.2f}% {r['sharpe_ratio']:>8.3f} "
                  f"{r['max_drawdown']:>7.2f}% {r['win_rate']:>7.1f}% {reasons_str}")

    # 生成报告
    report_path = generate_report(all_results, stock_names)
    print(f"\n📊 HTML报告: {report_path}")

    # 保存JSON
    json_data = {}
    for strat_name, scheme_results in all_results.items():
        json_data[strat_name] = []
        for r in scheme_results:
            json_data[strat_name].append({
                k: v for k, v in r.items()
                if k not in ('equity_curve', 'trades')
            })
    json_path = 'reports/trailing_stop_comparison.json'
    with open(json_path, 'w') as f:
        json.dump(json_data, f, ensure_ascii=False, indent=2, default=str)
    print(f"💾 JSON: {json_path}")
