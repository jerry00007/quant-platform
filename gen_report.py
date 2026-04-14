#!/usr/bin/env python3
"""读取 backtest_results.json → 生成可视化 HTML 报告"""
import json, os
import numpy as np

BASE = os.path.dirname(__file__) or "."
with open(os.path.join(BASE, "backtest_results.json"), "r") as f:
    R = json.load(f)

STOCKS = {"600519.SH":"贵州茅台","000858.SZ":"五粮液","601318.SH":"中国平安",
    "600036.SH":"招商银行","000001.SZ":"平安银行","000333.SZ":"美的集团",
    "601398.SH":"工商银行","000651.SZ":"格力电器"}
STRATS = {"dual_ma":"双均线交叉","bollinger":"布林带突破","rsi":"RSI超买超卖",
    "macd":"MACD金叉死叉","chip":"主力筹码","enhanced_chip":"增强筹码",
    "pullback_stable":"强势股回调企稳"}

# ---- 策略汇总 ----
summary = {}
for sk, sn in STRATS.items():
    rets, shar = [], []
    for sr in R.values():
        if sk in sr and "error" not in sr[sk]:
            rets.append(sr[sk]["total_return"])
            shar.append(sr[sk]["sharpe_ratio"])
    if rets:
        summary[sk] = {"name":sn, "avg":round(float(np.mean(rets)),2),
            "max":round(float(np.max(rets)),2), "min":round(float(np.min(rets)),2),
            "sharpe":round(float(np.mean(shar)),3) if shar else 0}

ranked = sorted(summary.items(), key=lambda x: x[1]["avg"], reverse=True)
cards = ""
for rank, (sk, sd) in enumerate(ranked, 1):
    medal = ["🥇","🥈","🥉"][rank-1] if rank<=3 else f"#{rank}"
    c = "#cf1322" if sd["avg"]>0 else "#3f8600"
    cards += f'<div style="flex:1;min-width:170px;background:#fff;border-radius:12px;padding:18px;border:1px solid #e8e8e8;box-shadow:0 2px 8px rgba(0,0,0,.06)"><div style="font-size:22px">{medal}</div><div style="font-size:15px;font-weight:700;margin:6px 0">{sd["name"]}</div><div style="font-size:26px;color:{c};font-weight:700">{sd["avg"]:+.2f}%</div><div style="font-size:11px;color:#888;margin-top:6px">平均夏普:{sd["sharpe"]:.3f}<br>最佳:{sd["max"]:+.2f}% 最差:{sd["min"]:+.2f}%</div></div>'

# ---- 表格 ----
shdr = "".join(f'<th style="min-width:120px">{STRATS[k]}</th>' for k in STRATS)
rows = ""
for sc, sn in STOCKS.items():
    sr = R.get(sc, {})
    br, bn = -999, ""
    for sk, res in sr.items():
        if "error" not in res and res["total_return"]>br: br=res["total_return"];bn=STRATS[sk]
    cr = "#cf1322" if br>0 else "#3f8600"
    cells = f'<td><b>{sn}</b><br><span style="color:#888;font-size:11px">{sc}</span></td>'
    cells += f'<td style="color:{cr};font-weight:700">{br:+.2f}%</td><td>{bn}</td>'
    for sk in STRATS:
        res = sr.get(sk, {})
        if "error" in res or not res:
            cells += '<td style="color:#999">-</td>'
        else:
            ret=res["total_return"];sha=res["sharpe_ratio"];dd=res["max_drawdown"]
            wr=res["win_rate"];tn=res["total_trades"]
            cc="#cf1322" if ret>0 else "#3f8600"
            bg="#fff1f0" if ret>5 else ("#f6ffed" if ret<-5 else "#fff")
            cells += f'<td style="background:{bg}"><span style="color:{cc};font-weight:700">{ret:+.2f}%</span><br><span style="font-size:10px;color:#666">夏普{sha:.2f} 回撤{dd:.1f}%<br>胜率{wr:.0f}% {tn}笔</span></td>'
    rows += f'<tr>{cells}</tr>\n'

# ---- 净值曲线 ----
ecd = {}
for sc, sn in STOCKS.items():
    sr = R.get(sc, {}); ds = []
    for sk, sname in STRATS.items():
        res = sr.get(sk, {})
        if "error" in res or not res or not res.get("equity_curve"): continue
        ec = res["equity_curve"]
        vals = [e["v"] for e in ec]; init = vals[0] if vals else 1e6
        ds.append({"label":sname, "values":[v/init*100 for v in vals], "dates":[e["date"] for e in ec]})
    if ds: ecd[sc] = {"name":sn, "datasets":ds}

chart_html = ""
ci = 0
for sc, info in ecd.items():
    chart_html += f'<div style="background:#fff;border-radius:12px;padding:16px;border:1px solid #eee"><div style="font-weight:600;margin-bottom:8px">{info["name"]}({sc})</div><canvas id="ch{ci}" height="220"></canvas></div>'
    ci += 1

colors = ['#cf1322','#52c41a','#faad14','#1890ff','#722ed1','#eb2f96','#13c2c2']
chart_js = ""
ci = 0
for sc, info in ecd.items():
    longest = max(info["datasets"], key=lambda d:len(d["dates"]))
    labels = [d[4:6]+"-"+d[6:8] if len(d)==8 else d for d in longest["dates"]]
    dss = ""
    for di, ds in enumerate(info["datasets"]):
        c = colors[di%len(colors)]
        dss += f"{{label:'{ds['label']}',data:{json.dumps(ds['values'])},borderColor:'{c}',backgroundColor:'{c}22',borderWidth:1.5,pointRadius:0,fill:false,tension:.3}},"
    lbl_json = json.dumps(labels)
    chart_js += (
        "new Chart(document.getElementById('ch" + str(ci) + "'),"
        "{type:'line',"
        "data:{labels:" + lbl_json + ",datasets:[" + dss + "]},"
        "options:{responsive:true,"
        "interaction:{mode:'index',intersect:false},"
        "plugins:{legend:{position:'bottom',labels:{boxWidth:12,font:{size:11}}}},"
        "scales:{"
        "x:{ticks:{maxTicksLimit:12,font:{size:10}}},"
        "y:{title:{display:true,text:'净值(%)'}}"
        "}}});\n"
    )
    ci += 1

import datetime
now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>QuantWeave 全策略回测报告</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'SF Pro Display','Plus Jakarta Sans',-apple-system,sans-serif;background:#f7f8fa;color:#1a1a2e;padding:20px}}
.C{{max-width:1400px;margin:0 auto}}
h1{{font-size:28px;font-weight:700;margin-bottom:4px}}
.sub{{color:#888;font-size:14px;margin-bottom:24px}}
.card{{background:#fff;border-radius:16px;padding:24px;box-shadow:0 2px 12px rgba(0,0,0,.06);margin-bottom:20px}}
.flex{{display:flex;gap:16px;flex-wrap:wrap}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th{{background:#fafafa;padding:10px 8px;text-align:center;border-bottom:2px solid #e8e8e8;font-weight:600;white-space:nowrap}}
td{{padding:10px 8px;text-align:center;border-bottom:1px solid #f0f0f0;vertical-align:top}}
tr:hover{{background:#fafafa}}
.g2{{display:grid;grid-template-columns:1fr 1fr;gap:20px}}
@media(max-width:900px){{.g2{{grid-template-columns:1fr}}}}
.st{{font-size:18px;font-weight:600;margin-bottom:16px;padding-left:12px;border-left:4px solid #52c41a}}
</style></head><body>
<div class="C">
<div style="text-align:center;margin-bottom:32px">
<h1>📊 QuantWeave 全策略回测报告</h1>
<p class="sub">2024-01-01 ~ 2025-04-10 | 8只股票 × 7种策略 | 初始¥100万 | Tushare Pro | {now}</p>
</div>
<div class="card"><div class="st">🏆 策略排名（按平均收益率）</div><div class="flex">{cards}</div></div>
<div class="card"><div class="st">📋 逐股逐策略明细</div><div style="overflow-x:auto"><table>
<tr><th>股票</th><th>最佳收益</th><th>最佳策略</th>{shdr}</tr>{rows}</table></div></div>
<div class="card"><div class="st">📈 净值曲线对比</div><div class="g2">{chart_html}</div></div>
<div class="card" style="text-align:center;color:#888;font-size:12px">QuantWeave 量化交易平台 | 数据:Tushare Pro | 策略:双均线/布林/RSI/MACD + 主力筹码/增强筹码 + 强势股回调企稳(通达信迁移)</div>
</div><script>{chart_js}</script></body></html>"""

out = os.path.join(BASE, "backtest-report.html")
with open(out, "w", encoding="utf-8") as f: f.write(html)
print(f"✅ 报告 → {out}")
