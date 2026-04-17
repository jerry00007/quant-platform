/**
 * QuantWeave 实时行情页面 v2.0
 *
 * 五大板块：
 *  1. 📊 指数速览 — 三大指数实时涨跌
 *  2. 📦 持仓卡片 — 持仓个股实时盈亏
 *  3. 📋 行情明细 — 持仓+关注列表详细报价
 *  4. 📈 涨跌分布 — 市场宽度柱状图
 *  5. 🌡️ 市场温度 — 综合情绪判断
 */

let _marketRefreshTimer = null;
let _marketData = null;

async function renderMarket() {
  const main = document.getElementById('mainContent');
  main.innerHTML = `
    <div class="page-header" style="display:flex;justify-content:space-between;align-items:center">
      <div>
        <h2>📈 实时行情</h2>
        <p>A股市场全景 · 30秒自动刷新</p>
      </div>
      <div style="display:flex;gap:8px;align-items:center">
        <span id="marketUpdateTime" style="font-size:12px;color:var(--text-muted);font-family:var(--font-mono)"></span>
        <button class="btn btn-outline btn-sm" onclick="refreshMarket()">🔄 刷新</button>
      </div>
    </div>
    <div id="marketContent"><div class="loading"><div class="spinner"></div>加载市场数据...</div></div>
  `;
  await refreshMarket();
  startMarketAutoRefresh();
}

// 页面离开时清除定时器
function destroyMarket() {
  if (_marketRefreshTimer) {
    clearInterval(_marketRefreshTimer);
    _marketRefreshTimer = null;
  }
}

function startMarketAutoRefresh() {
  destroyMarket();
  _marketRefreshTimer = setInterval(() => refreshMarket(true), 30000);
}

async function refreshMarket(silent = false) {
  const container = document.getElementById('marketContent');
  if (!container) return;

  if (!silent) {
    container.innerHTML = '<div class="loading"><div class="spinner"></div>加载市场数据...</div>';
  }

  try {
    const resp = await API.getMarketOverview();
    const data = resp?.data || resp;
    _marketData = data;

    // 更新时间
    const timeEl = document.getElementById('marketUpdateTime');
    if (timeEl) {
      const now = new Date();
      timeEl.textContent = `${now.getHours().toString().padStart(2,'0')}:${now.getMinutes().toString().padStart(2,'0')}:${now.getSeconds().toString().padStart(2,'0')}`;
    }

    renderMarketContent(container, data);
  } catch (err) {
    if (!silent) {
      container.innerHTML = `
        <div class="card" style="text-align:center;padding:40px">
          <p style="color:var(--text-muted);margin-bottom:16px">📡 后端服务未启动或数据加载失败</p>
          <p style="font-size:13px;color:var(--text-muted)">${err?.message || '请检查后端服务'}</p>
          <button class="btn btn-outline" style="margin-top:16px" onclick="refreshMarket()">🔄 重试</button>
        </div>
      `;
    }
  }
}

function renderMarketContent(container, data) {
  const { indices = [], breadth = {}, sectors = [], portfolio_realtime = [] } = data;

  container.innerHTML = `
    <!-- 1. 指数速览 -->
    <div class="market-section">
      <div class="section-title">📊 指数速览</div>
      <div class="grid-3" id="indexCards">
        ${renderIndexCards(indices)}
      </div>
    </div>

    <!-- 2. 持仓卡片 -->
    <div class="market-section">
      <div class="section-title">📦 持仓实时盈亏</div>
      <div id="portfolioCards">
        ${portfolio_realtime.length > 0 ? renderPortfolioCards(portfolio_realtime) : `
          <div class="card" style="text-align:center;padding:30px;color:var(--text-muted)">
            暂无持仓数据
          </div>
        `}
      </div>
    </div>

    <!-- 3. 涨跌分布 + 市场温度 -->
    <div class="grid-2 market-section">
      <div>
        <div class="section-title">📈 涨跌分布</div>
        ${renderBreadthChart(breadth)}
      </div>
      <div>
        <div class="section-title">🌡️ 市场温度</div>
        ${renderTemperature(breadth, sectors)}
      </div>
    </div>

    <!-- 4. 板块动量 -->
    <div class="market-section">
      <div class="section-title">🔥 板块动量 TOP10</div>
      ${renderSectorTable(sectors)}
    </div>

    <!-- 5. 行情明细表 -->
    <div class="market-section">
      <div class="section-title">📋 行情明细</div>
      ${renderDetailTable(portfolio_realtime)}
    </div>
  `;
}

// =============================================
// 1. 指数速览卡片
// =============================================
function renderIndexCards(indices) {
  if (!indices.length) {
    return '<div class="card" style="text-align:center;padding:20px;color:var(--text-muted)">指数数据加载中...</div>';
  }

  // 主要展示三大指数
  const mainIndices = ['上证指数', '深证成指', '创业板指'];

  return mainIndices.map(name => {
    const idx = indices.find(i => i.name === name) || {};
    const pct = idx.percent || 0;
    const isUp = pct >= 0;
    const color = isUp ? 'var(--color-up)' : 'var(--color-down)';
    const arrow = isUp ? '▲' : '▼';
    const tagClass = isUp ? 'tag-red' : 'tag-green';

    return `
      <div class="card" style="position:relative;overflow:hidden">
        <div style="position:absolute;top:0;right:0;width:80px;height:80px;background:${isUp ? 'rgba(34,197,94,0.08)' : 'rgba(239,68,68,0.08)'};border-radius:0 0 0 80px"></div>
        <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:12px">
          <div>
            <div style="font-size:13px;color:var(--text-secondary);margin-bottom:4px">${name}</div>
            <div style="font-family:var(--font-mono);font-size:28px;font-weight:700;color:${color};letter-spacing:-1px">
              ${formatNum(idx.current)}
            </div>
          </div>
          <span class="tag ${tagClass}" style="font-size:13px">${arrow} ${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%</span>
        </div>
        <div style="display:flex;gap:16px;font-size:12px;color:var(--text-muted);font-family:var(--font-mono)">
          <span>开 ${formatNum(idx.open)}</span>
          <span>高 <span style="color:var(--color-up)">${formatNum(idx.high)}</span></span>
          <span>低 <span style="color:var(--color-down)">${formatNum(idx.low)}</span></span>
        </div>
      </div>
    `;
  }).join('');
}

// =============================================
// 2. 持仓卡片
// =============================================
function renderPortfolioCards(positions) {
  // 计算汇总
  const totalMarketValue = positions.reduce((s, p) => s + (p.market_value || 0), 0);
  const totalCost = positions.reduce((s, p) => s + (p.avg_cost || 0) * (p.volume || 0), 0);
  const totalProfit = totalMarketValue - totalCost;
  const totalPct = totalCost > 0 ? (totalProfit / totalCost * 100) : 0;
  const isTotalUp = totalProfit >= 0;

  let html = `
    <div class="card" style="margin-bottom:16px;background:linear-gradient(135deg, ${isTotalUp ? 'rgba(34,197,94,0.08)' : 'rgba(239,68,68,0.08)'}, transparent)">
      <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:16px">
        <div>
          <div style="font-size:12px;color:var(--text-secondary);margin-bottom:4px">持仓总市值</div>
          <div style="font-family:var(--font-mono);font-size:24px;font-weight:700">
            ¥${formatMoney(totalMarketValue)}
          </div>
        </div>
        <div>
          <div style="font-size:12px;color:var(--text-secondary);margin-bottom:4px">总盈亏</div>
          <div style="font-family:var(--font-mono);font-size:20px;font-weight:700;color:${isTotalUp ? 'var(--color-up)' : 'var(--color-down)'}">
            ${isTotalUp ? '+' : ''}¥${formatMoney(totalProfit)} (${totalPct >= 0 ? '+' : ''}${totalPct.toFixed(2)}%)
          </div>
        </div>
        <div>
          <div style="font-size:12px;color:var(--text-secondary);margin-bottom:4px">持仓数量</div>
          <div style="font-family:var(--font-mono);font-size:20px;font-weight:700">${positions.length} 只</div>
        </div>
      </div>
    </div>
    <div class="grid-4" style="gap:12px">
  `;

  for (const p of positions) {
    const isUp = (p.profit || 0) >= 0;
    const color = isUp ? 'var(--color-up)' : 'var(--color-down)';
    const tagClass = isUp ? 'tag-red' : 'tag-green';
    const dayPct = p.change_pct || 0;
    const dayUp = dayPct >= 0;

    html += `
      <div class="card" style="padding:16px;cursor:pointer" onclick="showStockDetail('${p.ts_code}')">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
          <div>
            <div style="font-size:15px;font-weight:600">${p.name || p.ts_code}</div>
            <div style="font-size:11px;color:var(--text-muted);font-family:var(--font-mono)">${p.ts_code}</div>
          </div>
          <span class="tag ${dayUp ? 'tag-red' : 'tag-green'}" style="font-size:11px">
            ${dayPct >= 0 ? '+' : ''}${dayPct.toFixed(2)}%
          </span>
        </div>
        <div style="font-family:var(--font-mono);font-size:22px;font-weight:700;margin-bottom:8px">
          ¥${(p.current_price || 0).toFixed(2)}
        </div>
        <div style="display:flex;justify-content:space-between;font-size:11px">
          <span style="color:var(--text-muted)">成本 ${(p.avg_cost || 0).toFixed(2)}</span>
          <span style="color:${color};font-weight:600;font-family:var(--font-mono)">
            ${isUp ? '+' : ''}${(p.profit || 0).toFixed(0)}元 (${p.profit_pct >= 0 ? '+' : ''}${(p.profit_pct || 0).toFixed(2)}%)
          </span>
        </div>
      </div>
    `;
  }

  html += '</div>';
  return html;
}

// =============================================
// 3. 涨跌分布
// =============================================
function renderBreadthChart(breadth) {
  if (!breadth || !breadth.total_stocks) {
    return '<div class="card" style="text-align:center;padding:20px;color:var(--text-muted)">暂无数据</div>';
  }

  const { up_count, down_count, flat_count, limit_up, limit_down, up_ratio, sentiment, date, total_stocks } = breadth;
  const upPct = (up_count / total_stocks * 100).toFixed(1);
  const downPct = (down_count / total_stocks * 100).toFixed(1);
  const flatPct = (flat_count / total_stocks * 100).toFixed(1);

  return `
    <div class="card">
      <div style="margin-bottom:16px;display:flex;justify-content:space-between;align-items:center">
        <span style="font-size:12px;color:var(--text-muted)">日期: ${date || '-'}</span>
        <span class="tag ${sentiment === '偏多' ? 'tag-red' : sentiment === '偏空' ? 'tag-green' : 'tag-gray'}">${sentiment || '中性'}</span>
      </div>

      <!-- 比例条 -->
      <div style="display:flex;height:32px;border-radius:8px;overflow:hidden;margin-bottom:16px">
        <div style="width:${upPct}%;background:var(--color-up);display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:600;color:#000">
          ${parseFloat(upPct) > 15 ? up_count : ''}
        </div>
        <div style="width:${flatPct}%;background:var(--color-border);display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:600;color:var(--text-muted)"></div>
        <div style="width:${downPct}%;background:var(--color-down);display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:600;color:#fff">
          ${parseFloat(downPct) > 15 ? down_count : ''}
        </div>
      </div>

      <!-- 数据行 -->
      <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px">
        <div style="text-align:center">
          <div style="font-family:var(--font-mono);font-size:20px;font-weight:700;color:var(--color-up)">${up_count}</div>
          <div style="font-size:11px;color:var(--text-muted)">上涨 (${upPct}%)</div>
        </div>
        <div style="text-align:center">
          <div style="font-family:var(--font-mono);font-size:20px;font-weight:700;color:var(--text-secondary)">${flat_count}</div>
          <div style="font-size:11px;color:var(--text-muted)">平盘</div>
        </div>
        <div style="text-align:center">
          <div style="font-family:var(--font-mono);font-size:20px;font-weight:700;color:var(--color-down)">${down_count}</div>
          <div style="font-size:11px;color:var(--text-muted)">下跌 (${downPct}%)</div>
        </div>
      </div>

      <!-- 涨跌停 -->
      <div style="margin-top:16px;padding-top:12px;border-top:1px solid var(--color-border);display:flex;justify-content:space-around">
        <div style="text-align:center">
          <div style="font-family:var(--font-mono);font-size:16px;font-weight:700;color:var(--color-up)">${limit_up || 0}</div>
          <div style="font-size:11px;color:var(--text-muted)">涨停</div>
        </div>
        <div style="text-align:center">
          <div style="font-family:var(--font-mono);font-size:16px;font-weight:700;color:var(--color-down)">${limit_down || 0}</div>
          <div style="font-size:11px;color:var(--text-muted)">跌停</div>
        </div>
        <div style="text-align:center">
          <div style="font-family:var(--font-mono);font-size:16px;font-weight:700">${total_stocks}</div>
          <div style="font-size:11px;color:var(--text-muted)">总数</div>
        </div>
      </div>
    </div>
  `;
}

// =============================================
// 4. 市场温度
// =============================================
function renderTemperature(breadth, sectors) {
  const upRatio = breadth?.up_ratio || 0.5;
  const sentiment = breadth?.sentiment || '中性';

  // 温度计：0-100
  const temperature = Math.round(upRatio * 100);

  // 温度颜色
  let tempColor, tempLabel, tempEmoji;
  if (temperature >= 70) {
    tempColor = '#22C55E'; tempLabel = '贪婪'; tempEmoji = '🔥';
  } else if (temperature >= 55) {
    tempColor = '#84CC16'; tempLabel = '偏热'; tempEmoji = '☀️';
  } else if (temperature >= 45) {
    tempColor = '#F59E0B'; tempLabel = '中性'; tempEmoji = '🌡️';
  } else if (temperature >= 30) {
    tempColor = '#F97316'; tempLabel = '偏冷'; tempEmoji = '🍂';
  } else {
    tempColor = '#EF4444'; tempLabel = '恐惧'; tempEmoji = '❄️';
  }

  // 热门板块
  const hotSectors = (sectors || []).filter(s => s.avg_change > 0).slice(0, 5);
  const coldSectors = (sectors || []).filter(s => s.avg_change < 0).slice(-3).reverse();

  return `
    <div class="card">
      <!-- 温度计 -->
      <div style="text-align:center;margin-bottom:20px">
        <div style="font-size:48px;margin-bottom:8px">${tempEmoji}</div>
        <div style="font-family:var(--font-mono);font-size:40px;font-weight:700;color:${tempColor}">${temperature}°</div>
        <div style="font-size:14px;font-weight:600;color:${tempColor};margin-top:4px">${tempLabel}</div>

        <!-- 温度条 -->
        <div style="margin:16px auto 0;width:80%;height:8px;border-radius:4px;background:linear-gradient(90deg, #EF4444, #F59E0B, #22C55E);position:relative">
          <div style="position:absolute;top:-6px;left:${temperature}%;transform:translateX(-50%);width:16px;height:20px;border-radius:3px;background:${tempColor};border:2px solid var(--color-foreground);transition:left 0.5s ease"></div>
        </div>
        <div style="display:flex;justify-content:space-between;width:80%;margin:4px auto 0;font-size:10px;color:var(--text-muted)">
          <span>恐惧</span><span>中性</span><span>贪婪</span>
        </div>
      </div>

      <!-- 热门板块 -->
      ${hotSectors.length > 0 ? `
        <div style="margin-top:16px">
          <div style="font-size:12px;color:var(--text-secondary);margin-bottom:8px;font-weight:600">🔥 领涨板块</div>
          ${hotSectors.map(s => `
            <div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid rgba(51,65,85,0.3)">
              <span style="font-size:13px">${s.sector}</span>
              <span class="tag tag-red" style="font-size:11px">+${(s.avg_change || 0).toFixed(2)}%</span>
            </div>
          `).join('')}
        </div>
      ` : ''}

      <!-- 冷门板块 -->
      ${coldSectors.length > 0 ? `
        <div style="margin-top:12px">
          <div style="font-size:12px;color:var(--text-secondary);margin-bottom:8px;font-weight:600">❄️ 领跌板块</div>
          ${coldSectors.map(s => `
            <div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid rgba(51,65,85,0.3)">
              <span style="font-size:13px">${s.sector}</span>
              <span class="tag tag-green" style="font-size:11px">${(s.avg_change || 0).toFixed(2)}%</span>
            </div>
          `).join('')}
        </div>
      ` : ''}
    </div>
  `;
}

// =============================================
// 5. 板块动量表
// =============================================
function renderSectorTable(sectors) {
  if (!sectors || !sectors.length) {
    return '<div class="card" style="text-align:center;padding:20px;color:var(--text-muted)">暂无板块数据</div>';
  }

  const top10 = sectors.slice(0, 10);

  return `
    <div class="card" style="padding:0;overflow:hidden">
      <table class="data-table">
        <thead>
          <tr>
            <th style="width:40px">#</th>
            <th>板块</th>
            <th style="text-align:right">均涨%</th>
            <th style="text-align:right">个股数</th>
            <th style="width:120px">动量条</th>
          </tr>
        </thead>
        <tbody>
          ${top10.map((s, i) => {
            const chg = s.avg_change || 0;
            const isUp = chg >= 0;
            const barWidth = Math.min(Math.abs(chg) * 15, 100);
            const barColor = isUp ? 'var(--color-up)' : 'var(--color-down)';
            return `
              <tr>
                <td style="font-family:var(--font-mono);color:var(--text-muted)">${i + 1}</td>
                <td style="font-weight:600">${s.sector}</td>
                <td style="text-align:right;font-family:var(--font-mono);font-weight:600;color:${isUp ? 'var(--color-up)' : 'var(--color-down)'}">
                  ${chg >= 0 ? '+' : ''}${chg.toFixed(2)}%
                </td>
                <td style="text-align:right;font-family:var(--font-mono);color:var(--text-secondary)">${s.stock_count}</td>
                <td>
                  <div style="height:8px;border-radius:4px;background:rgba(51,65,85,0.5);overflow:hidden">
                    <div style="height:100%;width:${barWidth}%;background:${barColor};border-radius:4px;transition:width 0.3s ease"></div>
                  </div>
                </td>
              </tr>
            `;
          }).join('')}
        </tbody>
      </table>
    </div>
  `;
}

// =============================================
// 6. 行情明细表
// =============================================
function renderDetailTable(positions) {
  if (!positions || !positions.length) {
    return '<div class="card" style="text-align:center;padding:20px;color:var(--text-muted)">暂无持仓数据</div>';
  }

  return `
    <div class="card" style="padding:0;overflow:hidden">
      <table class="data-table">
        <thead>
          <tr>
            <th>代码</th>
            <th>名称</th>
            <th style="text-align:right">现价</th>
            <th style="text-align:right">涨跌幅</th>
            <th style="text-align:right">成本</th>
            <th style="text-align:right">盈亏</th>
            <th style="text-align:right">盈亏%</th>
            <th style="text-align:right">今开</th>
            <th style="text-align:right">最高</th>
            <th style="text-align:right">最低</th>
            <th style="text-align:right">换手率</th>
          </tr>
        </thead>
        <tbody>
          ${positions.map(p => {
            const dayPct = p.change_pct || 0;
            const isDayUp = dayPct >= 0;
            const profit = p.profit || 0;
            const profitPct = p.profit_pct || 0;
            const isProfit = profit >= 0;
            return `
              <tr style="cursor:pointer" onclick="showStockDetail('${p.ts_code}')">
                <td><strong style="font-family:var(--font-mono)">${p.ts_code}</strong></td>
                <td>${p.name || '-'}</td>
                <td style="text-align:right;font-family:var(--font-mono);font-weight:600">
                  ¥${(p.current_price || 0).toFixed(2)}
                </td>
                <td style="text-align:right;font-family:var(--font-mono);font-weight:600;color:${isDayUp ? 'var(--color-up)' : 'var(--color-down)'}">
                  ${dayPct >= 0 ? '+' : ''}${dayPct.toFixed(2)}%
                </td>
                <td style="text-align:right;font-family:var(--font-mono);color:var(--text-secondary)">
                  ${(p.avg_cost || 0).toFixed(2)}
                </td>
                <td style="text-align:right;font-family:var(--font-mono);font-weight:600;color:${isProfit ? 'var(--color-up)' : 'var(--color-down)'}">
                  ${isProfit ? '+' : ''}${profit.toFixed(0)}
                </td>
                <td style="text-align:right;font-family:var(--font-mono);font-weight:600;color:${isProfit ? 'var(--color-up)' : 'var(--color-down)'}">
                  ${profitPct >= 0 ? '+' : ''}${profitPct.toFixed(2)}%
                </td>
                <td style="text-align:right;font-family:var(--font-mono);color:var(--text-secondary)">${formatNum(p.open)}</td>
                <td style="text-align:right;font-family:var(--font-mono);color:var(--color-up)">${formatNum(p.high)}</td>
                <td style="text-align:right;font-family:var(--font-mono);color:var(--color-down)">${formatNum(p.low)}</td>
                <td style="text-align:right;font-family:var(--font-mono);color:var(--text-secondary)">${(p.turnover_rate || 0).toFixed(2)}%</td>
              </tr>
            `;
          }).join('')}
        </tbody>
      </table>
    </div>
  `;
}

// =============================================
// 工具函数
// =============================================
function formatNum(val) {
  if (val == null) return '-';
  return Number(val).toFixed(2);
}

function formatMoney(val) {
  if (val >= 10000) {
    return (val / 10000).toFixed(2) + '万';
  }
  return val.toFixed(2);
}

// 点击个股卡片 — 跳转分析
function showStockDetail(ts_code) {
  if (typeof analyzeStock === 'function') {
    analyzeStock(ts_code);
  } else {
    // 跳转到选股分析页
    if (typeof navigateTo === 'function') {
      navigateTo('screening');
      setTimeout(() => {
        if (typeof analyzeStock === 'function') {
          analyzeStock(ts_code);
        }
      }, 500);
    }
  }
}
