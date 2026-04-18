/**
 * QuantWeave 仪表盘页面 v2.0
 * 展示真实持仓、账户概览、市场快报
 * 支持点击个股分析
 */
async function renderDashboard() {
  const main = document.getElementById('mainContent');
  main.innerHTML = `
    <div class="page-header">
      <h2>📊 仪表盘</h2>
      <p>实时掌控量化交易全局</p>
    </div>
    <div id="dashboardContent"><div class="loading"><div class="spinner"></div>加载中...</div></div>
  `;

  const container = document.getElementById('dashboardContent');

  // 并行加载所有数据
  const [accountInfo, positionsData, dashData, watchlistData] = await Promise.all([
    API.getAccountInfo('main').catch(() => null),
    API.getPositions('main').catch(() => null),
    API.getDashboard().catch(() => null),
    API.getWatchlist().catch(() => null),
  ]);

  // 提取持仓数据
  const summary = positionsData?.data || positionsData;
  const positions = summary?.positions || summary?.items || [];
  const account = accountInfo?.data || accountInfo;

  // 提取关注列表数据
  const watchlistItems = watchlistData?.items || [];

  renderDashboardV2(container, { account, positions, dashData, watchlistItems });
}

function renderDashboardV2(container, { account, positions, dashData, watchlistItems }) {
  // 计算持仓统计
  const totalMarketValue = positions.reduce((sum, p) => sum + (p.market_value || 0), 0);
  const totalCost = positions.reduce((sum, p) => sum + (p.cost_value || (p.avg_cost || 0) * (p.volume || 0)), 0);
  const totalProfit = totalMarketValue - totalCost;
  const profitPct = totalCost > 0 ? (totalProfit / totalCost * 100) : 0;

  // 系统状态
  const isOnline = dashData && dashData.system_status === 'online';
  const statusColor = isOnline ? 'var(--color-up)' : 'var(--color-warning)';
  const statusText = isOnline ? '在线' : '离线';

  container.innerHTML = `
    <!-- 系统状态条 -->
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:20px;padding:8px 16px;background:var(--surface);border-radius:var(--radius);font-size:13px">
      <span style="width:8px;height:8px;border-radius:50%;background:${statusColor};display:inline-block"></span>
      <span style="color:var(--text-secondary)">系统状态: <strong style="color:${statusColor}">${statusText}</strong></span>
      <span style="color:var(--text-muted);margin-left:8px">|</span>
      <span style="color:var(--text-muted);margin-left:8px">持仓 ${positions.length} 只</span>
      <span style="color:var(--text-muted);margin-left:8px">关注 ${watchlistItems.length} 只</span>
    </div>

    <!-- 账户概览卡片 -->
    <div class="grid-4" style="margin-bottom:20px">
      <div class="card">
        <div class="card-title">💰 总资产</div>
        <div class="stat-value">${fmtDash(account?.total_assets || 0)}</div>
        <div class="stat-change ${(account?.profit_pct || 0) >= 0 ? 'up' : 'down'}">
          ${(account?.profit_pct || 0) >= 0 ? '▲' : '▼'} ${Math.abs(account?.profit_pct || 0).toFixed(2)}%
        </div>
      </div>
      <div class="card">
        <div class="card-title">💵 现金余额</div>
        <div class="stat-value">${fmtDash(account?.cash_balance || 0)}</div>
      </div>
      <div class="card">
        <div class="card-title">📊 持仓市值</div>
        <div class="stat-value">${fmtDash(totalMarketValue)}</div>
      </div>
      <div class="card">
        <div class="card-title">📈 浮动盈亏</div>
        <div class="stat-value ${totalProfit >= 0 ? 'positive' : 'negative'}">
          ${totalProfit >= 0 ? '+' : ''}${fmtDash(totalProfit)}
        </div>
        <div class="stat-change ${profitPct >= 0 ? 'up' : 'down'}">
          ${profitPct >= 0 ? '▲' : '▼'} ${Math.abs(profitPct).toFixed(2)}%
        </div>
      </div>
    </div>

    <div class="grid-2">
      <!-- 左：持仓列表 -->
      <div class="card" style="grid-column:span 1">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
          <div class="card-title" style="margin-bottom:0">📋 当前持仓</div>
          <button class="btn btn-sm btn-outline" onclick="syncAllPositionsDash()">🔄 同步价格</button>
        </div>
        ${positions.length === 0 ? `
          <div class="dash-empty">
            <div style="font-size:40px;margin-bottom:12px">📭</div>
            <p>暂无持仓数据</p>
            <p style="font-size:13px;color:var(--text-muted)">前往「持仓管理」添加持仓</p>
            <button class="btn btn-sm btn-primary" style="margin-top:12px" onclick="navigateTo('portfolio')">添加持仓</button>
          </div>
        ` : `
          <div class="dash-position-list">
            ${positions.map(p => {
              const cost = p.cost_value || (p.avg_cost || 0) * (p.volume || 0);
              const profit = (p.market_value || 0) - cost;
              const pct = cost > 0 ? (profit / cost * 100) : 0;
              const isUp = profit >= 0;
              return `
                <div class="dash-position-item" onclick="openStockAnalysis('${escapeHtml(p.ts_code || '')}','${escapeHtml(p.name || '')}')">
                  <div class="dash-pos-info">
                    <div class="dash-pos-name">${escapeHtml(p.name || p.ts_code)}</div>
                    <div class="dash-pos-code">${p.ts_code || ''} · ${p.volume || 0}股</div>
                  </div>
                  <div class="dash-pos-price">
                    <div class="dash-pos-val">${(p.current_price || 0).toFixed(2)}</div>
                    <div class="dash-pos-pnl ${isUp ? 'positive' : 'negative'}">
                      ${isUp ? '+' : ''}${fmtDash(profit)} (${isUp ? '+' : ''}${pct.toFixed(1)}%)
                    </div>
                  </div>
                  <div class="dash-pos-action">
                    <span class="btn-analyze">分析 →</span>
                  </div>
                </div>
              `;
            }).join('')}
          </div>
          <div style="text-align:center;margin-top:12px">
            <button class="btn btn-sm btn-outline" onclick="navigateTo('portfolio')">查看全部持仓 →</button>
          </div>
        `}
      </div>

      <!-- 右：关注列表快报 + 快捷入口 -->
      <div style="display:flex;flex-direction:column;gap:20px">
        <!-- 关注列表快报 -->
        <div class="card">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
            <div class="card-title" style="margin-bottom:0">⭐ 关注快报</div>
            <button class="btn btn-sm btn-outline" onclick="navigateTo('watchlist')">管理 →</button>
          </div>
          ${watchlistItems.length === 0 ? `
            <div class="dash-empty" style="padding:20px">
              <p style="color:var(--text-muted)">关注列表为空</p>
              <button class="btn btn-sm btn-primary" style="margin-top:8px" onclick="navigateTo('watchlist')">添加关注</button>
            </div>
          ` : `
            <div class="dash-watchlist-mini">
              ${watchlistItems.slice(0, 6).map(w => `
                <div class="dash-wl-item" onclick="openStockAnalysis('${escapeHtml(w.ts_code)}','${escapeHtml(w.name || '')}')">
                  <div class="dash-wl-name">${escapeHtml(w.name || w.ts_code)}</div>
                  <div class="dash-wl-code">${w.ts_code}</div>
                </div>
              `).join('')}
              ${watchlistItems.length > 6 ? `
                <div class="dash-wl-more">+${watchlistItems.length - 6} 更多</div>
              ` : ''}
            </div>
          `}
        </div>

        <!-- 快捷入口 -->
        <div class="card">
          <div class="card-title">⚡ 快捷操作</div>
          <div class="dash-shortcuts">
            <div class="dash-shortcut-btn" onclick="navigateTo('screening')">
              <span style="font-size:24px">🔍</span>
              <span>智能选股</span>
            </div>
            <div class="dash-shortcut-btn" onclick="navigateTo('signals')">
              <span style="font-size:24px">📡</span>
              <span>每日信号</span>
            </div>
            <div class="dash-shortcut-btn" onclick="navigateTo('backtest')">
              <span style="font-size:24px">📈</span>
              <span>策略回测</span>
            </div>
            <div class="dash-shortcut-btn" onclick="navigateTo('market')">
              <span style="font-size:24px">🌐</span>
              <span>市场总览</span>
            </div>
          </div>
        </div>

        <!-- 策略概况（来自 dashboard API） -->
        <div class="card">
          <div class="card-title">🎯 策略概况</div>
          <div class="dash-strategy-summary">
            ${dashData && dashData.active_strategies ? `
              <div style="display:flex;justify-content:space-between;margin-bottom:8px">
                <span style="color:var(--text-secondary)">活跃策略</span>
                <span style="font-weight:600">${dashData.active_strategies}</span>
              </div>
              <div style="display:flex;justify-content:space-between;margin-bottom:8px">
                <span style="color:var(--text-secondary)">综合胜率</span>
                <span style="font-weight:600">${(dashData.win_rate || 0).toFixed(1)}%</span>
              </div>
              <div style="display:flex;justify-content:space-between">
                <span style="color:var(--text-secondary)">风控告警</span>
                <span style="font-weight:600;color:${(dashData.unresolved_alerts || 0) > 0 ? 'var(--color-down)' : 'var(--color-up)'}">
                  ${(dashData.unresolved_alerts || 0) > 0 ? dashData.unresolved_alerts : '无'}
                </span>
              </div>
            ` : `
              <div style="text-align:center;color:var(--text-muted);padding:12px">
                启动后端查看策略数据
              </div>
            `}
          </div>
        </div>
      </div>
    </div>

    <!-- 底部：个股分析弹窗（全局复用） -->
    <div id="dashAnalysisModal" class="modal" style="display:none">
      <div class="modal-content" style="max-width:860px">
        <div class="modal-header">
          <div class="modal-title">📊 个股深度分析</div>
          <button class="modal-close" onclick="closeStockAnalysisModal()">×</button>
        </div>
        <div id="dashAnalysisContent" class="modal-body">
        </div>
      </div>
    </div>
  `;
}

// ========== 点击分析（委托给统一入口） ==========
async function openStockAnalysis(tsCode, name) {
  await openStockAnalysisModal(tsCode, name);
}

// 备用分析渲染（screening.js 未加载时）
function renderDashAnalysis(data) {
  const latest = data.latest || {};
  const rec = data.recommendation || {};

  return `
    <div class="info-grid" style="margin-bottom:16px">
      <div class="info-item">
        <span class="info-label">代码</span>
        <span class="info-value"><code>${data.ts_code}</code></span>
      </div>
      <div class="info-item">
        <span class="info-label">最新价</span>
        <span class="info-value ${(latest.change_pct || 0) >= 0 ? 'positive' : 'negative'}">
          ¥${(latest.close || 0).toFixed(2)}
        </span>
      </div>
      <div class="info-item">
        <span class="info-label">涨跌幅</span>
        <span class="info-value ${(latest.change_pct || 0) >= 0 ? 'positive' : 'negative'}">
          ${(latest.change_pct || 0) >= 0 ? '▲' : '▼'} ${Math.abs(latest.change_pct || 0).toFixed(2)}%
        </span>
      </div>
      <div class="info-item">
        <span class="info-label">日期</span>
        <span class="info-value">${latest.date || '—'}</span>
      </div>
    </div>
    ${rec.reason ? `
      <div style="background:var(--surface);border-radius:var(--radius);padding:16px;margin-bottom:16px">
        <strong>🎯 综合建议：</strong>
        <span class="tag ${rec.action === 'buy' ? 'tag-red' : rec.action === 'sell' ? 'tag-green' : 'tag-gray'}">
          ${rec.level || '—'}
        </span>
        <p style="margin-top:8px;color:var(--text-secondary)">${rec.reason}</p>
      </div>
    ` : ''}
    <div class="modal-actions" style="margin-top:16px">
      <button class="btn btn-primary" onclick="addToWatchlistFromDash('${escapeHtml(data.ts_code)}','${escapeHtml(latest.name || '')}')">👁️ 加入关注</button>
      <button class="btn btn-outline" onclick="closeStockAnalysisModal()">关闭</button>
    </div>
  `;
}

function closeDashAnalysis() {
  closeStockAnalysisModal();
}

async function addToWatchlistFromDash(tsCode, name) {
  try {
    const result = await API.addToWatchlist(tsCode, name);
    if (result && result.success) {
      showToast(`✅ ${name || tsCode} 已加入关注列表`, 'success');
    } else {
      showToast('添加失败，可能已在关注列表中', 'error');
    }
  } catch (err) {
    showToast('添加失败: ' + err.message, 'error');
  }
}

// ========== 同步持仓价格 ==========
async function syncAllPositionsDash() {
  showToast('正在同步持仓价格...', 'info');
  try {
    const result = await API.syncPositions('main');
    if (result && result.success) {
      showToast('同步成功', 'success');
      renderDashboard();
    } else {
      showToast(result?.message || '同步失败', 'error');
    }
  } catch (err) {
    showToast('同步失败: ' + err.message, 'error');
  }
}

// ========== 工具函数 ==========
function fmtDash(num) {
  if (num === null || num === undefined) return '0';
  return Number(num).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/**
 * escapeHtml 已在 app.js 全局定义，此处无需重复
 */

// ========== Dashboard 专用样式 ==========
(function addDashStyles() {
  if (document.getElementById('dashboard-v2-styles')) return;

  const style = document.createElement('style');
  style.id = 'dashboard-v2-styles';
  style.textContent = `
    .dash-empty {
      text-align: center;
      padding: 40px 20px;
      color: var(--text-muted);
    }
    .dash-position-list {
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
    .dash-position-item {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 14px 16px;
      background: var(--surface);
      border-radius: var(--radius);
      border: 1px solid transparent;
      cursor: pointer;
      transition: all 0.2s;
    }
    .dash-position-item:hover {
      border-color: var(--primary);
      background: var(--surface-hover);
      transform: translateX(4px);
    }
    .dash-pos-info {
      flex: 1;
      min-width: 0;
    }
    .dash-pos-name {
      font-weight: 600;
      font-size: 15px;
      color: var(--text);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .dash-pos-code {
      font-size: 12px;
      color: var(--text-muted);
      font-family: var(--font-mono);
      margin-top: 2px;
    }
    .dash-pos-price {
      text-align: right;
      margin: 0 16px;
    }
    .dash-pos-val {
      font-weight: 600;
      font-size: 16px;
      font-family: var(--font-mono);
    }
    .dash-pos-pnl {
      font-size: 13px;
      font-weight: 600;
      font-family: var(--font-mono);
      margin-top: 2px;
    }
    .dash-pos-action {
      opacity: 0;
      transition: opacity 0.2s;
    }
    .dash-position-item:hover .dash-pos-action {
      opacity: 1;
    }
    .btn-analyze {
      font-size: 13px;
      color: var(--primary);
      font-weight: 600;
    }
    .dash-watchlist-mini {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 8px;
    }
    .dash-wl-item {
      text-align: center;
      padding: 10px 8px;
      background: var(--surface);
      border-radius: var(--radius);
      cursor: pointer;
      transition: all 0.2s;
      border: 1px solid transparent;
    }
    .dash-wl-item:hover {
      border-color: var(--primary);
      transform: translateY(-2px);
    }
    .dash-wl-name {
      font-size: 13px;
      font-weight: 600;
      color: var(--text);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .dash-wl-code {
      font-size: 11px;
      color: var(--text-muted);
      font-family: var(--font-mono);
      margin-top: 2px;
    }
    .dash-wl-more {
      text-align: center;
      color: var(--text-muted);
      font-size: 13px;
      padding: 10px;
      grid-column: span 3;
    }
    .dash-shortcuts {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 10px;
    }
    .dash-shortcut-btn {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 6px;
      padding: 14px 8px;
      background: var(--surface);
      border-radius: var(--radius);
      cursor: pointer;
      transition: all 0.2s;
      font-size: 13px;
      font-weight: 500;
      color: var(--text-secondary);
      border: 1px solid transparent;
    }
    .dash-shortcut-btn:hover {
      border-color: var(--primary);
      color: var(--primary);
      transform: translateY(-2px);
    }
    .dash-strategy-summary {
      font-size: 14px;
    }
    @media (max-width: 1200px) {
      .dash-watchlist-mini {
        grid-template-columns: repeat(2, 1fr);
      }
      .dash-shortcuts {
        grid-template-columns: repeat(2, 1fr);
      }
    }
    @media (max-width: 768px) {
      .dash-position-item {
        flex-wrap: wrap;
        gap: 8px;
      }
      .dash-pos-action {
        opacity: 1;
      }
      .dash-shortcuts {
        grid-template-columns: repeat(2, 1fr);
      }
    }
  `;
  document.head.appendChild(style);
})();
