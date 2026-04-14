/**
 * QuantWeave 回测中心页面
 * 支持单股票/全市场动态选股回测
 */

let backtestResults = [];

function renderBacktest() {
  const main = document.getElementById('mainContent');
  main.innerHTML = `
    <div class="page-header">
      <h2>🔬 回测中心</h2>
      <p>模拟策略在历史数据上的表现</p>
    </div>

    <div class="card" style="margin-bottom:20px">
      <div class="card-title">回测模式</div>
      <div style="margin-top:12px;margin-bottom:16px">
        <label style="display:inline-flex;align-items:center;gap:8px;cursor:pointer;margin-right:24px">
          <input type="radio" name="backtestMode" value="single" checked onchange="toggleBacktestMode()">
          <span style="font-weight:500">📊 单股票回测</span>
          <span style="color:var(--text-secondary);font-size:13px">固定持有单只股票</span>
        </label>
        <label style="display:inline-flex;align-items:center;gap:8px;cursor:pointer">
          <input type="radio" name="backtestMode" value="market" onchange="toggleBacktestMode()">
          <span style="font-weight:500">🌐 全市场动态选股</span>
          <span style="color:var(--text-secondary);font-size:13px">每日全市场扫描调仓</span>
        </label>
      </div>
    </div>

    <!-- 单股票模式 -->
    <div id="singleModePanel">
      <div class="card" style="margin-bottom:20px">
        <div class="card-title">单股票回测配置</div>
        <div class="grid-4" style="gap:12px;margin-top:12px">
          <div class="form-group">
            <label class="form-label">策略</label>
            <select id="backtestStrategy" class="form-select">
              ${STRATEGY_TYPES.map(s => `<option value="${s.key}">${s.name}</option>`).join('')}
            </select>
          </div>
          <div class="form-group">
            <label class="form-label">股票代码</label>
            <input id="backtestCode" class="form-input" value="000001.SZ" placeholder="如 000001.SZ">
          </div>
          <div class="form-group">
            <label class="form-label">开始日期</label>
          <input id="backtestStart" class="form-input" type="date" value="2025-04-14">
        </div>
        <div class="form-group">
          <label class="form-label">结束日期</label>
          <input id="backtestEnd" class="form-input" type="date" value="2026-04-01">
          </div>
        </div>
        <div class="grid-4" style="gap:12px;margin-top:12px">
          <div class="form-group">
            <label class="form-label">初始资金</label>
            <input id="backtestCash" class="form-input" type="number" value="1000000">
          </div>
          <div class="form-group">
            <label class="form-label">仓位比例</label>
            <select id="backtestPosition" class="form-select">
              <option value="1.0">全仓 (100%)</option>
              <option value="0.5">半仓 (50%)</option>
              <option value="0.3">三成 (30%)</option>
              <option value="0.2">两成 (20%)</option>
            </select>
          </div>
          <div class="form-group">
            <label class="form-label">止损</label>
            <select id="backtestStopLoss" class="form-select">
              <option value="">不限</option>
              <option value="-0.05">-5%</option>
              <option value="-0.08" selected>-8%</option>
              <option value="-0.10">-10%</option>
            </select>
          </div>
          <div class="form-group">
            <label class="form-label">止盈</label>
            <select id="backtestTakeProfit" class="form-select">
              <option value="">不限</option>
              <option value="0.10">+10%</option>
              <option value="0.15" selected>+15%</option>
              <option value="0.20">+20%</option>
            </select>
          </div>
        </div>
        <div style="display:flex;gap:8px;margin-top:8px">
          <button class="btn btn-primary" onclick="runSingleBacktest()">▶ 运行单股票回测</button>
        </div>
      </div>
    </div>

    <!-- 全市场模式 -->
    <div id="marketModePanel" style="display:none">
      <div class="card" style="margin-bottom:20px">
        <div class="card-title">🌐 全市场动态选股配置</div>
        <div style="background:rgba(139,92,246,0.1);padding:12px;border-radius:8px;margin-top:12px;margin-bottom:16px;font-size:13px;color:var(--text-secondary)">
          每日扫描全市场股票，根据策略信号动态调仓。适合验证选股策略的有效性。
        </div>
        <div class="grid-4" style="gap:12px">
          <div class="form-group">
            <label class="form-label">选择策略（可多选）</label>
            <div style="display:flex;flex-wrap:wrap;gap:8px" id="marketStrategies">
              ${STRATEGY_TYPES.map(s => `
                <label style="display:inline-flex;align-items:center;gap:4px;cursor:pointer;background:var(--bg-secondary);padding:6px 12px;border-radius:6px">
                  <input type="checkbox" value="${s.key}" checked> ${s.name}
                </label>
              `).join('')}
            </div>
          </div>
        </div>
        <div class="grid-4" style="gap:12px;margin-top:12px">
          <div class="form-group">
            <label class="form-label">开始日期</label>
            <input id="marketStart" class="form-input" type="date" value="2025-04-14">
          </div>
          <div class="form-group">
            <label class="form-label">结束日期</label>
            <input id="marketEnd" class="form-input" type="date" value="2026-04-01">
          </div>
          <div class="form-group">
            <label class="form-label">初始资金</label>
            <input id="marketCash" class="form-input" type="number" value="1000000">
          </div>
          <div class="form-group">
            <label class="form-label">最大持仓数</label>
            <input id="marketMaxPos" class="form-input" type="number" value="10" min="1" max="20">
          </div>
        </div>
        <div class="grid-4" style="gap:12px;margin-top:12px">
          <div class="form-group">
            <label class="form-label">单只仓位</label>
            <select id="marketPosPerStock" class="form-select">
              <option value="0.1">10%</option>
              <option value="0.2" selected>20%</option>
              <option value="0.3">30%</option>
              <option value="0.5">50%</option>
            </select>
          </div>
          <div class="form-group">
            <label class="form-label">止损</label>
            <select id="marketStopLoss" class="form-select">
              <option value="-0.05">-5%</option>
              <option value="-0.08" selected>-8%</option>
              <option value="-0.10">-10%</option>
            </select>
          </div>
          <div class="form-group">
            <label class="form-label">止盈</label>
            <select id="marketTakeProfit" class="form-select">
              <option value="0.10" selected>+10%</option>
              <option value="0.15">+15%</option>
              <option value="0.20">+20%</option>
              <option value="0.30">+30%</option>
            </select>
          </div>
          <div class="form-group">
            <label class="form-label">扫描股票数</label>
            <select id="marketStockLimit" class="form-select">
              <option value="100">100只</option>
              <option value="200" selected>200只</option>
              <option value="500">500只</option>
            </select>
          </div>
        </div>
        <div style="display:flex;gap:8px;margin-top:8px">
          <button class="btn btn-primary" onclick="runMarketBacktest()">🌐 运行全市场回测</button>
        </div>
      </div>
    </div>

    <!-- 回测结果 -->
    <div id="backtestResults"></div>
  `;
}

function toggleBacktestMode() {
  const mode = document.querySelector('input[name="backtestMode"]:checked').value;
  document.getElementById('singleModePanel').style.display = mode === 'single' ? 'block' : 'none';
  document.getElementById('marketModePanel').style.display = mode === 'market' ? 'block' : 'none';
}

async function runSingleBacktest() {
  const params = {
    mode: 'single',
    strategy: document.getElementById('backtestStrategy').value,
    ts_code: document.getElementById('backtestCode').value,
    start_date: document.getElementById('backtestStart').value.replace(/-/g, ''),
    end_date: document.getElementById('backtestEnd').value.replace(/-/g, ''),
    initial_cash: parseFloat(document.getElementById('backtestCash').value),
    position_ratio: parseFloat(document.getElementById('backtestPosition').value),
    stop_loss: document.getElementById('backtestStopLoss').value || null,
    take_profit: document.getElementById('backtestTakeProfit').value || null,
  };

  showToast('正在运行单股票回测...', 'info');
  const result = await API.runBacktest(params);

  if (result && !result.error) {
    backtestResults.push(result);
    renderSingleResult(result);
    showToast('回测完成！', 'success');
  } else {
    showToast(result?.error || '回测失败，请检查后端服务', 'error');
  }
}

async function runMarketBacktest() {
  const strategyCheckboxes = document.querySelectorAll('#marketStrategies input:checked');
  const strategies = Array.from(strategyCheckboxes).map(cb => cb.value);
  
  if (strategies.length === 0) {
    showToast('请至少选择一个策略', 'error');
    return;
  }

  const params = {
    mode: 'market',
    strategies: strategies,
    start_date: document.getElementById('marketStart').value.replace(/-/g, ''),
    end_date: document.getElementById('marketEnd').value.replace(/-/g, ''),
    initial_cash: parseFloat(document.getElementById('marketCash').value),
    max_positions: parseInt(document.getElementById('marketMaxPos').value),
    position_per_stock: parseFloat(document.getElementById('marketPosPerStock').value),
    stop_loss_pct: parseFloat(document.getElementById('marketStopLoss').value),
    take_profit_pct: parseFloat(document.getElementById('marketTakeProfit').value),
    stock_limit: parseInt(document.getElementById('marketStockLimit').value),
  };

  showToast('正在运行全市场动态回测（需较长时间）...', 'info');
  const result = await API.runBacktest(params);

  if (result && !result.error) {
    backtestResults.push(result);
    renderMarketResult(result);
    showToast('全市场回测完成！', 'success');
  } else {
    showToast(result?.error || '回测失败，请检查后端服务', 'error');
  }
}

function renderSingleResult(result) {
  const container = document.getElementById('backtestResults');
  const pnl = result.total_return || 0;
  const annual = result.annual_return || 0;
  const trades = result.trades || [];
  
  const tradesHtml = trades.length > 0 ? `
    <div class="card" style="margin-top:16px">
      <div class="card-title">📋 交割单</div>
      <table class="data-table" style="margin-top:12px;font-size:13px">
        <thead>
          <tr>
            <th>日期</th>
            <th>方向</th>
            <th>价格</th>
            <th>数量</th>
            <th>金额</th>
            <th>手续费</th>
            <th>盈亏</th>
            <th>信号</th>
          </tr>
        </thead>
        <tbody>
          ${trades.map(t => {
            const isBuy = t.direction === 'buy';
            const profit = t.profit || 0;
            return `
              <tr>
                <td>${t.date || '-'}</td>
                <td><span class="tag ${isBuy ? 'tag-green' : 'tag-red'}">${isBuy ? '买入' : '卖出'}</span></td>
                <td>${(t.price || 0).toFixed(2)}</td>
                <td>${formatNumber(t.volume || 0)}</td>
                <td>¥${formatNumber(t.amount || 0)}</td>
                <td style="color:#94A3B8">¥${(t.commission || 0).toFixed(2)}</td>
                <td class="${profit >= 0 ? 'positive' : 'negative'}">${isBuy ? '-' : (profit >= 0 ? '+' : '')}${profit >= 0 ? profit.toFixed(2) : Math.abs(profit).toFixed(2)}</td>
                <td style="color:#94A3B8;font-size:12px">${t.signal || '-'}</td>
              </tr>
            `;
          }).join('')}
        </tbody>
      </table>
    </div>
  ` : '';

  container.innerHTML = `
    <div class="card" style="margin-bottom:16px">
      <div class="card-title">📊 单股票回测结果 — ${result.strategy_name || result.strategy}</div>
      <div class="grid-4" style="margin-top:12px">
        <div>
          <div class="card-title">总收益</div>
          <div class="stat-value ${pnl >= 0 ? 'positive' : 'negative'}">${pnl >= 0 ? '+' : ''}${pnl.toFixed(2)}%</div>
        </div>
        <div>
          <div class="card-title">年化收益</div>
          <div class="stat-value ${annual >= 0 ? 'positive' : 'negative'}">${annual >= 0 ? '+' : ''}${annual.toFixed(2)}%</div>
        </div>
        <div>
          <div class="card-title">最大回撤</div>
          <div class="stat-value negative">${(result.max_drawdown || 0).toFixed(2)}%</div>
        </div>
        <div>
          <div class="card-title">夏普比率</div>
          <div class="stat-value">${(result.sharpe_ratio || 0).toFixed(3)}</div>
        </div>
      </div>
      <div class="grid-4" style="margin-top:16px">
        <div><span class="card-title">胜率</span> <strong>${(result.win_rate || 0).toFixed(1)}%</strong></div>
        <div><span class="card-title">盈亏比</span> <strong>${(result.profit_loss_ratio || 0).toFixed(2)}</strong></div>
        <div><span class="card-title">交易次数</span> <strong>${result.total_trades || 0}</strong></div>
        <div><span class="card-title">最终资产</span> <strong>¥${formatNumber(result.final_value || 0)}</strong></div>
      </div>
    </div>
    ${tradesHtml}
  `;
}

function renderMarketResult(result) {
  const container = document.getElementById('backtestResults');
  const pnl = result.total_return || 0;
  const annual = result.annual_return || 0;
  const trades = result.trades || [];
  
  const tradesHtml = trades.length > 0 ? `
    <div class="card" style="margin-top:16px">
      <div class="card-title">📋 交割单（共 ${trades.length} 笔）</div>
      <div style="max-height:400px;overflow-y:auto">
        <table class="data-table" style="margin-top:12px;font-size:12px">
          <thead>
            <tr>
              <th>日期</th>
              <th>方向</th>
              <th>代码</th>
              <th>价格</th>
              <th>数量</th>
              <th>金额</th>
              <th>手续费</th>
              <th>盈亏</th>
              <th>信号</th>
            </tr>
          </thead>
          <tbody>
            ${trades.map(t => {
              const isBuy = t.direction === 'buy';
              const profit = t.profit || 0;
              return `
                <tr>
                  <td>${t.date || '-'}</td>
                  <td><span class="tag ${isBuy ? 'tag-green' : 'tag-red'}">${isBuy ? '买入' : '卖出'}</span></td>
                  <td><code>${t.ts_code || '-'}</code></td>
                  <td>${(t.price || 0).toFixed(2)}</td>
                  <td>${formatNumber(t.volume || 0)}</td>
                  <td>¥${formatNumber(t.amount || 0)}</td>
                  <td style="color:#94A3B8">¥${(t.commission || 0).toFixed(2)}</td>
                  <td class="${profit >= 0 ? 'positive' : 'negative'}">${isBuy ? '-' : (profit >= 0 ? '+' : '')}${profit >= 0 ? profit.toFixed(2) : Math.abs(profit).toFixed(2)}</td>
                  <td style="color:#94A3B8;font-size:11px">${t.signal || '-'}</td>
                </tr>
              `;
            }).join('')}
          </tbody>
        </table>
      </div>
    </div>
  ` : '';

  container.innerHTML = `
    <div class="card" style="margin-bottom:16px">
      <div class="card-title">🌐 全市场动态选股结果 — ${result.strategy_name || ''}</div>
      <div class="grid-4" style="margin-top:12px">
        <div>
          <div class="card-title">总收益</div>
          <div class="stat-value ${pnl >= 0 ? 'positive' : 'negative'}">${pnl >= 0 ? '+' : ''}${pnl.toFixed(2)}%</div>
        </div>
        <div>
          <div class="card-title">年化收益</div>
          <div class="stat-value ${annual >= 0 ? 'positive' : 'negative'}">${annual >= 0 ? '+' : ''}${annual.toFixed(2)}%</div>
        </div>
        <div>
          <div class="card-title">最大回撤</div>
          <div class="stat-value negative">${(result.max_drawdown || 0).toFixed(2)}%</div>
        </div>
        <div>
          <div class="card-title">夏普比率</div>
          <div class="stat-value">${(result.sharpe_ratio || 0).toFixed(3)}</div>
        </div>
      </div>
      <div class="grid-4" style="margin-top:16px">
        <div><span class="card-title">胜率</span> <strong>${(result.win_rate || 0).toFixed(1)}%</strong></div>
        <div><span class="card-title">盈亏比</span> <strong>${(result.profit_loss_ratio || 0).toFixed(2)}</strong></div>
        <div><span class="card-title">交易次数</span> <strong>${result.total_trades || 0}</strong></div>
        <div><span class="card-title">最终资产</span> <strong>¥${formatNumber(result.final_value || 0)}</strong></div>
      </div>
      <div class="grid-2" style="margin-top:16px;padding-top:16px;border-top:1px solid var(--border-color)">
        <div><span class="card-title">平均持仓</span> <strong>${result.avg_positions || 0} 只</strong></div>
        <div><span class="card-title">最大持仓</span> <strong>${result.max_positions || 0} 只</strong></div>
      </div>
    </div>
    ${tradesHtml}
  `;
}

async function runCompare() {
  const tsCode = document.getElementById('backtestCode').value;
  const startDate = document.getElementById('backtestStart').value.replace(/-/g, '');
  const endDate = document.getElementById('backtestEnd').value.replace(/-/g, '');

  showToast('正在运行全策略对比...', 'info');
  const results = [];

  for (const s of STRATEGY_TYPES) {
    const result = await API.runBacktest({
      strategy: s.key,
      ts_code: tsCode,
      start_date: startDate,
      end_date: endDate,
    });
    if (result && !result.error) {
      results.push({ ...result, strategy_key: s.key, strategy_name: s.name });
    }
  }

  if (results.length > 0) {
    renderCompareResults(results, tsCode);
    showToast(`完成 ${results.length} 个策略对比`, 'success');
  } else {
    showToast('对比失败，请检查后端服务', 'error');
  }
}

function renderCompareResults(results, tsCode) {
  const container = document.getElementById('backtestResults');
  const sorted = [...results].sort((a, b) => (b.total_return || 0) - (a.total_return || 0));

  container.innerHTML = `
    <div class="card" style="margin-bottom:16px">
      <div class="card-title">策略对比 — ${tsCode}</div>
      <table class="data-table" style="margin-top:12px">
        <thead>
          <tr>
            <th>排名</th><th>策略</th><th>总收益</th><th>年化</th>
            <th>最大回撤</th><th>夏普</th><th>胜率</th><th>交易数</th>
          </tr>
        </thead>
        <tbody>
          ${sorted.map((r, i) => `
            <tr>
              <td>${i + 1}</td>
              <td><strong>${r.strategy_name}</strong></td>
              <td class="stat-value" style="font-size:14px;color:${(r.total_return||0)>=0?'var(--color-up)':'var(--color-down)'}">
                ${(r.total_return || 0).toFixed(2)}%
              </td>
              <td>${(r.annual_return || 0).toFixed(2)}%</td>
              <td style="color:var(--color-down)">${(r.max_drawdown || 0).toFixed(2)}%</td>
              <td>${(r.sharpe_ratio || 0).toFixed(3)}</td>
              <td>${(r.win_rate || 0).toFixed(1)}%</td>
              <td>${r.total_trades || 0}</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    </div>
    <div class="card">
      <div class="card-title">收益对比图</div>
      <canvas id="compareChart" height="250"></canvas>
    </div>
  `;

  const ctx = document.getElementById('compareChart');
  if (ctx) {
    new Chart(ctx, {
      type: 'bar',
      data: {
        labels: sorted.map(r => r.strategy_name),
        datasets: [{
          label: '总收益率 (%)',
          data: sorted.map(r => r.total_return || 0),
          backgroundColor: sorted.map(r => (r.total_return || 0) >= 0 ? '#22C55E' : '#EF4444'),
          borderRadius: 6,
        }],
      },
      options: {
        responsive: true,
        plugins: { legend: { display: false } },
        scales: { y: { grid: { color: '#f1f5f9' } } },
      },
    });
  }
}