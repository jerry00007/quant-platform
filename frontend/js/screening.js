/**
 * QuantWeave 智能选股页面
 * 功能：全市场扫描、多策略筛选、个股深度分析
 */

let currentScanResults = [];
let currentAnalysis = null;
let presetsCache = null;

async function renderScreening() {
  const main = document.getElementById('mainContent');
  main.innerHTML = `
    <div class="page-header">
      <h2>🔍 智能选股</h2>
      <p>基于多策略共振的全市场扫描系统</p>
    </div>
    
    <div id="screeningContent">
      <div class="grid-2">
        <div class="card">
          <div class="card-title">选股预设模板</div>
          <div id="presetCards" class="loading"><div class="spinner"></div>加载模板...</div>
        </div>
        
        <div class="card">
          <div class="card-title">自定义筛选</div>
          <div class="form-group">
            <label class="form-label">预设模板</label>
            <select id="presetSelect" class="form-select">
              <option value="" disabled selected>请选择...</option>
            </select>
            <div class="form-help">系统预定义的筛选组合</div>
          </div>
          
          <div class="form-group">
            <label class="form-label">策略选择</label>
            <div id="strategyCheckboxes" class="checkbox-group">
              <div class="loading">加载策略...</div>
            </div>
          </div>
          
          <div class="form-group">
            <label class="form-label">市场范围</label>
            <div class="radio-group">
              <label class="radio-label">
                <input type="radio" name="market" value="all" checked>
                <span>全市场（股票+ETF）</span>
              </label>
              <label class="radio-label">
                <input type="radio" name="market" value="sh">
                <span>沪市股票(.SH)</span>
              </label>
              <label class="radio-label">
                <input type="radio" name="market" value="sz">
                <span>深市股票(.SZ)</span>
              </label>
              <label class="radio-label">
                <input type="radio" name="market" value="etf">
                <span>ETF基金</span>
              </label>
            </div>
          </div>
          
          <div class="form-row">
            <div class="form-group" style="flex:2">
              <label class="form-label">回看天数</label>
              <input type="number" id="daysInput" class="form-input" value="120" min="30" max="500">
            </div>
            <div class="form-group" style="flex:1">
              <label class="form-label">返回数量</label>
              <input type="number" id="topNInput" class="form-input" value="20" min="5" max="100">
            </div>
          </div>
          
          <div class="form-actions">
            <button id="startScanBtn" class="btn btn-primary" onclick="startScreening()">
              🔍 开始扫描
            </button>
            <button id="refreshBtn" class="btn btn-outline" onclick="loadPresets()">
              🔄 刷新模板
            </button>
          </div>
        </div>
      </div>
      
      <div id="resultsSection" class="card" style="margin-top:20px; display:none">
        <div class="card-header">
          <div class="card-title">选股结果</div>
          <div class="card-subtitle" id="resultsStats"></div>
        </div>
        <div id="resultsContainer" class="loading"><div class="spinner"></div>扫描中...</div>
      </div>
      
      <div id="analysisModal" class="modal" style="display:none">
        <div class="modal-content" style="max-width:800px">
          <div class="modal-header">
            <div class="modal-title">📊 个股深度分析</div>
            <button class="modal-close" onclick="closeAnalysisModal()">×</button>
          </div>
          <div id="analysisContent" class="modal-body">
            <!-- 分析内容动态加载 -->
          </div>
        </div>
      </div>
    </div>
  `;
  
  await loadPresets();
  await loadStrategies();
}

async function loadPresets() {
  const container = document.getElementById('presetCards');
  if (!container) return;
  
  try {
    const data = await API.getScreeningPresets();
    presetsCache = Array.isArray(data) ? data : (data.items || []);
    
    container.innerHTML = `
      <div class="grid-2">
        ${presetsCache.map(p => `
          <div class="preset-card" onclick="selectPreset('${p.key}')">
            <div class="preset-title">${p.name}</div>
            <div class="preset-desc">${p.description}</div>
            <div class="preset-badges">
              ${p.strategies ? p.strategies.map(s => `<span class="badge badge-blue">${s}</span>`).join('') : ''}
            </div>
          </div>
        `).join('')}
      </div>
    `;
    
    // 填充下拉框
    const select = document.getElementById('presetSelect');
    if (select) {
      select.innerHTML = '<option value="" disabled selected>请选择...</option>' +
        presetsCache.map(p => `<option value="${p.key}">${p.name}</option>`).join('');
    }
  } catch (err) {
    container.innerHTML = `<div class="error">⚠️ 加载失败: ${err.message || '未知错误'}</div>`;
  }
}

async function loadStrategies() {
  const container = document.getElementById('strategyCheckboxes');
  if (!container) return;
  
  try {
    const data = await API.getStrategyTypes();
    const items = Array.isArray(data) ? data : (data.items || []);
    container.innerHTML = items.map(s => `
      <label class="checkbox-label">
        <input type="checkbox" name="strategy" value="${s.key}" checked>
        <span>${s.name}</span>
      </label>
    `).join('');
  } catch (err) {
    container.innerHTML = `<div class="error">⚠️ 加载失败: ${err.message || '未知错误'}</div>`;
  }
}

function selectPreset(key) {
  const select = document.getElementById('presetSelect');
  if (select) {
    select.value = key;
    select.dispatchEvent(new Event('change'));
  }
  
  // 更新策略复选框
  if (presetsCache) {
    const preset = presetsCache.find(p => p.key === key);
    if (preset && preset.strategies) {
      const checkboxes = document.querySelectorAll('#strategyCheckboxes input[name="strategy"]');
      checkboxes.forEach(cb => {
        cb.checked = preset.strategies.includes(cb.value);
      });
    }
  }
}

async function startScreening() {
  const presetSelect = document.getElementById('presetSelect');
  const daysInput = document.getElementById('daysInput');
  const topNInput = document.getElementById('topNInput');
  
  if (!presetSelect || !presetSelect.value) {
    alert('请先选择一个预设模板');
    return;
  }
  
  const preset = presetSelect.value;
  const days = parseInt(daysInput?.value || 120);
  const top_n = parseInt(topNInput?.value || 20);
  
  // 获取选中的策略
  const selectedStrategies = Array.from(document.querySelectorAll('#strategyCheckboxes input[name="strategy"]:checked'))
    .map(cb => cb.value)
    .join(',');
  
  const market = document.querySelector('input[name="market"]:checked')?.value || 'all';
  
  // 显示结果区域
  const resultsSection = document.getElementById('resultsSection');
  const container = document.getElementById('resultsContainer');
  if (resultsSection) resultsSection.style.display = 'block';
  if (container) container.innerHTML = '<div class="loading"><div class="spinner"></div>正在扫描全市场...</div>';
  
  try {
    // 根据市场获取股票列表
    let stocks = null;
    if (market !== 'all') {
      const stockList = await API.getStockList();
      let filtered = [];
      if (market === 'sh') {
        filtered = stockList.filter(s => s.ts_code.endsWith('.SH') && !s.name.includes('ETF'));
      } else if (market === 'sz') {
        filtered = stockList.filter(s => s.ts_code.endsWith('.SZ') && !s.name.includes('ETF'));
      } else if (market === 'etf') {
        // ETF基金：名称包含ETF或代码以.ETF结尾（兼容多种数据源）
        filtered = stockList.filter(s => s.name.includes('ETF') || s.ts_code.includes('.ETF'));
      }
      stocks = filtered.map(s => s.ts_code).join(',');
    }
    
    const results = await API.scanMarket(preset, selectedStrategies, stocks, days, top_n);
    currentScanResults = results.items || [];
    
    renderResults(currentScanResults);
    
  } catch (err) {
    if (container) {
      container.innerHTML = `
        <div class="error">
          <strong>❌ 扫描失败</strong>
          <p>${err.message || '未知错误'}</p>
          <button onclick="startScreening()" class="btn btn-sm btn-outline" style="margin-top:8px">重试</button>
        </div>
      `;
    }
  }
}

function renderResults(results) {
  const container = document.getElementById('resultsContainer');
  const stats = document.getElementById('resultsStats');
  
  if (!container || !stats) return;
  
  if (!results || results.length === 0) {
    container.innerHTML = `
      <div class="empty">
        <div>🔍 未发现符合条件的股票</div>
        <p>尝试放宽筛选条件或选择其他预设模板</p>
      </div>
    `;
    stats.innerHTML = '0 只股票符合条件';
    return;
  }
  
  stats.innerHTML = `${results.length} 只股票符合条件 | 最高评分: ${Math.max(...results.map(r => r.score || 0))}`;
  
  container.innerHTML = `
    <table class="data-table">
      <thead>
        <tr>
          <th>股票</th>
          <th>名称</th>
          <th>最新价</th>
          <th>涨跌幅</th>
          <th>信号数</th>
          <th>评分</th>
          <th>策略</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        ${results.map(r => `
          <tr>
            <td><code class="stock-code">${r.ts_code}</code></td>
            <td><strong>${r.name || '—'}</strong></td>
            <td class="${(r.change_pct || 0) >= 0 ? 'positive' : 'negative'}">
              ¥${(r.close || 0).toFixed(2)}
            </td>
            <td class="${(r.change_pct || 0) >= 0 ? 'positive' : 'negative'}">
              ${(r.change_pct || 0) >= 0 ? '▲' : '▼'} ${Math.abs(r.change_pct || 0).toFixed(2)}%
            </td>
            <td><span class="badge ${r.signal_count >= 3 ? 'badge-green' : 'badge-blue'}">${r.signal_count}</span></td>
            <td><span class="score-badge" style="background:${getScoreColor(r.score)}">${r.score}</span></td>
            <td>
              ${(r.strategies_hit || []).slice(0,3).map(s => `<span class="badge badge-outline">${s}</span>`).join('')}
            </td>
            <td>
              <button class="btn btn-sm btn-secondary" onclick="analyzeStock('${escapeHtml(r.ts_code)}')">分析</button>
              <button class="btn btn-sm btn-outline" onclick="addToWatchlist('${escapeHtml(r.ts_code)}','${escapeHtml(r.name || '')}')">关注</button>
            </td>
          </tr>
        `).join('')}
      </tbody>
    </table>
  `;
}

function getScoreColor(score) {
  if (score >= 150) return '#22C55E';
  if (score >= 100) return '#3B82F6';
  if (score >= 50) return '#F59E0B';
  return '#EF4444';
}

async function analyzeStock(ts_code) {
  const modal = document.getElementById('analysisModal');
  const content = document.getElementById('analysisContent');
  if (!modal || !content) return;
  
  modal.style.display = 'flex';
  content.innerHTML = '<div class="loading"><div class="spinner"></div>分析中...</div>';
  
  try {
    const data = await API.analyzeStock(ts_code, 250);
    currentAnalysis = data;
    
    content.innerHTML = renderAnalysis(data);
  } catch (err) {
    content.innerHTML = `
      <div class="error">
        <strong>❌ 分析失败</strong>
        <p>${err.message || '未知错误'}</p>
      </div>
    `;
  }
}

function renderAnalysis(data) {
  if (!data || data.error) {
    return `<div class="error">${data?.error || '分析数据为空'}</div>`;
  }
  
  const latest = data.latest || {};
  const rec = data.recommendation || {};
  const signals = data.signals || {};
  const ma = data.ma || {};
  
  return `
    <div class="grid-2">
      <div class="card">
        <div class="card-title">📈 实时信息</div>
        <div class="info-grid">
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
            <span class="info-label">成交量</span>
            <span class="info-value">${formatScreeningNumber(latest.vol || 0)}手</span>
          </div>
          <div class="info-item">
            <span class="info-label">成交额</span>
            <span class="info-value">${formatScreeningNumber(latest.amount || 0)}元</span>
          </div>
          <div class="info-item">
            <span class="info-label">日期</span>
            <span class="info-value">${latest.date || '—'}</span>
          </div>
        </div>
      </div>
      
      <div class="card">
        <div class="card-title">📊 指标</div>
        <div class="info-grid">
          ${Object.entries(ma).map(([key, value]) => `
            <div class="info-item">
              <span class="info-label">${key}</span>
              <span class="info-value">${value.toFixed(2)}</span>
            </div>
          `).join('')}
          ${data.rsi ? `
            <div class="info-item">
              <span class="info-label">RSI(14)</span>
              <span class="info-value ${data.rsi > 70 ? 'negative' : data.rsi < 30 ? 'positive' : ''}">
                ${data.rsi}
                ${data.rsi > 70 ? '(超买)' : data.rsi < 30 ? '(超卖)' : ''}
              </span>
            </div>
          ` : ''}
        </div>
      </div>
    </div>
    
    <div class="card" style="margin-top:16px">
      <div class="card-header">
        <div class="card-title">🎯 综合建议</div>
        <span class="tag ${rec.action === 'buy' ? 'tag-green' : rec.action === 'sell' ? 'tag-red' : 'tag-gray'}">
          ${rec.level || '—'}
        </span>
      </div>
      <div class="card-body">
        <p><strong>理由：</strong>${rec.reason || '—'}</p>
        <div class="grid-2" style="margin-top:12px">
          <div>
            <strong>买入策略：</strong>
            ${(rec.buy_strategies || []).length > 0 ? rec.buy_strategies.map(s => `<span class="badge badge-green">${s}</span>`).join(' ') : '无'}
          </div>
          <div>
            <strong>卖出策略：</strong>
            ${(rec.sell_strategies || []).length > 0 ? rec.sell_strategies.map(s => `<span class="badge badge-red">${s}</span>`).join(' ') : '无'}
          </div>
        </div>
        <div class="grid-2" style="margin-top:12px">
          <div>
            <strong>止损位：</strong>
            <code>¥${rec.stop_loss || '—'}</code>
            <div class="text-sm text-muted">建议跌破此价位止损</div>
          </div>
          <div>
            <strong>止盈位：</strong>
            <code>¥${rec.take_profit || '—'}</code>
            <div class="text-sm text-muted">建议到达此价位止盈</div>
          </div>
        </div>
      </div>
    </div>
    
    <div class="card" style="margin-top:16px">
      <div class="card-title">📡 详细信号</div>
      ${Object.keys(signals).length > 0 ? 
        Object.entries(signals).map(([key, sigs]) => `
          <details style="margin-bottom:8px">
            <summary><strong>${key}</strong> 策略 (${sigs.length}个信号)</summary>
            <div style="margin-top:8px">
              ${sigs.map(s => `
                <div class="signal-item ${s.signal === 'buy' ? 'signal-buy' : 'signal-sell'}">
                  <span class="signal-date">${s.date}</span>
                  <span class="signal-type ${s.signal === 'buy' ? 'type-buy' : 'type-sell'}">${s.signal === 'buy' ? '买入' : '卖出'}</span>
                  <span>${s.reason || '—'}</span>
                </div>
              `).join('')}
            </div>
          </details>
        `).join('') : 
        '<div class="empty">暂无信号</div>'
      }
    </div>
    
    <div class="modal-actions" style="margin-top:20px">
      <button class="btn btn-primary" onclick="addToWatchlist('${data.ts_code}', '${latest.name || ''}')">
        👁️ 加入关注
      </button>
      <button class="btn btn-outline" onclick="closeAnalysisModal()">
        关闭
      </button>
    </div>
  `;
}

function closeAnalysisModal() {
  const modal = document.getElementById('analysisModal');
  if (modal) modal.style.display = 'none';
}

async function addToWatchlist(ts_code, name) {
  try {
    const result = await API.addToWatchlist(ts_code);
    if (result && result.success) {
      alert(`✅ ${name || ts_code} 已加入关注列表`);
    } else {
      alert('❌ 添加失败，可能已在关注列表中');
    }
  } catch (err) {
    alert(`❌ 添加失败: ${err.message || '未知错误'}`);
  }
}

// 工具函数（选股专用，带万/亿格式化，避免覆盖全局 formatNumber）
function formatScreeningNumber(num) {
  if (num >= 1e8) return (num / 1e8).toFixed(1) + '亿';
  if (num >= 1e4) return (num / 1e4).toFixed(1) + '万';
  return num.toString();
}

function escapeHtml(str) {
  if (!str) return '';
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

// 添加必要的CSS样式
(function addStyles() {
  if (document.getElementById('screening-styles')) return;
  
  const style = document.createElement('style');
  style.id = 'screening-styles';
  style.textContent = `
    .preset-card {
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 16px;
      background: var(--surface);
      cursor: pointer;
      transition: all 0.2s;
    }
    .preset-card:hover {
      background: var(--surface-hover);
      border-color: var(--primary);
      transform: translateY(-2px);
    }
    .preset-title {
      font-weight: 600;
      margin-bottom: 4px;
      color: var(--text);
    }
    .preset-desc {
      font-size: 13px;
      color: var(--text-secondary);
      margin-bottom: 8px;
    }
    .preset-badges {
      display: flex;
      flex-wrap: wrap;
      gap: 4px;
    }
    .score-badge {
      display: inline-block;
      padding: 2px 8px;
      border-radius: 10px;
      color: white;
      font-weight: 600;
      font-size: 12px;
    }
    .signal-item {
      padding: 6px 10px;
      border-radius: 6px;
      margin-bottom: 4px;
      background: var(--surface);
      display: flex;
      align-items: center;
      gap: 10px;
    }
    .signal-buy { border-left: 3px solid var(--success); }
    .signal-sell { border-left: 3px solid var(--danger); }
    .signal-date {
      font-family: var(--font-mono);
      font-size: 12px;
      color: var(--text-muted);
      min-width: 70px;
    }
    .signal-type {
      font-size: 12px;
      padding: 1px 6px;
      border-radius: 4px;
      font-weight: 600;
    }
    .type-buy { background: var(--success-bg); color: var(--success); }
    .type-sell { background: var(--danger-bg); color: var(--danger); }
    .info-grid {
      display: grid;
      grid-template-columns: repeat(2, 1fr);
      gap: 12px;
    }
    .info-item {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 8px 0;
      border-bottom: 1px solid var(--border);
    }
    .info-label {
      font-size: 14px;
      color: var(--text-secondary);
    }
    .info-value {
      font-family: var(--font-mono);
      font-weight: 600;
    }
    .modal-content {
      max-height: 85vh;
      overflow-y: auto;
    }
  `;
  document.head.appendChild(style);
})();