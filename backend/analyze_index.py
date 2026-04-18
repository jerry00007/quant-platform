#!/usr/bin/env python3
"""指数技术分析"""
import os, sys, json, requests, numpy as np
from dotenv import load_dotenv
sys.path.insert(0, os.path.dirname(__file__))
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

def get_index_kline(code):
    prefix = 'sh' if code in ('000001','000688') else 'sz'
    url = f'https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={prefix}{code}&scale=240&ma=no&datalen=60'
    headers = {'Referer': 'https://finance.sina.com.cn', 'User-Agent': 'Mozilla/5.0'}
    r = requests.get(url, headers=headers, timeout=10)
    if r.status_code == 200 and r.text.strip():
        return json.loads(r.text)
    return None

# 实时行情
def get_realtime():
    codes = 's_sh000001,s_sz399001,s_sz399006,s_sh000688'
    url = f'https://hq.sinajs.cn/list={codes}'
    headers = {'Referer': 'https://finance.sina.com.cn', 'User-Agent': 'Mozilla/5.0'}
    r = requests.get(url, headers=headers, timeout=10)
    return r.text

index_map = {'000001':'上证指数','399001':'深证成指','399006':'创业板指','000688':'科创50'}

# 先拿实时行情
print("=" * 60)
print("📊 四大指数实时行情（今日收盘）")
print("=" * 60)
rt = get_realtime()
for line in rt.strip().split('\n'):
    if 'hq_str_' in line:
        parts = line.split('"')[1].split(',')
        if len(parts) >= 4:
            print(f"  {parts[0]}: {parts[1]}  涨跌幅:{parts[3]}%")
print()

# 技术分析
results = {}
for code, name in index_map.items():
    data = get_index_kline(code)
    if not data:
        print(f"{name}: 获取K线失败")
        continue
    
    closes = np.array([float(d['close']) for d in data])
    dates = [d['day'] for d in data]
    n = len(closes)
    
    ma5 = np.mean(closes[-5:])
    ma10 = np.mean(closes[-10:])
    ma20 = np.mean(closes[-20:])
    ma60 = np.mean(closes[-60:]) if n >= 60 else np.mean(closes)
    
    chg = (closes[-1]/closes[-2]-1)*100
    chg5 = (closes[-1]/closes[-6]-1)*100 if n>=6 else 0
    chg20 = (closes[-1]/closes[-21]-1)*100 if n>=21 else 0
    chg60 = (closes[-1]/closes[0]-1)*100
    
    diffs = np.diff(closes[-15:])
    gains = np.where(diffs>0,diffs,0)
    losses = np.where(diffs<0,-diffs,0)
    avg_g = np.mean(gains[-14:])
    avg_l = np.mean(losses[-14:])
    rsi = 100 - 100/(1 + avg_g/max(avg_l, 0.01))
    
    dev5 = (closes[-1]/ma5-1)*100
    dev20 = (closes[-1]/ma20-1)*100
    dev60 = (closes[-1]/ma60-1)*100
    
    vols = np.array([float(d.get('volume',1)) for d in data])
    vol_ratio = vols[-1]/np.mean(vols[-6:-1]) if n>=6 else 1
    
    if n >= 22:
        c20 = closes[-21:]
        rets = np.diff(c20) / c20[:-1]
        vol20 = np.std(rets)*np.sqrt(250)*100
    else:
        vol20 = 0
    
    # 均线排列
    if ma5 > ma10 > ma20 > ma60:
        ma_status = "多头排列(强)"
    elif ma5 > ma10 > ma20:
        ma_status = "短多中多"
    elif ma5 > ma10:
        ma_status = "短多"
    elif ma5 < ma10 < ma20 < ma60:
        ma_status = "空头排列(弱)"
    elif ma5 < ma10 < ma20:
        ma_status = "短空中空"
    else:
        ma_status = "震荡"
    
    results[name] = {
        'close': closes[-1], 'date': dates[-1],
        'chg': chg, 'chg5': chg5, 'chg20': chg20, 'chg60': chg60,
        'ma5': ma5, 'ma10': ma10, 'ma20': ma20, 'ma60': ma60,
        'rsi': rsi, 'vol_ratio': vol_ratio, 'vol20': vol20,
        'dev5': dev5, 'dev20': dev20, 'dev60': dev60,
        'ma_status': ma_status
    }
    
    print(f"{'='*50}")
    print(f"📈 {name}")
    print(f"{'='*50}")
    print(f"  收盘:{closes[-1]:.2f} 今日:{chg:+.2f}%")
    print(f"  5日:{chg5:+.2f}%  20日:{chg20:+.2f}%  60日:{chg60:+.2f}%")
    print(f"  MA5:{ma5:.2f} MA10:{ma10:.2f} MA20:{ma20:.2f} MA60:{ma60:.2f}")
    print(f"  均线排列: {ma_status}")
    print(f"  RSI(14): {rsi:.1f}  量比: {vol_ratio:.2f}  波动率: {vol20:.1f}%")
    print(f"  偏离MA5:{dev5:+.2f}% MA20:{dev20:+.2f}% MA60:{dev60:+.2f}%")
    print(f"  近10日:")
    for i in range(-10, 0):
        dc = (closes[i]/closes[i-1]-1)*100
        flag = "🔴" if dc > 0 else "🟢"
        print(f"    {dates[i]} {closes[i]:.2f} {flag}{dc:+.2f}%")
    print()

# 综合风险判断
print("=" * 60)
print("⚠️ 综合风险评估")
print("=" * 60)

risk_score = 0
reasons = []

for name, r in results.items():
    # RSI超买
    if r['rsi'] > 70:
        risk_score += 2
        reasons.append(f"⚠️ {name} RSI={r['rsi']:.1f} 超买区(>70)")
    elif r['rsi'] > 60:
        risk_score += 1
        reasons.append(f"⚡ {name} RSI={r['rsi']:.1f} 偏高")
    
    # 偏离均线过远
    if r['dev20'] > 5:
        risk_score += 2
        reasons.append(f"⚠️ {name} 偏离MA20达{r['dev20']:+.1f}% 过远")
    elif r['dev20'] > 3:
        risk_score += 1
    
    # 短期涨幅过大
    if r['chg5'] > 5:
        risk_score += 2
        reasons.append(f"⚠️ {name} 5日涨{r['chg5']:+.1f}% 过猛")
    elif r['chg5'] > 3:
        risk_score += 1
    
    # 量能异常
    if r['vol_ratio'] > 2:
        reasons.append(f"⚡ {name} 量比{r['vol_ratio']:.1f} 放量明显")

for reason in reasons:
    print(f"  {reason}")

print()
if risk_score >= 8:
    print("🔴 风险等级: 高风险 — 建议减仓/防守")
elif risk_score >= 5:
    print("🟡 风险等级: 中等偏高 — 可适度减仓，保留底仓")
elif risk_score >= 3:
    print("🟢 风险等级: 中等 — 持仓观望，注意止盈")
else:
    print("✅ 风险等级: 低 — 可继续持有")

print()
print("📝 操作建议:")
if risk_score >= 5:
    print("  1. 短期涨幅偏大，建议将仓位降至5-6成")
    print("  2. 已盈利个股：设置跟踪止盈，别让利润回吐")
    print("  3. 新开仓需谨慎，等待回调确认后再进")
    print("  4. 关注北向资金动向和大盘成交量变化")
elif risk_score >= 3:
    print("  1. 可维持当前仓位，设置好止盈止损")
    print("  2. 关注MA20支撑，破位需警惕")
    print("  3. 新仓可选强势板块回踩机会")
else:
    print("  1. 市场健康，可正常操作")
    print("  2. 继续执行策略信号，纪律优先")
