/**
 * QuantWeave 仪表盘页面
 * 对接真实后端数据（支持离线模式）
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
  const data = await API.getDashboard();

  if (data && data.system_status === 'online') {
    renderRealDashboard(container, data);
  } else {
    renderOfflineDashboard(container);
  }
}

function renderRealDashboard(container, data) {
  const pnl = data.today_pnl || 0;
  const hasEquityCurve = Array.isArray(data.equity_curve) && data.equity_curve.length > 0;
  const hasStrategyReturns = Array.isArray(data.strategy_returns) && data.strategy_returns.length > 0;

  container.innerHTML = `
    <div class="grid-4" style="margin-bottom:20px">
      <div class="card">
        <div class="card-title">总资产</div>
        <div class="stat-value">¥${formatNumber(data.total_assets || 1000000)}</div>
        <div class="stat-change ${(data.total_return || 0) >= 0 ? 'up' : 'down'}">
          ${(data.total_return || 0) >= 0 ? '▲' : '▼'} ${Math.abs(data.total_return || 0).toFixed(2)}%
        </div>
      </div>
      <div class="card">
        <div class="card-title">今日收益</div>
        <div class="stat-value ${pnl >= 0 ? 'positive' : 'negative'}">
          ¥${formatNumber(pnl)}
        </div>
      </div>
      <div class="card">
        <div class="card-title">运行策略</div>
        <div class="stat-value">${data.active_strategies || 0}</div>
      </div>
      <div class="card">
        <div class="card-title">胜率</div>
        <div class="stat-value">${(data.win_rate || 0).toFixed(1)}%</div>
      </div>
    </div>
    <div class="grid-4" style="margin-bottom:20px">
      <div class="card">
        <div class="card-title">持仓市值</div>
        <div class="stat-value">¥${formatNumber(data.market_value || 0)}</div>
      </div>
      <div class="card">
        <div class="card-title">现金余额</div>
        <div class="stat-value">¥${formatNumber(data.cash_balance || 0)}</div>
      </div>
      <div class="card">
        <div class="card-title">浮动盈亏</div>
        <div class="stat-value ${(data.profit || 0) >= 0 ? 'positive' : 'negative'}">
          ¥${formatNumber(data.profit || 0)}
        </div>
      </div>
      <div class="card">
        <div class="card-title">风控告警</div>
        <div class="stat-value">${(data.unresolved_alerts || 0) > 0 ? data.unresolved_alerts : '无'}</div>
      </div>
    </div>
    <div class="grid-2">
      <div class="card">
        <div class="card-title">净值曲线</div>
        ${hasEquityCurve
          ? '<canvas id="equityChart" height="200"></canvas>'
          : '<div class="empty">暂无回测数据，运行回测后显示</div>'}
      </div>
      <div class="card">
        <div class="card-title">策略收益对比</div>
        ${hasStrategyReturns
          ? '<canvas id="strategyChart" height="200"></canvas>'
          : '<div class="empty">暂无回测数据，运行回测后显示</div>'}
      </div>
    </div>
  `;

  if (hasEquityCurve) drawEquityChart(data.equity_curve);
  if (hasStrategyReturns) drawStrategyChart(data.strategy_returns);
}

function drawEquityChart(curveData) {
  const canvas = document.getElementById('equityChart');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  if (!Array.isArray(curveData) || curveData.length === 0) return;

  // Retina 适配
  const dpr = window.devicePixelRatio || 1;
  const displayW = canvas.offsetWidth;
  const displayH = 200;
  canvas.width = displayW * dpr;
  canvas.height = displayH * dpr;
  canvas.style.width = displayW + 'px';
  canvas.style.height = displayH + 'px';
  ctx.scale(dpr, dpr);

  const w = displayW;
  const h = displayH;
  const values = curveData.map(p => typeof p === 'number' ? p : (p.value || p.equity || 0));
  if (values.length === 0) return;

  const minV = Math.min(...values);
  const maxV = Math.max(...values);
  const range = maxV - minV || 1;
  const step = w / (values.length - 1 || 1);

  ctx.clearRect(0, 0, w, h);
  ctx.beginPath();
  ctx.strokeStyle = '#3b82f6';
  ctx.lineWidth = 2;
  values.forEach((v, i) => {
    const x = i * step;
    const y = h - ((v - minV) / range) * (h - 20) - 10;
    i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
  });
  ctx.stroke();
}

function drawStrategyChart(returnsData) {
  const canvas = document.getElementById('strategyChart');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  if (!Array.isArray(returnsData) || returnsData.length === 0) return;

  // Retina 适配
  const dpr = window.devicePixelRatio || 1;
  const displayW = canvas.offsetWidth;
  const displayH = 200;
  canvas.width = displayW * dpr;
  canvas.height = displayH * dpr;
  canvas.style.width = displayW + 'px';
  canvas.style.height = displayH + 'px';
  ctx.scale(dpr, dpr);

  const w = displayW;
  const h = displayH;
  const values = returnsData.map(r => typeof r === 'number' ? r : (r.return || r.value || 0));
  if (values.length === 0) return;

  const maxAbs = Math.max(...values.map(Math.abs), 1);
  const barW = Math.max(2, (w / values.length) - 2);
  const midY = h / 2;

  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = '#94a3b8';
  ctx.fillRect(0, midY, w, 1);

  values.forEach((v, i) => {
    const barH = (v / maxAbs) * (midY - 10);
    ctx.fillStyle = v >= 0 ? '#22C55E' : '#EF4444';
    ctx.fillRect(i * (barW + 2) + 4, v >= 0 ? midY - barH : midY, barW, Math.abs(barH));
  });
}

function renderOfflineDashboard(container) {
  container.innerHTML = `
    <div class="grid-4" style="margin-bottom:20px">
      <div class="card">
        <div class="card-title">总资产</div>
        <div class="stat-value">¥1,000,000</div>
        <div class="stat-change up">▲ 系统待启动</div>
      </div>
      <div class="card">
        <div class="card-title">策略数量</div>
        <div class="stat-value">${STRATEGY_TYPES.length}</div>
      </div>
      <div class="card">
        <div class="card-title">支持的数据源</div>
        <div class="stat-value">3</div>
        <div style="font-size:12px;color:var(--text-muted);margin-top:4px">Tushare · AKShare · 网易</div>
      </div>
      <div class="card">
        <div class="card-title">系统状态</div>
        <div class="stat-value" style="color:var(--warning)">离线</div>
        <div style="font-size:12px;color:var(--text-muted);margin-top:4px">启动后端获取实时数据</div>
      </div>
    </div>
    <div class="card" style="margin-bottom:16px">
      <div class="card-title">策略一览</div>
      <table class="data-table">
        <thead><tr><th>策略</th><th>类型</th><th>状态</th><th>描述</th></tr></thead>
        <tbody>
          ${STRATEGY_TYPES.map(s => `
            <tr>
              <td><strong>${s.name}</strong></td>
              <td><span class="tag tag-blue">${s.type}</span></td>
              <td><span class="tag tag-green">可用</span></td>
              <td>${s.desc}</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    </div>
    <div class="card">
      <div style="text-align:center;padding:20px;color:var(--text-muted)">
        🚀 启动后端服务查看实时数据：<br>
        <code style="font-family:var(--font-mono);background:#f1f5f9;padding:4px 8px;border-radius:6px;font-size:13px">
          cd backend && python run.py
        </code>
      </div>
    </div>
  `;
}
