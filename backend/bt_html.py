"""HTML报告生成模块 — 增强版
- 收益率曲线（每个策略一条线）
- 红色B标记买入 + 股票名称
- 绿色S标记卖出 + 股票名称
- 完整交割单
- 策略排名 + 回撤曲线
"""
from datetime import datetime
from pathlib import Path


def build_html(results, stock_names, start, end, capital, max_pos, sl, tp):
    COLORS = ['#ef4444', '#3b82f6', '#f59e0b', '#10b981', '#8b5cf6']
    strategy_list = list(results.items())

    # ---- 收益率曲线数据 ----
    ret_ds = []
    for idx, (key, res) in enumerate(strategy_list):
        curve = res.get('equity_curve', [])
        if not curve:
            continue
        pts = ",".join(
            f'{{"x":"{e["date"]}","y":{round((e["value"]/capital - 1)*100, 2)}}}'
            for e in curve
        )
        c = COLORS[idx % len(COLORS)]
        ret_ds.append(f'{{label:"{res["name"]}",borderColor:"{c}",'
                      f'backgroundColor:"rgba(0,0,0,0)",data:[{pts}],'
                      f'borderWidth:2.5,pointRadius:0,tension:0.1}}')

    # ---- 买卖标记数据 ----
    buy_annotations = []
    sell_annotations = []
    for idx, (key, res) in enumerate(strategy_list):
        c = COLORS[idx % len(COLORS)]
        curve = res.get('equity_curve', [])
        if not curve:
            continue
        # build date->return map
        date_ret = {e['date']: round((e['value']/capital - 1)*100, 2) for e in curve}
        for t in res.get('trades', []):
            d = t.get('date', '')
            if d not in date_ret:
                continue
            y = date_ret[d]
            nm = stock_names.get(t['code'], t['code'])
            short_nm = nm[:4] if len(nm) > 4 else nm
            if t['dir'] == 'B':
                buy_annotations.append(f'{{x:"{d}",y:{y},name:"{short_nm}",code:"{t["code"]}",color:"{c}"}}')
            else:
                reason = t.get('reason', '')
                profit = t.get('profit', 0)
                profit_str = f'{profit:+.0f}' if profit else ''
                sell_annotations.append(
                    f'{{x:"{d}",y:{y},name:"{short_nm}",code:"{t["code"]}",'
                    f'color:"{c}",reason:"{reason}",profit:"{profit_str}"}}')

    buy_js = ",".join(buy_annotations)
    sell_js = ",".join(sell_annotations)

    # ---- 回撤曲线 ----
    dd_ds = []
    for idx, (key, res) in enumerate(strategy_list):
        curve = res.get('dd_curve', [])
        if not curve:
            continue
        pts = ",".join(f'{{"x":"{e["date"]}","y":{e["dd"]}}}' for e in curve)
        c = COLORS[idx % len(COLORS)]
        dd_ds.append(f'{{label:"{res["name"]}",borderColor:"{c}",'
                     f'backgroundColor:"rgba(0,0,0,0)",data:[{pts}],'
                     f'borderWidth:1.5,pointRadius:0,fill:true}}')

    # ---- 排名 ----
    ranked = sorted(strategy_list, key=lambda x: -x[1].get('sharpe_ratio', 0))
    rank_rows = ""
    for rank, (key, r) in enumerate(ranked, 1):
        medal = ["🥇", "🥈", "🥉"][rank-1] if rank <= 3 else str(rank)
        rc = "positive" if r['total_return'] > 0 else "negative"
        rank_rows += (f'<tr><td>{medal}</td><td>{r["name"]}</td>'
            f'<td class="{rc}">{r["total_return"]:+.2f}%</td>'
            f'<td>{r["annual_return"]:+.2f}%</td>'
            f'<td>{r["sharpe_ratio"]:.3f}</td>'
            f'<td>{r["max_drawdown"]:.2f}%</td>'
            f'<td>{r["win_rate"]:.1f}%</td>'
            f'<td>{r["profit_loss_ratio"]:.2f}</td>'
            f'<td>{r["total_trades"]}</td></tr>')

    # ---- 卡片 ----
    cards = ""
    for idx, (key, res) in enumerate(strategy_list):
        ret = res['total_return']
        rc = "positive" if ret > 0 else "negative"
        c = COLORS[idx % len(COLORS)]
        fv = res.get('final_value', 0)
        cards += (f'<div class="card" style="--accent:{c}">'
            f'<div class="lb">{res["name"]}</div>'
            f'<div class="vl {rc}">{ret:+.2f}%</div>'
            f'<div class="info">夏普 {res["sharpe_ratio"]:.3f} | 回撤 {res["max_drawdown"]:.2f}% | 胜率 {res["win_rate"]:.1f}%</div>'
            f'<div class="info">终值 ¥{fv:,.0f} | 交易 {res["total_trades"]}笔</div></div>')

    # ---- 完整交割单 ----
    settlement_rows = ""
    trade_id = 0
    for key, res in strategy_list:
        for t in res.get('trades', []):
            trade_id += 1
            nm = stock_names.get(t['code'], t['code'])
            dc = "buy" if t['dir'] == 'B' else "sell"
            dl = "买入" if t['dir'] == 'B' else "卖出"
            d = t.get('date', '')
            pr = t.get('price', 0)
            vol = t.get('vol', 0)
            amt = pr * vol
            profit = t.get('profit', 0)
            reason = t.get('reason', '')
            ps = f"{profit:+.2f}" if t['dir'] == 'S' and profit else "—"
            pc = "positive" if profit > 0 else ("negative" if profit < 0 else "")
            settlement_rows += (
                f'<tr><td>{trade_id}</td><td>{res["name"]}</td>'
                f'<td class="{dc}">{dl}</td>'
                f'<td>{d}</td><td>{nm}({t["code"]})</td>'
                f'<td>¥{pr:.2f}</td><td>{vol}</td><td>¥{amt:,.0f}</td>'
                f'<td class="{pc}">{ps}</td><td>{reason}</td></tr>')

    # ---- 最佳策略最近交易明细 ----
    best_res = ranked[0][1]
    trade_rows = ""
    for t in best_res.get('trades', [])[-50:]:
        nm = stock_names.get(t['code'], t['code'])
        dc = "buy" if t['dir'] == 'B' else "sell"
        dl = "买入" if t['dir'] == 'B' else "卖出"
        ps = f"{t.get('profit',0):+.2f}" if t.get('profit') else "—"
        pc = "positive" if t.get('profit',0) and t.get('profit',0)>0 else ("negative" if t.get('profit',0) and t.get('profit',0)<0 else "")
        trade_rows += (f'<tr><td class="{dc}">{dl}</td><td>{nm}({t["code"]})</td>'
            f'<td>{t.get("date","")}</td><td>¥{t["price"]:.2f}</td>'
            f'<td>{t["vol"]}</td><td class="{pc}">{ps}</td>'
            f'<td>{t.get("reason","")}</td></tr>')

    now = datetime.now().strftime('%Y-%m-%d %H:%M')
    ret_js = ",".join(ret_ds)
    dd_js = ",".join(dd_ds)
    sl_pct = f"{sl*100:.0f}"; tp_pct = f"{tp*100:.0f}"

    return f'''<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>QuantWeave 全量策略回测报告</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<script src="https://cdn.jsdelivr.net/npm/date-fns@3"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@3"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-annotation@3"></script>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'Plus Jakarta Sans',-apple-system,sans-serif;background:#f8fafc;color:#1e293b}}
.header{{background:linear-gradient(135deg,#0f172a 0%,#1e40af 100%);color:#fff;padding:40px;text-align:center}}
.header h1{{font-size:2em;margin-bottom:8px}}.header .sub{{opacity:0.8;font-size:1.1em}}
.ctn{{max-width:1400px;margin:0 auto;padding:20px}}
.sec{{background:#fff;border-radius:12px;box-shadow:0 1px 3px rgba(0,0,0,0.1);padding:24px;margin-bottom:20px}}
.sec h2{{font-size:1.3em;margin-bottom:16px;color:#1e40af;border-bottom:2px solid #e2e8f0;padding-bottom:8px}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:16px;margin-bottom:20px}}
.card{{background:#fff;border-radius:12px;padding:20px;box-shadow:0 1px 3px rgba(0,0,0,0.1);border-left:4px solid var(--accent,#3b82f6)}}
.card .lb{{font-size:0.85em;color:#64748b;margin-bottom:4px}}.card .vl{{font-size:1.8em;font-weight:700}}
.card .info{{font-size:0.85em;color:#64748b;margin-top:4px}}
.positive{{color:#dc2626}}.negative{{color:#16a34a}}
.buy{{color:#dc2626;font-weight:600}}.sell{{color:#16a34a;font-weight:600}}
table{{width:100%;border-collapse:collapse;font-size:0.85em}}
th{{background:#f1f5f9;padding:8px 10px;text-align:left;font-weight:600;color:#475569;position:sticky;top:0;z-index:1}}
td{{padding:8px 10px;border-bottom:1px solid #f1f5f9}}
.cb{{position:relative;height:400px}}
.scroll-table{{max-height:500px;overflow-y:auto;border:1px solid #e2e8f0;border-radius:8px}}
.ft{{text-align:center;padding:20px;color:#94a3b8;font-size:0.85em}}
.legend-box{{display:inline-flex;align-items:center;gap:6px;margin-right:16px;font-size:0.85em}}
.legend-dot{{width:12px;height:12px;border-radius:50%;display:inline-block}}
.tab-bar{{display:flex;gap:8px;margin-bottom:16px;flex-wrap:wrap}}
.tab-btn{{padding:8px 16px;border:2px solid #e2e8f0;border-radius:8px;background:#fff;cursor:pointer;
  font-weight:600;color:#475569;transition:all 0.2s}}
.tab-btn:hover{{border-color:#3b82f6;color:#1e40af}}
.tab-btn.active{{background:#1e40af;color:#fff;border-color:#1e40af}}
.tab-content{{display:none}}.tab-content.active{{display:block}}
.filter-input{{padding:6px 12px;border:1px solid #e2e8f0;border-radius:6px;font-size:0.9em;width:200px}}
</style></head><body>
<div class="header"><h1>📊 QuantWeave 全量策略回测报告</h1>
<div class="sub">区间: {start} ~ {end} | 初始资金: ¥{capital:,} | 最大持仓: {max_pos}只 | 止损{sl_pct}% / 止盈+{tp_pct}%</div></div>
<div class="ctn">

<div class="cards">{cards}</div>

<div class="sec"><h2>📈 收益率曲线</h2>
<div style="margin-bottom:12px">
<span class="legend-box"><span style="color:#dc2626;font-weight:700;font-size:1.1em">B</span> = 买入(红)</span>
<span class="legend-box"><span style="color:#16a34a;font-weight:700;font-size:1.1em">S</span> = 卖出(绿)</span>
<span class="legend-box">悬停标记可查看股票名称</span>
</div>
<div class="cb"><canvas id="retC"></canvas></div></div>

<div class="sec"><h2>📉 最大回撤</h2><div class="cb"><canvas id="ddC"></canvas></div></div>

<div class="sec"><h2>🏆 策略综合排名 (按夏普)</h2>
<table><thead><tr><th>#</th><th>策略</th><th>总收益</th><th>年化</th><th>夏普</th><th>最大回撤</th><th>胜率</th><th>盈亏比</th><th>交易数</th></tr></thead>
<tbody>{rank_rows}</tbody></table></div>

<div class="sec"><h2>📋 最近交易明细 (最佳策略: {best_res["name"]})</h2>
<div class="scroll-table" style="max-height:400px">
<table><thead><tr><th>方向</th><th>股票</th><th>日期</th><th>价格</th><th>数量</th><th>盈亏</th><th>原因</th></tr></thead>
<tbody>{trade_rows}</tbody></table></div></div>

<div class="sec">
<h2>📑 完整交割单</h2>
<div style="margin-bottom:12px">
<input type="text" class="filter-input" id="settleFilter" placeholder="搜索股票名称/代码/策略..." oninput="filterSettlement()">
<span style="margin-left:12px;color:#64748b;font-size:0.85em" id="settleCount"></span>
</div>
<div class="scroll-table">
<table id="settleTable"><thead><tr><th>#</th><th>策略</th><th>方向</th><th>日期</th><th>股票</th><th>价格</th><th>数量</th><th>金额</th><th>盈亏</th><th>原因</th></tr></thead>
<tbody>{settlement_rows}</tbody></table></div></div>

</div>
<div class="ft">QuantWeave · 全量策略回测 · 止损{sl_pct}% / 止盈+{tp_pct}% · {now}</div>

<script>
const dc={{type:'time',time:{{unit:'month',displayFormats:{{month:'yyyy-MM'}}}},ticks:{{maxTicksLimit:12}}}};

// 收益率曲线
const retChart = new Chart(document.getElementById('retC'),{{
  type:'line',
  data:{{datasets:[{ret_js}]}},
  options:{{
    responsive:true,maintainAspectRatio:false,
    interaction:{{intersect:false,mode:'index'}},
    scales:{{
      x:dc,
      y:{{ticks:{{callback:v=>v.toFixed(1)+'%'}},title:{{display:true,text:'收益率(%)'}}}}
    }},
    plugins:{{
      legend:{{position:'top'}},
      tooltip:{{callbacks:{{label:ctx=>ctx.dataset.label+': '+ctx.parsed.y.toFixed(2)+'%'}}}},
    }}
  }},
  plugins: [{{
    id: 'tradeMarkers',
    afterDraw(chart) {{
      const ctx = chart.ctx;
      const xScale = chart.scales.x;
      const yScale = chart.scales.y;
      const buys = [{buy_js}];
      const sells = [{sell_js}];

      // Draw buy markers (B)
      buys.forEach(b => {{
        const xPos = xScale.getPixelForValue(b.x);
        const yPos = yScale.getPixelForValue(b.y);
        if (isNaN(xPos) || isNaN(yPos)) return;

        ctx.save();
        ctx.font = 'bold 10px sans-serif';
        ctx.fillStyle = '#dc2626';
        ctx.textAlign = 'center';
        // Draw B label above point
        ctx.beginPath();
        ctx.arc(xPos, yPos - 12, 8, 0, Math.PI * 2);
        ctx.fillStyle = 'rgba(220,38,38,0.85)';
        ctx.fill();
        ctx.fillStyle = '#fff';
        ctx.fillText('B', xPos, yPos - 8);
        ctx.restore();
      }});

      // Draw sell markers (S)
      sells.forEach(s => {{
        const xPos = xScale.getPixelForValue(s.x);
        const yPos = yScale.getPixelForValue(s.y);
        if (isNaN(xPos) || isNaN(yPos)) return;

        ctx.save();
        ctx.font = 'bold 10px sans-serif';
        ctx.textAlign = 'center';
        ctx.beginPath();
        ctx.arc(xPos, yPos + 12, 8, 0, Math.PI * 2);
        ctx.fillStyle = 'rgba(22,163,74,0.85)';
        ctx.fill();
        ctx.fillStyle = '#fff';
        ctx.fillText('S', xPos, yPos + 16);
        ctx.restore();
      }});
    }}
  }}]
}});

// 买卖点交互提示
const tooltipEl = document.getElementById('retC');
tooltipEl.addEventListener('mousemove', function(e) {{
  const chart = Chart.getChart('retC');
  if (!chart) return;
  const rect = chart.canvas.getBoundingClientRect();
  const x = e.clientX - rect.left;
  const y = e.clientY - rect.top;
  const xScale = chart.scales.x;
  const yScale = chart.scales.y;

  const buys = [{buy_js}];
  const sells = [{sell_js}];

  let found = null;
  for (const b of buys) {{
    const xp = xScale.getPixelForValue(b.x);
    const yp = yScale.getPixelForValue(b.y) - 12;
    if (Math.abs(x - xp) < 12 && Math.abs(y - yp) < 12) {{
      found = {{type: '买入', name: b.name, code: b.code, date: b.x, ret: b.y}};
      break;
    }}
  }}
  if (!found) {{
    for (const s of sells) {{
      const xp = xScale.getPixelForValue(s.x);
      const yp = yScale.getPixelForValue(s.y) + 12;
      if (Math.abs(x - xp) < 12 && Math.abs(y - yp) < 12) {{
        found = {{type: '卖出', name: s.name, code: s.code, date: s.x, ret: s.y, reason: s.reason, profit: s.profit}};
        break;
      }}
    }}
  }}

  chart.canvas.title = found
    ? (found.type + ': ' + found.name + '(' + found.code + ')\\n' +
       '日期: ' + found.date + ' | 收益率: ' + found.y + '%' +
       (found.profit ? ' | 盈亏: ¥' + found.profit : '') +
       (found.reason ? ' | ' + found.reason : ''))
    : '';
}});

// 回撤曲线
new Chart(document.getElementById('ddC'),{{
  type:'line',data:{{datasets:[{dd_js}]}},
  options:{{
    responsive:true,maintainAspectRatio:false,
    interaction:{{intersect:false,mode:'index'}},
    scales:{{x:dc,y:{{ticks:{{callback:v=>v.toFixed(1)+'%'}},title:{{display:true,text:'回撤(%)'}}}}}},
    plugins:{{legend:{{position:'top'}},tooltip:{{callbacks:{{label:ctx=>ctx.dataset.label+': '+ctx.parsed.y.toFixed(2)+'%'}}}}}}
  }}
}});

// 交割单搜索过滤
function filterSettlement() {{
  const q = document.getElementById('settleFilter').value.toLowerCase();
  const rows = document.querySelectorAll('#settleTable tbody tr');
  let count = 0;
  rows.forEach(row => {{
    const text = row.textContent.toLowerCase();
    const show = !q || text.includes(q);
    row.style.display = show ? '' : 'none';
    if (show) count++;
  }});
  document.getElementById('settleCount').textContent = '显示 ' + count + ' 条记录';
}}
// 初始计数
document.getElementById('settleCount').textContent = '共 ' + document.querySelectorAll('#settleTable tbody tr').length + ' 条记录';
</script></body></html>'''
