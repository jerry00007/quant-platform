/**
 * QuantWeave 数据中心页面
 * 功能：股票/ETF同步管理、数据浏览、实时行情查询
 */

let dcState = {
  stockPage: 1,
  stockKeyword: '',
  stockTotal: 0,
  etfPage: 1,
  etfKeyword: '',
  etfTotal: 0,
  stockCount: 0,
  etfCount: 0,
  stockSyncTime: null,
  etfSyncTime: null,
};

const PAGE_SIZE = 15;

async function renderDataCenter() {
  const main = document.getElementById('mainContent');
  main.innerHTML = `
    <div class="page-header">
      <h2>🗄️ 数据中心</h2>
      <p>管理市场数据同步与缓存</p>
    </div>
    <div id="dcContent"><div class="loading"><div class="spinner"></div>加载中...</div></div>
  `;

  await loadSyncPanel();
}

async function loadSyncPanel() {
  const container = document.getElementById('dcContent');
  if (!container) return;

  container.innerHTML = `
    <!-- Section 1: Sync Control Panel -->
    <div class="grid-3" id="dcSyncPanel">
      <div class="card">
        <div class="card-title">📊 股票列表同步</div>
        <div id="dcStockSyncInfo" class="loading"><div class="spinner"></div>加载中...</div>
        <div style="margin-top:12px">
          <button id="dcSyncStockBtn" class="btn btn-primary btn-sm" onclick="syncStockList()">🔄 立即同步</button>
        </div>
      </div>
      <div class="card">
        <div class="card-title">📈 ETF列表同步</div>
        <div id="dcEtfSyncInfo" class="loading"><div class="spinner"></div>加载中...</div>
        <div style="margin-top:12px">
          <button id="dcSyncEtfBtn" class="btn btn-primary btn-sm" onclick="syncETFList()">🔄 立即同步</button>
        </div>
      </div>
      <div class="card">
        <div class="card-title">📋 数据概览</div>
        <div id="dcOverviewInfo" class="loading"><div class="spinner"></div>加载中...</div>
      </div>
    </div>

    <!-- Section 2: Stock List Browser -->
    <div class="card" style="margin-top:20px">
      <div class="card-title">📊 股票列表</div>
      <div class="form-group" style="margin-bottom:12px">
        <input type="text" id="dcStockSearch" class="form-input" placeholder="搜索股票代码或名称..." value="${dcState.stockKeyword}">
      </div>
      <div id="dcStockTable"><div class="loading"><div class="spinner"></div>加载中...</div></div>
    </div>

    <!-- Section 3: ETF List Browser -->
    <div class="card" style="margin-top:20px">
      <div class="card-title">📈 ETF列表</div>
      <div class="form-group" style="margin-bottom:12px">
        <input type="text" id="dcEtfSearch" class="form-input" placeholder="搜索ETF代码或名称..." value="${dcState.etfKeyword}">
      </div>
      <div id="dcEtfTable"><div class="loading"><div class="spinner"></div>加载中...</div></div>
    </div>

    <!-- Section 4: Quick Quote Lookup -->
    <div class="card" style="margin-top:20px">
      <div class="card-title">⚡ 实时行情查询</div>
      <div class="grid-2">
        <div class="form-group">
          <label class="form-label">股票代码（逗号分隔，如 000001.SZ,600519.SH）</label>
          <input type="text" id="dcQuoteCodes" class="form-input" placeholder="输入代码...">
        </div>
        <div class="form-group">
          <label class="form-label">&nbsp;</label>
          <button class="btn btn-primary" onclick="lookupQuotes()">🔍 查询行情</button>
        </div>
      </div>
      <div id="dcQuoteResult"></div>
    </div>

    <!-- Section 5: Historical Data Sync -->
    <div class="card" style="margin-top:20px">
      <div class="card-title">📥 历史数据同步（用于回测/选股）</div>
      <div class="grid-3" style="margin-bottom:16px">
        <div class="form-group" style="margin-bottom:0">
          <label class="form-label">开始日期</label>
          <input type="date" id="dcHistStartDate" class="form-input" value="2025-04-01">
        </div>
        <div class="form-group" style="margin-bottom:0">
          <label class="form-label">结束日期</label>
          <input type="date" id="dcHistEndDate" class="form-input" value="2026-04-01">
        </div>
        <div class="form-group" style="margin-bottom:0">
          <label class="form-label">股票范围</label>
          <select id="dcHistScope" class="form-select">
            <option value="selected">手动选择</option>
            <option value="all">全部股票 (限50只)</option>
          </select>
        </div>
      </div>
      <div id="dcHistStockSelect" style="margin-bottom:16px">
        <textarea id="dcHistCodes" class="form-input" rows="2" placeholder="输入股票代码，逗号或换行分隔，如: 000001.SZ,600519.SH,000002.SZ"></textarea>
      </div>
      <div style="display:flex;gap:12px;align-items:center">
        <button class="btn btn-primary" onclick="syncHistoricalData()">📥 开始同步历史数据</button>
        <span id="dcHistStatus" style="color:#94A3B8;font-size:13px"></span>
      </div>
      <div id="dcHistResult"></div>
    </div>
  `;

  // Debounced search
  setupSearchHandlers();

  // Parallel data load
  await Promise.all([
    loadStockSyncInfo(),
    loadEtfSyncInfo(),
    loadOverviewInfo(),
    loadStockTable(),
    loadEtfTable(),
  ]);
}

function setupSearchHandlers() {
  let stockTimer = null;
  let etfTimer = null;

  const stockInput = document.getElementById('dcStockSearch');
  if (stockInput) {
    stockInput.addEventListener('input', () => {
      clearTimeout(stockTimer);
      stockTimer = setTimeout(() => {
        dcState.stockKeyword = stockInput.value.trim();
        dcState.stockPage = 1;
        loadStockTable();
      }, 400);
    });
  }

  const etfInput = document.getElementById('dcEtfSearch');
  if (etfInput) {
    etfInput.addEventListener('input', () => {
      clearTimeout(etfTimer);
      etfTimer = setTimeout(() => {
        dcState.etfKeyword = etfInput.value.trim();
        dcState.etfPage = 1;
        loadEtfTable();
      }, 400);
    });
  }
}

// ===== Section 1: Sync Panel =====

async function loadStockSyncInfo() {
  const el = document.getElementById('dcStockSyncInfo');
  if (!el) return;

  try {
    const data = await API.getStocks(null, 1, 1);
    if (!data) throw new Error('无法获取股票数据');
    dcState.stockCount = data.total || 0;
    el.innerHTML = `
      <div style="margin-bottom:8px">
        <span class="stat-value">${formatNumber(dcState.stockCount)}</span>
        <span style="color:var(--text-secondary);margin-left:4px">只股票</span>
      </div>
      <span class="tag ${dcState.stockCount > 0 ? 'tag-green' : 'tag-gray'}">
        ${dcState.stockCount > 0 ? '✓ 已同步' : '未同步'}
      </span>
    `;
  } catch (err) {
    el.innerHTML = `<span class="tag tag-red">加载失败</span>`;
  }
}

async function loadEtfSyncInfo() {
  const el = document.getElementById('dcEtfSyncInfo');
  if (!el) return;

  try {
    const data = await API.getETFList(null, 1, 1);
    if (!data) throw new Error('无法获取ETF数据');
    dcState.etfCount = data.total || 0;
    el.innerHTML = `
      <div style="margin-bottom:8px">
        <span class="stat-value">${formatNumber(dcState.etfCount)}</span>
        <span style="color:var(--text-secondary);margin-left:4px">只ETF</span>
      </div>
      <span class="tag ${dcState.etfCount > 0 ? 'tag-green' : 'tag-gray'}">
        ${dcState.etfCount > 0 ? '✓ 已同步' : '未同步'}
      </span>
    `;
  } catch (err) {
    el.innerHTML = `<span class="tag tag-red">加载失败</span>`;
  }
}

async function loadOverviewInfo() {
  const el = document.getElementById('dcOverviewInfo');
  if (!el) return;

  try {
    const status = await API.getDataStatus();
    const latestDate = status.latest_date ? formatDate(status.latest_date) : '暂无数据';
    const stockCount = status.stock_count || 0;
    const dailyRecords = status.daily_records || 0;

    el.innerHTML = `
      <div style="margin-bottom:8px">
        <span class="tag ${dailyRecords > 0 ? 'tag-green' : 'tag-gray'}">
          ${dailyRecords > 0 ? '● 数据已更新' : '● 无行情数据'}
        </span>
      </div>
      <div style="font-size:13px;color:#94A3B8">
        <div style="margin-bottom:4px">📊 最新日期: <strong style="color:#F8FAFC">${latestDate}</strong></div>
        <div>📈 股票: ${formatNumber(stockCount)} 只</div>
        <div>📋 日线记录: ${formatNumber(dailyRecords)} 条</div>
      </div>
    `;
  } catch (err) {
    el.innerHTML = `<span class="tag tag-red">加载失败</span>`;
  }
}

function formatDate(dateStr) {
  if (!dateStr) return '';
  if (dateStr.length === 8) {
    return `${dateStr.slice(0,4)}-${dateStr.slice(4,6)}-${dateStr.slice(6,8)}`;
  }
  return dateStr;
}

async function syncStockList() {
  const btn = document.getElementById('dcSyncStockBtn');
  if (btn) {
    btn.disabled = true;
    btn.textContent = '⏳ 同步中...';
  }

  try {
    const result = await API.syncStockList();
    if (result) {
      showToast(result.message || `同步完成，新增 ${result.count || 0} 只`, 'success');
    } else {
      showToast('同步请求已发送', 'info');
    }
    await loadStockSyncInfo();
    await loadOverviewInfo();
    await loadStockTable();
  } catch (err) {
    showToast('股票同步失败: ' + (err.message || '未知错误'), 'error');
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = '🔄 立即同步';
    }
  }
}

async function syncETFList() {
  const btn = document.getElementById('dcSyncEtfBtn');
  if (btn) {
    btn.disabled = true;
    btn.textContent = '⏳ 同步中...';
  }

  try {
    const result = await API.syncETFList();
    if (result) {
      showToast(result.message || `ETF同步完成，新增 ${result.count || 0} 只`, 'success');
    } else {
      showToast('同步请求已发送', 'info');
    }
    await loadEtfSyncInfo();
    await loadOverviewInfo();
    await loadEtfTable();
  } catch (err) {
    showToast('ETF同步失败: ' + (err.message || '未知错误'), 'error');
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = '🔄 立即同步';
    }
  }
}

// ===== Section 2: Stock List Browser =====

async function loadStockTable() {
  const container = document.getElementById('dcStockTable');
  if (!container) return;

  container.innerHTML = '<div class="loading"><div class="spinner"></div>加载中...</div>';

  try {
    const data = await API.getStocks(dcState.stockKeyword || null, dcState.stockPage, PAGE_SIZE);
    if (!data) throw new Error('无法获取股票列表');

    dcState.stockTotal = data.total || 0;
    const items = data.items || [];
    const totalPages = Math.ceil(dcState.stockTotal / PAGE_SIZE);

    if (items.length === 0) {
      container.innerHTML = '<div style="text-align:center;padding:24px;color:var(--text-secondary)">暂无股票数据，请先同步</div>';
      return;
    }

    container.innerHTML = `
      <div style="font-size:13px;color:var(--text-secondary);margin-bottom:8px">
        共 ${formatNumber(dcState.stockTotal)} 只 | 第 ${dcState.stockPage}/${totalPages} 页
      </div>
      <table class="data-table">
        <thead>
          <tr>
            <th>代码</th>
            <th>名称</th>
            <th>行业</th>
            <th>市场</th>
          </tr>
        </thead>
        <tbody>
          ${items.map(s => `
            <tr>
              <td><code>${s.ts_code || ''}</code></td>
              <td><strong>${s.name || '—'}</strong></td>
              <td><span class="tag tag-blue">${s.industry || '—'}</span></td>
              <td>${getMarketLabel(s.market || s.ts_code)}</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
      <div style="display:flex;justify-content:space-between;align-items:center;margin-top:12px">
        <button class="btn btn-sm btn-outline" ${dcState.stockPage <= 1 ? 'disabled' : ''} onclick="dcStockPrev()">上一页</button>
        <span style="font-size:13px;color:var(--text-secondary)">${dcState.stockPage} / ${totalPages}</span>
        <button class="btn btn-sm btn-outline" ${dcState.stockPage >= totalPages ? 'disabled' : ''} onclick="dcStockNext()">下一页</button>
      </div>
    `;
  } catch (err) {
    container.innerHTML = `<div style="text-align:center;padding:24px;color:var(--text-secondary)">加载失败: ${err.message}</div>`;
  }
}

function dcStockPrev() {
  if (dcState.stockPage > 1) {
    dcState.stockPage--;
    loadStockTable();
  }
}

function dcStockNext() {
  const totalPages = Math.ceil(dcState.stockTotal / PAGE_SIZE);
  if (dcState.stockPage < totalPages) {
    dcState.stockPage++;
    loadStockTable();
  }
}

// ===== Section 3: ETF List Browser =====

async function loadEtfTable() {
  const container = document.getElementById('dcEtfTable');
  if (!container) return;

  container.innerHTML = '<div class="loading"><div class="spinner"></div>加载中...</div>';

  try {
    const data = await API.getETFList(dcState.etfKeyword || null, dcState.etfPage, PAGE_SIZE);
    if (!data) throw new Error('无法获取ETF列表');

    dcState.etfTotal = data.total || 0;
    const items = data.items || [];
    const totalPages = Math.ceil(dcState.etfTotal / PAGE_SIZE);

    if (items.length === 0) {
      container.innerHTML = '<div style="text-align:center;padding:24px;color:var(--text-secondary)">暂无ETF数据，请先同步</div>';
      return;
    }

    container.innerHTML = `
      <div style="font-size:13px;color:var(--text-secondary);margin-bottom:8px">
        共 ${formatNumber(dcState.etfTotal)} 只 | 第 ${dcState.etfPage}/${totalPages} 页
      </div>
      <table class="data-table">
        <thead>
          <tr>
            <th>代码</th>
            <th>名称</th>
            <th>基金类型</th>
            <th>管理费率</th>
          </tr>
        </thead>
        <tbody>
          ${items.map(e => `
            <tr>
              <td><code>${e.ts_code || ''}</code></td>
              <td><strong>${e.name || '—'}</strong></td>
              <td><span class="tag tag-yellow">${e.fund_type || '—'}</span></td>
              <td>${e.management_fee ? (e.management_fee * 100).toFixed(2) + '%' : '—'}</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
      <div style="display:flex;justify-content:space-between;align-items:center;margin-top:12px">
        <button class="btn btn-sm btn-outline" ${dcState.etfPage <= 1 ? 'disabled' : ''} onclick="dcEtfPrev()">上一页</button>
        <span style="font-size:13px;color:var(--text-secondary)">${dcState.etfPage} / ${totalPages}</span>
        <button class="btn btn-sm btn-outline" ${dcState.etfPage >= totalPages ? 'disabled' : ''} onclick="dcEtfNext()">下一页</button>
      </div>
    `;
  } catch (err) {
    container.innerHTML = `<div style="text-align:center;padding:24px;color:var(--text-secondary)">加载失败: ${err.message}</div>`;
  }
}

function dcEtfPrev() {
  if (dcState.etfPage > 1) {
    dcState.etfPage--;
    loadEtfTable();
  }
}

function dcEtfNext() {
  const totalPages = Math.ceil(dcState.etfTotal / PAGE_SIZE);
  if (dcState.etfPage < totalPages) {
    dcState.etfPage++;
    loadEtfTable();
  }
}

// ===== Section 4: Quick Quote Lookup =====

async function lookupQuotes() {
  const input = document.getElementById('dcQuoteCodes');
  const resultEl = document.getElementById('dcQuoteResult');
  if (!input || !resultEl) return;

  const raw = input.value.trim();
  if (!raw) {
    showToast('请输入股票代码', 'error');
    return;
  }

  const codes = raw.split(/[,，\s]+/).filter(c => c.length > 0);
  if (codes.length === 0) {
    showToast('请输入有效的股票代码', 'error');
    return;
  }

  if (codes.length > 20) {
    showToast('单次最多查询20只', 'error');
    return;
  }

  resultEl.innerHTML = '<div class="loading"><div class="spinner"></div>查询中...</div>';

  try {
    const data = await API.getRealtime(codes.join(','));
    if (!data) throw new Error('无法获取行情数据');

    const items = data.items || [];
    if (items.length === 0) {
      resultEl.innerHTML = '<div style="text-align:center;padding:16px;color:var(--text-secondary)">未查询到数据，请检查代码格式</div>';
      return;
    }

    resultEl.innerHTML = `
      <table class="data-table">
        <thead>
          <tr>
            <th>代码</th>
            <th>名称</th>
            <th>最新价</th>
            <th>涨跌幅</th>
            <th>成交量</th>
            <th>成交额</th>
            <th>最高</th>
            <th>最低</th>
            <th>今开</th>
          </tr>
        </thead>
        <tbody>
          ${items.map(q => {
            const chg = q.change_pct || 0;
            const cls = chg >= 0 ? 'positive' : 'negative';
            const arrow = chg >= 0 ? '▲' : '▼';
            return `
              <tr>
                <td><code>${q.ts_code || ''}</code></td>
                <td><strong>${q.name || '—'}</strong></td>
                <td class="${cls}">${(q.price || 0).toFixed(2)}</td>
                <td class="${cls}">${arrow} ${Math.abs(chg).toFixed(2)}%</td>
                <td>${formatNumber(q.vol || 0)}</td>
                <td>${formatNumber(q.amount || 0)}</td>
                <td>${(q.high || 0).toFixed(2)}</td>
                <td>${(q.low || 0).toFixed(2)}</td>
                <td>${(q.open || 0).toFixed(2)}</td>
              </tr>
            `;
          }).join('')}
        </tbody>
      </table>
    `;
  } catch (err) {
    resultEl.innerHTML = `<div style="text-align:center;padding:16px;color:var(--text-secondary)">查询失败: ${err.message}</div>`;
  }
}

// ===== Utilities =====

function getMarketLabel(code) {
  if (!code) return '—';
  if (code.endsWith('.SH')) return '<span class="tag tag-green">沪市</span>';
  if (code.endsWith('.SZ')) return '<span class="tag tag-blue">深市</span>';
  if (code.endsWith('.BJ')) return '<span class="tag tag-yellow">北交所</span>';
  return '<span class="tag tag-gray">其他</span>';
}

async function syncHistoricalData() {
  const startDate = document.getElementById('dcHistStartDate').value.replace(/-/g, '');
  const endDate = document.getElementById('dcHistEndDate').value.replace(/-/g, '');
  const scope = document.getElementById('dcHistScope').value;
  const statusEl = document.getElementById('dcHistStatus');
  const resultEl = document.getElementById('dcHistResult');

  if (!startDate || !endDate) {
    showToast('请选择开始和结束日期', 'error');
    return;
  }

  let tsCodes = [];
  if (scope === 'selected') {
    const codesText = document.getElementById('dcHistCodes').value;
    tsCodes = codesText.split(/[,，\n]/).map(c => c.trim()).filter(c => c);
  }

  if (tsCodes.length === 0 && scope === 'selected') {
    showToast('请输入股票代码', 'error');
    return;
  }

  statusEl.textContent = '同步中...';
  resultEl.innerHTML = '<div class="loading"><div class="spinner"></div>正在同步历史数据...</div>';

  try {
    let result;
    if (scope === 'all') {
      result = await API.syncAllDaily(startDate, endDate, 50);
    } else {
      result = await API.batchSyncDaily(tsCodes, startDate, endDate);
    }

    statusEl.textContent = '';
    
    if (result.saved > 0) {
      resultEl.innerHTML = `
        <div style="margin-top:12px;padding:12px;background:rgba(34,197,94,0.1);border-radius:8px;border:1px solid rgba(34,197,94,0.3)">
          <div style="color:#22C55E;font-weight:600">✅ 同步完成</div>
          <div style="color:#94A3B8;font-size:13px;margin-top:4px">
            成功保存 ${result.saved} 条数据
            ${result.results ? `（成功 ${result.results.filter(r => r.status === 'success').length} 只）` : ''}
          </div>
        </div>
      `;
      showToast(`成功同步 ${result.saved} 条数据`, 'success');
    } else {
      resultEl.innerHTML = `
        <div style="margin-top:12px;padding:12px;background:rgba(245,158,11,0.1);border-radius:8px;border:1px solid rgba(245,158,11,0.3)">
          <div style="color:#F59E0B;font-weight:600">⚠️ 同步完成但无数据</div>
          <div style="color:#94A3B8;font-size:13px;margin-top:4px">请检查股票代码是否正确，或日期范围是否有交易数据</div>
        </div>
      `;
      showToast('同步完成但无数据', 'info');
    }
  } catch (err) {
    statusEl.textContent = '';
    resultEl.innerHTML = `<div style="margin-top:12px;color:#EF4444">同步失败: ${err.message}</div>`;
    showToast('同步失败: ' + err.message, 'error');
  }
}
