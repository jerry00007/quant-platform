/**
 * ML策略选股页面
 * 共振+ML择时 v2.0 — 趋势回调反弹专用
 */

let mlPicksData = null;

async function renderMLPicks() {
  const content = document.getElementById('mainContent');
  content.innerHTML = `
    <div class="page-header">
      <h2>🤖 ML策略选股</h2>
      <p class="page-subtitle">共振+ML择时 v2.0 — 趋势回调反弹专用 | 夏普1.948 / 回撤-9.03%</p>
    </div>
    
    <!-- 策略卡片 -->
    <div class="ml-strategy-cards" id="mlStrategyCards"></div>
    
    <!-- 操作栏 -->
    <div class="ml-toolbar" id="mlToolbar"></div>
    
    <!-- 选股结果 -->
    <div id="mlPicksResult"></div>
    
    <!-- 策略详情 -->
    <div id="mlStrategyDetail"></div>
  `;
  
  renderStrategyCards();
  renderToolbar();
  await loadMLPicks();
  renderStrategyDetail();
}

function renderStrategyCards() {
  const container = document.getElementById('mlStrategyCards');
  container.innerHTML = `
    <div class="ml-card-row">
      <div class="ml-stat-card">
        <div class="ml-stat-icon">📊</div>
        <div class="ml-stat-value" style="color:#EF4444">+98.68%</div>
        <div class="ml-stat-label">2年总收益</div>
      </div>
      <div class="ml-stat-card">
        <div class="ml-stat-icon">⚡</div>
        <div class="ml-stat-value">1.948</div>
        <div class="ml-stat-label">夏普比率</div>
      </div>
      <div class="ml-stat-card">
        <div class="ml-stat-icon">🛡️</div>
        <div class="ml-stat-value" style="color:#22C55E">-9.03%</div>
        <div class="ml-stat-label">最大回撤</div>
      </div>
      <div class="ml-stat-card">
        <div class="ml-stat-icon">🎯</div>
        <div class="ml-stat-value">51.5%</div>
        <div class="ml-stat-label">胜率</div>
      </div>
      <div class="ml-stat-card">
        <div class="ml-stat-icon">🔥</div>
        <div class="ml-stat-value">5.4%</div>
        <div class="ml-stat-label">止损率</div>
      </div>
      <div class="ml-stat-card">
        <div class="ml-stat-icon">✅</div>
        <div class="ml-stat-value" style="color:#059669">三身份验证通过</div>
        <div class="ml-stat-label">🦅鹰眼 🦊狐探 🦉夜枭</div>
      </div>
    </div>
  `;
}

function renderToolbar() {
  const container = document.getElementById('mlToolbar');
  container.innerHTML = `
    <div class="ml-toolbar-inner">
      <button class="ml-btn ml-btn-primary" id="mlRefreshBtn" onclick="mlRefreshPicks()">
        🔄 刷新选股
      </button>
      <span class="ml-toolbar-hint" id="mlToolbarHint">加载中...</span>
    </div>
  `;
}

async function loadMLPicks() {
  const resultEl = document.getElementById('mlPicksResult');
  const hintEl = document.getElementById('mlToolbarHint');
  
  resultEl.innerHTML = `<div class="ml-loading">⏳ 加载ML选股数据中...</div>`;
  
  try {
    const resp = await API.request('/ml/picks');
    if (resp.error) {
      resultEl.innerHTML = `<div class="ml-error">❌ ${resp.message || '加载失败'}</div>`;
      hintEl.textContent = '加载失败';
      return;
    }
    
    mlPicksData = resp.data;
    const date = mlPicksData.date || '';
    const ds = date ? `${date.slice(0,4)}-${date.slice(4,6)}-${date.slice(6)}` : '未知';
    hintEl.textContent = `数据日期: ${ds}`;
    
    renderPicksTable(mlPicksData);
  } catch (e) {
    resultEl.innerHTML = `<div class="ml-error">❌ 网络错误: ${e.message}</div>`;
    hintEl.textContent = '加载失败';
  }
}

function renderPicksTable(data) {
  const resultEl = document.getElementById('mlPicksResult');
  const picks = data.picks || [];
  
  if (!picks.length) {
    resultEl.innerHTML = `<div class="ml-empty">📭 今日无符合条件的选股</div>`;
    return;
  }
  
  resultEl.innerHTML = `
    <div class="ml-picks-section">
      <h3 class="ml-section-title">🎯 ML选股 Top ${picks.length}</h3>
      <div class="ml-picks-grid">
        ${picks.map((p, i) => renderPickCard(p, i)).join('')}
      </div>
    </div>
  `;
}

function renderPickCard(p, idx) {
  const chgColor = p.returns_1d >= 0 ? '#EF4444' : '#22C55E';
  const chgSign = p.returns_1d >= 0 ? '+' : '';
  const r5 = p.returns_5d !== null ? `${p.returns_5d >= 0 ? '+' : ''}${p.returns_5d.toFixed(1)}%` : 'N/A';
  const r20 = p.returns_20d !== null ? `${p.returns_20d >= 0 ? '+' : ''}${p.returns_20d.toFixed(1)}%` : 'N/A';
  const r5Color = p.returns_5d >= 0 ? '#EF4444' : '#22C55E';
  const r20Color = p.returns_20d >= 0 ? '#EF4444' : '#22C55E';
  
  // 概率条颜色
  const probPct = Math.round(p.prob_up * 100);
  const probColor = probPct >= 70 ? '#059669' : probPct >= 60 ? '#F59E0B' : '#6B7280';
  
  return `
    <div class="ml-pick-card">
      <div class="ml-pick-header">
        <span class="ml-pick-rank">#${idx + 1}</span>
        <span class="ml-pick-name">${escapeHtml(p.name)}</span>
        <span class="ml-pick-code">${p.ts_code}</span>
      </div>
      <div class="ml-pick-price">
        <span class="ml-pick-close">¥${p.close.toFixed(2)}</span>
        <span class="ml-pick-chg" style="color:${chgColor}">${chgSign}${p.returns_1d.toFixed(2)}%</span>
      </div>
      <div class="ml-pick-prob">
        <div class="ml-prob-bar">
          <div class="ml-prob-fill" style="width:${probPct}%;background:${probColor}"></div>
        </div>
        <span class="ml-prob-text">反弹概率 ${probPct}%</span>
      </div>
      <div class="ml-pick-stats">
        <div class="ml-pick-stat">
          <span class="ml-stat-key">RSI</span>
          <span class="ml-stat-val">${p.rsi_14.toFixed(1)}</span>
        </div>
        <div class="ml-pick-stat">
          <span class="ml-stat-key">量比</span>
          <span class="ml-stat-val">${p.volume_ratio.toFixed(2)}</span>
        </div>
        <div class="ml-pick-stat">
          <span class="ml-stat-key">5日</span>
          <span class="ml-stat-val" style="color:${r5Color}">${r5}</span>
        </div>
        <div class="ml-pick-stat">
          <span class="ml-stat-key">20日</span>
          <span class="ml-stat-val" style="color:${r20Color}">${r20}</span>
        </div>
      </div>
    </div>
  `;
}

function renderStrategyDetail() {
  const container = document.getElementById('mlStrategyDetail');
  container.innerHTML = `
    <div class="ml-detail-section">
      <h3 class="ml-section-title">📋 策略详情</h3>
      <div class="ml-detail-grid">
        <div class="ml-detail-card">
          <h4>模型参数</h4>
          <table class="ml-detail-table">
            <tr><td>模型</td><td>HistGradientBoosting</td></tr>
            <tr><td>特征维度</td><td>18维（13基础+5趋势）</td></tr>
            <tr><td>概率阈值</td><td>≥55%</td></tr>
            <tr><td>持有天数</td><td>3天（快进快出）</td></tr>
            <tr><td>每日选股</td><td>Top 3</td></tr>
            <tr><td>止损</td><td>-7%</td></tr>
            <tr><td>最大持仓</td><td>6只</td></tr>
          </table>
        </div>
        <div class="ml-detail-card">
          <h4>选股逻辑</h4>
          <ol class="ml-logic-list">
            <li>✅ 价格在MA60上方（上升趋势确认）</li>
            <li>✅ 从高点回调≥3%（回调到位）</li>
            <li>✅ RSI &lt; 70（未超买）</li>
            <li>✅ ML预测反弹概率≥55%</li>
            <li>✅ 量比 &lt; 3.5（排除异常放量）</li>
            <li>✅ ST风控过滤（排除ST/*ST）</li>
          </ol>
        </div>
        <div class="ml-detail-card">
          <h4>核心创新特征</h4>
          <ul class="ml-logic-list">
            <li><b>price_to_ma60</b> — 距MA60偏移</li>
            <li><b>pullback_depth</b> — 回调深度</li>
            <li><b>pullback_days</b> — 连续下跌天数</li>
            <li><b>ma7_slope</b> — 短期趋势强度</li>
            <li><b>ma60_slope</b> — 长期趋势方向</li>
          </ul>
        </div>
      </div>
      <div class="ml-disclaimer">
        ⚠️ 本策略由AI生成，仅供参考，不构成投资建议。投资有风险，入市需谨慎。
      </div>
    </div>
  `;
}

async function mlRefreshPicks() {
  const btn = document.getElementById('mlRefreshBtn');
  btn.disabled = true;
  btn.textContent = '⏳ 选股中...';
  
  try {
    // 调用后端触发新选股
    const resp = await API.request('/ml/picks', { method: 'POST' }, 180000);
    if (resp.error) {
      showToast('选股失败: ' + (resp.message || '未知错误'), 'error');
    } else {
      showToast('选股完成！', 'success');
      mlPicksData = resp.data;
      renderPicksTable(mlPicksData);
    }
  } catch (e) {
    showToast('选股失败: ' + e.message, 'error');
  }
  
  btn.disabled = false;
  btn.textContent = '🔄 刷新选股';
}
