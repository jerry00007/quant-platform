/**
 * QuantWeave 持仓管理页面
 * 功能：账户概览、持仓CRUD、存取现金、交易流水
 */

let portfolioState = {
  currentAccount: 'main',
  positions: [],
  accountInfo: null,
  transactions: [],
};

async function renderPortfolio() {
  const main = document.getElementById('mainContent');
  main.innerHTML = `
    <div class="page-header">
      <h2>💼 持仓管理</h2>
      <p>账户概览与持仓流水</p>
    </div>
    <div id="pfContent"><div class="loading"><div class="spinner"></div>加载中...</div></div>
  `;

  await loadPortfolioData();
}

async function loadPortfolioData() {
  const container = document.getElementById('pfContent');
  
  try {
    // 并行获取账户信息和持仓
    const [accountInfo, positions, health] = await Promise.all([
      API.getAccountInfo(portfolioState.currentAccount),
      API.getPositions(portfolioState.currentAccount),
      API.getPortfolioHealth(),
    ]);

    portfolioState.accountInfo = accountInfo?.data || accountInfo;
    
    // 后端返回 {success, data: summary}，summary中包含 positions 列表
    const summary = positions?.data || positions;
    portfolioState.positions = summary?.positions || summary?.items || [];
    
    renderPortfolioPage(container, portfolioState.accountInfo, portfolioState.positions, health);
  } catch (err) {
    console.error('加载持仓数据失败:', err);
    container.innerHTML = `
      <div class="card">
        <p style="color:#f00">加载数据失败: ${err.message}</p>
        <button class="btn btn-primary" onclick="loadPortfolioData()">重试</button>
      </div>
    `;
  }
}

function renderPortfolioPage(container, account, positions, health) {
  const totalValue = positions.reduce((sum, p) => sum + (p.market_value || 0), 0);
  const totalCost = positions.reduce((sum, p) => sum + (p.cost_value || 0), 0);
  const totalProfit = totalValue - totalCost;
  const profitPct = totalCost > 0 ? (totalProfit / totalCost * 100) : 0;

  // 计算持仓相关统计
  const longCount = positions.filter(p => p.direction === 'long').length;
  const shortCount = positions.filter(p => p.direction === 'short').length;

  container.innerHTML = `
    <!-- 账户概览 -->
    <div class="grid-4" style="margin-bottom:20px">
      <div class="card">
        <div class="card-title">💰 总资产</div>
        <div class="stat-value">${formatPortfolioNumber(account?.total_assets || 0)}</div>
      </div>
      <div class="card">
        <div class="card-title">💵 现金余额</div>
        <div class="stat-value">${formatPortfolioNumber(account?.cash_balance || 0)}</div>
      </div>
      <div class="card">
        <div class="card-title">📊 持仓市值</div>
        <div class="stat-value">${formatPortfolioNumber(totalValue)}</div>
      </div>
      <div class="card">
        <div class="card-title">📈 浮动盈亏</div>
        <div class="stat-value ${totalProfit >= 0 ? 'positive' : 'negative'}">
          ${totalProfit >= 0 ? '+' : ''}${formatPortfolioNumber(totalProfit)} (${profitPct.toFixed(2)}%)
        </div>
      </div>
    </div>

    <!-- 快捷操作 -->
    <div class="card" style="margin-bottom:20px">
      <div class="card-title">⚡ 快捷操作</div>
      <div style="display:flex;gap:12px;flex-wrap:wrap">
        <button class="btn btn-primary" onclick="showAddPositionModal()">➕ 添加持仓</button>
        <button class="btn btn-success" onclick="showDepositModal()">💳 存入现金</button>
        <button class="btn btn-warning" onclick="showWithdrawModal()">💸 取出现金</button>
        <button class="btn btn-outline" onclick="syncAllPositions()">🔄 同步价格</button>
      </div>
    </div>

    <!-- 持仓列表 -->
    <div class="card" style="margin-bottom:20px">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
        <div class="card-title" style="margin-bottom:0">📋 当前持仓 <span style="font-weight:normal;font-size:14px;color:#888">(共 ${positions.length} 项，多头 ${longCount} / 空头 ${shortCount})</span></div>
      </div>
      ${positions.length === 0 ? `
        <p style="text-align:center;color:#888;padding:40px 0">
          暂无持仓，请点击"添加持仓"创建
        </p>
      ` : `
        <table class="data-table">
          <thead>
            <tr>
              <th>代码</th>
              <th>名称</th>
              <th>方向</th>
              <th>数量</th>
              <th>成本价</th>
              <th>当前价</th>
              <th>市值</th>
              <th>盈亏</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            ${positions.map(p => {
              const profit = (p.market_value || 0) - (p.cost_value || 0);
              const profitPct = (p.cost_value || 0) > 0 ? (profit / p.cost_value * 100) : 0;
              const directionTag = p.direction === 'long' 
                ? '<span class="tag tag-green">多头</span>' 
                : '<span class="tag tag-red">空头</span>';
              return `
                <tr>
                  <td style="font-weight:600">${p.ts_code}</td>
                  <td>${p.name || '-'}</td>
                  <td>${directionTag}</td>
                  <td>${p.volume}</td>
                  <td>${(p.avg_cost || 0).toFixed(2)}</td>
                  <td>${(p.current_price || 0).toFixed(2)}</td>
                  <td>${formatPortfolioNumber(p.market_value || 0)}</td>
                  <td class="${profit >= 0 ? 'positive' : 'negative'}">
                    ${profit >= 0 ? '+' : ''}${formatPortfolioNumber(profit)} (${profitPct.toFixed(1)}%)
                  </td>
                  <td>
                    <button class="btn btn-sm btn-outline" onclick="showUpdatePriceModal('${p.id}','${p.ts_code}',${p.current_price || 0})">改价</button>
                    <button class="btn btn-sm btn-danger" onclick="showClosePositionModal('${p.id}','${p.ts_code}','${p.name}',${p.volume})">平仓</button>
                  </td>
                </tr>
              `;
            }).join('')}
          </tbody>
        </table>
      `}
    </div>

    <!-- 交易流水 -->
    <div class="card">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
        <div class="card-title" style="margin-bottom:0">📜 交易流水</div>
        <button class="btn btn-sm btn-outline" onclick="loadMoreTransactions()">加载更多</button>
      </div>
      <div id="pfTransactionList">
        <p style="text-align:center;color:#888;padding:20px">暂无交易记录</p>
      </div>
    </div>
  `;

  // 自动加载交易流水
  loadTransactionsList();
}

// ========== 持仓操作 ==========

async function showAddPositionModal() {
  const modal = document.createElement('div');
  modal.className = 'modal';
  modal.id = 'addPositionModal';
  modal.innerHTML = `
    <div class="modal-content">
      <div class="modal-header">
        <h3>添加持仓</h3>
        <button class="modal-close" onclick="closeModal('addPositionModal')">&times;</button>
      </div>
      <div class="modal-body">
        <div class="form-group">
          <label class="form-label">证券代码 *</label>
          <input type="text" id="apTsCode" class="form-input" placeholder="如: 600519">
        </div>
        <div class="form-group">
          <label class="form-label">证券名称 *</label>
          <input type="text" id="apName" class="form-input" placeholder="如: 贵州茅台">
        </div>
        <div class="form-group">
          <label class="form-label">方向</label>
          <select id="apDirection" class="form-select">
            <option value="long">多头 (买入)</option>
            <option value="short">空头 (融券)</option>
          </select>
        </div>
        <div class="form-group">
          <label class="form-label">数量 *</label>
          <input type="number" id="apVolume" class="form-input" placeholder="股数">
        </div>
        <div class="form-group">
          <label class="form-label">成本价 *</label>
          <input type="number" id="apCost" class="form-input" step="0.01" placeholder="单价">
        </div>
        <div class="form-group">
          <label class="form-label">备注</label>
          <input type="text" id="apNotes" class="form-input" placeholder="可选">
        </div>
      </div>
      <div class="modal-footer">
        <button class="btn btn-outline" onclick="closeModal('addPositionModal')">取消</button>
        <button class="btn btn-primary" onclick="submitAddPosition()">确认添加</button>
      </div>
    </div>
  `;
  document.body.appendChild(modal);
  modal.style.display = 'block';
}

async function submitAddPosition() {
  const tsCode = document.getElementById('apTsCode').value.trim();
  const name = document.getElementById('apName').value.trim();
  const direction = document.getElementById('apDirection').value;
  const volume = parseInt(document.getElementById('apVolume').value);
  const avgCost = parseFloat(document.getElementById('apCost').value);
  const notes = document.getElementById('apNotes').value.trim();

  if (!tsCode || !name || !volume || !avgCost) {
    showToast('请填写所有必填项', 'error');
    return;
  }

  try {
    const result = await API.createPosition({
      ts_code: tsCode,
      symbol: tsCode,
      name: name,
      direction: direction,
      volume: volume,
      avg_cost: avgCost,
      account_name: portfolioState.currentAccount,
      notes: notes,
    });

    if (result && result.id) {
      showToast('持仓添加成功', 'success');
      closeModal('addPositionModal');
      loadPortfolioData();
    } else {
      showToast(result?.message || '添加失败', 'error');
    }
  } catch (err) {
    showToast('添加失败: ' + err.message, 'error');
  }
}

async function showUpdatePriceModal(positionId, tsCode, currentPrice) {
  const modal = document.createElement('div');
  modal.className = 'modal';
  modal.id = 'updatePriceModal';
  modal.innerHTML = `
    <div class="modal-content">
      <div class="modal-header">
        <h3>更新价格 - ${tsCode}</h3>
        <button class="modal-close" onclick="closeModal('updatePriceModal')">&times;</button>
      </div>
      <div class="modal-body">
        <div class="form-group">
          <label class="form-label">当前价格</label>
          <input type="number" id="upPrice" class="form-input" step="0.01" value="${currentPrice}">
        </div>
      </div>
      <div class="modal-footer">
        <button class="btn btn-outline" onclick="closeModal('updatePriceModal')">取消</button>
        <button class="btn btn-primary" onclick="submitUpdatePrice('${positionId}')">确认更新</button>
      </div>
    </div>
  `;
  document.body.appendChild(modal);
  modal.style.display = 'block';
}

async function submitUpdatePrice(positionId) {
  const price = parseFloat(document.getElementById('upPrice').value);
  if (!price || price <= 0) {
    showToast('请输入有效价格', 'error');
    return;
  }

  try {
    const result = await API.updatePositionPrice(positionId, price);
    if (result && result.id) {
      showToast('价格更新成功', 'success');
      closeModal('updatePriceModal');
      loadPortfolioData();
    } else {
      showToast(result?.message || '更新失败', 'error');
    }
  } catch (err) {
    showToast('更新失败: ' + err.message, 'error');
  }
}

async function showClosePositionModal(positionId, tsCode, name, volume) {
  const modal = document.createElement('div');
  modal.className = 'modal';
  modal.id = 'closePositionModal';
  modal.innerHTML = `
    <div class="modal-content">
      <div class="modal-header">
        <h3>平仓 - ${tsCode} (${name})</h3>
        <button class="modal-close" onclick="closeModal('closePositionModal')">&times;</button>
      </div>
      <div class="modal-body">
        <div class="form-group">
          <label class="form-label">平仓数量 (剩余 ${volume})</label>
          <input type="number" id="cpVolume" class="form-input" value="${volume}">
        </div>
        <div class="form-group">
          <label class="form-label">平仓价格 *</label>
          <input type="number" id="cpPrice" class="form-input" step="0.01" placeholder="平仓单价">
        </div>
        <div class="form-group">
          <label class="form-label">交易类型</label>
          <select id="cpType" class="form-select">
            <option value="sell">卖出</option>
            <option value="cover">融券偿还</option>
          </select>
        </div>
        <div class="form-group">
          <label class="form-label">备注</label>
          <input type="text" id="cpNotes" class="form-input" placeholder="可选">
        </div>
      </div>
      <div class="modal-footer">
        <button class="btn btn-outline" onclick="closeModal('closePositionModal')">取消</button>
        <button class="btn btn-danger" onclick="submitClosePosition('${positionId}')">确认平仓</button>
      </div>
    </div>
  `;
  document.body.appendChild(modal);
  modal.style.display = 'block';
}

async function submitClosePosition(positionId) {
  const volume = parseInt(document.getElementById('cpVolume').value);
  const price = parseFloat(document.getElementById('cpPrice').value);
  const transactionType = document.getElementById('cpType').value;
  const notes = document.getElementById('cpNotes').value.trim();

  if (!volume || !price || price <= 0) {
    showToast('请填写所有必填项', 'error');
    return;
  }

  try {
    const result = await API.closePosition(positionId, {
      close_price: price,
      volume: volume,
      transaction_type: transactionType,
      notes: notes,
    });

    if (result && result.success) {
      showToast('平仓成功', 'success');
      closeModal('closePositionModal');
      loadPortfolioData();
    } else {
      showToast(result?.message || '平仓失败', 'error');
    }
  } catch (err) {
    showToast('平仓失败: ' + err.message, 'error');
  }
}

// ========== 现金操作 ==========

async function showDepositModal() {
  const modal = document.createElement('div');
  modal.className = 'modal';
  modal.id = 'depositModal';
  modal.innerHTML = `
    <div class="modal-content">
      <div class="modal-header">
        <h3>💳 存入现金</h3>
        <button class="modal-close" onclick="closeModal('depositModal')">&times;</button>
      </div>
      <div class="modal-body">
        <div class="form-group">
          <label class="form-label">金额 *</label>
          <input type="number" id="depositAmount" class="form-input" step="0.01" placeholder="存入金额">
        </div>
        <div class="form-group">
          <label class="form-label">备注</label>
          <input type="text" id="depositNotes" class="form-input" placeholder="可选">
        </div>
      </div>
      <div class="modal-footer">
        <button class="btn btn-outline" onclick="closeModal('depositModal')">取消</button>
        <button class="btn btn-success" onclick="submitDeposit()">确认存入</button>
      </div>
    </div>
  `;
  document.body.appendChild(modal);
  modal.style.display = 'block';
}

async function submitDeposit() {
  const amount = parseFloat(document.getElementById('depositAmount').value);
  const notes = document.getElementById('depositNotes').value.trim();

  if (!amount || amount <= 0) {
    showToast('请输入有效金额', 'error');
    return;
  }

  try {
    const result = await API.depositCash({
      amount: amount,
      account_name: portfolioState.currentAccount,
      notes: notes,
    });

    if (result && result.success) {
      showToast('存入成功', 'success');
      closeModal('depositModal');
      loadPortfolioData();
    } else {
      showToast(result?.message || '存入失败', 'error');
    }
  } catch (err) {
    showToast('存入失败: ' + err.message, 'error');
  }
}

async function showWithdrawModal() {
  const modal = document.createElement('div');
  modal.className = 'modal';
  modal.id = 'withdrawModal';
  const maxCash = portfolioState.accountInfo?.cash_balance || 0;
  modal.innerHTML = `
    <div class="modal-content">
      <div class="modal-header">
        <h3>💸 取出现金</h3>
        <button class="modal-close" onclick="closeModal('withdrawModal')">&times;</button>
      </div>
      <div class="modal-body">
        <p style="color:#888;margin-bottom:12px">最大可取: ${formatPortfolioNumber(maxCash)}</p>
        <div class="form-group">
          <label class="form-label">金额 *</label>
          <input type="number" id="withdrawAmount" class="form-input" step="0.01" placeholder="取出金额">
        </div>
        <div class="form-group">
          <label class="form-label">备注</label>
          <input type="text" id="withdrawNotes" class="form-input" placeholder="可选">
        </div>
      </div>
      <div class="modal-footer">
        <button class="btn btn-outline" onclick="closeModal('withdrawModal')">取消</button>
        <button class="btn btn-warning" onclick="submitWithdraw()">确认取出</button>
      </div>
    </div>
  `;
  document.body.appendChild(modal);
  modal.style.display = 'block';
}

async function submitWithdraw() {
  const amount = parseFloat(document.getElementById('withdrawAmount').value);
  const notes = document.getElementById('withdrawNotes').value.trim();
  const maxCash = portfolioState.accountInfo?.cash_balance || 0;

  if (!amount || amount <= 0) {
    showToast('请输入有效金额', 'error');
    return;
  }
  if (amount > maxCash) {
    showToast('余额不足', 'error');
    return;
  }

  try {
    const result = await API.withdrawCash({
      amount: amount,
      account_name: portfolioState.currentAccount,
      notes: notes,
    });

    if (result && result.success) {
      showToast('取出成功', 'success');
      closeModal('withdrawModal');
      loadPortfolioData();
    } else {
      showToast(result?.message || '取出失败', 'error');
    }
  } catch (err) {
    showToast('取出失败: ' + err.message, 'error');
  }
}

// ========== 同步与交易流水 ==========

async function syncAllPositions() {
  showToast('正在同步持仓价格...', 'info');
  try {
    const result = await API.syncPositions(portfolioState.currentAccount);
    if (result && result.success) {
      showToast('同步成功', 'success');
      loadPortfolioData();
    } else {
      showToast(result?.message || '同步失败', 'error');
    }
  } catch (err) {
    showToast('同步失败: ' + err.message, 'error');
  }
}

let transactionOffset = 0;
const TRANSACTION_LIMIT = 20;

async function loadTransactionsList() {
  const container = document.getElementById('pfTransactionList');
  if (!container) return;

  container.innerHTML = '<div class="loading"><div class="spinner"></div>加载中...</div>';

  try {
    const result = await API.getTransactions(portfolioState.currentAccount, TRANSACTION_LIMIT, transactionOffset);
    const txList = result?.transactions || [];
    
    if (txList.length === 0) {
      container.innerHTML = '<p style="text-align:center;color:#888;padding:20px">暂无交易记录</p>';
      return;
    }

    // 追加到现有列表
    if (transactionOffset === 0) {
      portfolioState.transactions = txList;
    } else {
      portfolioState.transactions = portfolioState.transactions.concat(txList);
    }
    transactionOffset += txList.length;

    renderTransactionList(container, portfolioState.transactions, result?.total || txList.length);
  } catch (err) {
    container.innerHTML = `<p style="color:#f00">加载失败: ${err.message}</p>`;
  }
}

function renderTransactionList(container, transactions, total) {
  container.innerHTML = `
    <table class="data-table">
      <thead>
        <tr>
          <th>时间</th>
          <th>类型</th>
          <th>证券</th>
          <th>数量</th>
          <th>价格</th>
          <th>金额</th>
          <th>备注</th>
        </tr>
      </thead>
      <tbody>
        ${transactions.map(tx => {
          const typeTag = getTransactionTypeTag(tx.transaction_type);
          return `
            <tr>
              <td>${formatDateTime(tx.created_at)}</td>
              <td>${typeTag}</td>
              <td>${tx.ts_code || '-'}</td>
              <td>${tx.volume || '-'}</td>
              <td>${(tx.price || 0).toFixed(2)}</td>
              <td>${formatPortfolioNumber(tx.amount || 0)}</td>
              <td>${tx.notes || '-'}</td>
            </tr>
          `;
        }).join('')}
      </tbody>
    </table>
    ${transactions.length < total ? `<p style="text-align:center;color:#888;padding:10px">显示 ${transactions.length} / ${total} 条</p>` : ''}
  `;
}

function getTransactionTypeTag(type) {
  const tags = {
    'buy': '<span class="tag tag-green">买入</span>',
    'sell': '<span class="tag tag-red">卖出</span>',
    'deposit': '<span class="tag tag-blue">入金</span>',
    'withdraw': '<span class="tag tag-orange">出金</span>',
    'open': '<span class="tag tag-green">开仓</span>',
    'close': '<span class="tag tag-red">平仓</span>',
    'cover': '<span class="tag tag-orange">还券</span>',
  };
  return tags[type] || `<span class="tag tag-gray">${type}</span>`;
}

async function loadMoreTransactions() {
  await loadTransactionsList();
}

// ========== 工具函数 ==========

function closeModal(modalId) {
  const modal = document.getElementById(modalId);
  if (modal) {
    modal.style.display = 'none';
    modal.remove();
  }
}

function formatPortfolioNumber(num) {
  if (num === null || num === undefined) return '0';
  return Number(num).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function formatDateTime(dateStr) {
  if (!dateStr) return '-';
  const date = new Date(dateStr);
  return date.toLocaleString('zh-CN', { 
    year: 'numeric', 
    month: '2-digit', 
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}