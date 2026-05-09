/**
 * QuantWeave 模拟盘页面
 * 超短线模拟交易 — 完全独立于核心策略
 */

// 保存 Chart 实例，防止重复创建
let _paperChartInstance = null;

function destroyPaperChart() {
  if (_paperChartInstance) {
    _paperChartInstance.destroy();
    _paperChartInstance = null;
  }
}

// 页面离开时的清理（由 app.js 调用）
function destroyPaper() {
  destroyPaperChart();
}

function renderPaper() {
  // 先销毁旧 chart
  destroyPaperChart();

  const mc = document.getElementById('mainContent');
  mc.innerHTML = `
    <div class="page-header">
      <h2>📝 超短线模拟盘</h2>
      <p>独立于核心策略的实验性交易系统 · 初始资金70万 · 日K级别验证</p>
    </div>

    <div style="display:flex;gap:10px;margin-bottom:24px;flex-wrap:wrap">
      <button class="btn btn-success" onclick="paperAction('scan')">🔍 手动扫描</button>
      <button class="btn btn-warning" onclick="paperAction('sell')">💰 卖出检测</button>
      <button class="btn btn-danger" onclick="paperConfirmReset()">🔄 重置账户</button>
      <button class="btn btn-secondary" onclick="loadPaperStatus()">🔄 刷新</button>
    </div>

    <div id="paperStats" class="grid-4" style="margin-bottom:24px">
      <div class="card"><div class="card-title">总资产</div><div class="loading"><div class="spinner"></div>加载中...</div></div>
      <div class="card"><div class="card-title">累计盈亏</div><div class="loading"><div class="spinner"></div></div></div>
      <div class="card"><div class="card-title">胜率 / 交易</div><div class="loading"><div class="spinner"></div></div></div>
      <div class="card"><div class="card-title">最大回撤 / 仓位</div><div class="loading"><div class="spinner"></div></div></div>
    </div>

    <div class="grid-2" style="margin-bottom:24px">
      <div class="card" id="paperPositionsCard">
        <div class="card-title">📋 当前持仓</div>
        <div class="loading"><div class="spinner"></div>加载中...</div>
      </div>
      <div class="card" id="paperTradesCard">
        <div class="card-title">📜 最近交易</div>
        <div class="loading"><div class="spinner"></div>加载中...</div>
      </div>
    </div>

    <div class="card" style="margin-bottom:24px">
      <div class="card-title">ℹ️ 系统说明</div>
      <div style="font-size:13px;color:var(--text-secondary);line-height:1.8">
        <b>超短线模拟盘</b> · 初始资金70万 · 最多3只同时持仓 · 总仓位≤50%<br>
        <b>选股模式</b>：隔夜T / D+2D+3低吸 / 强势回调（10分评分卡）<br>
        <b>退出机制</b>：硬止损-5% / 分段止盈(+3%→+5%→+8%) / 破涨停低点 / 最长持有2天 / 移动止盈<br>
        <b>自动调度</b>：14:50扫描买入 + 09:35卖出检测（交易日）<br>
        <b>⚠️ 注意</b>：日K回测收益为负，此模块仅供实盘信号跟踪验证，不作为投资建议
      </div>
    </div>
  `;
  loadPaperStatus();
}

async function loadPaperStatus() {
  const statsEl = document.getElementById('paperStats');
  if (!statsEl) return; // 页面已切走

  const r = await API.request('/paper/status', {}, 15000);
  if (!statsEl) return; // 再次检查（await 后页面可能已变）

  if (!r || r.error) {
    statsEl.innerHTML =
      '<div class="card" style="grid-column:span 4;text-align:center;padding:40px;color:var(--color-destructive)">❌ 无法获取模拟盘数据，请检查后端服务</div>';
    return;
  }

  const acc = r.account || {};
  const positions = r.positions || [];
  const trades = (r.recent_trades || []).slice(0, 30);
  const totalAssets = acc.total_assets || 700000;
  const cashBal = acc.cash_balance || 0;
  const totalProfit = acc.total_profit || 0;
  const profitPct = acc.total_profit_pct || 0;
  const maxDD = acc.max_drawdown || 0;
  const totalTrades = acc.total_trades || 0;
  const winTrades = acc.win_trades || 0;
  const winRate = totalTrades > 0 ? (winTrades / totalTrades * 100) : 0;
  const posCount = positions.length;
  const posPct = totalAssets > 0 ? ((totalAssets - cashBal) / totalAssets * 100) : 0;
  const profitClass = totalProfit >= 0 ? 'positive' : 'negative';

  // 统计卡片
  statsEl.innerHTML = `
    <div class="card">
      <div class="card-title">总资产</div>
      <div class="stat-value">¥${formatNumber(totalAssets)}</div>
      <div class="stat-change" style="color:var(--text-secondary)">现金 ¥${formatNumber(cashBal)}</div>
    </div>
    <div class="card">
      <div class="card-title">累计盈亏</div>
      <div class="stat-value ${profitClass}">¥${totalProfit >= 0 ? '+' : ''}${formatNumber(totalProfit)}</div>
      <div class="stat-change ${profitClass}">${profitPct >= 0 ? '+' : ''}${profitPct.toFixed(2)}%</div>
    </div>
    <div class="card">
      <div class="card-title">胜率 / 交易</div>
      <div class="stat-value">${winRate.toFixed(1)}%</div>
      <div class="stat-change" style="color:var(--text-secondary)">${winTrades}胜 / ${totalTrades}笔</div>
    </div>
    <div class="card">
      <div class="card-title">最大回撤 / 仓位</div>
      <div class="stat-value negative">-${maxDD.toFixed(2)}%</div>
      <div class="stat-change" style="color:var(--text-secondary)">${posCount}只持仓 · ${posPct.toFixed(1)}%仓位</div>
    </div>
  `;

  // 持仓表格
  const posCard = document.getElementById('paperPositionsCard');
  if (posCard) {
    posCard.innerHTML = `
      <div class="card-title">📋 当前持仓 (${posCount}/3)</div>
      ${posCount === 0 ? '<div style="text-align:center;padding:30px;color:var(--text-muted)">空仓中，等待扫描信号</div>' : `
      <div style="overflow-x:auto">
        <table class="data-table">
          <thead><tr>
            <th>代码</th><th>名称</th><th>数量</th><th>成本</th><th>现价</th><th>盈亏%</th><th>模式</th><th>天数</th>
          </tr></thead>
          <tbody>${positions.map(p => {
            const pnl = p.avg_cost > 0 ? ((p.current_price || 0) - p.avg_cost) / p.avg_cost * 100 : 0;
            return `<tr>
              <td style="font-family:var(--font-mono)">${escapeHtml(p.ts_code)}</td>
              <td>${escapeHtml(p.name)}</td>
              <td style="font-family:var(--font-mono)">${p.volume || 0}</td>
              <td style="font-family:var(--font-mono)">${(p.avg_cost || 0).toFixed(2)}</td>
              <td style="font-family:var(--font-mono);font-weight:600">${(p.current_price || 0).toFixed(2)}</td>
              <td class="${pnl >= 0 ? 'positive' : 'negative'}" style="font-weight:600">${pnl >= 0 ? '+' : ''}${pnl.toFixed(2)}%</td>
              <td>${escapeHtml(p.mode_name || '-')}</td>
              <td style="font-family:var(--font-mono)">${p.hold_days || 0}天</td>
            </tr>`;
          }).join('')}</tbody>
        </table>
      </div>`}
    `;
  }

  // 交易记录表格
  const tradeCard = document.getElementById('paperTradesCard');
  if (tradeCard) {
    tradeCard.innerHTML = `
      <div class="card-title">📜 最近交易 (共${totalTrades}笔)</div>
      ${trades.length === 0 ? '<div style="text-align:center;padding:30px;color:var(--text-muted)">暂无交易记录</div>' : `
      <div style="overflow-x:auto;max-height:320px;overflow-y:auto">
        <table class="data-table">
          <thead style="position:sticky;top:0;background:var(--color-muted);z-index:1"><tr>
            <th>日期</th><th>代码</th><th>名称</th><th>方向</th><th>价格</th><th>盈亏%</th><th>原因</th>
          </tr></thead>
          <tbody>${trades.map(t => `<tr>
            <td style="font-family:var(--font-mono);font-size:12px">${escapeHtml(t.trade_date || '')}</td>
            <td style="font-family:var(--font-mono);font-size:12px">${escapeHtml(t.ts_code || '')}</td>
            <td>${escapeHtml(t.name || '')}</td>
            <td style="font-weight:600"><span class="tag ${t.direction === 'buy' ? 'tag-red' : 'tag-green'}">${t.direction === 'buy' ? '买入' : '卖出'}</span></td>
            <td style="font-family:var(--font-mono)">${(t.price || 0).toFixed(2)}</td>
            <td class="${(t.profit_pct || 0) >= 0 ? 'positive' : 'negative'}" style="font-family:var(--font-mono)">${t.profit_pct != null ? (t.profit_pct >= 0 ? '+' : '') + t.profit_pct.toFixed(2) + '%' : '-'}</td>
            <td style="max-width:140px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--text-secondary);font-size:12px" title="${escapeHtml(t.reason || '')}">${escapeHtml(t.reason || '-')}</td>
          </tr>`).join('')}</tbody>
        </table>
      </div>`}
    `;
  }
}

async function paperAction(action) {
  const endpoints = { scan: '/paper/scan', sell: '/paper/sell-check' };
  const names = { scan: '扫描+买入', sell: '卖出检测' };
  showToast(`正在执行${names[action]}...`, 'info');

  const r = await API.request(endpoints[action], { method: 'POST' }, 300000);
  if (r && !r.error) {
    showToast(`${names[action]}完成！`, 'success');
    loadPaperStatus();
  } else {
    showToast(r?.message || `${names[action]}失败`, 'error');
  }
}

function paperConfirmReset() {
  const modal = document.createElement('div');
  modal.className = 'modal';
  modal.style.display = 'flex';
  modal.innerHTML = `
    <div class="modal-content">
      <div class="modal-header">
        <h3>⚠️ 确认重置模拟盘？</h3>
        <button class="modal-close" onclick="this.closest('.modal').remove()">✕</button>
      </div>
      <div class="modal-body">
        <p style="color:var(--text-secondary);line-height:1.8">
          此操作将清空所有持仓和交易记录，账户恢复到初始70万状态。<br>
          <b style="color:var(--color-destructive)">此操作不可撤销！</b>
        </p>
      </div>
      <div class="modal-footer">
        <button class="btn btn-secondary" onclick="this.closest('.modal').remove()">取消</button>
        <button class="btn btn-danger" id="confirmResetBtn">确认重置</button>
      </div>
    </div>
  `;
  document.body.appendChild(modal);
  document.getElementById('confirmResetBtn').addEventListener('click', async () => {
    modal.remove();
    showToast('正在重置...', 'info');
    const r = await API.request('/paper/init', { method: 'POST' });
    if (r && !r.error) {
      showToast('模拟盘已重置为初始70万', 'success');
      loadPaperStatus();
    } else {
      showToast(r?.message || '重置失败', 'error');
    }
  });
}
