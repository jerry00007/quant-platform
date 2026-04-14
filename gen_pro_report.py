#!/usr/bin/env python3
"""QuantWeave 专业级回测报告生成器 v3.0
读取 advanced_full_data.json，生成交互式 HTML 报告
"""
import json, os, datetime

def gen_report(data_path="advanced_full_data.json", output_path="pro-backtest-report.html"):
    base = os.path.dirname(__file__) or "."
    with open(os.path.join(base, data_path), "r", encoding="utf-8") as f:
        data = json.load(f)

    all_res = data.get("all_results", {})
    wf = data.get("wf_results", {})
    mc = data.get("mc_results", {})
    port = data.get("portfolio", {})
    ranking = data.get("ranking", [])

    STOCKS = {"600519.SH":"贵州茅台","000858.SZ":"五粮液","601318.SH":"中国平安",
        "600036.SH":"招商银行","000001.SZ":"平安银行","000333.SZ":"美的集团",
        "601398.SH":"工商银行","000651.SZ":"格力电器"}

    # 策略排名表
    rank_rows = ""
    for r in ranking:
        sk, s = r
        wf_str = f"{s['wf_ratio']:.2f}" if isinstance(s.get('wf_ratio'), (int,float)) else str(s.get('wf_ratio','N/A'))
        overfit = "⚠️ 过拟合" if s.get('is_overfit') else "✅ 稳健"
        rank_rows += f"""<tr>
            <td>{s.get('composite_score',0)}</td>
            <td><b>{s['strategy']}</b></td>
            <td class="{'positive' if s['avg_return']>0 else 'negative'}">{s['avg_return']:+.2f}%</td>
            <td>{s['positive_rate']:.0f}%</td>
            <td>{wf_str}</td>
            <td>{overfit}</td>
            <td>{s.get('mc_positive_prob',0):.0f}%</td>
            <td>{s.get('mc_p95_mdd',0):.1f}%</td>
        </tr>"""

    # 每只股票详情卡
    stock_cards = ""
    for sc, sn in STOCKS.items():
        sr = all_res.get(sc, {})
        if not sr: continue
        best_ret, best_name = -999, ""
        strat_rows = ""
        for sk, r in sr.items():
            if "total_return" not in r: continue
            if r["total_return"] > best_ret: best_ret = r["total_return"]; best_name = r.get("strategy", sk)
            ret_cls = "positive" if r["total_return"]>0 else "negative"
            strat_rows += f"""<tr>
                <td><b>{r.get('strategy',sk)}</b></td>
                <td class="{ret_cls}">{r['total_return']:+.2f}%</td>
                <td>{r.get('annual_return',0):.2f}%</td>
                <td>{r.get('sharpe',0):.3f}</td>
                <td>{r.get('sortino',0):.3f}</td>
                <td>{r.get('calmar',0):.3f}</td>
                <td>{r.get('max_drawdown',0):.2f}%</td>
                <td>{r.get('var95',0):.3f}%</td>
                <td>{r.get('cvar95',0):.3f}%</td>
                <td>{r.get('ulcer',0):.3f}</td>
                <td>{r.get('win_rate',0):.1f}%</td>
                <td>{r.get('profit_loss_ratio',0):.2f}</td>
            </tr>"""
        ret_cls = "positive" if best_ret>0 else "negative"
        # 权益曲线数据
        ec_data = {}
        for sk, r in sr.items():
            if "equity_curve" in r:
                ec_data[sk] = r["equity_curve"]
        ec_json = json.dumps(ec_data, ensure_ascii=False)
        card_id = sc.replace(".", "_")
        stock_cards += f"""
        <div class="card" id="card_{card_id}">
            <div class="card-header">
                <h3>{sn} <span class="code">{sc}</span></h3>
                <div class="best">最优: <b>{best_name}</b> <span class="{ret_cls}">{best_ret:+.2f}%</span></div>
            </div>
            <div class="chart-container">
                <canvas id="chart_{card_id}"></canvas>
            </div>
            <div class="table-wrap">
                <table>
                    <thead><tr>
                        <th>策略</th><th>总收益</th><th>年化</th><th>Sharpe</th><th>Sortino</th>
                        <th>Calmar</th><th>最大回撤</th><th>VaR95</th><th>CVaR95</th>
                        <th>Ulcer</th><th>胜率</th><th>盈亏比</th>
                    </tr></thead>
                    <tbody>{strat_rows}</tbody>
                </table>
            </div>
        </div>
        <script>
        (function(){{
            var ctx = document.getElementById('chart_{card_id}').getContext('2d');
            var ecData = {ec_json};
            var datasets = [];
            var colors = ['#10b981','#3b82f6','#f59e0b','#ef4444','#8b5cf6','#06b6d4','#f97316','#ec4899','#84cc16','#6366f1'];
            var ci = 0;
            for (var sk in ecData) {{
                var pts = ecData[sk].map(function(e){{return {{x:e.date,y:e.v}};}});
                datasets.push({{
                    label: sk, data: pts, borderColor: colors[ci%colors.length],
                    borderWidth: 1.5, pointRadius: 0, fill: false, tension: 0.1
                }});
                ci++;
            }}
            new Chart(ctx, {{
                type:'line', data:{{datasets:datasets}},
                options:{{
                    responsive:true, maintainAspectRatio:false,
                    plugins:{{legend:{{position:'bottom',labels:{{boxWidth:12,font:{{size:10}}}}}}}},
                    scales:{{
                        x:{{type:'category',display:true,ticks:{{maxTicksLimit:8,font:{{size:9}}}}}},
                        y:{{ticks:{{callback:function(v){{return (v/10000).toFixed(1)+'万';}},font:{{size:9}}}}}}
                    }}
                }}
            }});
        }})();
        </script>"""

    # Walk-Forward 汇总
    wf_section = ""
    for sk, w in wf.items():
        status = "⚠️ 过拟合" if w.get("is_overfit") else "✅ 稳健"
        wf_section += f"""<div class="wf-item">
            <b>{w.get('strategy',sk)}</b>
            <span>WF比={w.get('avg_wf_ratio','N/A')} {status}</span>
        </div>"""

    # Monte Carlo 汇总（选重要数据）
    mc_section = ""
    mc_count = 0
    for key, m in mc.items():
        mc_count += 1
        if mc_count > 20: break
        parts = key.split("_", 1)
        sc_part = parts[0] if parts else ""
        sk_part = parts[1] if len(parts)>1 else ""
        sn = STOCKS.get(sc_part, sc_part)
        mc_section += f"""<div class="mc-item">
            <b>{sn} | {sk_part}</b>
            <span>MC中位={m.get('mc_median_return',0):+.1f}% P95回撤={m.get('mc_p95_mdd',0):.1f}% 正概率={m.get('positive_prob',0):.0f}%</span>
        </div>"""

    # 组合分析
    port_section = ""
    if port:
        pm = port.get("portfolio_metrics", {})
        port_section = f"""
        <div class="card">
            <h3>组合级分析（等权8股）</h3>
            <div class="port-grid">
                <div class="port-item"><div class="port-label">组合总收益</div>
                    <div class="port-value {'positive' if pm.get('total_return',0)>0 else 'negative'}">{pm.get('total_return','N/A')}%</div></div>
                <div class="port-item"><div class="port-label">组合Sharpe</div>
                    <div class="port-value">{pm.get('sharpe','N/A')}</div></div>
                <div class="port-item"><div class="port-label">组合Sortino</div>
                    <div class="port-value">{pm.get('sortino','N/A')}</div></div>
                <div class="port-item"><div class="port-label">组合Calmar</div>
                    <div class="port-value">{pm.get('calmar','N/A')}</div></div>
                <div class="port-item"><div class="port-label">最大回撤</div>
                    <div class="port-value negative">{pm.get('max_drawdown','N/A')}%</div></div>
                <div class="port-item"><div class="port-label">VaR95</div>
                    <div class="port-value">{pm.get('var95','N/A')}%</div></div>
            </div>
        </div>"""

    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>QuantWeave 专业级回测报告 v3.0</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
:root {{--primary:#10b981;--bg:#f8fafb;--card:#fff;--text:#1e293b;--muted:#64748b;
    --positive:#ef4444;--negative:#22c55e;--border:#e2e8f0;--shadow:0 1px 3px rgba(0,0,0,.08);}}
* {{margin:0;padding:0;box-sizing:border-box;}}
body {{font-family:'Plus Jakarta Sans',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
    background:var(--bg);color:var(--text);line-height:1.6;padding:20px;max-width:1400px;margin:0 auto;}}
h1 {{font-size:28px;font-weight:700;color:var(--text);margin-bottom:8px;}}
h2 {{font-size:20px;font-weight:600;margin:24px 0 12px;padding-bottom:8px;border-bottom:2px solid var(--primary);}}
h3 {{font-size:16px;font-weight:600;margin-bottom:12px;}}
.subtitle {{color:var(--muted);font-size:14px;margin-bottom:24px;}}
.card {{background:var(--card);border-radius:12px;padding:20px;margin-bottom:16px;box-shadow:var(--shadow);border:1px solid var(--border);}}
.card-header {{display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;flex-wrap:wrap;gap:8px;}}
.code {{font-family:'JetBrains Mono',monospace;font-size:12px;color:var(--muted);background:#f1f5f9;padding:2px 8px;border-radius:4px;}}
.best {{font-size:14px;}}
.positive {{color:var(--positive);font-weight:600;}}
.negative {{color:var(--negative);font-weight:600;}}
.chart-container {{height:280px;margin-bottom:16px;}}
.table-wrap {{overflow-x:auto;}}
table {{width:100%;border-collapse:collapse;font-size:12px;}}
th {{background:#f1f5f9;padding:8px 6px;text-align:left;font-weight:600;white-space:nowrap;position:sticky;top:0;}}
td {{padding:6px;white-space:nowrap;border-bottom:1px solid var(--border);}}
tr:hover {{background:#f8fafc;}}
.rank-grid {{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px;margin-bottom:20px;}}
.rank-card {{background:var(--card);border-radius:8px;padding:12px;border-left:4px solid var(--primary);}}
.rank-card .score {{font-size:24px;font-weight:700;color:var(--primary);}}
.rank-card .name {{font-size:14px;font-weight:600;margin:4px 0;}}
.rank-card .meta {{font-size:12px;color:var(--muted);}}
.wf-item,.mc-item {{display:flex;justify-content:space-between;padding:8px 12px;border-bottom:1px solid var(--border);font-size:13px;}}
.wf-item:last-child,.mc-item:last-child {{border-bottom:none;}}
.port-grid {{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:12px;}}
.port-item {{text-align:center;padding:12px;background:#f8fafb;border-radius:8px;}}
.port-label {{font-size:12px;color:var(--muted);margin-bottom:4px;}}
.port-value {{font-size:20px;font-weight:700;}}
.badge {{display:inline-block;padding:2px 8px;border-radius:12px;font-size:11px;font-weight:600;}}
.badge-green {{background:#dcfce7;color:#166534;}}
.badge-red {{background:#fef2f2;color:#991b1b;}}
.badge-yellow {{background:#fef9c3;color:#854d0e;}}
.tabs {{display:flex;gap:8px;margin-bottom:16px;flex-wrap:wrap;}}
.tab {{padding:6px 16px;border-radius:20px;border:1px solid var(--border);cursor:pointer;font-size:13px;background:var(--card);transition:all .2s;}}
.tab:hover {{background:#f1f5f9;}}
.tab.active {{background:var(--primary);color:#fff;border-color:var(--primary);}}
.section {{display:none;}}
.section.active {{display:block;}}
.footer {{text-align:center;padding:20px;color:var(--muted);font-size:12px;margin-top:24px;border-top:1px solid var(--border);}}
@media(max-width:768px) {{
    .card-header {{flex-direction:column;align-items:flex-start;}}
    .rank-grid {{grid-template-columns:1fr;}}
    table {{font-size:11px;}}
}}
</style>
</head>
<body>
<div style="display:flex;align-items:center;gap:12px;margin-bottom:4px;">
    <div style="width:36px;height:36px;background:var(--primary);border-radius:8px;display:flex;align-items:center;justify-content:center;color:#fff;font-weight:700;font-size:18px;">Q</div>
    <h1>QuantWeave 专业级回测报告</h1>
</div>
<p class="subtitle">v3.0 | Walk-Forward + Monte Carlo + 组合分析 | {now} | 数据区间: 2023-01-01 ~ 2025-04-10</p>

<div class="tabs">
    <div class="tab active" onclick="showSection('overview')">📊 总览排名</div>
    <div class="tab" onclick="showSection('stocks')">📈 个股详情</div>
    <div class="tab" onclick="showSection('wf')">🔄 Walk-Forward</div>
    <div class="tab" onclick="showSection('mc')">🎲 Monte Carlo</div>
    <div class="tab" onclick="showSection('portfolio')">💼 组合分析</div>
</div>

<div id="overview" class="section active">
    <h2>策略综合排名</h2>
    <p style="color:var(--muted);font-size:13px;margin-bottom:12px;">
        评分 = 收益(40%) + Walk-Forward稳健性(30%) + MC正概率(20%) + 正收益比例(10%)
    </p>
    <div class="card">
        <div class="table-wrap"><table>
            <thead><tr><th>综合评分</th><th>策略</th><th>平均收益</th><th>正收益比例</th>
                <th>WF比</th><th>过拟合?</th><th>MC正概率</th><th>MC P95回撤</th></tr></thead>
            <tbody>{rank_rows}</tbody>
        </table></div>
    </div>
</div>

<div id="stocks" class="section">
    <h2>个股详情（增强指标）</h2>
    <p style="color:var(--muted);font-size:13px;margin-bottom:12px;">
        每只股票包含: 权益曲线图 + Sortino/Calmar/VaR/CVaR/Ulcer完整风险指标
    </p>
    {stock_cards}
</div>

<div id="wf" class="section">
    <h2>Walk-Forward 滚动验证</h2>
    <p style="color:var(--muted);font-size:13px;margin-bottom:12px;">
        训练窗口244天(1年) → 测试窗口60天(1季度)，滚动推进。WF比&lt;0.7视为过拟合。
    </p>
    <div class="card">{wf_section if wf_section else "<p>数据加载中...</p>"}</div>
</div>

<div id="mc" class="section">
    <h2>Monte Carlo 稳健性检验</h2>
    <p style="color:var(--muted);font-size:13px;margin-bottom:12px;">
        5000次随机打乱交易顺序模拟。关注: P95最大回撤 vs 原始回撤、正收益概率、破产概率。
    </p>
    <div class="card">{mc_section if mc_section else "<p>数据加载中...</p>"}</div>
</div>

<div id="portfolio" class="section">
    <h2>组合级分析</h2>
    <p style="color:var(--muted);font-size:13px;margin-bottom:12px;">
        每只股票使用最优策略，等权(12.5万/股)配置组合。
    </p>
    {port_section if port_section else "<p>数据加载中...</p>"}
</div>

<div class="footer">
    QuantWeave v3.0 | Powered by Tushare Pro + Chart.js | {now}
</div>

<script>
function showSection(id) {{
    document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.getElementById(id).classList.add('active');
    event.target.classList.add('active');
}}
</script>
</body>
</html>"""
    out = os.path.join(base, output_path)
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"📊 报告已生成 → {out}")
    return out

if __name__ == "__main__":
    gen_report()
