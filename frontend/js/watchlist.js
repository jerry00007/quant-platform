/**
 * QuantWeave 关注列表页面
 * 管理自选股与ETF关注列表
 */

async function renderWatchlist() {
  const main = document.getElementById('mainContent');
  main.innerHTML = `
    <div class="page-header">
      <h2>⭐ 关注列表</h2>
      <p>管理自选股与ETF关注列表</p>
    </div>
    <div id="wlContent"><div class="loading"><div class="spinner"></div>加载中...</div></div>
  `;

  const container = document.getElementById('wlContent');
  const data = await API.getWatchlist();

  if (!data || !data.items) {
    container.innerHTML = '<div class="card"><p>无法加载关注列表数据，请检查后端服务。</p></div>';
    return;
  }

  const groups = buildGroups(data.items);
  renderWatchlistPage(container, data.items, groups);
}

function buildGroups(items) {
  const groupMap = {};
  items.forEach(item => {
    const g = item.group_name || '默认';
    if (!groupMap[g]) groupMap[g] = [];
    groupMap[g].push(item);
  });
  return groupMap;
}

function renderWatchlistPage(container, items, groups) {
  const totalItems = items.length;
  const groupCount = Object.keys(groups).length;
  const stockCount = items.filter(i => (i.asset_type || 'stock') === 'stock').length;
  const etfCount = items.filter(i => i.asset_type === 'etf').length;

  container.innerHTML = `
    <div class="grid-3" style="margin-bottom:20px">
      <div class="card">
        <div class="card-title">关注总数</div>
        <div class="stat-value">${totalItems}</div>
      </div>
      <div class="card">
        <div class="card-title">分组数量</div>
        <div class="stat-value">${groupCount}</div>
      </div>
      <div class="card">
        <div class="card-title">构成</div>
        <div class="stat-value">${stockCount} 股票 / ${etfCount} ETF</div>
      </div>
    </div>

    <div class="card" style="margin-bottom:20px">
      <div class="card-title">添加关注</div>
      <div class="grid-2">
        <div class="form-group">
          <label class="form-label">搜索</label>
          <div style="display:flex;gap:8px">
            <input type="text" id="wlSearchInput" class="form-input" placeholder="输入股票/ETF名称或代码...">
            <select id="wlSearchType" class="form-select" style="width:120px">
              <option value="stock">股票</option>
              <option value="etf">ETF</option>
            </select>
            <button class="btn btn-primary" id="wlSearchBtn">搜索</button>
          </div>
        </div>
        <div class="form-group">
          <label class="form-label">添加到分组</label>
          <div style="display:flex;gap:8px">
            <select id="wlAddGroup" class="form-select">
              ${Object.keys(groups).map(g => `<option value="${g}">${g}</option>`).join('')}
              <option value="__new__">+ 新分组</option>
            </select>
            <input type="text" id="wlNewGroupInput" class="form-input" placeholder="新分组名" style="display:none">
            <input type="text" id="wlNotesInput" class="form-input" placeholder="备注（可选）" style="max-width:160px">
          </div>
        </div>
      </div>
      <div id="wlSearchResults"></div>
    </div>

    <div id="wlGroups"></div>
  `;

  document.getElementById('wlSearchBtn').addEventListener('click', () => handleWatchlistSearch(items));
  document.getElementById('wlSearchInput').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') handleWatchlistSearch(items);
  });
  document.getElementById('wlAddGroup').addEventListener('change', (e) => {
    const newInput = document.getElementById('wlNewGroupInput');
    newInput.style.display = e.target.value === '__new__' ? 'inline-block' : 'none';
  });

  renderWatchlistGroups(items, groups);
}

async function handleWatchlistSearch(allItems) {
  const keyword = document.getElementById('wlSearchInput').value.trim();
  const type = document.getElementById('wlSearchType').value;
  const resultsDiv = document.getElementById('wlSearchResults');

  if (!keyword) {
    showToast('请输入搜索关键词', 'info');
    return;
  }

  resultsDiv.innerHTML = '<div class="loading"><div class="spinner"></div>搜索中...</div>';

  let result;
  if (type === 'etf') {
    result = await API.getETFList(keyword);
  } else {
    result = await API.getStocks(keyword);
  }

  if (!result || !result.items || result.items.length === 0) {
    resultsDiv.innerHTML = '<p style="margin-top:10px;color:#888">未找到匹配结果</p>';
    return;
  }

  const existingCodes = new Set(allItems.map(i => i.ts_code));

  resultsDiv.innerHTML = `
    <table class="data-table" style="margin-top:12px">
      <thead>
        <tr>
          <th>代码</th>
          <th>名称</th>
          <th>${type === 'etf' ? '基金类型' : '行业'}</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        ${result.items.slice(0, 15).map(item => {
          const code = item.ts_code;
          const name = item.name;
          const extra = type === 'etf' ? (item.fund_type || '-') : (item.industry || '-');
          const added = existingCodes.has(code);
          return `
            <tr>
              <td>${code}</td>
              <td>${name}</td>
              <td>${extra}</td>
              <td>
                ${added
                  ? '<span class="tag tag-gray">已添加</span>'
                  : `<button class="btn btn-sm btn-primary" onclick="addToWatchlistAction('${code}','${name}','${type}')">添加</button>`
                }
              </td>
            </tr>
          `;
        }).join('')}
      </tbody>
    </table>
    ${result.total > 15 ? `<p style="margin-top:8px;color:#888;font-size:13px">显示前15条，共 ${result.total} 条结果</p>` : ''}
  `;
}

async function addToWatchlistAction(tsCode, name, assetType) {
  const groupSelect = document.getElementById('wlAddGroup');
  let group = groupSelect.value;
  if (group === '__new__') {
    group = document.getElementById('wlNewGroupInput').value.trim() || '默认';
  }
  const notes = document.getElementById('wlNotesInput').value.trim();

  const result = await API.addToWatchlist(tsCode, name, assetType, group, notes);

  if (result && result.success) {
    showToast(`已添加 ${name} 到关注列表`, 'success');
    document.getElementById('wlNotesInput').value = '';
    renderWatchlist();
  } else {
    showToast(result?.message || '添加失败', 'error');
  }
}

async function removeFromWatchlistAction(tsCode, name) {
  if (!confirm(`确认移除 ${name}(${tsCode})？`)) return;

  const result = await API.removeFromWatchlist(tsCode);

  if (result && result.success) {
    showToast(`已移除 ${name}`, 'success');
    renderWatchlist();
  } else {
    showToast(result?.message || '移除失败', 'error');
  }
}

function renderWatchlistGroups(items, groups) {
  const groupsContainer = document.getElementById('wlGroups');
  const groupNames = Object.keys(groups);

  if (groupNames.length === 0) {
    groupsContainer.innerHTML = `
      <div class="card">
        <p style="text-align:center;color:#888;padding:40px 0">
          关注列表为空，请使用上方搜索添加股票或ETF
        </p>
      </div>
    `;
    return;
  }

  groupsContainer.innerHTML = groupNames.map(groupName => {
    const groupItems = groups[groupName];
    return `
      <div class="card" style="margin-bottom:20px">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
          <div class="card-title" style="margin-bottom:0">${groupName}</div>
          <button class="btn btn-sm btn-outline" onclick="loadGroupQuotes('${groupName}')">
            📊 实时行情
          </button>
        </div>
        <table class="data-table">
          <thead>
            <tr>
              <th>代码</th>
              <th>名称</th>
              <th>类型</th>
              <th>备注</th>
              <th id="quoteHeader_${groupName}">行情</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            ${groupItems.map(item => {
              const typeTag = (item.asset_type || 'stock') === 'etf'
                ? '<span class="tag tag-blue">ETF</span>'
                : '<span class="tag tag-green">股票</span>';
              return `
                <tr>
                  <td>${item.ts_code}</td>
                  <td>${item.name}</td>
                  <td>${typeTag}</td>
                  <td>${item.notes || '-'}</td>
                  <td class="quote-cell" data-code="${item.ts_code}">-</td>
                  <td>
                    <button class="btn btn-sm btn-danger" onclick="removeFromWatchlistAction('${item.ts_code}','${item.name}')">移除</button>
                  </td>
                </tr>
              `;
            }).join('')}
          </tbody>
        </table>
      </div>
    `;
  }).join('');
}

async function loadGroupQuotes(groupName) {
  const cells = document.querySelectorAll(`.quote-cell`);
  const groupCells = Array.from(cells).filter(cell => {
    const row = cell.closest('tr');
    if (!row) return false;
    const card = row.closest('.card');
    if (!card) return false;
    const title = card.querySelector('.card-title');
    return title && title.textContent.trim() === groupName;
  });

  if (groupCells.length === 0) return;

  const codes = groupCells.map(c => c.dataset.code);
  groupCells.forEach(c => { c.innerHTML = '<div class="spinner" style="width:16px;height:16px;border-width:2px"></div>'; });

  const data = await API.getRealtime(codes.join(','));

  if (!data || !data.items) {
    groupCells.forEach(c => { c.textContent = '获取失败'; });
    showToast('获取实时行情失败', 'error');
    return;
  }

  const quoteMap = {};
  data.items.forEach(q => { quoteMap[q.ts_code] = q; });

  groupCells.forEach(cell => {
    const q = quoteMap[cell.dataset.code];
    if (q) {
      const cls = (q.change_pct || 0) >= 0 ? 'positive' : 'negative';
      const arrow = (q.change_pct || 0) >= 0 ? '▲' : '▼';
      cell.innerHTML = `
        <span style="font-weight:600">${(q.price || 0).toFixed(2)}</span>
        <span class="${cls}" style="margin-left:6px;font-size:12px">
          ${arrow}${Math.abs(q.change_pct || 0).toFixed(2)}%
        </span>
      `;
    } else {
      cell.textContent = '无数据';
    }
  });
}
