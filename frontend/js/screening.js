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

      <!-- 📥 拉取当天数据 -->
      <div class="card" style="margin-bottom:12px">
        <div style="display:flex;gap:12px;align-items:center;flex-wrap:wrap">
          <button id="syncDataBtn" class="btn btn-outline" onclick="syncTodayData()" style="padding:8px 20px;font-size:14px">
            📥 拉取当天数据
          </button>
          <span style="font-size:12px;color:var(--text-muted)">同步股票列表 + 近5天日线行情（约1~2分钟）</span>
        </div>
        <div id="syncDataStatus" style="margin-top:8px;font-size:13px;display:none"></div>
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
        <div class="modal-content" style="max-width:920px">
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

async function forceRescan() {
  const btn = document.getElementById('quickPicksBtn');
  const resultDiv = document.getElementById('quickPicksResult');
  if (!resultDiv) return;
  if (btn) { btn.disabled = true; btn.innerHTML = '⏳ 重新扫描中...'; }
  resultDiv.style.display = 'block';
  resultDiv.innerHTML = '<div class="loading" style="padding:40px;text-align:center"><div class="spinner" style="margin:0 auto 16px"></div><div>强制重新扫描中...<br><span style="font-size:12px;color:var(--text-muted)">预计约2~3分钟完成</span></div></div>';

  try {
    const forceResp = await API.triggerQuickPicks(true);
    console.log('[QuickPicks] force rescan response:', forceResp);

    if (forceResp && forceResp.error) {
      resultDiv.innerHTML = `<div style="text-align:center;padding:40px;color:var(--color-down)"><strong>触发失败</strong><p style="margin-top:8px">${forceResp.message || '未知错误'}</p></div>`;
      if (btn) { btn.disabled = false; btn.textContent = '🚀 开始选股'; }
      return;
    }

    // 轮询等待新结果
    let attempts = 0;
    const maxAttempts = 25;
    const pollInterval = 10000;
    const startTime = Date.now();

    const poll = async () => {
      attempts++;
      try {
        const latest = await API.getLatestQuickPicks();
        if (latest && latest.status === 'ok' && latest.scan_time) {
          // 检查 scan_time 是否比触发时间更新（允许2秒误差）
          const scanTs = new Date(latest.scan_time).getTime();
          if (scanTs >= startTime - 2000) {
            const pollDiv = document.getElementById('quickPicksResult');
            if (!pollDiv) return;
            pollDiv.style.display = 'block';
            renderQuickPicksResult(latest.result, pollDiv, latest.scan_time);
            if (btn) { btn.disabled = false; btn.textContent = '🚀 开始选股'; }
            showToast('✅ 重新扫描完成！', 'success');
            return;
          }
        }
      } catch (e) { /* 忽略轮询错误 */ }
      if (attempts < maxAttempts) {
        const pDiv = document.getElementById('quickPicksResult');
        if (pDiv) pDiv.innerHTML = `<div class="loading" style="padding:40px;text-align:center"><div class="spinner" style="margin:0 auto 16px"></div><div>重新扫描中... (${attempts * 10}秒)<br><span style="font-size:12px;color:var(--text-muted)">预计还需约${Math.max(1, Math.round((maxAttempts - attempts) * 10 / 60))}分钟</span></div></div>`;
        setTimeout(poll, pollInterval);
      } else {
        const pDiv = document.getElementById('quickPicksResult');
        if (pDiv) pDiv.innerHTML = `<div style="text-align:center;padding:40px;color:var(--color-warning)"><strong>⏳ 扫描时间较长</strong><p style="margin-top:8px">请稍后刷新页面查看结果</p></div>`;
        if (btn) { btn.disabled = false; btn.textContent = '🚀 开始选股'; }
      }
    };
    setTimeout(poll, 15000);
  } catch (err) {
    const errDiv = document.getElementById('quickPicksResult');
    if (errDiv) errDiv.innerHTML = `<div style="text-align:center;padding:40px;color:var(--color-down)"><strong>扫描失败</strong><p style="margin-top:8px">${err.message || '未知错误'}</p></div>`;
    if (btn) { btn.disabled = false; btn.textContent = '🚀 开始选股'; }
  }
}

async function loadLatestQuickPicks() {
  const resultDiv = document.getElementById('quickPicksResult');
  if (!resultDiv) return;

  try {
    const data = await API.getLatestQuickPicks();
    console.log('[QuickPicks] latest response:', data?.status, data?.scan_time, 'data_fresh:', data?.data_fresh);
    if (!data || data.status === 'no_data') {
      console.log('[QuickPicks] 无数据');
      return;
    }
    if (data.error) {
      console.warn('[QuickPicks] API error:', data.message);
      return;
    }

    // 🦉 夜枭补充：数据新鲜度处理
    // 如果数据不新鲜，在结果区域顶部显示警告
    const currentDiv = document.getElementById('quickPicksResult');
    if (!currentDiv) return;
    currentDiv.style.display = 'block';

    // 收集新鲜度信息
    const dataFresh = data.data_fresh !== false;  // 默认新鲜
    const dataFreshMsg = data.data_fresh_msg || (dataFresh ? '' : '数据非今日，请检查Token或强制重新扫描');

    console.log('[QuickPicks] 渲染结果, resonance:', (data.result?.resonance || []).length, 'strategies:', Object.keys(data.result?.strategies || {}).length, 'dataFresh:', dataFresh);
    try {
      // 传入新鲜度信息给渲染函数
      renderQuickPicksResult(data.result, currentDiv, data.scan_time, {
        dataFresh,
        dataFreshMsg,
        dataDate: data.data_date,
      });
    } catch (innerErr) {
      console.error('[QuickPicks] 渲染失败:', innerErr.message);
      try { currentDiv.innerHTML = '<div style="padding:20px;color:var(--color-down)">渲染出错，请刷新页面重试</div>'; } catch(ie) {}
    }
  } catch (err) {
    // 静默失败，不阻塞页面
    console.warn('[QuickPicks] 加载失败:', err.message);
  }
}

async function runQuickPicks() {
  const btn = document.getElementById('quickPicksBtn');
  const resultDiv = document.getElementById('quickPicksResult');
  if (btn && btn.disabled) return;

  if (!resultDiv) return;  // 页面已切换，安全退出
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
      // 🦊 狐探优化：区分"数据新鲜"和"数据不新鲜"两种情况
      const dataFresh = triggerResp.data_fresh !== false;
      const dataFreshMsg = triggerResp.data_fresh_msg || '';
      const dataDate = triggerResp.data_date || '';

      console.log('[QuickPicks] already_done, dataFresh:', dataFresh, 'dataFreshMsg:', dataFreshMsg);
      await loadLatestQuickPicks();
      if (btn) { btn.disabled = false; btn.textContent = '🚀 开始选股'; }

      const resultArea = document.getElementById('quickPicksResult');
      if (resultArea && resultArea.style.display !== 'none') {
        const existingHtml = resultArea.innerHTML;
        // 🦉 夜枭补充：根据数据新鲜度显示不同颜色提示
        const bannerBg = dataFresh
          ? 'rgba(59,130,246,0.1)'
          : 'rgba(245,158,11,0.15)';  // 警告用黄色
        const bannerColor = dataFresh
          ? 'var(--text-secondary)'
          : 'var(--color-warning)';
        const bannerIcon = dataFresh ? '📅' : '⚠️';
        const bannerText = dataFresh
          ? `今日已扫描过（${dataDate}），以下为最新结果`
          : `数据日期(${dataDate})不是今天，以下为缓存结果 — ${dataFreshMsg || '请强制重新扫描'}`;

        resultArea.innerHTML = `
          <div style="padding:10px 16px;background:${bannerBg};border-radius:8px 8px 0 0;font-size:13px;color:${bannerColor};display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">
            <span>${bannerIcon} ${bannerText}</span>
            <button class="btn btn-sm btn-outline" onclick="forceRescan()" style="white-space:nowrap">🔄 强制重新扫描</button>
          </div>
          ${existingHtml}
        `;
      }
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
            const pollDiv = document.getElementById('quickPicksResult');
            if (!pollDiv) return;
            pollDiv.style.display = 'block';
            renderQuickPicksResult(latest.result, pollDiv, latest.scan_time);
            if (btn) { btn.disabled = false; btn.textContent = '🚀 开始选股'; }
            showToast('✅ 选股扫描完成！', 'success');
            return;
          }
        }
      } catch (e) { /* 忽略轮询错误 */ }

      if (attempts < maxAttempts) {
        // 更新等待提示
        const pDiv2 = document.getElementById('quickPicksResult');
        if (pDiv2) pDiv2.innerHTML = `<div class="loading" style="padding:40px;text-align:center"><div class="spinner" style="margin:0 auto 16px"></div><div>后台扫描中... (${attempts * 10}秒)<br><span style="font-size:12px;color:var(--text-muted)">预计还需 ${Math.max(1, Math.round((maxAttempts * 10 - attempts * 10) / 10))} 分钟内完成</span></div></div>`;
        setTimeout(poll, pollInterval);
      } else {
        const pDiv2 = document.getElementById('quickPicksResult');
        if (pDiv2) pDiv2.innerHTML = `<div style="text-align:center;padding:40px;color:var(--color-warning)"><strong>⏳ 扫描时间较长</strong><p style="margin-top:8px">请稍后刷新页面查看结果，或点击重新选股</p></div>`;
        if (btn) { btn.disabled = false; btn.textContent = '🚀 开始选股'; }
      }
    };

    // 首次延迟15秒开始轮询（给扫描启动时间）
    setTimeout(poll, 15000);

  } catch (err) {
    const errDiv = document.getElementById('quickPicksResult');
    if (errDiv) errDiv.innerHTML = `<div style="text-align:center;padding:40px;color:var(--color-down)"><strong>扫描失败</strong><p style="margin-top:8px">${err.message || '未知错误'}</p></div>`;
    if (btn) { btn.disabled = false; btn.textContent = '🚀 开始选股'; }
  }
}

function renderQuickPicksResult(data, container, scanTime, freshnessInfo) {
  if (!container) return;
  if (!data) { try { container.innerHTML = '<div style="padding:20px;color:var(--text-muted)">无数据</div>'; } catch(e) {} return; }

  const resonance = data.resonance || [];
  const strategies = data.strategies || {};
  const industry = data.industry_distribution || {};
  const MAX_PER_STRATEGY = 10;

  // 🦉 夜枭补充：数据新鲜度警告标签
  // 从 freshnessInfo 或 data 中获取新鲜度信息
  const dataFresh = freshnessInfo ? freshnessInfo.dataFresh : (data.data_date_fresh !== false);
  const dataFreshMsg = freshnessInfo ? freshnessInfo.dataFreshMsg : (data.data_freshness_msg || '');
  const dataDate = freshnessInfo ? (freshnessInfo.dataDate || data.data_date) : data.data_date;

  let freshnessBanner = '';
  if (!dataFresh) {
    freshnessBanner = `
      <div style="margin-bottom:12px;padding:10px 14px;background:rgba(245,158,11,0.12);border:1px solid rgba(245,158,11,0.4);border-radius:var(--radius);font-size:13px;color:var(--color-warning)">
        ⚠️ <strong>数据新鲜度警告</strong>：数据日期(${dataDate})不是今天，可能因Tushare Token失效或同步中断导致。
        ${dataFreshMsg ? `<br>原因：${dataFreshMsg}` : ''}
        <br><span style="font-size:12px">请检查 Token 配置或点击「🔄 强制重新扫描」更新数据</span>
      </div>
    `;
  }

  let html = '';
  try {
    html = `
    ${freshnessBanner}
    <div class="card-header" style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
      <div class="card-title" style="margin-bottom:0">📋 一键选股结果${scanTime ? ` <span style="font-size:12px;color:var(--text-muted);font-weight:normal">— 扫描时间: ${scanTime}</span>` : ''}</div>
      <div style="font-size:13px;color:var(--text-muted)">
        数据日期: ${dataDate || '—'} | 扫描: ${data.total_stocks_scanned || 0}只 | 信号: ${data.total_signals_found || 0}只
        ${data.risk_summary ? ` | <span style="color:var(--color-down)">🚫排除${data.risk_summary.blocked_count || 0}</span> <span style="color:var(--color-warning)">⚠️警告${data.risk_summary.warning_count || 0}</span> <span style="color:var(--color-up)">🛡️安全${data.risk_summary.safe_count || 0}</span>` : ''}
      </div>
    </div>
    `;

  // ===== 共振股（最亮眼 — 按综合评分排序） =====
  if (resonance.length > 0) {
    const displayResonance = resonance.slice(0, 10);
    html += `
      <div style="margin-bottom:20px;padding:16px;background:linear-gradient(135deg,rgba(239,68,68,0.1),rgba(59,130,246,0.08));border-radius:var(--radius);border:1px solid rgba(239,68,68,0.3)">
        <div style="font-weight:700;font-size:16px;margin-bottom:12px;color:var(--color-up)">🔥 多策略共振 — 按AI评分排序 (${resonance.length}只${resonance.length > 10 ? '，展示前10' : ''})</div>
        <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(360px,1fr));gap:12px">
          ${displayResonance.map((s, idx) => {
            const sc = s.score || {};
            const scoreTotal = sc.total || 0;
            const scoreIcon = sc.icon || '⚪';
            const scoreAdvice = sc.advice || '—';
            const scoreColor = scoreTotal >= 65 ? 'var(--color-up)' : (scoreTotal >= 50 ? 'var(--color-warning)' : 'var(--color-down)');
            return `
            <div class="quick-pick-card" style="padding:12px;background:var(--color-background);border-radius:var(--radius);border:1px solid ${scoreTotal >= 65 ? 'rgba(239,68,68,0.4)' : 'var(--border)'};cursor:pointer" onclick="analyzeStock('${escapeHtml(s.ts_code)}')">
              <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
                <div>
                  <strong style="font-size:15px">${s.name || '—'}</strong>
                  <code style="font-family:var(--font-mono);font-size:12px;color:var(--text-muted);margin-left:6px">${s.ts_code}</code>
                </div>
                <div style="display:flex;align-items:center;gap:6px">
                  <span class="tag tag-green" style="font-size:11px">⚡${s.hit_count}策略</span>
                  <span style="font-size:16px;font-weight:700;color:${scoreColor}">${scoreIcon} ${scoreTotal}</span>
                </div>
              </div>
              <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
                <span style="padding:2px 8px;border-radius:4px;font-size:12px;font-weight:600;background:${scoreTotal >= 65 ? 'rgba(239,68,68,0.2);color:var(--color-up)' : (scoreTotal >= 50 ? 'rgba(245,158,11,0.2);color:var(--color-warning)' : 'rgba(34,197,94,0.2);color:var(--color-down)')}">${scoreAdvice}</span>
                ${sc.rsi != null ? `<span style="font-size:11px;color:var(--text-muted)">RSI:${sc.rsi}</span>` : ''}
                ${sc.macd ? `<span style="font-size:11px;color:${sc.macd === '金叉' ? 'var(--color-up)' : 'var(--color-down)'}">MACD:${sc.macd}</span>` : ''}
                ${sc.ma_status ? `<span style="font-size:11px;color:var(--text-muted)">均线:${sc.ma_status}</span>` : ''}
                ${sc.today_chg != null ? `<span style="font-size:11px;color:${sc.today_chg >= 0 ? 'var(--color-up)' : 'var(--color-down)'}">${sc.today_chg >= 0 ? '+' : ''}${sc.today_chg}%</span>` : ''}
              </div>
              ${scoreTotal > 0 ? `
              <div style="display:flex;gap:4px;margin-bottom:8px;font-size:11px">
                <span style="color:var(--text-muted)">技术:${sc.tech}</span>
                <span style="color:var(--text-muted)">|</span>
                <span style="color:var(--text-muted)">基本:${sc.base}</span>
                <span style="color:var(--text-muted)">|</span>
                <span style="color:var(--text-muted)">消息:${sc.news}</span>
                <span style="color:var(--text-muted)">|</span>
                <span style="color:var(--text-muted)">资金:${sc.fund}</span>
                ${s.trend_strength != null ? `<span style="color:var(--text-muted)">|</span><span style="color:var(--text-muted)">趋势:${s.trend_strength}</span>` : ''}
                ${s.volume_score != null ? `<span style="color:var(--text-muted)">|</span><span style="color:var(--text-muted)">量能:${s.volume_score}</span>` : ''}
              </div>
              ` : ''}
              <div style="display:flex;flex-wrap:wrap;gap:4px;margin-bottom:8px">
                ${(s.strategies || []).map(st => `<span class="tag tag-purple" style="font-size:11px">${st.strategy}: ${st.reason}</span>`).join('')}
              </div>
              ${s.entry_points ? `
                <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;font-size:12px">
                  <div><span style="color:var(--text-muted)">当前价</span><br><strong style="font-family:var(--font-mono)">¥${s.price?.toFixed(2) || '—'}</strong></div>
                  <div><span style="color:var(--text-muted)">买入区间</span><br><strong style="font-family:var(--font-mono);color:var(--color-up)">¥${(s.entry_points.buy_zone || ['—','—'])[0]} ~ ${(s.entry_points.buy_zone || ['—','—'])[1]}</strong></div>
                  <div><span style="color:var(--text-muted)">止损</span><br><strong style="font-family:var(--font-mono);color:var(--color-down)">¥${s.entry_points.stop_loss || '—'}</strong></div>
                  <div><span style="color:var(--text-muted)">目标1</span><br><strong style="font-family:var(--font-mono);color:var(--color-up)">¥${s.entry_points.target_1 || '—'}</strong></div>
                </div>
                <div style="display:flex;gap:12px;margin-top:6px;font-size:11px;flex-wrap:wrap">
                  ${s.entry_points.target_2 ? `<span style="color:var(--text-muted)">目标2: <strong style="font-family:var(--font-mono);color:var(--color-up)">¥${s.entry_points.target_2}</strong></span>` : ''}
                  ${s.entry_points.resistance ? `<span style="color:var(--text-muted)">前高压力: <strong style="font-family:var(--font-mono)">¥${s.entry_points.resistance}</strong></span>` : ''}
                  ${s.entry_points.invalid_price ? `<span style="color:var(--text-muted)">破位放弃: <strong style="font-family:var(--font-mono);color:var(--color-down)">¥${s.entry_points.invalid_price}</strong></span>` : ''}
                </div>
              ` : ''}
              ${s.risk && !s.risk.pass ? `<div style="margin-top:6px;font-size:11px;color:var(--color-down)">⚠️ ${(s.risk.warnings || []).join('、')}</div>` : ''}
              ${(() => {
                const rl = s.risk_level || 'safe';
                if (rl === 'safe') {
                  return '<div style="margin-top:6px;font-size:11px;display:flex;align-items:center;gap:4px"><span style="color:var(--color-up)">🛡️ 风控安全</span></div>';
                } else if (rl === 'warning') {
                  const summ = s.risk_summary || '';
                  return `<div style="margin-top:6px;font-size:11px;display:flex;align-items:center;gap:4px"><span style="color:var(--color-warning)">⚠️ ${summ || '有风控警告'}</span></div>`;
                } else {
                  const summ = s.risk_summary || '';
                  return `<div style="margin-top:6px;font-size:11px;display:flex;align-items:center;gap:4px"><span style="color:var(--color-down)">🚫 ${summ || '已排除'}</span></div>`;
                }
              })()}
            </div>
          `}).join('')}
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
          ${info.name} — ${info.total_signals}只信号 (按AI评分排序${isLongList ? `，展示Top${MAX_PER_STRATEGY}` : ''})
        </summary>
        <table class="data-table" style="margin-top:8px">
          <thead>
            <tr>
              <th>评分</th>
              <th>代码</th>
              <th>名称</th>
              <th>行业</th>
              <th>信号价</th>
              <th>信号日期</th>
              <th>原因</th>
              <th>趋势/量能</th>
              <th>风控</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            ${displayPicks.map(p => {
              const risk = p.risk || {};
              const entry = p.entry_points || {};
              const riskOk = risk.pass !== false;
              const sc = p.score || {};
              const scoreTotal = sc.total || 0;
              const scoreIcon = sc.icon || '⚪';
              const scoreAdvice = sc.advice || '—';
              const riskLevel = p.risk_level || 'safe';
              const riskSummary = p.risk_summary || '';
              let riskBadge = '';
              if (riskLevel === 'safe') {
                riskBadge = '<span style="color:var(--color-up)">🛡️安全</span>';
              } else if (riskLevel === 'warning') {
                riskBadge = `<span style="color:var(--color-warning)" title="${escapeHtml(riskSummary)}">⚠️警告</span>`;
              } else {
                riskBadge = `<span style="color:var(--color-down)" title="${escapeHtml(riskSummary)}">🚫排除</span>`;
              }
              return `
                <tr>
                  <td>
                    <div style="font-weight:700;color:${scoreTotal >= 65 ? 'var(--color-up)' : (scoreTotal >= 50 ? 'var(--color-warning)' : 'var(--color-down)')}">${scoreIcon} ${scoreTotal}</div>
                    <div style="font-size:10px;color:var(--text-muted)">${scoreAdvice}</div>
                  </td>
                  <td><code style="font-family:var(--font-mono);font-size:12px">${p.ts_code}</code></td>
                  <td><strong>${p.name || '—'}</strong></td>
                  <td style="font-size:13px;color:var(--text-muted)">${p.industry || '—'}</td>
                  <td style="font-family:var(--font-mono)">¥${p.signal?.price?.toFixed(2) || '—'}</td>
                  <td style="font-family:var(--font-mono);font-size:12px">${p.signal?.date || '—'}</td>
                  <td style="font-size:12px">${p.signal?.reason || '—'}</td>
                  <td style="font-size:11px">
                    <div>${p.trend_strength != null ? `<span style="color:var(--text-muted)">趋势${p.trend_strength}</span>` : ''}</div>
                    <div>${p.volume_score != null ? `<span style="color:var(--text-muted)">量能${p.volume_score}</span>` : ''}</div>
                    <div>${p.recent_gain != null ? `<span style="color:${p.recent_gain >= 0 ? 'var(--color-up)' : 'var(--color-down)'}">${p.recent_gain >= 0 ? '+' : ''}${p.recent_gain}%</span>` : ''}</div>
                  </td>
                  <td>
                    <div>${riskBadge}</div>
                    ${riskSummary && riskLevel !== 'safe' ? `<div style="font-size:10px;color:var(--text-muted);max-width:100px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${escapeHtml(riskSummary)}">${escapeHtml(riskSummary)}</div>` : ''}
                    ${!riskOk ? `<div style="font-size:10px;color:var(--color-down)">⚠️${(risk.warnings || []).join('、')}</div>` : ''}
                  </td>
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
      <br>🛡️ 风控排雷: 自动过滤ST/*ST | 业绩预告首亏/预减/续亏 | 大股东减持>1% | 连续亏损 | 高负债率 | 财报窗口期预警
      <br><span style="color:var(--color-down)">仅供投资参考，不构成投资建议。</span>
    </div>
  `;
  } catch (buildErr) {
    console.error('[QuickPicks] HTML构建失败:', buildErr.message, buildErr.stack);
    if (container) container.innerHTML = `<div style="padding:20px;color:var(--color-down)">渲染出错: ${buildErr.message}</div>`;
    return;
  }

  // 最终安全检查
  if (!container) {
    console.warn('[QuickPicks] container became null before innerHTML assignment');
    return;
  }
  try {
    container.innerHTML = html;
    console.log('[QuickPicks] 渲染完成, html length:', html.length);
  } catch (renderErr) {
    console.error('[QuickPicks] innerHTML assignment failed:', renderErr.message);
    container.innerHTML = '<div style="padding:20px;color:var(--text-muted)">渲染结果时出错，请刷新页面重试</div>';
  }
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
  if (score >= 150) return '#EF4444';
  if (score >= 100) return '#3B82F6';
  if (score >= 50) return '#F59E0B';
  return '#22C55E';
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
        <div class="modal-content" style="max-width:920px">
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
    const data = await API.analyzeStockSense(tsCode, 250);
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
  const scores = data.scores || {};
  const ma = data.ma || {};
  const risk = data.risk || {};
  const entry = data.entry_points || {};
  const rt = data.realtime || null;
  const news = data.news_sentiment || null;

  function scoreColor(s) {
    if (s >= 80) return '#ef4444';
    if (s >= 65) return 'var(--color-up)';
    if (s >= 50) return '#eab308';
    if (s >= 35) return '#f97316';
    return 'var(--color-down)';
  }
  function gaugeRing(score, size = 120) {
    const r = 46;
    const circ = 2 * Math.PI * r;
    const pct = Math.min(Math.max(score, 0), 100) / 100;
    const dashLen = pct * circ;
    const gap = circ - dashLen;
    const col = scoreColor(score);
    return `
      <svg width="${size}" height="${size}" viewBox="0 0 100 100" style="transform:rotate(-90deg)">
        <circle cx="50" cy="50" r="${r}" fill="none" stroke="var(--border)" stroke-width="7" opacity="0.4"/>
        <circle cx="50" cy="50" r="${r}" fill="none" stroke="${col}" stroke-width="7"
          stroke-dasharray="${dashLen} ${gap}" stroke-linecap="round"
          style="transition:stroke-dasharray 1s ease;filter:drop-shadow(0 0 6px ${col}40)"/>
      </svg>`;
  }

  function dimBar(label, value, weight) {
    const v = Math.round(value || 0);
    const col = scoreColor(v);
    return `
      <div style="flex:1;min-width:0">
        <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:6px">
          <span style="font-size:13px;color:var(--text-secondary)">${label} <span style="color:var(--text-muted);font-size:11px">(${weight}%)</span></span>
          <span style="font-size:18px;font-weight:700;color:${col};font-family:var(--font-mono)">${v}</span>
        </div>
        <div style="height:6px;background:var(--border);border-radius:3px;overflow:hidden">
          <div style="height:100%;width:${v}%;background:linear-gradient(90deg,${col}30,${col});border-radius:3px;transition:width .8s ease"></div>
        </div>
      </div>`;
  }

  function sentimentGauge(val) {
    const pct = ((val + 1) / 2) * 100;
    const col = val >= 0.3 ? 'var(--color-up)' : val <= -0.3 ? 'var(--color-down)' : '#eab308';
    return `
      <div style="position:relative;width:100%;height:8px;background:var(--border);border-radius:4px;overflow:hidden">
        <div style="position:absolute;left:0;top:0;height:100%;width:${pct}%;background:${col};border-radius:4px;transition:width .6s ease"></div>
      </div>`;
  }

  function priceTag(label, value, color, borderColor) {
    if (value == null) return '';
    return `
      <div style="display:flex;justify-content:space-between;align-items:center;padding:8px 12px;
        background:var(--surface);border-radius:var(--radius);border-left:3px solid ${borderColor || color}">
        <span style="font-size:13px;color:var(--text-muted)">${label}</span>
        <span style="font-size:16px;font-weight:700;font-family:var(--font-mono);color:${color}">¥${Number(value).toFixed(2)}</span>
      </div>`;
  }

  function keyLevelsLadder(levels) {
    if (!levels || !levels.length) return '';
    const sorted = [...levels].sort((a, b) => b[0] - a[0]);
    return sorted.map(([price, label]) => {
      const isTarget = label.includes('目标');
      const isResist = label.includes('压力') || label.includes('阻力');
      const col = isTarget ? 'var(--color-up)' : isResist ? 'var(--color-warning)' : 'var(--text-secondary)';
      return `
        <div style="display:flex;align-items:center;gap:10px;padding:5px 0">
          <div style="flex:1;height:1px;background:${col}30"></div>
          <span style="font-size:12px;color:var(--text-muted);white-space:nowrap">${label}</span>
          <span style="font-size:14px;font-weight:600;font-family:var(--font-mono);color:${col};min-width:60px;text-align:right">¥${Number(price).toFixed(2)}</span>
        </div>`;
    }).join('');
  }

  const changePct = latest.change_pct || 0;
  const isUp = changePct >= 0;
  const priceColor = isUp ? 'var(--color-up)' : 'var(--color-down)';
  const totalScore = scores.total || 0;

  function rsiColor(v) {
    if (v > 70) return 'var(--color-down)';
    if (v < 30) return 'var(--color-up)';
    return '#eab308';
  }

  function macdColor(v) {
    if (v === '金叉') return 'var(--color-up)';
    if (v === '死叉') return 'var(--color-down)';
    return 'var(--text-secondary)';
  }

  return `
    <style>
      .ss-section { margin-bottom: 20px; }
      .ss-section-title {
        font-size: 13px; font-weight: 600; color: var(--text-muted);
        text-transform: uppercase; letter-spacing: 1px; margin-bottom: 10px;
        padding-bottom: 6px; border-bottom: 1px solid var(--border);
      }
      .ss-gauge-wrap {
        position: relative; display: flex; align-items: center; justify-content: center;
      }
      .ss-gauge-score {
        position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%);
        text-align: center;
      }
      .ss-gauge-score .num { font-size: 32px; font-weight: 800; font-family: var(--font-mono); line-height: 1; }
      .ss-gauge-score .label { font-size: 12px; color: var(--text-muted); margin-top: 2px; }
      .ss-kv { display: flex; flex-direction: column; align-items: center; gap: 2px;
        padding: 10px 8px; background: var(--surface); border-radius: var(--radius); }
      .ss-kv .k { font-size: 11px; color: var(--text-muted); }
      .ss-kv .v { font-size: 15px; font-weight: 600; font-family: var(--font-mono); }
      .ss-risk-tag { display: inline-flex; align-items: center; gap: 4px; padding: 4px 10px;
        border-radius: 4px; font-size: 12px; font-weight: 600; }
    </style>

    <!-- Section 1: Header -->
    <div class="ss-section" style="display:flex;justify-content:space-between;align-items:center;
      padding:16px 20px;background:var(--surface);border-radius:var(--radius);
      border:1px solid var(--border)">
      <div style="display:flex;align-items:center;gap:12px">
        <div>
          <div style="font-size:22px;font-weight:800;letter-spacing:-0.5px">${data.name || latest.name || ''}</div>
          <div style="font-size:12px;color:var(--text-muted);font-family:var(--font-mono);margin-top:2px">${data.ts_code}</div>
        </div>
        ${data.industry ? `<span class="tag tag-blue" style="font-size:12px">${escapeHtml(data.industry)}</span>` : ''}
        ${data.data_date ? `<span class="tag tag-gray" style="font-size:11px">数据 ${data.data_date.replace(/^(\d{4})(\d{2})(\d{2})$/, '$1-$2-$3')}</span>` : ''}
        ${rt ? `<span class="tag tag-gray" style="font-size:11px">实时</span>` : ''}
      </div>
      <div style="text-align:right">
        <div style="font-size:28px;font-weight:800;font-family:var(--font-mono);color:${priceColor};letter-spacing:-0.5px">
          ¥${(rt ? rt.price : latest.close || 0).toFixed(2)}
        </div>
        <div style="font-size:14px;font-weight:600;color:${priceColor};margin-top:2px">
          ${isUp ? '▲' : '▼'} ${Math.abs(changePct).toFixed(2)}%
          ${rt && rt.change_pct !== changePct ? `<span style="font-size:11px;opacity:0.7;margin-left:6px">盘中 ${rt.change_pct >= 0 ? '+' : ''}${rt.change_pct.toFixed(2)}%</span>` : ''}
        </div>
      </div>
    </div>

    <!-- Realtime stats row -->
    ${rt ? `
    <div class="ss-section" style="display:grid;grid-template-columns:repeat(5,1fr);gap:8px">
      <div class="ss-kv"><span class="k">总市值</span><span class="v">${(rt.market_cap || 0).toFixed(0)}亿</span></div>
      <div class="ss-kv"><span class="k">PE(TTM)</span><span class="v">${rt.pe != null ? rt.pe.toFixed(1) : '—'}</span></div>
      <div class="ss-kv"><span class="k">PB</span><span class="v">${rt.pb != null ? rt.pb.toFixed(2) : '—'}</span></div>
      <div class="ss-kv"><span class="k">换手率</span><span class="v">${(rt.turnover_rate || 0).toFixed(2)}%</span></div>
      <div class="ss-kv"><span class="k">成交量</span><span class="v">${fmtScreenVol(rt.volume || latest.vol || 0)}</span></div>
    </div>` : `
    <div class="ss-section" style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px">
      <div class="ss-kv"><span class="k">开盘</span><span class="v">¥${(latest.open || 0).toFixed(2)}</span></div>
      <div class="ss-kv"><span class="k">最高</span><span class="v" style="color:var(--color-up)">¥${(latest.high || 0).toFixed(2)}</span></div>
      <div class="ss-kv"><span class="k">最低</span><span class="v" style="color:var(--color-down)">¥${(latest.low || 0).toFixed(2)}</span></div>
      <div class="ss-kv"><span class="k">成交额</span><span class="v">${fmtScreenAmt(latest.amount || 0)}</span></div>
    </div>`}

    <!-- Section 2: Composite Score Dashboard -->
    <div class="ss-section" style="padding:20px;background:var(--surface);border-radius:var(--radius);border:1px solid var(--border)">
      <div class="ss-section-title">综合评分</div>
      <div style="display:flex;gap:24px;align-items:center">
        <!-- Gauge -->
        <div style="flex-shrink:0">
          <div class="ss-gauge-wrap" style="width:130px;height:130px;margin:0 auto">
            ${gaugeRing(totalScore, 130)}
            <div class="ss-gauge-score">
              <div class="num" style="color:${scoreColor(totalScore)}">${Math.round(totalScore)}</div>
              <div class="label">${scores.advice || ''}</div>
            </div>
          </div>
          <div style="text-align:center;margin-top:8px;font-size:14px;font-weight:700;color:${scoreColor(totalScore)}">
            ${scores.advice || ''} ${scores.icon || ''}
          </div>
        </div>
        <!-- Dimension bars -->
        <div style="flex:1;display:grid;grid-template-columns:1fr 1fr;gap:14px 20px;min-width:0">
          ${dimBar('技术面', scores.tech, 30)}
          ${dimBar('基本面', scores.base, 25)}
          ${dimBar('消息面', scores.news, 20)}
          ${dimBar('资金面', scores.fund, 15)}
        </div>
      </div>
    </div>

    <!-- Section 3: Key Indicators Grid -->
    <div class="ss-section">
      <div class="ss-section-title">核心指标</div>
      <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px">
        <div class="ss-kv">
          <span class="k">RSI(14)</span>
          <span class="v" style="color:${rsiColor(scores.rsi || 0)}">${(scores.rsi || 0).toFixed(1)}</span>
        </div>
        <div class="ss-kv">
          <span class="k">量比</span>
          <span class="v">${(scores.vol_ratio || 0).toFixed(2)}</span>
        </div>
        <div class="ss-kv">
          <span class="k">MACD</span>
          <span class="v" style="color:${macdColor(scores.macd || '')}">${scores.macd || '—'}</span>
        </div>
        <div class="ss-kv">
          <span class="k">MA状态</span>
          <span class="v" style="color:${(scores.ma_status || '').includes('多') ? 'var(--color-up)' : 'var(--text-secondary)'}">${scores.ma_status || '—'}</span>
        </div>
        <div class="ss-kv">
          <span class="k">趋势强度</span>
          <span class="v" style="color:${(data.trend_strength || 0) >= 60 ? 'var(--color-up)' : 'var(--text-secondary)'}">${Math.round(data.trend_strength || 0)}/100</span>
        </div>
        <div class="ss-kv">
          <span class="k">量能评分</span>
          <span class="v" style="color:${(data.volume_score || 0) >= 60 ? 'var(--color-up)' : 'var(--text-secondary)'}">${Math.round(data.volume_score || 0)}/100</span>
        </div>
        <div class="ss-kv">
          <span class="k">MA60偏离</span>
          <span class="v" style="color:${Math.abs(scores.ma60_dev || 0) > 8 ? 'var(--color-warning)' : 'var(--text-secondary)'}">${(scores.ma60_dev || 0).toFixed(1)}%</span>
        </div>
        <div class="ss-kv">
          <span class="k">当日涨跌</span>
          <span class="v" style="color:${priceColor}">${isUp ? '+' : ''}${changePct.toFixed(2)}%</span>
        </div>
      </div>
    </div>

    <!-- Section 4: Risk Assessment -->
    <div class="ss-section">
      <details ${risk.pass === false ? 'open' : ''} style="background:var(--surface);border-radius:var(--radius);border:1px solid var(--border);overflow:hidden">
        <summary style="cursor:pointer;padding:12px 16px;font-weight:600;font-size:14px;display:flex;align-items:center;gap:8px">
          <span class="ss-risk-tag" style="background:${risk.pass ? 'rgba(34,197,94,0.15)' : 'rgba(239,68,68,0.15)'};color:${risk.pass ? '#22c55e' : '#ef4444'}">
            ${risk.pass ? '✓ 风险通过' : '⚠ 风险警示'}
          </span>
          <span style="color:var(--text-muted);font-size:12px">MA20偏离 ${(risk.ma20_deviation || 0).toFixed(1)}% · ATR比率 ${(risk.atr_ratio || 0).toFixed(1)}%</span>
        </summary>
        <div style="padding:0 16px 12px">
          ${(risk.warnings && risk.warnings.length > 0) ? `
            <div style="margin-bottom:8px">${risk.warnings.map(w => `<span class="tag tag-yellow" style="font-size:12px;margin:2px">${escapeHtml(w)}</span>`).join('')}</div>
          ` : ''}
          ${(risk.flags && risk.flags.length > 0) ? `
            <div style="margin-top:8px">
              ${risk.flags.map(f => `
                <div style="display:flex;align-items:center;gap:8px;padding:6px 0;font-size:13px;border-bottom:1px solid var(--border)">
                  <span class="tag ${(f.level || '').includes('高') || (f.level || '').includes('danger') ? 'tag-red' : (f.level || '').includes('中') ? 'tag-yellow' : 'tag-gray'}" style="font-size:11px">${f.dimension || '—'}</span>
                  <span style="color:var(--text-secondary)">${escapeHtml(f.detail || f.reason || '')}</span>
                </div>
              `).join('')}
            </div>
          ` : `<div style="font-size:13px;color:var(--text-muted)">未检测到异常风险信号</div>`}
        </div>
      </details>
    </div>

    <!-- Section 5: Entry Points -->
    <div class="ss-section">
      <div class="ss-section-title">关键价位</div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px">
        ${(entry.buy_zone && entry.buy_zone.length === 2) ? priceTag('买入区间', ((entry.buy_zone[0] + entry.buy_zone[1]) / 2), 'var(--color-up)', 'var(--color-up)') + `<div style="font-size:11px;color:var(--text-muted);grid-column:1/-1;margin-top:-4px;padding-left:12px">区间 ¥${Number(entry.buy_zone[0]).toFixed(2)} ~ ¥${Number(entry.buy_zone[1]).toFixed(2)}</div>` : ''}
        ${priceTag('止损位', entry.stop_loss, 'var(--color-down)', 'var(--color-down)')}
        ${priceTag('目标①', entry.target_1, 'var(--color-up)', 'var(--color-up)')}
        ${priceTag('目标②', entry.target_2, 'var(--color-up)', 'rgba(34,197,94,0.4)')}
        ${priceTag('阻力位', entry.resistance, 'var(--color-warning)', 'var(--color-warning)')}
        ${priceTag('失效价', entry.invalid_price, 'var(--text-muted)', 'var(--border)')}
      </div>
      ${(entry.key_levels && entry.key_levels.length > 0) ? `
        <div style="margin-top:12px;padding:10px 14px;background:var(--surface);border-radius:var(--radius)">
          <div style="font-size:12px;color:var(--text-muted);margin-bottom:6px">价格阶梯</div>
          ${keyLevelsLadder(entry.key_levels)}
        </div>
      ` : ''}
    </div>

    <!-- Section 6: MA Values -->
    ${Object.keys(ma).length > 0 ? `
    <div class="ss-section">
      <div class="ss-section-title">均线系统</div>
      <div style="display:flex;flex-wrap:wrap;gap:8px">
        ${Object.entries(ma).map(([key, value]) => {
          const maNum = key.replace('ma', '');
          const isAbove = latest.close && value < latest.close;
          return `<span class="tag ${isAbove ? 'tag-red' : 'tag-green'}" style="font-size:13px;font-family:var(--font-mono)">MA${maNum}: ${value.toFixed(2)}</span>`;
        }).join('')}
      </div>
    </div>` : ''}

    <!-- Section 7: News Sentiment -->
    ${news ? `
    <div class="ss-section">
      <details style="background:var(--surface);border-radius:var(--radius);border:1px solid var(--border);overflow:hidden">
        <summary style="cursor:pointer;padding:12px 16px;font-weight:600;font-size:14px;display:flex;align-items:center;gap:8px">
          消息面情绪
          <span style="font-size:14px;font-weight:700;font-family:var(--font-mono);color:${news.score >= 0.3 ? 'var(--color-up)' : news.score <= -0.3 ? 'var(--color-down)' : '#eab308'}">
            ${(news.score >= 0 ? '+' : '')}${news.score.toFixed(2)}
          </span>
          <span style="font-size:12px;color:var(--text-muted)">${news.stock_mentions || 0}次提及</span>
        </summary>
        <div style="padding:0 16px 12px">
          ${sentimentGauge(news.score)}
          <div style="margin-top:8px;display:flex;flex-wrap:wrap;gap:6px">
            ${(news.hot_topics || []).map(t => `<span class="tag tag-blue" style="font-size:12px">${escapeHtml(t)}</span>`).join('')}
          </div>
        </div>
      </details>
    </div>` : ''}

    <!-- Section 8: Footer -->
    <div class="modal-actions" style="margin-top:20px;display:flex;gap:10px;justify-content:flex-end">
      <button class="btn btn-primary" onclick="quickAddWatchlistByCode('${escapeHtml(data.ts_code)}', '${escapeHtml(data.name || latest.name || '')}')">
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

/**
 * 更新当天数据：同步股票列表 + 当日日线行情
 */
async function syncTodayData() {
  const btn = document.getElementById('syncDataBtn');
  const status = document.getElementById('syncDataStatus');
  if (!btn || !status) return;

  btn.disabled = true;
  btn.textContent = '⏳ 同步中...';
  status.style.display = 'block';
  status.style.color = 'var(--text-muted)';
  status.textContent = '正在同步股票列表和当日行情数据，请稍候...';

  try {
    // 第一步：同步股票列表（名称、行业等）
    status.textContent = '① 同步股票列表（名称/行业）...';
    const stockResult = await API.syncStockList();
    const stockCount = stockResult?.count ?? stockResult?.synced ?? '—';

    // 第二步：同步当日日线数据
    const today = new Date();
    const todayStr = today.getFullYear() +
      String(today.getMonth() + 1).padStart(2, '0') +
      String(today.getDate()).padStart(2, '0');

    // 同步最近5天数据以确保覆盖
    const fiveDaysAgo = new Date(today);
    fiveDaysAgo.setDate(fiveDaysAgo.getDate() - 7);
    const startDate = fiveDaysAgo.getFullYear() +
      String(fiveDaysAgo.getMonth() + 1).padStart(2, '0') +
      String(fiveDaysAgo.getDate()).padStart(2, '0');

    status.textContent = '② 同步近5天日线行情数据...（可能需要1-2分钟）';
    const dailyResult = await API.syncAllDaily(startDate, todayStr, 100);
    const dailyCount = dailyResult?.saved ?? dailyResult?.synced ?? '—';

    status.style.color = '#22c55e';
    const stockMsg = stockCount > 0 ? `新增 ${stockCount} 只` : '已是最新';
    const dailyMsg = dailyCount > 0 ? `新增 ${dailyCount} 条` : '已是最新';
    status.textContent = `✅ 数据同步完成 — 股票列表: ${stockMsg} | 日线行情: ${dailyMsg}`;
  } catch (e) {
    console.error('syncTodayData error:', e);
    status.style.color = '#ef4444';
    status.textContent = `❌ 同步失败: ${e.message || '未知错误'}，可前往数据中心手动同步`;
  } finally {
    btn.disabled = false;
    btn.textContent = '🔄 更新当天数据';
  }
}
