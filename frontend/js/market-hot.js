/**
 * QuantWeave 市场热度页面 v1.0
 *
 * 四大板块：
 *  1. 🔥 涨停&连板榜 — 涨停明细、连板统计
 *  2. 🏆 龙虎榜 — 上榜个股、机构/游资操作
 *  3. 💰 资金流向 — 北向资金、个股资金TOP
 *  4. 🌡️ 市场情绪 — 综合情绪评分 Dashboard
 */

// 当前激活的 tab
let _marketHotTab = 'limit';

async function renderMarketHot() {
  const main = document.getElementById('mainContent');
  main.innerHTML = `
    <div class="page-header" style="display:flex;justify-content:space-between;align-items:center">
      <div>
        <h2>🔥 市场热度</h2>
        <p>涨停连板 · 龙虎榜 · 资金流向 · 市场情绪</p>
      </div>
      <div style="display:flex;gap:8px;align-items:center">
        <span id="mhotUpdateTime" style="font-size:12px;color:var(--text-muted);font-family:var(--font-mono)"></span>
        <button class="btn btn-outline btn-sm" onclick="refreshMarketHot()">🔄 刷新</button>
      </div>
    </div>

    <!-- Tab 切换 -->
    <div style="display:flex;gap:4px;margin-bottom:24px;background:var(--color-muted);padding:4px;border-radius:var(--radius);width:fit-content">
      <button class="mhot-tab active" onclick="switchMarketHotTab('limit')">🔥 涨停连板</button>
      <button class="mhot-tab" onclick="switchMarketHotTab('dragon')">🏆 龙虎榜</button>
      <button class="mhot-tab" onclick="switchMarketHotTab('money')">💰 资金流向</button>
      <button class="mhot-tab" onclick="switchMarketHotTab('sentiment')">🌡️ 市场情绪</button>
    </div>

    <div id="mhotContent"><div class="loading"><div class="spinner"></div>加载市场热度数据...</div></div>
  `;

  // 注入 tab 样式
  _injectMarketHotStyles();

  await refreshMarketHot();
}

function _injectMarketHotStyles() {
  if (document.getElementById('mhot-styles')) return;
  const style = document.createElement('style');
  style.id = 'mhot-styles';
  style.textContent = `
    .mhot-tab {
      padding: 8px 16px; border-radius: 6px; border: none; font-size: 13px; font-weight: 600;
      background: transparent; color: var(--text-secondary); cursor: pointer; transition: all 0.2s;
      white-space: nowrap;
    }
    .mhot-tab:hover { color: var(--color-foreground); background: rgba(245,158,11,0.1); }
    .mhot-tab.active { background: var(--color-primary); color: var(--color-on-primary); }

    .mhot-stat-card {
      background: linear-gradient(135deg, #1E293B 0%, #0F172A 100%);
      border: 1px solid var(--color-border); border-radius: var(--radius-lg);
      padding: 20px; text-align: center;
    }
    .mhot-stat-val {
      font-family: var(--font-mono); font-size: 28px; font-weight: 700; letter-spacing: -1px;
    }
    .mhot-stat-label { font-size: 12px; color: var(--text-muted); margin-top: 4px; }

    .mhot-badge {
      display: inline-flex; align-items: center; padding: 2px 8px; border-radius: 4px;
      font-size: 11px; font-weight: 700; font-family: var(--font-mono);
    }
    .mhot-badge-1 { background: rgba(239,68,68,0.15); color: #EF4444; }
    .mhot-badge-2 { background: rgba(245,158,11,0.15); color: #F59E0B; }
    .mhot-badge-3 { background: rgba(139,92,246,0.15); color: #8B5CF6; }
    .mhot-badge-4plus { background: rgba(59,130,246,0.2); color: #3B82F6; }

    .mhot-flow-bar { height: 8px; border-radius: 4px; background: rgba(51,65,85,0.5); overflow: hidden; }
    .mhot-flow-fill { height: 100%; border-radius: 4px; transition: width 0.3s ease; }

    .mhot-temp-ring {
      width: 140px; height: 140px; border-radius: 50%; display: flex; align-items: center;
      justify-content: center; margin: 0 auto 16px; position: relative;
    }
    .mhot-temp-ring::before {
      content: ''; position: absolute; inset: 0; border-radius: 50%;
      border: 6px solid rgba(51,65,85,0.5);
    }
    .mhot-temp-ring::after {
      content: ''; position: absolute; inset: 0; border-radius: 50%;
      border: 6px solid transparent; border-top-color: var(--color-primary);
      animation: mhot-spin 1s linear infinite;
    }
    @keyframes mhot-spin { to { transform: rotate(360deg); } }
  `;
  document.head.appendChild(style);
}

function switchMarketHotTab(tab) {
  _marketHotTab = tab;
  document.querySelectorAll('.mhot-tab').forEach(el => el.classList.remove('active'));
  event.target.classList.add('active');
  refreshMarketHot();
}

async function refreshMarketHot() {
  const container = document.getElementById('mhotContent');
  if (!container) return;
  container.innerHTML = '<div class="loading"><div class="spinner"></div>加载中...</div>';

  // 更新时间
  const timeEl = document.getElementById('mhotUpdateTime');
  if (timeEl) {
    const now = new Date();
    timeEl.textContent = `${now.getHours().toString().padStart(2,'0')}:${now.getMinutes().toString().padStart(2,'0')}:${now.getSeconds().toString().padStart(2,'0')}`;
  }

  try {
    switch (_marketHotTab) {
      case 'limit': await _renderLimitTab(container); break;
      case 'dragon': await _renderDragonTab(container); break;
      case 'money': await _renderMoneyTab(container); break;
      case 'sentiment': await _renderSentimentTab(container); break;
    }
  } catch (err) {
    container.innerHTML = `
      <div class="card" style="text-align:center;padding:40px">
        <p style="color:var(--text-muted);margin-bottom:16px">📡 数据加载失败</p>
        <p style="font-size:13px;color:var(--text-muted)">${err?.message || '请检查后端服务'}</p>
        <button class="btn btn-outline" style="margin-top:16px" onclick="refreshMarketHot()">🔄 重试</button>
      </div>
    `;
  }
}


// ================================================================
// 1. 涨停&连板榜
// ================================================================
async function _renderLimitTab(container) {
  const resp = await API.getLimitList();
  const data = resp?.data || resp;
  if (!data || !data.limit_up_list) {
    container.innerHTML = '<div class="card" style="text-align:center;padding:40px;color:var(--text-muted)">暂无涨停数据（可能非交易日）</div>';
    return;
  }

  const { limit_up_list = [], consecutive_stats = {}, summary = {}, date } = data;
  const byDays = consecutive_stats?.by_days || {};

  container.innerHTML = `
    <!-- 统计卡片 -->
    <div class="grid-4" style="margin-bottom:24px">
      <div class="mhot-stat-card">
        <div class="mhot-stat-val" style="color:var(--color-up)">${summary.total_limit_up || 0}</div>
        <div class="mhot-stat-label">涨停家数</div>
      </div>
      <div class="mhot-stat-card">
        <div class="mhot-stat-val" style="color:#F59E0B">${consecutive_stats.max_days || 0}</div>
        <div class="mhot-stat-label">最高连板</div>
      </div>
      <div class="mhot-stat-card">
        <div class="mhot-stat-val" style="color:#8B5CF6">${summary.consecutive_2_plus || 0}</div>
        <div class="mhot-stat-label">2连板+</div>
      </div>
      <div class="mhot-stat-card">
        <div class="mhot-stat-val">${date || '-'}</div>
        <div class="mhot-stat-label">数据日期</div>
      </div>
    </div>

    <!-- 连板分布 -->
    ${Object.keys(byDays).length > 0 ? `
    <div class="card" style="margin-bottom:24px">
      <div class="card-title">📊 连板分布</div>
      <div style="display:flex;gap:12px;flex-wrap:wrap">
        ${Object.entries(byDays)
          .sort((a, b) => b[1].days - a[1].days)
          .map(([key, val]) => `
            <div style="background:var(--color-muted);border-radius:8px;padding:12px 16px;min-width:120px">
              <div style="font-family:var(--font-mono);font-size:18px;font-weight:700;color:var(--color-up)">${val.count}</div>
              <div style="font-size:12px;color:var(--text-secondary)">${key}</div>
              <div style="margin-top:6px;font-size:11px;color:var(--text-muted);max-height:60px;overflow:hidden">
                ${val.stocks.slice(0, 3).map(s => s.name || s.ts_code).join('、')}
                ${val.stocks.length > 3 ? `等${val.stocks.length}只` : ''}
              </div>
            </div>
          `).join('')}
      </div>
    </div>
    ` : ''}

    <!-- 涨停明细表 -->
    <div class="card" style="padding:0;overflow:hidden">
      <div class="card-title" style="padding:20px 24px 0">📋 涨停明细 (${limit_up_list.length}只)</div>
      <table class="data-table">
        <thead>
          <tr>
            <th>代码</th>
            <th>名称</th>
            <th style="text-align:right">现价</th>
            <th style="text-align:right">涨跌幅</th>
            <th style="text-align:center">连板</th>
            <th style="text-align:right">成交额(万)</th>
            <th style="text-align:right">封板率</th>
            <th>首封时间</th>
          </tr>
        </thead>
        <tbody>
          ${limit_up_list.map(s => {
            const days = s.limit_days || 1;
            const badgeClass = days >= 4 ? 'mhot-badge-4plus' : `mhot-badge-${days}`;
            const amt = s.amount ? (s.amount / 10000).toFixed(0) : '-';
            return `
              <tr>
                <td style="font-family:var(--font-mono)">${s.ts_code || '-'}</td>
                <td style="font-weight:600">${s.name || '-'}</td>
                <td style="text-align:right;font-family:var(--font-mono);font-weight:600">${s.price || '-'}</td>
                <td style="text-align:right;font-family:var(--font-mono);color:var(--color-up);font-weight:600">
                  ${s.pct_chg != null ? '+' + s.pct_chg.toFixed(2) + '%' : '-'}
                </td>
                <td style="text-align:center">
                  <span class="mhot-badge ${badgeClass}">${days}板</span>
                </td>
                <td style="text-align:right;font-family:var(--font-mono);color:var(--text-secondary)">${amt}</td>
                <td style="text-align:right;font-family:var(--font-mono);color:var(--text-secondary)">
                  ${s.seal_ratio != null ? s.seal_ratio + '%' : '-'}
                </td>
                <td style="font-family:var(--font-mono);font-size:12px;color:var(--text-muted)">${s.first_time || '-'}</td>
              </tr>
            `;
          }).join('')}
        </tbody>
      </table>
    </div>
  `;
}


// ================================================================
// 2. 龙虎榜
// ================================================================
async function _renderDragonTab(container) {
  const resp = await API.getTopList();
  const data = resp?.data || resp;
  if (!data || !data.top_list) {
    container.innerHTML = '<div class="card" style="text-align:center;padding:40px;color:var(--text-muted)">暂无龙虎榜数据</div>';
    return;
  }

  const { top_list = [], institutional = {}, hot_money = {}, summary = {}, date } = data;

  container.innerHTML = `
    <!-- 统计卡片 -->
    <div class="grid-4" style="margin-bottom:24px">
      <div class="mhot-stat-card">
        <div class="mhot-stat-val" style="color:var(--color-up)">${summary.total_stocks || 0}</div>
        <div class="mhot-stat-label">上榜个股</div>
      </div>
      <div class="mhot-stat-card">
        <div class="mhot-stat-val">${summary.total_net_buy != null ? (summary.total_net_buy / 10000).toFixed(0) + '万' : '-'}</div>
        <div class="mhot-stat-label">总净买入</div>
      </div>
      <div class="mhot-stat-card">
        <div class="mhot-stat-val" style="color:#8B5CF6">${Object.keys(institutional).length}</div>
        <div class="mhot-stat-label">机构参与</div>
      </div>
      <div class="mhot-stat-card">
        <div class="mhot-stat-val" style="color:#F59E0B">${Object.keys(hot_money).length}</div>
        <div class="mhot-stat-label">游资营业部</div>
      </div>
    </div>

    <!-- 龙虎榜个股明细 -->
    <div class="card" style="padding:0;overflow:hidden;margin-bottom:24px">
      <div class="card-title" style="padding:20px 24px 0">🏆 上榜个股明细 (${top_list.length}只)</div>
      <table class="data-table">
        <thead>
          <tr>
            <th>代码</th>
            <th>名称</th>
            <th style="text-align:right">收盘价</th>
            <th style="text-align:right">涨跌幅</th>
            <th>上榜原因</th>
            <th style="text-align:right">买入额(万)</th>
            <th style="text-align:right">卖出额(万)</th>
            <th style="text-align:right">净买入(万)</th>
          </tr>
        </thead>
        <tbody>
          ${top_list.map(s => {
            const isNetBuy = (s.net_buy || 0) >= 0;
            return `
              <tr>
                <td style="font-family:var(--font-mono)">${s.ts_code || '-'}</td>
                <td style="font-weight:600">${s.name || '-'}</td>
                <td style="text-align:right;font-family:var(--font-mono)">${s.close || '-'}</td>
                <td style="text-align:right;font-family:var(--font-mono);font-weight:600;color:${(s.pct_chg||0) >= 0 ? 'var(--color-up)' : 'var(--color-down)'}">
                  ${s.pct_chg != null ? (s.pct_chg >= 0 ? '+' : '') + s.pct_chg.toFixed(2) + '%' : '-'}
                </td>
                <td><span class="tag tag-blue">${s.reason || '-'}</span></td>
                <td style="text-align:right;font-family:var(--font-mono);color:var(--color-up)">${s.buy_amount ? (s.buy_amount / 10000).toFixed(0) : '-'}</td>
                <td style="text-align:right;font-family:var(--font-mono);color:var(--color-down)">${s.sell_amount ? (s.sell_amount / 10000).toFixed(0) : '-'}</td>
                <td style="text-align:right;font-family:var(--font-mono);font-weight:700;color:${isNetBuy ? 'var(--color-up)' : 'var(--color-down)'}">
                  ${s.net_buy != null ? (isNetBuy ? '+' : '') + (s.net_buy / 10000).toFixed(0) : '-'}
                </td>
              </tr>
            `;
          }).join('')}
        </tbody>
      </table>
    </div>

    <!-- 游资 TOP20 -->
    ${Object.keys(hot_money).length > 0 ? `
    <div class="card" style="padding:0;overflow:hidden">
      <div class="card-title" style="padding:20px 24px 0">🎭 游资营业部 TOP20</div>
      <table class="data-table">
        <thead>
          <tr>
            <th style="width:40px">#</th>
            <th>营业部</th>
            <th style="text-align:right">买入(万)</th>
            <th style="text-align:right">卖出(万)</th>
            <th style="text-align:right">净额(万)</th>
            <th>操作个股</th>
          </tr>
        </thead>
        <tbody>
          ${Object.entries(hot_money).map(([name, info], i) => {
            const net = info.net || 0;
            const isBuy = net >= 0;
            return `
              <tr>
                <td style="font-family:var(--font-mono);color:var(--text-muted)">${i + 1}</td>
                <td style="font-weight:600;font-size:13px">${name}</td>
                <td style="text-align:right;font-family:var(--font-mono);color:var(--color-up)">${(info.buy / 10000).toFixed(0)}</td>
                <td style="text-align:right;font-family:var(--font-mono);color:var(--color-down)">${(info.sell / 10000).toFixed(0)}</td>
                <td style="text-align:right;font-family:var(--font-mono);font-weight:700;color:${isBuy ? 'var(--color-up)' : 'var(--color-down)'}">
                  ${isBuy ? '+' : ''}${(net / 10000).toFixed(0)}
                </td>
                <td style="font-size:12px;color:var(--text-secondary)">
                  ${(info.stocks || []).slice(0, 3).map(s => s.name || s.ts_code).join('、')}
                  ${(info.stocks || []).length > 3 ? `等${info.stocks.length}只` : ''}
                </td>
              </tr>
            `;
          }).join('')}
        </tbody>
      </table>
    </div>
    ` : ''}
  `;
}


// ================================================================
// 3. 资金流向
// ================================================================
async function _renderMoneyTab(container) {
  const resp = await API.getMoneyflow(5);
  const data = resp?.data || resp;
  if (!data) {
    container.innerHTML = '<div class="card" style="text-align:center;padding:40px;color:var(--text-muted)">暂无资金流向数据</div>';
    return;
  }

  const { northbound = {}, top_inflow = [], top_outflow = [] } = data;
  const history = northbound.history || [];
  const latest = northbound.latest || {};

  container.innerHTML = `
    <!-- 北向资金概况 -->
    <div class="grid-3" style="margin-bottom:24px">
      <div class="mhot-stat-card">
        <div class="mhot-stat-val" style="color:${(latest.north_money || 0) >= 0 ? 'var(--color-up)' : 'var(--color-down)'}">
          ${latest.north_money != null ? (latest.north_money >= 0 ? '+' : '') + latest.north_money.toFixed(2) + '亿' : '-'}
        </div>
        <div class="mhot-stat-label">今日北向净流入</div>
      </div>
      <div class="mhot-stat-card">
        <div class="mhot-stat-val" style="color:${(northbound.avg_daily || 0) >= 0 ? 'var(--color-up)' : 'var(--color-down)'}">
          ${northbound.avg_daily != null ? (northbound.avg_daily >= 0 ? '+' : '') + northbound.avg_daily.toFixed(2) + '亿' : '-'}
        </div>
        <div class="mhot-stat-label">日均净流入</div>
      </div>
      <div class="mhot-stat-card">
        <div class="mhot-stat-val">${northbound.total_net != null ? (northbound.total_net >= 0 ? '+' : '') + northbound.total_net.toFixed(2) + '亿' : '-'}</div>
        <div class="mhot-stat-label">区间累计净流入</div>
      </div>
    </div>

    <!-- 北向资金趋势 -->
    ${history.length > 0 ? `
    <div class="card" style="margin-bottom:24px">
      <div class="card-title">📈 北向资金近${history.length}日趋势</div>
      <div style="display:flex;align-items:flex-end;gap:8px;height:120px;padding:0 4px">
        ${history.slice().reverse().map(h => {
          const val = h.north_money || 0;
          const maxVal = Math.max(...history.map(x => Math.abs(x.north_money || 0)), 1);
          const height = Math.max(4, Math.abs(val) / maxVal * 100);
          const isUp = val >= 0;
          return `
            <div style="flex:1;display:flex;flex-direction:column;align-items:center;gap:4px">
              <span style="font-size:10px;font-family:var(--font-mono);color:${isUp ? 'var(--color-up)' : 'var(--color-down)'};font-weight:600">
                ${val >= 0 ? '+' : ''}${val.toFixed(0)}
              </span>
              <div style="width:100%;height:${height}px;background:${isUp ? 'var(--color-up)' : 'var(--color-down)'};border-radius:4px 4px 0 0;min-height:4px;opacity:0.8"></div>
              <span style="font-size:9px;color:var(--text-muted);font-family:var(--font-mono)">${(h.date || '').slice(-4)}</span>
            </div>
          `;
        }).join('')}
      </div>
    </div>
    ` : ''}

    <!-- 个股资金流 TOP -->
    <div class="grid-2">
      <!-- 净流入 TOP -->
      <div class="card" style="padding:0;overflow:hidden">
        <div class="card-title" style="padding:20px 24px 0">💰 净流入 TOP20</div>
        <table class="data-table">
          <thead>
            <tr><th>#</th><th>代码</th><th style="text-align:right">净流入(万)</th></tr>
          </thead>
          <tbody>
            ${top_inflow.map((s, i) => `
              <tr>
                <td style="font-family:var(--font-mono);color:var(--text-muted)">${i + 1}</td>
                <td style="font-family:var(--font-mono);font-weight:600">${s.ts_code || '-'}</td>
                <td style="text-align:right;font-family:var(--font-mono);font-weight:600;color:var(--color-up)">
                  +${(s.net_mf / 10000).toFixed(0)}
                </td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>

      <!-- 净流出 TOP -->
      <div class="card" style="padding:0;overflow:hidden">
        <div class="card-title" style="padding:20px 24px 0">💸 净流出 TOP20</div>
        <table class="data-table">
          <thead>
            <tr><th>#</th><th>代码</th><th style="text-align:right">净流出(万)</th></tr>
          </thead>
          <tbody>
            ${top_outflow.map((s, i) => `
              <tr>
                <td style="font-family:var(--font-mono);color:var(--text-muted)">${i + 1}</td>
                <td style="font-family:var(--font-mono);font-weight:600">${s.ts_code || '-'}</td>
                <td style="text-align:right;font-family:var(--font-mono);font-weight:600;color:var(--color-down)">
                  ${(s.net_mf / 10000).toFixed(0)}
                </td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>
    </div>
  `;
}


// ================================================================
// 4. 市场情绪聚合
// ================================================================
async function _renderSentimentTab(container) {
  const resp = await API.getMarketSentiment();
  const data = resp?.data || resp;
  if (!data) {
    container.innerHTML = '<div class="card" style="text-align:center;padding:40px;color:var(--text-muted)">暂无情绪数据</div>';
    return;
  }

  const { limit_summary = {}, top_list_summary = {}, moneyflow_summary = {}, sentiment_score = 50, sentiment_label = '🌤️ 中性' } = data;

  // 温度颜色
  let tempColor;
  if (sentiment_score >= 75) tempColor = '#EF4444';
  else if (sentiment_score >= 60) tempColor = '#F59E0B';
  else if (sentiment_score >= 40) tempColor = '#3B82F6';
  else if (sentiment_score >= 25) tempColor = '#F97316';
  else tempColor = '#22C55E';

  container.innerHTML = `
    <!-- 情绪评分大圆 -->
    <div class="card" style="text-align:center;padding:40px;margin-bottom:24px">
      <div class="mhot-temp-ring">
        <div>
          <div style="font-family:var(--font-mono);font-size:48px;font-weight:700;color:${tempColor}">${sentiment_score}</div>
          <div style="font-size:14px;color:var(--text-muted)">/ 100</div>
        </div>
      </div>
      <div style="font-size:24px;font-weight:700;margin-bottom:8px">${sentiment_label}</div>
      <div style="font-size:13px;color:var(--text-muted)">综合涨停、龙虎榜、北向资金多维度计算</div>

      <!-- 温度条 -->
      <div style="margin:24px auto 0;width:60%;height:10px;border-radius:5px;background:linear-gradient(90deg, #22C55E, #F59E0B, #EF4444);position:relative">
        <div style="position:absolute;top:-8px;left:${sentiment_score}%;transform:translateX(-50%);width:18px;height:26px;border-radius:4px;background:${tempColor};border:3px solid var(--color-foreground);transition:left 0.5s ease"></div>
      </div>
      <div style="display:flex;justify-content:space-between;width:60%;margin:6px auto 0;font-size:11px;color:var(--text-muted)">
        <span>极度低迷</span><span>中性</span><span>极度亢奋</span>
      </div>
    </div>

    <!-- 三维度卡片 -->
    <div class="grid-3" style="margin-bottom:24px">
      <!-- 涨停维度 -->
      <div class="card">
        <div class="card-title">🔥 涨停情绪</div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px">
          <div>
            <div style="font-family:var(--font-mono);font-size:24px;font-weight:700;color:var(--color-up)">${limit_summary.total_limit_up || 0}</div>
            <div style="font-size:12px;color:var(--text-muted)">涨停家数</div>
          </div>
          <div>
            <div style="font-family:var(--font-mono);font-size:24px;font-weight:700;color:#F59E0B">${limit_summary.max_consecutive || 0}</div>
            <div style="font-size:12px;color:var(--text-muted)">最高连板</div>
          </div>
        </div>
        <div style="margin-top:16px;padding-top:12px;border-top:1px solid var(--color-border);font-size:12px;color:var(--text-muted)">
          2连板以上: <strong style="color:#8B5CF6">${limit_summary.consecutive_2_plus || 0}</strong> 只
        </div>
      </div>

      <!-- 龙虎榜维度 -->
      <div class="card">
        <div class="card-title">🏆 龙虎榜活跃度</div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px">
          <div>
            <div style="font-family:var(--font-mono);font-size:24px;font-weight:700;color:var(--color-up)">${top_list_summary.total_stocks || 0}</div>
            <div style="font-size:12px;color:var(--text-muted)">上榜个股</div>
          </div>
          <div>
            <div style="font-family:var(--font-mono);font-size:24px;font-weight:700;color:#8B5CF6">${top_list_summary.hot_money_count || 0}</div>
            <div style="font-size:12px;color:var(--text-muted)">游资营业部</div>
          </div>
        </div>
        <div style="margin-top:16px;padding-top:12px;border-top:1px solid var(--color-border);font-size:12px;color:var(--text-muted)">
          机构参与: <strong style="color:#3B82F6">${top_list_summary.institutional_count || 0}</strong> 只
        </div>
      </div>

      <!-- 资金维度 -->
      <div class="card">
        <div class="card-title">💰 北向资金</div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px">
          <div>
            <div style="font-family:var(--font-mono);font-size:24px;font-weight:700;color:${(moneyflow_summary.latest_flow || 0) >= 0 ? 'var(--color-up)' : 'var(--color-down)'}">
              ${moneyflow_summary.latest_flow != null ? (moneyflow_summary.latest_flow >= 0 ? '+' : '') + moneyflow_summary.latest_flow.toFixed(1) : '-'}
            </div>
            <div style="font-size:12px;color:var(--text-muted)">今日净流入(亿)</div>
          </div>
          <div>
            <div style="font-family:var(--font-mono);font-size:24px;font-weight:700;color:${(moneyflow_summary.avg_daily || 0) >= 0 ? 'var(--color-up)' : 'var(--color-down)'}">
              ${moneyflow_summary.avg_daily != null ? (moneyflow_summary.avg_daily >= 0 ? '+' : '') + moneyflow_summary.avg_daily.toFixed(1) : '-'}
            </div>
            <div style="font-size:12px;color:var(--text-muted)">日均(亿)</div>
          </div>
        </div>
        <div style="margin-top:16px;padding-top:12px;border-top:1px solid var(--color-border);font-size:12px;color:var(--text-muted)">
          区间累计: <strong style="color:${(moneyflow_summary.total_net || 0) >= 0 ? 'var(--color-up)' : 'var(--color-down)'}">
            ${moneyflow_summary.total_net != null ? (moneyflow_summary.total_net >= 0 ? '+' : '') + moneyflow_summary.total_net.toFixed(1) + '亿' : '-'}
          </strong>
        </div>
      </div>
    </div>

    <!-- 数据时间 -->
    <div style="text-align:center;font-size:12px;color:var(--text-muted)">
      数据更新时间: ${data.timestamp || '-'}
    </div>
  `;
}
