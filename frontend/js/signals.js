/**
 * QuantWeave 持仓个股页面
 * 功能：显示持仓个股的次日操作建议、止损止盈位、生成微信通知
 */

let refreshInterval = null;

async function renderSignals() {
  const main = document.getElementById('mainContent');
  main.innerHTML = `
    <div class="page-header">
      <h2>📡 持仓个股</h2>
      <p>基于核心策略的持仓个股操作建议</p>
    </div>
    
    <div id="signalsContent">
      <div class="card">
        <div class="card-header">
          <div class="card-title">🎯 信号控制台</div>
          <div class="card-subtitle">实时生成交易日的操作建议</div>
        </div>
        <div class="card-body">
          <div class="grid-2">
            <div class="form-group">
              <label class="form-label">股票池</label>
              <select id="stockPoolSelect" class="form-select">
                <option value="portfolio" selected>📦 我的持仓</option>
                <option value="watchlist">👁️ 关注列表</option>
                <option value="tracking_pool">📋 跟踪池</option>
                <option value="all">🌐 全市场扫描</option>
                <option value="custom">✏️ 自定义...</option>
              </select>
              <div class="form-help" id="stockPoolHelp">正在加载持仓...</div>
            </div>
            
            <div class="form-group">
              <label class="form-label">策略组合</label>
              <select id="strategyGroupSelect" class="form-select">
                <option value="all" selected>🚀 全部策略（共振优先）</option>
                <option value="dual_ma">📈 双均线交叉(7/60)</option>
                <option value="pullback_stable">🔄 回调企稳(8/95/5)</option>
                <option value="bollinger_upper">📊 布林带突破(25/1.8)</option>
                <option value="enhanced_chip">🧮 增强筹码(5/98/5)</option>
                <option value="trend_ma">📉 均线趋势(15/3)</option>
              </select>
            </div>
          </div>
          
          <div class="form-actions" style="margin-top:16px">
            <button id="generateBtn" class="btn btn-primary" onclick="generateSignals()">
              🔄 生成今日信号
            </button>
            <button id="wechatBtn" class="btn btn-success" onclick="generateWechatNotice()">
              💬 生成微信通知
            </button>
            <button id="scheduleBtn" class="btn btn-outline" onclick="showScheduleDialog()">
              ⏰ 定时提醒
            </button>
          </div>
        </div>
      </div>
      
      <div id="signalsSection" style="display:none">
        <div class="grid-2">
          <div class="card">
            <div class="card-title">📊 信号概览</div>
            <div id="signalsSummary" class="card-body">
              <div class="loading"><div class="spinner"></div>生成中...</div>
            </div>
          </div>
          
          <div class="card">
            <div class="card-title">ℹ️ 系统信息</div>
            <div id="systemInfo" class="card-body">
              <div class="loading"><div class="spinner"></div>加载中...</div>
            </div>
          </div>
        </div>
        
        <div class="card" style="margin-top:16px">
          <div class="card-header">
            <div class="card-title">📋 详细建议</div>
            <div class="card-subtitle" id="signalsDate"></div>
          </div>
          <div id="signalsDetails" class="card-body">
            <div class="loading"><div class="spinner"></div>加载详细建议...</div>
          </div>
        </div>
        
        <div class="card" style="margin-top:16px">
          <div class="card-title">📝 微信通知文本</div>
          <div class="card-body">
            <textarea id="wechatText" class="form-textarea" rows="6" readonly placeholder="点击“生成微信通知”获取文本"></textarea>
            <div class="form-actions" style="margin-top:8px">
              <button class="btn btn-sm btn-secondary" onclick="copyWechatText()">
                📋 复制文本
              </button>
              <button class="btn btn-sm btn-outline" onclick="sendTestNotification()">
                🔔 测试发送
              </button>
              <div class="text-sm text-muted" style="margin-top:4px">建议在交易日 9:15 前发送</div>
            </div>
          </div>
        </div>
      </div>
      
      <div id="scheduleDialog" class="modal" style="display:none">
        <div class="modal-content" style="max-width:500px">
          <div class="modal-header">
            <div class="modal-title">⏰ 定时提醒设置</div>
            <button class="modal-close" onclick="closeScheduleDialog()">×</button>
          </div>
          <div class="modal-body">
            <div class="form-group">
              <label class="form-label">提醒时间</label>
              <input type="time" id="reminderTime" class="form-input" value="09:30">
              <div class="form-help">交易日开盘前发送通知</div>
            </div>
            
            <div class="form-group">
              <label class="form-label">通知方式</label>
              <div class="checkbox-group">
                <label class="checkbox-label">
                  <input type="checkbox" id="wechatNotify" checked>
                  <span>微信通知</span>
                </label>
                <label class="checkbox-label">
                  <input type="checkbox" id="emailNotify">
                  <span>邮箱通知</span>
                </label>
                <label class="checkbox-label">
                  <input type="checkbox" id="dingTalkNotify">
                  <span>钉钉通知</span>
                </label>
              </div>
            </div>
            
            <div class="form-group">
              <label class="form-label">仅交易日提醒</label>
              <label class="switch">
                <input type="checkbox" id="tradingDayOnly" checked>
                <span class="switch-slider"></span>
              </label>
              <div class="form-help">非交易日跳过提醒</div>
            </div>
            
            <div class="modal-actions">
              <button class="btn btn-primary" onclick="saveSchedule()">
                保存设置
              </button>
              <button class="btn btn-outline" onclick="closeScheduleDialog()">
                取消
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  `;
  
  loadPortfolioInfo();
  loadSystemInfo();
  setupAutoRefresh();
  
  // 监听股票池切换，更新帮助文本
  const poolSelect = document.getElementById('stockPoolSelect');
  if (poolSelect) {
    poolSelect.addEventListener('change', () => updatePoolHelp(poolSelect.value));
  }
}

function setupAutoRefresh() {
  // 每5分钟自动刷新一次
  if (refreshInterval) clearInterval(refreshInterval);
  refreshInterval = setInterval(() => {
    const signalsSection = document.getElementById('signalsSection');
    if (signalsSection && signalsSection.style.display !== 'none') {
      console.log('🔄 自动刷新信号...');
      generateSignals();
    }
  }, 5 * 60 * 1000); // 5分钟
}

function stopAutoRefresh() {
  if (refreshInterval) {
    clearInterval(refreshInterval);
    refreshInterval = null;
  }
}

// 当前持仓缓存
let _cachedPositions = null;

async function loadPortfolioInfo() {
  const helpEl = document.getElementById('stockPoolHelp');
  if (!helpEl) return;
  
  try {
    const resp = await API.getPositions();
    if (resp && resp.error) {
      helpEl.textContent = '⚠️ 持仓数据加载失败';
      return;
    }
    
    const data = resp?.data || resp;
    const positions = data?.positions || data?.items || [];
    _cachedPositions = positions;
    
    if (positions.length === 0) {
      helpEl.textContent = '📦 当前无持仓';
      return;
    }
    
    const names = positions.map(p => p.name || p.stock_name || p.ts_code).join('、');
    helpEl.textContent = `📦 持仓 ${positions.length} 只：${names}`;
  } catch (err) {
    helpEl.textContent = '⚠️ 持仓数据加载失败';
    _cachedPositions = null;
  }
}

function updatePoolHelp(poolType) {
  const helpEl = document.getElementById('stockPoolHelp');
  if (!helpEl) return;
  
  switch (poolType) {
    case 'portfolio':
      if (_cachedPositions && _cachedPositions.length > 0) {
        const names = _cachedPositions.map(p => p.name || p.stock_name || p.ts_code).join('、');
        helpEl.textContent = `📦 持仓 ${_cachedPositions.length} 只：${names}`;
      } else {
        helpEl.textContent = '📦 当前无持仓';
      }
      break;
    case 'watchlist':
      helpEl.textContent = '👁️ 关注列表中的股票（需先添加关注）';
      break;
    case 'tracking_pool':
      helpEl.textContent = '📋 跟踪池中状态为 tracking 的股票';
      break;
    case 'all':
      helpEl.textContent = '🌐 全市场约5000只股票扫描，耗时较长';
      break;
    case 'custom':
      helpEl.textContent = '✏️ 请在下方输入股票代码，多个用逗号分隔（如：000001.SZ,600519.SH）';
      // 动态插入输入框
      showCustomInput();
      return;
    default:
      helpEl.textContent = '';
  }
  // 移除自定义输入框（如果存在）
  removeCustomInput();
}

function showCustomInput() {
  if (document.getElementById('customStockInput')) return;
  const helpEl = document.getElementById('stockPoolHelp');
  const input = document.createElement('input');
  input.type = 'text';
  input.id = 'customStockInput';
  input.className = 'form-input';
  input.style.marginTop = '8px';
  input.placeholder = '输入股票代码，逗号分隔，如：000001.SZ,600519.SH';
  helpEl.parentNode.appendChild(input);
}

function removeCustomInput() {
  const existing = document.getElementById('customStockInput');
  if (existing) existing.remove();
}

async function loadSystemInfo() {
  const container = document.getElementById('systemInfo');
  if (!container) return;
  
  try {
    const health = await API.getHealth();
    const today = new Date().toISOString().split('T')[0];
    
    container.innerHTML = `
      <div class="info-grid">
        <div class="info-item">
          <span class="info-label">系统状态</span>
          <span class="info-value" style="color:var(--success)">✅ 运行中</span>
        </div>
        <div class="info-item">
          <span class="info-label">当前日期</span>
          <span class="info-value">${today}</span>
        </div>
        <div class="info-item">
          <span class="info-label">策略数量</span>
          <span class="info-value">11</span>
        </div>
        <div class="info-item">
          <span class="info-label">数据源</span>
          <span class="info-value">Tushare</span>
        </div>
        <div class="info-item">
          <span class="info-label">自动刷新</span>
          <span class="info-value" id="autoRefreshStatus">启用</span>
        </div>
        <div class="info-item">
          <span class="info-label">上次生成</span>
          <span class="info-value" id="lastGenerateTime">—</span>
        </div>
      </div>
    `;
  } catch (err) {
    container.innerHTML = `<div class="error">⚠️ 系统信息加载失败</div>`;
  }
}

async function generateSignals() {
  const btn = document.getElementById('generateBtn');
  if (btn) btn.disabled = true;
  
  const section = document.getElementById('signalsSection');
  const summary = document.getElementById('signalsSummary');
  const details = document.getElementById('signalsDetails');
  const dateElem = document.getElementById('signalsDate');
  
  if (section) section.style.display = 'block';
  if (summary) summary.innerHTML = '<div class="loading"><div class="spinner"></div>扫描中...</div>';
  if (details) details.innerHTML = '<div class="loading"><div class="spinner"></div>生成详细建议...</div>';
  
  const stockPool = document.getElementById('stockPoolSelect')?.value || 'portfolio';
  const strategyGroup = document.getElementById('strategyGroupSelect')?.value || 'all';
  
  try {
    // 根据股票池类型解析实际股票代码
    let stocksParam = null;
    let strategiesParam = null;
    
    if (stockPool === 'portfolio') {
      // 从缓存中取持仓代码
      if (_cachedPositions && _cachedPositions.length > 0) {
        stocksParam = _cachedPositions.map(p => p.ts_code).join(',');
      } else {
        // 缓存为空则实时拉取
        const resp = await API.getPositions();
        const data = resp?.data || resp;
        const positions = data?.positions || data?.items || [];
        if (positions.length === 0) {
          if (summary) summary.innerHTML = '<div class="empty">📦 当前无持仓，请先添加持仓或切换其他股票池</div>';
          if (btn) btn.disabled = false;
          return;
        }
        stocksParam = positions.map(p => p.ts_code).join(',');
      }
    } else if (stockPool === 'tracking_pool') {
      // 跟踪池：从后端 tracking_pool 接口获取（或用 signals 接口的特殊参数）
      // 暂时通过 scan 接口 + tracking_pool 标记来实现
      stocksParam = 'tracking_pool';
    } else if (stockPool === 'watchlist') {
      stocksParam = 'watchlist';
    } else if (stockPool === 'custom') {
      const customInput = document.getElementById('customStockInput');
      const customVal = customInput?.value?.trim();
      if (!customVal) {
        if (summary) summary.innerHTML = '<div class="empty">✏️ 请输入自定义股票代码</div>';
        if (btn) btn.disabled = false;
        return;
      }
      stocksParam = customVal;
    }
    // stockPool === 'all' 时不传参，全市场扫描
    
    if (strategyGroup !== 'all') {
      strategiesParam = strategyGroup;
    }
    
    const data = await API.getDailySignals(stocksParam, strategiesParam);
    
    // 更新最后生成时间
    const timeElem = document.getElementById('lastGenerateTime');
    if (timeElem) {
      const now = new Date().toLocaleTimeString('zh-CN');
      timeElem.textContent = now;
    }
    
    // 显示概要信息
    renderSignalsSummary(data);
    
    // 显示详细建议
    renderSignalsDetails(data);
    
    // 更新日期
    if (dateElem) {
      const nextDay = data.next_trade_day || '(未知)';
      dateElem.textContent = `下一交易日: ${nextDay}`;
    }
    
    // 自动生成微信文本
    generateWechatNotice();
    
  } catch (err) {
    if (summary) {
      summary.innerHTML = `
        <div class="error">
          <strong>❌ 信号生成失败</strong>
          <p>${err.message || '未知错误'}</p>
        </div>
      `;
    }
    if (details) details.innerHTML = '';
  } finally {
    if (btn) btn.disabled = false;
  }
}

function renderSignalsSummary(data) {
  const container = document.getElementById('signalsSummary');
  if (!container) return;
  
  if (!data || !data.summary) {
    container.innerHTML = '<div class="empty">无信号数据</div>';
    return;
  }
  
  const summary = data.summary;
  const total = summary.total || 0;
  const buys = summary.buy || 0;
  const sells = summary.sell || 0;
  const holds = summary.hold || 0;
  
  container.innerHTML = `
    <div class="summary-grid">
      <div class="summary-card summary-total">
        <div class="summary-label">总信号数</div>
        <div class="summary-value">${total}</div>
      </div>
      <div class="summary-card summary-buy">
        <div class="summary-label">买入建议</div>
        <div class="summary-value">${buys}</div>
      </div>
      <div class="summary-card summary-sell">
        <div class="summary-label">卖出建议</div>
        <div class="summary-value">${sells}</div>
      </div>
      <div class="summary-card summary-hold">
        <div class="summary-label">观望建议</div>
        <div class="summary-value">${holds}</div>
      </div>
    </div>
    
    <div style="margin-top:12px">
      <strong>说明：</strong>
      <ul style="margin-top:4px;padding-left:20px;font-size:13px">
        <li>买入：至少1个策略触发买入信号</li>
        <li>卖出：至少1个策略触发卖出信号</li>
        <li>观望：买卖信号持平或无信号</li>
      </ul>
    </div>
  `;
}

function renderSignalsDetails(data) {
  const container = document.getElementById('signalsDetails');
  if (!container || !data || !data.signals) return;
  
  const signals = data.signals;
  if (signals.length === 0) {
    container.innerHTML = '<div class="empty">今日无操作建议，继续观望或调整策略</div>';
    return;
  }
  
  container.innerHTML = signals.map(s => `
    <div class="signal-card ${s.action}">
      <div class="signal-header">
        <div class="signal-title">
          <span class="signal-action ${s.action}">
            ${s.action === 'buy' ? '🟢 买入' : s.action === 'sell' ? '🔴 卖出' : '⚪ 观望'}
          </span>
          <strong>${s.name}</strong>
          <code class="stock-code">${s.ts_code}</code>
          <span class="tag ${s.urgency === 'high' ? 'tag-red' : s.urgency === 'medium' ? 'tag-orange' : 'tag-blue'}">
            ${s.urgency === 'high' ? '紧急' : s.urgency === 'medium' ? '中等' : '低'}
          </span>
        </div>
        <div class="signal-date">${s.date}</div>
      </div>
      
      <div class="signal-body">
        <div class="grid-3">
          <div class="info-item">
            <span class="info-label">最新价</span>
            <span class="info-value">¥${(s.price || 0).toFixed(2)}</span>
          </div>
          ${s.stop_loss ? `
            <div class="info-item">
              <span class="info-label">止损位</span>
              <span class="info-value" style="color:var(--danger)">¥${s.stop_loss.toFixed(2)}</span>
            </div>
          ` : ''}
          ${s.take_profit ? `
            <div class="info-item">
              <span class="info-label">止盈位</span>
              <span class="info-value" style="color:var(--success)">¥${s.take_profit.toFixed(2)}</span>
            </div>
          ` : ''}
        </div>
        
        ${s.strategies && s.strategies.length > 0 ? `
          <div style="margin-top:8px">
            <strong>策略：</strong>
            ${s.strategies.map(st => `<span class="badge badge-blue">${st}</span>`).join(' ')}
          </div>
        ` : ''}
        
        ${s.reasons && s.reasons.length > 0 ? `
          <div style="margin-top:8px">
            <strong>理由：</strong>
            <ul style="margin-top:4px;padding-left:20px">
              ${s.reasons.slice(0,3).map(r => `<li>${r.strategy}: ${r.reason}</li>`).join('')}
            </ul>
          </div>
        ` : ''}
        
        <div class="signal-actions" style="margin-top:12px;display:flex;gap:8px">
          <button class="btn btn-sm btn-secondary" onclick="analyzeSignal('${s.ts_code}')">
            📊 详细分析
          </button>
          <button class="btn btn-sm btn-outline" onclick="addToWatchlistAction('${s.ts_code}','${s.name}','stock')">
            👁️ 关注
          </button>
        </div>
      </div>
    </div>
  `).join('');
}

async function analyzeSignal(ts_code) {
  // 使用全局统一分析入口
  if (typeof openStockAnalysisModal === 'function') {
    await openStockAnalysisModal(ts_code, '');
  } else if (typeof analyzeStock === 'function') {
    await analyzeStock(ts_code);
  } else {
    // 最终备用方法
    try {
      const data = await API.analyzeStock(ts_code);
      showToast(`分析完成: ${ts_code} — 建议: ${data.recommendation?.action || '无'}`, 'success');
    } catch (err) {
      showToast(`分析失败: ${err.message}`, 'error');
    }
  }
}

async function generateWechatNotice() {
  const btn = document.getElementById('wechatBtn');
  if (btn) btn.disabled = true;
  
  const textarea = document.getElementById('wechatText');
  if (!textarea) return;
  
  textarea.value = '正在生成微信通知文本...';
  
  try {
    const data = await API.getMorningBrief();
    if (data && data.text) {
      textarea.value = data.text;
    } else {
      textarea.value = '📊 QuantWeave 早盘提醒\n\n服务器返回数据格式不正确，请检查后端服务。';
    }
  } catch (err) {
    textarea.value = `📊 QuantWeave 早盘提醒\n\n⚠️ 生成失败: ${err.message || '未知错误'}`;
  } finally {
    if (btn) btn.disabled = false;
  }
}

function copyWechatText() {
  const textarea = document.getElementById('wechatText');
  if (textarea && textarea.value) {
    textarea.select();
    navigator.clipboard?.writeText(textarea.value).then(() => {
      showToast('✅ 文本已复制到剪贴板');
    }).catch(() => {
      document.execCommand('copy');
      showToast('📋 文本已复制');
    });
  }
}

async function sendTestNotification() {
  const text = document.getElementById('wechatText')?.value;
  if (!text) {
    showToast('请先生成微信通知文本', 'warning');
    return;
  }
  
  if (!confirm('将要向测试通道发送通知，确定继续吗？')) return;
  
  // 这里应该调用后端通知API，但目前后端只支持钉钉/企微/邮件
  showToast('⚠️ 微信个人通知功能需额外配置，目前仅支持企业微信/钉钉渠道，请复制文本手动发送微信', 'warning');
}

function showScheduleDialog() {
  const dialog = document.getElementById('scheduleDialog');
  if (dialog) dialog.style.display = 'flex';
}

function closeScheduleDialog() {
  const dialog = document.getElementById('scheduleDialog');
  if (dialog) dialog.style.display = 'none';
}

async function saveSchedule() {
  const timeInput = document.getElementById('reminderTime');
  const time = timeInput?.value || '09:30';
  
  showToast(`✅ 定时提醒已设置为 ${time}（注：实际执行需后端配置定时任务）`, 'success');
  
  // 这里应该调用后端API配置定时任务
  // 但后端scheduler_service.py已经有一个9:15的数据同步任务，需要添加9:30的提醒任务
  
  closeScheduleDialog();
}

// showToast 使用 app.js 中的全局定义

// 添加必要的CSS样式
(function addStyles() {
  if (document.getElementById('signals-styles')) return;
  
  const style = document.createElement('style');
  style.id = 'signals-styles';
  style.textContent = `
    .summary-grid {
      display: grid;
      grid-template-columns: repeat(2, 1fr);
      gap: 12px;
    }
    @media (min-width: 768px) {
      .summary-grid {
        grid-template-columns: repeat(4, 1fr);
      }
    }
    .summary-card {
      border-radius: var(--radius);
      padding: 16px;
      text-align: center;
      background: var(--surface);
      border: 1px solid var(--border);
    }
    .summary-total { border-top: 4px solid var(--primary); }
    .summary-buy { border-top: 4px solid var(--success); }
    .summary-sell { border-top: 4px solid var(--danger); }
    .summary-hold { border-top: 4px solid var(--warning); }
    .summary-label {
      font-size: 13px;
      color: var(--text-secondary);
      margin-bottom: 4px;
    }
    .summary-value {
      font-size: 24px;
      font-weight: 700;
      color: var(--text);
    }
    .signal-card {
      border: 1px solid var(--border);
      border-radius: var(--radius);
      margin-bottom: 16px;
      overflow: hidden;
    }
    .signal-card.buy { border-left: 3px solid var(--success); }
    .signal-card.sell { border-left: 3px solid var(--danger); }
    .signal-card.hold { border-left: 3px solid var(--warning); }
    .signal-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 12px 16px;
      background: var(--surface);
      border-bottom: 1px solid var(--border);
    }
    .signal-title {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
    }
    .signal-action {
      font-weight: 600;
      font-size: 13px;
      padding: 2px 8px;
      border-radius: 4px;
    }
    .signal-action.buy { background: var(--success-bg); color: var(--success); }
    .signal-action.sell { background: var(--danger-bg); color: var(--danger); }
    .signal-action.hold { background: rgba(245, 158, 11, 0.15); color: var(--warning); }
    .signal-date {
      font-size: 12px;
      color: var(--text-muted);
      font-family: var(--font-mono);
    }
    .signal-body {
      padding: 16px;
      background: var(--surface);
    }
    .grid-3 {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 12px;
    }
    @media (max-width: 768px) {
      .grid-3 { grid-template-columns: 1fr; }
    }
    .tag-orange {
      background: #fed7aa;
      color: #9a3412;
      border: none;
    }
    .switch {
      position: relative;
      display: inline-block;
      width: 46px;
      height: 24px;
      vertical-align: middle;
    }
    .switch input {
      opacity: 0;
      width: 0;
      height: 0;
    }
    .switch-slider {
      position: absolute;
      cursor: pointer;
      top: 0;
      left: 0;
      right: 0;
      bottom: 0;
      background: var(--border);
      transition: .3s;
      border-radius: 34px;
    }
    .switch-slider:before {
      position: absolute;
      content: "";
      height: 16px;
      width: 16px;
      left: 4px;
      bottom: 4px;
      background: white;
      transition: .3s;
      border-radius: 50%;
    }
    input:checked + .switch-slider {
      background: var(--primary);
    }
    input:checked + .switch-slider:before {
      transform: translateX(22px);
    }
    .form-textarea {
      width: 100%;
      padding: 12px;
      border: 1px solid var(--border);
      border-radius: var(--radius);
      font-family: var(--font-body);
      font-size: 14px;
      line-height: 1.6;
      background: var(--surface);
      color: var(--text);
      resize: vertical;
    }
    .form-textarea:focus {
      outline: none;
      border-color: var(--primary);
    }
  `;
  document.head.appendChild(style);
})();