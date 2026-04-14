/**
 * QuantWeave 风控中心页面
 */
function renderRisk() {
  const main = document.getElementById('mainContent');
  main.innerHTML = `
    <div class="page-header">
      <h2>🛡️ 风控中心</h2>
      <p>监控交易风险，管理告警</p>
    </div>
    <div class="grid-3" style="margin-bottom:20px">
      <div class="card">
        <div class="card-title">单只最大仓位</div>
        <div class="stat-value">30%</div>
        <div style="font-size:12px;color:var(--text-muted)">MAX_POSITION_RATIO</div>
      </div>
      <div class="card">
        <div class="card-title">单日最大亏损</div>
        <div class="stat-value">5%</div>
        <div style="font-size:12px;color:var(--text-muted)">MAX_LOSS_RATIO</div>
      </div>
      <div class="card">
        <div class="card-title">止损线</div>
        <div class="stat-value" style="color:var(--danger)">8%</div>
        <div style="font-size:12px;color:var(--text-muted)">STOP_LOSS_RATIO</div>
      </div>
    </div>
    <div class="card" id="alertList">
      <div class="card-title">告警记录</div>
      <div id="alertsContent"><div class="loading"><div class="spinner"></div>加载中...</div></div>
    </div>
  `;
  loadAlerts();
}

async function loadAlerts() {
  const container = document.getElementById('alertsContent');
  const data = await API.getRiskAlerts();
  const items = data?.items || [];
  if (items.length > 0) {
    container.innerHTML = `
      <table class="data-table">
        <thead><tr><th>时间</th><th>级别</th><th>类型</th><th>内容</th></tr></thead>
        <tbody>
          ${items.map(a => `
            <tr>
              <td>${a.created_at || '-'}</td>
              <td><span class="tag tag-${a.level === 'critical' ? 'red' : a.level === 'warning' ? 'yellow' : 'blue'}">${a.level || 'info'}</span></td>
              <td>${a.alert_type || '-'}</td>
              <td>${a.title || '-'}</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    `;
  } else {
    container.innerHTML = `
      <div style="text-align:center;padding:30px;color:var(--text-muted)">
        ✅ 暂无告警记录
      </div>
    `;
  }
}
