/**
 * QuantWeave 实时行情页面
 */
function renderMarket() {
  const main = document.getElementById('mainContent');
  main.innerHTML = `
    <div class="page-header">
      <h2>📈 实时行情</h2>
      <p>查看A股实时行情数据</p>
    </div>
    <div id="marketContent"><div class="loading"><div class="spinner"></div>加载中...</div></div>
  `;
  loadMarketData();
}

async function loadMarketData() {
  const container = document.getElementById('marketContent');
  const watchlist = ['000001.SZ', '600519.SH', '000858.SZ', '601318.SH', '600036.SH'];

  const data = await API.getRealtimeQuotes(watchlist);
  const items = data?.items || [];

  if (items.length > 0) {
    container.innerHTML = `
      <table class="data-table">
        <thead>
          <tr><th>代码</th><th>名称</th><th>最新价</th><th>涨跌幅</th><th>成交量</th><th>成交额</th></tr>
        </thead>
        <tbody>
          ${items.map(s => `
            <tr>
              <td><strong>${s.ts_code}</strong></td>
              <td>${s.name || '-'}</td>
              <td style="font-family:var(--font-mono);font-weight:600">¥${(s.price || 0).toFixed(2)}</td>
              <td style="color:${(s.change_pct || 0) >= 0 ? 'var(--color-up)' : 'var(--color-down)'};font-weight:600">
                ${(s.change_pct || 0) >= 0 ? '+' : ''}${(s.change_pct || 0).toFixed(2)}%
              </td>
              <td style="font-family:var(--font-mono)">${formatNumber(s.vol || 0)}</td>
              <td style="font-family:var(--font-mono)">${formatNumber(s.amount || 0)}</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    `;
  } else {
    container.innerHTML = `
      <div class="card" style="text-align:center;padding:40px">
        <p style="color:var(--text-muted);margin-bottom:16px">📡 后端服务未启动</p>
        <p style="font-size:13px;color:var(--text-muted)">关注列表：${watchlist.join(', ')}</p>
        <button class="btn btn-outline" style="margin-top:16px" onclick="loadMarketData()">🔄 重新加载</button>
      </div>
    `;
  }
}
