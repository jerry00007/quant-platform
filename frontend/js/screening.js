/**
 * QuantWeave 智能选股页面 v2.0
 * 功能：快速选股、全市场扫描、个股深度分析、自选管理
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
      <!-- 快速选股入口 -->
      <div class="card" style="margin-bottom:20px">
        <div class="card-title">⚡ 快速选股</div>
        <div style="display:flex;gap:12px;align-items:center;flex-wrap:wrap">
          <input type="text" id="quickSearchInput" class="form-input" 
            placeholder="输入股票代码或名称，如：600519 / 茅台" 
            style="flex:1;min-width:240px"
            onkeydown="if(event.key==='Enter')quickAnalyze()">
          <button class="btn btn-primary" onclick="quickAnalyze()">📊 分析</button>
          <button class="btn btn-outline" onclick="quickAddWatchlist()">⭐ 加关注</button>
        </div>
        <div id="quickSearchHint" style="margin-top:8px;font-size:13px;color:var(--text-muted)"></div>
      </div>

      <!-- 🎯 一键选股 — 双均线+回调企稳 -->
      <div class="card" style="margin-bottom:20px;border:2px solid var(--primary);position:relative;overflow:hidden">
        <div style="position:absolute;top:0;right:0;background:var(--primary);color:white;padding:2px 12px;font-size:11px;border-radius:0 0 0 8px">实盘策略</div>
        <div class="card-title">🎯 一键选股 — 双均线 + 回调企稳</div>
        <p style="font-size:13px;color:var(--text-muted);margin-bottom:12px">
          使用回测验证的两大核心策略全市场扫描，自动检测多策略共振股，含入场点位和风控指标
        </p>
        <div style="display:flex;gap:12px;align-items:center;flex-wrap:wrap">
          <button id="quickPicksBtn" class="btn btn-primary" onclick="runQuickPicks()" style="padding:10px 28px;font-size:15px;font-weight:600">
            🚀 开始选股
          </button>
          <span style="font-size:12px;color:var(--text-muted)">双均线(7/60) · 回调企稳(8/95/5) · 扫描约2~3分钟</span>
        </div>
      </div>

      <!-- 一键选股结果 -->
      <div id="quickPicksResult" class="card" style="margin-bottom:20px;display:none">
      </div>

      <!-- 扫描配置（折叠） -->
      <details id="scanConfigPanel" class="card" style="margin-bottom:20px">
        <summary style="cursor:pointer;font-weight:600;color:var(--text-secondary)">
          ⚙️ 高级扫描配置
        </summary>
        <div style="margin-top:16px">
          <div class="grid-2">
            <div class="card" style="background:var(--surface)">
              <div class="card-title">选股预设模板</div>
              <div id="presetCards" style="color:var(--text-muted);font-size:14px">加载中...</div>
            </div>
            
            <div class="card" style="background:var(--surface)">
              <div class="card-title">自定义筛选</div>
              <div class="form-group">
                <label class="form-label">预设模板</label>
                <select id="presetSelect" class="form-select">
                  <option value="" disabled selected>请选择...</option>
                </select>
              </div>
              
              <div class="form-group">
                <label class="form-label">策略选择</label>
                <div id="strategyCheckboxes" style="color:var(--text-muted);font-size:14px">
                  加载策略...
                </div>
              </div>
              
              <div class="form-group">
                <label class="form-label">市场范围</label>
                <div style="display:flex;gap:16px;flex-wrap:wrap">
                  <label style="display:flex;align-items:center;gap:6px;cursor:pointer;font-size:14px">
                    <input type="radio" name="market" value="all" checked> 全市场
                  </label>
                  <label style="display:flex;align-items:center;gap:6px;cursor:pointer;font-size:14px">
                    <input type="radio" name="market" value="sh"> 沪市
                  </label>
                  <label style="display:flex;align-items:center;gap:6px;cursor:pointer;font-size:14px">
                    <input type="radio" name="market" value="sz"> 深市
                  </label>
                  <label style="display:flex;align-items:center;gap:6px;cursor:pointer;font-size:14px">
                    <input type="radio" name="market" value="etf"> ETF
                  </label>
                </div>
              </div>
              
              <div class="form-row" style="display:flex;gap:12px">
                <div class="form-group" style="flex:2">
                  <label class="form-label">回看天数</label>
                  <input type="number" id="daysInput" class="form-input" value="120" min="30" max="500">
                </div>
                <div class="form-group" style="flex:1">
                  <label class="form-label">返回数量</label>
                  <input type="number" id="topNInput" class="form-input" value="20" min="5" max="100">
                </div>
              </div>
              
              <div class="form-actions" style="display:flex;gap:8px">
                <button class="btn btn-primary" onclick="startScreening()">🔍 开始扫描</button>
                <button class="btn btn-outline" onclick="loadPresets()">🔄 刷新</button>
              </div>
            </div>
          </div>
        </div>
      </details>

      <!-- 选股结果 -->
      <div id="resultsSection" class="card" style="margin-top:0; display:none">
        <div class="card-header" style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
          <div class="card-title" style="margin-bottom:0">📋 选股结果</div>
          <div id="resultsStats" style="font-size:13px;color:var(--text-muted)"></div>
        </div>
        <div id="resultsContainer"></div>
      </div>
      
      <!-- 分析弹窗 -->
      <div id="analysisModal" class="modal" style="display:none">
        <div class="modal-content" style="max-width:860px">
          <div class="modal-header">
            <div class="modal-title">📊 个股深度分析</div>
            <button class="modal-close" onclick="closeStockAnalysisModal()">×</button>
          </div>
          <div id="analysisContent" class="modal-body"></div>
        </div>
      </div>
    </div>
  `;
  
  // 异步加载模板和策略（不阻塞页面渲染）
  loadPresets();
  loadStrategies();
  
  // 自动加载最新一键选股结果
  loadLatestQuickPicks();
}

// ========== 快速选股 ==========
async function quickAnalyze() {
  const input = document.getElementById('quickSearchInput');
  const hint = document.getElementById('quickSearchHint');
  const keyword = input.value.trim();
  
  if (!keyword) {
    hint.innerHTML = '<span style="color:var(--color-down)">请输入股票代码或名称</span>';
    return;
  }

  hint.innerHTML = '正在搜索...';

  // 先尝试精确匹配（代码），再模糊匹配（名称）
  let tsCode = '';
  let stockName = '';

  // 判断是代码还是名称
  if (/^\d{6}$/.test(keyword)) {
    // 6位数字，直接补后缀（6/9=沪 0/3=深 8/4=北交所）
    tsCode = resolveStockSuffix(keyword);
  } else if (/^\d{6}\.(SZ|SH|BJ)$/.test(keyword)) {
    tsCode = keyword;
  } else {
    // 名称搜索
    hint.innerHTML = '正在搜索匹配的股票...';
    const stockList = await API.getStocks(keyword);
    if (stockList && stockList.items && stockList.items.length > 0) {
      const match = stockList.items[0];
      tsCode = match.ts_code;
      stockName = match.name;
      hint.innerHTML = `找到: <strong>${stockName}</strong> (${tsCode})`;
    } else {
      hint.innerHTML = '<span style="color:var(--color-down)">未找到匹配的股票</span>';
      return;
    }
  }

  if (!tsCode) return;

  hint.innerHTML = `正在分析 ${stockName || tsCode}...`;
  analyzeStock(tsCode);
}

async function quickAddWatchlist() {
  const input = document.getElementById('quickSearchInput');
  const hint = document.getElementById('quickSearchHint');
  const keyword = input.value.trim();

  if (!keyword) {
    hint.innerHTML = '<span style="color:var(--color-down)">请输入股票代码或名称</span>';
    return;
  }

  let tsCode = '';
  let stockName = '';

  if (/^\d{6}$/.test(keyword)) {
    tsCode = resolveStockSuffix(keyword);
  } else if (/^\d{6}\.(SZ|SH|BJ)$/.test(keyword)) {
    tsCode = keyword;
  } else {
    const stockList = await API.getStocks(keyword);
    if (stockList && stockList.items && stockList.items.length > 0) {
      tsCode = stockList.items[0].ts_code;
      stockName = stockList.items[0].name;
    } else {
      hint.innerHTML = '<span style="color:var(--color-down)">未找到匹配的股票</span>';
      return;
    }
  }

  const result = await API.addToWatchlist(tsCode, stockName);
  if (result && result.success) {
    hint.innerHTML = `<span style="color:var(--color-up)">✅ ${stockName || tsCode} 已加入关注列表</span>`;
    showToast(`${stockName || tsCode} 已加关注`, 'success');
  } else {
    hint.innerHTML = '<span style="color:var(--color-down)">添加失败，可能已在关注列表中</span>';
  }
}

function startFullScan() {
  const panel = document.getElementById('scanConfigPanel');
  if (panel) panel.open = true;
  // 滚动到扫描配置
  panel?.scrollIntoView({ behavior: 'smooth' });
}

// ========== 一键选股（异步模式） ==========
async function loadLatestQuickPicks() {
  const resultDiv = document.getElementById('quickPicksResult');
  if (!resultDiv) return;

  try {
    const data = await API.getLatestQuickPicks();
    if (!data || data.status === 'no_data') return;
    if (data.error) return;
    
    // 有历史数据，直接渲染
    resultDiv.style.display = 'block';
    renderQuickPicksResult(data.result, resultDiv, data.scan_time);
  } catch (err) {
    // 静默失败，不阻塞页面
    console.warn('加载最新选股结果失败:', err.message);
  }
}

async function runQuickPicks() {
  const btn = document.getElementById('quickPicksBtn');
  const resultDiv = document.getElementById('quickPicksResult');
  if (btn && btn.disabled) return;

  if (btn) { btn.disabled = true; btn.innerHTML = '⏳ 扫描已启动...'; }
  resultDiv.style.display = 'block';
  resultDiv.innerHTML = '<div class="loading" style="padding:40px;text-align:center"><div class="spinner" style="margin:0 auto 16px"></div><div>后台扫描已启动...<br><span style="font-size:12px;color:var(--text-muted)">双均线+回调企稳策略分析中，预计约2~3分钟<br>你可以先浏览其他页面，稍后回来查看结果</span></div></div>';
  resultDiv.scrollIntoView({ behavior: 'smooth', block: 'start' });

  try {
    const triggerResp = await API.triggerQuickPicks();
    
    if (triggerResp && triggerResp.error) {
      resultDiv.innerHTML = `<div style="text-align:center;padding:40px;color:var(--color-down)"><strong>触发失败</strong><p style="margin-top:8px">${triggerResp.message || '未知错误'}</p></div>`;
      if (btn) { btn.disabled = false; btn.textContent = '🚀 开始选股'; }
      return;
    }

    if (triggerResp.status === 'already_done') {
      // 今天已经扫过了，直接加载结果
      showToast(`今日已扫描过，直接加载结果`, 'info');
      await loadLatestQuickPicks();
      if (btn) { btn.disabled = false; btn.textContent = '🚀 开始选股'; }
      return;
    }

    // 轮询等待结果（每10秒检查一次，最多20次=200秒）
    let attempts = 0;
    const maxAttempts = 20;
    const pollInterval = 10000;

    const poll = async () => {
      attempts++;
      try {
        const latest = await API.getLatestQuickPicks();
        if (latest && latest.status === 'ok' && latest.scan_time) {
          // 检查是否是新扫描的结果
          const scanTime = latest.scan_time;
          if (triggerResp.status === 'scanning' || scanTime) {
            resultDiv.style.display = 'block';
            renderQuickPicksResult(latest.result, resultDiv, latest.scan_time);
            if (btn) { btn.disabled = false; btn.textContent = '🚀 开始选股'; }
            showToast('✅ 选股扫描完成！', 'success');
            return;
          }
        }
      } catch (e) { /* 忽略轮询错误 */ }

      if (attempts < maxAttempts) {
        // 更新等待提示
        resultDiv.innerHTML = `<div class="loading" style="padding:40px;text-align:center"><div class="spinner" style="margin:0 auto 16px"></div><div>后台扫描中... (${attempts * 10}秒)<br><span style="font-size:12px;color:var(--text-muted)">预计还需 ${Math.max(1, Math.round((maxAttempts * 10 - attempts * 10) / 10))} 分钟内完成</span></div></div>`;
        setTimeout(poll, pollInterval);
      } else {
        resultDiv.innerHTML = `<div style="text-align:center;padding:40px;color:var(--color-warning)"><strong>⏳ 扫描时间较长</strong><p style="margin-top:8px">请稍后刷新页面查看结果，或点击重新选股</p></div>`;
        if (btn) { btn.disabled = false; btn.textContent = '🚀 开始选股'; }
      }
    };

    // 首次延迟15秒开始轮询（给扫描启动时间）
    setTimeout(poll, 15000);

  } catch (err) {
    resultDiv.innerHTML = `<div style="text-align:center;padding:40px;color:var(--color-down)"><strong>扫描失败</strong><p style="margin-top:8px">${err.message || '未知错误'}</p></div>`;
    if (btn) { btn.disabled = false; btn.textContent = '🚀 开始选股'; }
  }
}

function renderQuickPicksResult(data, container, scanTime) {
  if (!data) { container.innerHTML = '<div style="padding:20px;color:var(--text-muted)">无数据</div>'; return; }

  const resonance = data.resonance || [];
  const strategies = data.strategies || {};
  const industry = data.industry_distribution || {};

  // 如果信号特别多，各策略只展示 Top10
  const MAX_PER_STRATEGY = 10;

  let html = `
    <div class="card-header" style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
      <div class="card-title" style="margin-bottom:0">📋 一键选股结果${scanTime ? ` <span style="font-size:12px;color:var(--text-muted);font-weight:normal">— 扫描时间: ${scanTime}</span>` : ''}</div>
      <div style="font-size:13px;color:var(--text-muted)">
        数据日期: ${data.data_date || '—'} | 扫描: ${data.total_stocks_scanned || 0}只 | 信号: ${data.total_signals_found || 0}只
      </div>
    </div>
  `;

  // ===== 共振股（最亮眼） =====
  if (resonance.length > 0) {
    const displayResonance = resonance.slice(0, 10);
    html += `
      <div style="margin-bottom:20px;padding:16px;background:linear-gradient(135deg,rgba(34,197,94,0.1),rgba(59,130,246,0.08));border-radius:var(--radius);border:1px solid rgba(34,197,94,0.3)">
        <div style="font-weight:700;font-size:16px;margin-bottom:12px;color:var(--color-up)">🔥 多策略共振 — 最值得关注 (${resonance.length}只${resonance.length > 10 ? '，展示前10' : ''})</div>
        <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:12px">
          ${displayResonance.map(s => `
            <div class="quick-pick-card" style="padding:12px;background:var(--color-background);border-radius:var(--radius);border:1px solid var(--border);cursor:pointer" onclick="analyzeStock('${escapeHtml(s.ts_code)}')">
              <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
                <div>
                  <strong style="font-size:15px">${s.name || '—'}</strong>
                  <code style="font-family:var(--font-mono);font-size:12px;color:var(--text-muted);margin-left:6px">${s.ts_code}</code>
                </div>
                <span class="tag tag-green" style="font-size:12px">⚡ ${s.hit_count}策略共振</span>
              </div>
              <div style="display:flex;flex-wrap:wrap;gap:4px;margin-bottom:8px">
                ${(s.strategies || []).map(st => `<span class="tag tag-purple" style="font-size:11px">${st.strategy}: ${st.reason}</span>`).join('')}
              </div>
              ${s.entry_points ? `
                <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;font-size:12px">
                  <div><span style="color:var(--text-muted)">当前价</span><br><strong style="font-family:var(--font-mono)">¥${s.price?.toFixed(2) || '—'}</strong></div>
                  <div><span style="color:var(--text-muted)">买入区间</span><br><strong style="font-family:var(--font-mono);color:var(--color-up)">¥${(s.entry_points.buy_zone || ['—','—'])[0]} ~ ${(s.entry_points.buy_zone || ['—','—'])[1]}</strong></div>
                  <div><span style="color:var(--text-muted)">止损</span><br><strong style="font-family:var(--font-mono);color:var(--color-down)">¥${s.entry_points.stop_loss || '—'}</strong></div>
                </div>
                ${s.entry_points.target_1 ? `<div style="margin-top:6px;font-size:12px"><span style="color:var(--text-muted)">目标1:</span> <strong style="font-family:var(--font-mono);color:var(--color-up)">¥${s.entry_points.target_1}</strong></div>` : ''}
              ` : ''}
              ${s.risk && !s.risk.pass ? `<div style="margin-top:6px;font-size:11px;color:var(--color-down)">⚠️ ${(s.risk.warnings || []).join('、')}</div>` : ''}
            </div>
          `).join('')}
        </div>
      </div>
    `;
  }

  // ===== 各策略信号股列表 =====
  for (const [key, info] of Object.entries(strategies)) {
    const allPicks = info.top_picks || [];
    if (allPicks.length === 0) continue;

    const displayPicks = allPicks.slice(0, MAX_PER_STRATEGY);
    const isLongList = allPicks.length > MAX_PER_STRATEGY;

    html += `
      <details style="margin-bottom:12px;background:var(--surface);border-radius:var(--radius);padding:12px 16px" ${displayPicks.length <= 10 ? 'open' : ''}>
        <summary style="cursor:pointer;font-weight:600;font-size:14px;margin-bottom:${displayPicks.length <= 10 ? '12px' : '0'}">
          ${info.name} — ${info.total_signals}只信号${isLongList ? ` (展示Top${MAX_PER_STRATEGY})` : ''}
        </summary>
        <table class="data-table" style="margin-top:8px">
          <thead>
            <tr>
              <th>代码</th>
              <th>名称</th>
              <th>行业</th>
              <th>信号价</th>
              <th>信号日期</th>
              <th>原因</th>
              <th>风控</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            ${displayPicks.map(p => {
              const risk = p.risk || {};
              const entry = p.entry_points || {};
              const riskOk = risk.pass !== false;
              return `
                <tr>
                  <td><code style="font-family:var(--font-mono);font-size:12px">${p.ts_code}</code></td>
                  <td><strong>${p.name || '—'}</strong></td>
                  <td style="font-size:13px;color:var(--text-muted)">${p.industry || '—'}</td>
                  <td style="font-family:var(--font-mono)">¥${p.signal?.price?.toFixed(2) || '—'}</td>
                  <td style="font-family:var(--font-mono);font-size:12px">${p.signal?.date || '—'}</td>
                  <td style="font-size:12px">${p.signal?.reason || '—'}</td>
                  <td>${riskOk ? '<span style="color:var(--color-up)">✅</span>' : '<span style="color:var(--color-down)" title="' + escapeHtml((risk.warnings || []).join('、')) + '">⚠️</span>'}</td>
                  <td>
                    <button class="btn btn-sm btn-primary" onclick="analyzeStock('${escapeHtml(p.ts_code)}')">分析</button>
                    <button class="btn btn-sm btn-outline" onclick="quickAddWatchlistByCode('${escapeHtml(p.ts_code)}','${escapeHtml(p.name || '')}')">⭐</button>
                  </td>
                </tr>
              `;
            }).join('')}
          </tbody>
        </table>
        ${isLongList ? `<div style="text-align:center;color:var(--text-muted);font-size:12px;padding:8px">...还有 ${allPicks.length - MAX_PER_STRATEGY} 只信号股</div>` : ''}
      </details>
    `;
  }

  // ===== 行业分布 =====
  const industryEntries = Object.entries(industry);
  if (industryEntries.length > 0) {
    html += `
      <div style="margin-top:12px;padding:12px;background:var(--surface);border-radius:var(--radius)">
        <div style="font-weight:600;font-size:13px;margin-bottom:8px;color:var(--text-secondary)">📊 行业分布 (前10)</div>
        <div style="display:flex;flex-wrap:wrap;gap:6px">
          ${industryEntries.slice(0, 10).map(([ind, cnt]) => `
            <span class="tag tag-blue" style="font-size:12px">${ind}: ${cnt}只</span>
          `).join('')}
        </div>
      </div>
    `;
  }

  // ===== 策略说明 =====
  html += `
    <div style="margin-top:12px;padding:10px;font-size:12px;color:var(--text-muted);border-top:1px solid var(--border)">
      💡 策略说明: 
      <strong>双均线(7/60)</strong> — MA7上穿MA60金叉买入，回测+101% |
      <strong>回调企稳(8/95/5)</strong> — ZLCMQ达到95后回调企稳，回测+100%。
      <span style="color:var(--color-down)">仅供投资参考，不构成投资建议。</span>
    </div>
  `;

  container.innerHTML = html;
}

// ========== 预设和策略加载 ==========
async function loadPresets() {
  const container = document.getElementById('presetCards');
  if (!container) return;
  
  try {
    const data = await API.getScreeningPresets();
    presetsCache = Array.isArray(data) ? data : (data.items || []);
    
    container.innerHTML = `
      <div style="display:grid;grid-template-columns:repeat(2,1fr);gap:8px">
        ${presetsCache.map(p => `
          <div class="preset-card" onclick="selectPreset('${p.key}')">
            <div style="font-weight:600;margin-bottom:2px;font-size:14px">${p.name}</div>
            <div style="font-size:12px;color:var(--text-muted)">${p.description}</div>
          </div>
        `).join('')}
      </div>
    `;
    
    const select = document.getElementById('presetSelect');
    if (select) {
      select.innerHTML = '<option value="" disabled selected>请选择...</option>' +
        presetsCache.map(p => `<option value="${p.key}">${p.name}</option>`).join('');
    }
  } catch (err) {
    container.innerHTML = `<span style="color:var(--color-down)">加载失败</span>`;
  }
}

async function loadStrategies() {
  const container = document.getElementById('strategyCheckboxes');
  if (!container) return;
  
  try {
    const data = await API.getStrategyTypes();
    const items = Array.isArray(data) ? data : (data.items || []);
    container.innerHTML = items.map(s => `
      <label style="display:flex;align-items:center;gap:6px;margin-bottom:6px;cursor:pointer">
        <input type="checkbox" name="strategy" value="${s.key}" checked>
        <span style="font-size:14px">${s.name}</span>
      </label>
    `).join('');
  } catch (err) {
    container.innerHTML = `<span style="color:var(--color-down)">加载失败</span>`;
  }
}

function selectPreset(key) {
  const select = document.getElementById('presetSelect');
  if (select) {
    select.value = key;
  }
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

// ========== 全市场扫描 ==========
async function startScreening() {
  const presetSelect = document.getElementById('presetSelect');
  const daysInput = document.getElementById('daysInput');
  const topNInput = document.getElementById('topNInput');
  
  if (!presetSelect || !presetSelect.value) {
    showToast('请先选择一个预设模板', 'error');
    return;
  }
  
  const preset = presetSelect.value;
  const days = parseInt(daysInput?.value || 120);
  const top_n = parseInt(topNInput?.value || 20);
  const selectedStrategies = Array.from(document.querySelectorAll('#strategyCheckboxes input[name="strategy"]:checked'))
    .map(cb => cb.value).join(',');
  const market = document.querySelector('input[name="market"]:checked')?.value || 'all';
  
  const resultsSection = document.getElementById('resultsSection');
  const container = document.getElementById('resultsContainer');
  if (resultsSection) resultsSection.style.display = 'block';
  if (container) container.innerHTML = '<div class="loading"><div class="spinner"></div>正在扫描全市场...</div>';
  
  try {
    let stocks = null;
    if (market !== 'all') {
      const stockList = await API.getStockList();
      let filtered = [];
      if (market === 'sh') {
        filtered = stockList.filter(s => s.ts_code.endsWith('.SH') && !s.name.includes('ETF'));
      } else if (market === 'sz') {
        filtered = stockList.filter(s => s.ts_code.endsWith('.SZ') && !s.name.includes('ETF'));
      } else if (market === 'etf') {
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
        <div style="text-align:center;padding:40px;color:var(--color-down)">
          <strong>扫描失败</strong>
          <p style="margin-top:8px">${err.message || '未知错误'}</p>
          <button onclick="startScreening()" class="btn btn-sm btn-outline" style="margin-top:12px">重试</button>
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
      <div style="text-align:center;padding:40px;color:var(--text-muted)">
        <div style="font-size:40px;margin-bottom:12px">🔍</div>
        <p>未发现符合条件的股票</p>
        <p style="font-size:13px">尝试放宽筛选条件或选择其他预设模板</p>
      </div>
    `;
    stats.innerHTML = '0 只股票';
    return;
  }
  
  const maxScore = Math.max(...results.map(r => r.score || 0));
  stats.innerHTML = `${results.length} 只股票 | 最高评分: ${maxScore}`;
  
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
            <td><code style="font-family:var(--font-mono);font-size:13px">${r.ts_code}</code></td>
            <td><strong>${r.name || '—'}</strong></td>
            <td class="${(r.change_pct || 0) >= 0 ? 'positive' : 'negative'}">
              ¥${(r.close || 0).toFixed(2)}
            </td>
            <td class="${(r.change_pct || 0) >= 0 ? 'positive' : 'negative'}">
              ${(r.change_pct || 0) >= 0 ? '▲' : '▼'} ${Math.abs(r.change_pct || 0).toFixed(2)}%
            </td>
            <td><span class="tag ${r.signal_count >= 3 ? 'tag-green' : 'tag-blue'}">${r.signal_count}</span></td>
            <td><span class="score-badge" style="background:${getScoreColor(r.score)}">${r.score}</span></td>
            <td>
              ${(r.strategies_hit || []).slice(0,3).map(s => `<span class="tag tag-purple" style="font-size:11px">${s}</span>`).join('')}
            </td>
            <td>
              <button class="btn btn-sm btn-primary" onclick="analyzeStock('${escapeHtml(r.ts_code)}')">分析</button>
              <button class="btn btn-sm btn-outline" onclick="quickAddWatchlistByCode('${escapeHtml(r.ts_code)}','${escapeHtml(r.name || '')}')">⭐</button>
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

// ========== 个股深度分析（全局统一入口） ==========

// 全局分析弹窗引用（动态创建，不依赖页面 DOM）
let _globalAnalysisModal = null;
let _globalAnalysisContent = null;

/**
 * 全局个股分析入口 — 任何页面都可以调用
 * 动态创建 modal，不依赖 screening 页面的 DOM
 */
async function openStockAnalysisModal(tsCode, name) {
  // 如果 screening 页面的 modal 存在，复用
  const screeningModal = document.getElementById('analysisModal');
  const screeningContent = document.getElementById('analysisContent');

  // 如果 dashboard 页面的 modal 存在，复用
  const dashModal = document.getElementById('dashAnalysisModal');
  const dashContent = document.getElementById('dashAnalysisContent');

  // 优先用当前页面的 modal，否则动态创建
  let modal, content;
  if (screeningModal && screeningContent) {
    modal = screeningModal;
    content = screeningContent;
  } else if (dashModal && dashContent) {
    modal = dashModal;
    content = dashContent;
  } else {
    // 动态创建全局 modal（signals 等页面使用）
    if (!_globalAnalysisModal) {
      _globalAnalysisModal = document.createElement('div');
      _globalAnalysisModal.className = 'modal';
      _globalAnalysisModal.innerHTML = `
        <div class="modal-content" style="max-width:860px">
          <div class="modal-header">
            <div class="modal-title">📊 个股深度分析</div>
            <button class="modal-close" onclick="closeStockAnalysisModal()">×</button>
          </div>
          <div id="globalAnalysisContent" class="modal-body"></div>
        </div>
      `;
      document.body.appendChild(_globalAnalysisModal);
    }
    modal = _globalAnalysisModal;
    content = modal.querySelector('#globalAnalysisContent');
  }

  modal.style.display = 'flex';
  content.innerHTML = `
    <div style="text-align:center;padding:40px">
      <div class="spinner" style="margin:0 auto 12px"></div>
      <div>正在分析 ${name || tsCode}...</div>
    </div>
  `;

  try {
    const data = await API.analyzeStock(tsCode, 250);
    currentAnalysis = data;
    content.innerHTML = renderAnalysis(data);
  } catch (err) {
    content.innerHTML = `
      <div style="text-align:center;padding:40px;color:var(--color-down)">
        <strong>分析失败</strong>
        <p style="margin-top:8px">${err.message || '未知错误'}</p>
        <button class="btn btn-sm btn-outline" style="margin-top:12px" onclick="openStockAnalysisModal('${escapeHtml(tsCode)}','${escapeHtml(name || '')}')">重试</button>
      </div>
    `;
  }
}

/**
 * 统一关闭函数 — 关闭任何来源的分析弹窗
 */
function closeStockAnalysisModal() {
  // 关闭 screening 的
  const sm = document.getElementById('analysisModal');
  if (sm) sm.style.display = 'none';
  // 关闭 dashboard 的
  const dm = document.getElementById('dashAnalysisModal');
  if (dm) dm.style.display = 'none';
  // 关闭全局动态创建的
  if (_globalAnalysisModal) _globalAnalysisModal.style.display = 'none';
}

/**
 * screening 页面专用入口（保持兼容）
 */
async function analyzeStock(ts_code) {
  await openStockAnalysisModal(ts_code, '');
}

function renderAnalysis(data) {
  if (!data || data.error) {
    return `<div style="text-align:center;padding:40px;color:var(--text-muted)">${data?.error || '分析数据为空'}</div>`;
  }
  
  const latest = data.latest || {};
  const rec = data.recommendation || {};
  const signals = data.signals || {};
  const ma = data.ma || {};
  
  // 统计买入/卖出信号数
  let buyCount = 0, sellCount = 0;
  Object.values(signals).forEach(sigs => {
    sigs.forEach(s => { if (s.signal === 'buy') buyCount++; else sellCount++; });
  });

  return `
    <!-- 核心信息 -->
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:20px;padding:16px;background:var(--surface);border-radius:var(--radius)">
      <div>
        <div style="font-size:20px;font-weight:700">${latest.name || data.ts_code}</div>
        <div style="font-size:13px;color:var(--text-muted);font-family:var(--font-mono)">${data.ts_code}</div>
      </div>
      <div style="text-align:right">
        <div style="font-size:24px;font-weight:700;font-family:var(--font-mono);color:${(latest.change_pct || 0) >= 0 ? 'var(--color-up)' : 'var(--color-down)'}">
          ¥${(latest.close || 0).toFixed(2)}
        </div>
        <div style="font-size:14px;font-weight:600;color:${(latest.change_pct || 0) >= 0 ? 'var(--color-up)' : 'var(--color-down)'}">
          ${(latest.change_pct || 0) >= 0 ? '▲' : '▼'} ${Math.abs(latest.change_pct || 0).toFixed(2)}%
        </div>
      </div>
    </div>

    <!-- 数据概览 -->
    <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:20px">
      <div style="text-align:center;padding:12px;background:var(--surface);border-radius:var(--radius)">
        <div style="font-size:12px;color:var(--text-muted)">成交量</div>
        <div style="font-size:16px;font-weight:600;font-family:var(--font-mono)">${fmtScreenVol(latest.vol || 0)}</div>
      </div>
      <div style="text-align:center;padding:12px;background:var(--surface);border-radius:var(--radius)">
        <div style="font-size:12px;color:var(--text-muted)">成交额</div>
        <div style="font-size:16px;font-weight:600;font-family:var(--font-mono)">${fmtScreenAmt(latest.amount || 0)}</div>
      </div>
      <div style="text-align:center;padding:12px;background:var(--surface);border-radius:var(--radius)">
        <div style="font-size:12px;color:var(--text-muted)">买入信号</div>
        <div style="font-size:16px;font-weight:600;color:var(--color-up)">${buyCount}</div>
      </div>
      <div style="text-align:center;padding:12px;background:var(--surface);border-radius:var(--radius)">
        <div style="font-size:12px;color:var(--text-muted)">卖出信号</div>
        <div style="font-size:16px;font-weight:600;color:var(--color-down)">${sellCount}</div>
      </div>
    </div>

    <!-- 均线指标 -->
    ${Object.keys(ma).length > 0 ? `
      <div style="margin-bottom:20px">
        <div style="font-weight:600;margin-bottom:8px;font-size:14px;color:var(--text-secondary)">📊 均线指标</div>
        <div style="display:flex;flex-wrap:wrap;gap:8px">
          ${Object.entries(ma).map(([key, value]) => `
            <span class="tag tag-blue" style="font-size:13px">${key}: ${value.toFixed(2)}</span>
          `).join('')}
          ${data.rsi ? `
            <span class="tag ${data.rsi > 70 ? 'tag-red' : data.rsi < 30 ? 'tag-green' : 'tag-yellow'}" style="font-size:13px">
              RSI(14): ${data.rsi}${data.rsi > 70 ? ' (超买)' : data.rsi < 30 ? ' (超卖)' : ''}
            </span>
          ` : ''}
        </div>
      </div>
    ` : ''}
    
    <!-- 综合建议 -->
    ${rec.reason ? `
      <div style="margin-bottom:20px;padding:16px;background:var(--surface);border-radius:var(--radius);border-left:3px solid ${rec.action === 'buy' ? 'var(--color-up)' : rec.action === 'sell' ? 'var(--color-down)' : 'var(--color-warning)'}">
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
          <strong>🎯 综合建议</strong>
          <span class="tag ${rec.action === 'buy' ? 'tag-green' : rec.action === 'sell' ? 'tag-red' : 'tag-gray'}">
            ${rec.level || '—'}
          </span>
        </div>
        <p style="color:var(--text-secondary);font-size:14px">${rec.reason || '—'}</p>
        <div style="display:grid;grid-template-columns:repeat(2,1fr);gap:12px;margin-top:12px">
          <div>
            <span style="font-size:12px;color:var(--text-muted)">买入策略</span>
            <div style="margin-top:4px">
              ${(rec.buy_strategies || []).length > 0 ? rec.buy_strategies.map(s => `<span class="tag tag-green" style="font-size:11px">${s}</span>`).join(' ') : '<span style="color:var(--text-muted);font-size:13px">无</span>'}
            </div>
          </div>
          <div>
            <span style="font-size:12px;color:var(--text-muted)">卖出策略</span>
            <div style="margin-top:4px">
              ${(rec.sell_strategies || []).length > 0 ? rec.sell_strategies.map(s => `<span class="tag tag-red" style="font-size:11px">${s}</span>`).join(' ') : '<span style="color:var(--text-muted);font-size:13px">无</span>'}
            </div>
          </div>
        </div>
        <div style="display:grid;grid-template-columns:repeat(2,1fr);gap:12px;margin-top:12px">
          <div>
            <span style="font-size:12px;color:var(--text-muted)">止损位</span>
            <code style="display:block;margin-top:4px;font-size:16px;font-weight:600;color:var(--color-down)">¥${rec.stop_loss || '—'}</code>
          </div>
          <div>
            <span style="font-size:12px;color:var(--text-muted)">止盈位</span>
            <code style="display:block;margin-top:4px;font-size:16px;font-weight:600;color:var(--color-up)">¥${rec.take_profit || '—'}</code>
          </div>
        </div>
      </div>
    ` : ''}
    
    <!-- 详细信号 -->
    ${Object.keys(signals).length > 0 ? `
      <div style="margin-bottom:16px">
        <div style="font-weight:600;margin-bottom:12px;font-size:14px;color:var(--text-secondary)">📡 详细信号</div>
        ${Object.entries(signals).map(([key, sigs]) => `
          <details style="margin-bottom:8px;background:var(--surface);border-radius:var(--radius);padding:8px 12px" ${sigs.length <= 5 ? 'open' : ''}>
            <summary style="cursor:pointer;font-weight:600;font-size:14px">
              ${key} (${sigs.length}个信号: <span style="color:var(--color-up)">${sigs.filter(s => s.signal === 'buy').length}买</span> / <span style="color:var(--color-down)">${sigs.filter(s => s.signal === 'sell').length}卖</span>)
            </summary>
            <div style="margin-top:8px">
              ${sigs.slice(0, 20).map(s => `
                <div style="padding:6px 10px;border-radius:4px;margin-bottom:4px;display:flex;align-items:center;gap:10px;font-size:13px;border-left:3px solid ${s.signal === 'buy' ? 'var(--color-up)' : 'var(--color-down)'}">
                  <span style="font-family:var(--font-mono);color:var(--text-muted);min-width:70px">${s.date}</span>
                  <span class="tag ${s.signal === 'buy' ? 'tag-green' : 'tag-red'}" style="font-size:11px">${s.signal === 'buy' ? '买入' : '卖出'}</span>
                  <span style="color:var(--text-secondary)">${s.reason || '—'}</span>
                </div>
              `).join('')}
              ${sigs.length > 20 ? `<div style="text-align:center;color:var(--text-muted);font-size:12px;padding:8px">...还有 ${sigs.length - 20} 个信号</div>` : ''}
            </div>
          </details>
        `).join('')}
      </div>
    ` : ''}
    
    <div class="modal-actions" style="margin-top:20px">
      <button class="btn btn-primary" onclick="quickAddWatchlistByCode('${data.ts_code}', '${latest.name || ''}')">
        ⭐ 加入关注
      </button>
      <button class="btn btn-outline" onclick="closeStockAnalysisModal()">关闭</button>
    </div>
  `;
}

// 兼容旧调用
function closeAnalysisModal() {
  closeStockAnalysisModal();
}

async function quickAddWatchlistByCode(tsCode, name) {
  const result = await API.addToWatchlist(tsCode, name);
  if (result && result.success) {
    showToast(`✅ ${name || tsCode} 已加入关注列表`, 'success');
  } else {
    showToast('添加失败，可能已在关注列表中', 'error');
  }
}

// ========== 工具函数 ==========

/**
 * 根据 6 位数字代码自动判断交易所后缀
 * 6/9 开头 → .SH（沪市）
 * 0/3 开头 → .SZ（深市）
 * 8/4 开头 → .BJ（北交所）
 */
function resolveStockSuffix(code) {
  if (code.startsWith('6') || code.startsWith('9')) return code + '.SH';
  if (code.startsWith('8') || code.startsWith('4')) return code + '.BJ';
  return code + '.SZ';
}

function fmtScreenVol(num) {
  if (num >= 1e6) return (num / 1e6).toFixed(1) + '万手';
  if (num >= 1e4) return (num / 1e4).toFixed(1) + '万手';
  return num.toLocaleString() + '手';
}

function fmtScreenAmt(num) {
  if (num >= 1e8) return (num / 1e8).toFixed(1) + '亿';
  if (num >= 1e4) return (num / 1e4).toFixed(1) + '万';
  return num.toLocaleString();
}

/**
 * escapeHtml 已在 app.js 全局定义，此处无需重复
 */

// ========== 样式 ==========
(function addStyles() {
  if (document.getElementById('screening-styles')) return;
  
  const style = document.createElement('style');
  style.id = 'screening-styles';
  style.textContent = `
    .preset-card {
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 12px;
      background: var(--color-background);
      cursor: pointer;
      transition: all 0.2s;
    }
    .preset-card:hover {
      background: var(--surface-hover);
      border-color: var(--primary);
      transform: translateY(-2px);
    }
    .score-badge {
      display: inline-block;
      padding: 2px 8px;
      border-radius: 10px;
      color: white;
      font-weight: 600;
      font-size: 12px;
    }
    .modal-content {
      max-height: 85vh;
      overflow-y: auto;
    }
    details summary {
      list-style: none;
    }
    details summary::-webkit-details-marker {
      display: none;
    }
    details summary::before {
      content: '▶ ';
      font-size: 10px;
      transition: transform 0.2s;
      display: inline-block;
    }
    details[open] summary::before {
      content: '▼ ';
    }
  `;
  document.head.appendChild(style);
})();
