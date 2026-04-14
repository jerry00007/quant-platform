/**
 * QuantWeave 系统设置页面
 */
function renderSettings() {
  const main = document.getElementById('mainContent');
  main.innerHTML = `
    <div class="page-header">
      <h2>⚙️ 系统设置</h2>
      <p>配置数据源、风控参数和通知</p>
    </div>
    <div class="grid-2">
      <div class="card">
        <div class="card-title">数据源配置</div>
        <div class="form-group" style="margin-top:12px">
          <label class="form-label">Tushare Token</label>
          <input class="form-input" type="password" value="***************" disabled>
          <small style="color:var(--text-muted)">已配置（从 .env 读取）</small>
        </div>
        <div class="form-group">
          <label class="form-label">备用数据源</label>
          <input class="form-input" value="AKShare（无需Token）" disabled>
        </div>
        <div class="form-group">
          <label class="form-label">数据缓存</label>
          <input class="form-input" value="本地 SQLite，有效期30天" disabled>
        </div>
      </div>
      <div class="card">
        <div class="card-title">风控参数</div>
        <div class="grid-2" style="margin-top:12px">
          <div class="form-group">
            <label class="form-label">单只最大仓位</label>
            <input class="form-input" type="number" value="0.3" step="0.1">
          </div>
          <div class="form-group">
            <label class="form-label">单日最大亏损</label>
            <input class="form-input" type="number" value="0.05" step="0.01">
          </div>
          <div class="form-group">
            <label class="form-label">止损线</label>
            <input class="form-input" type="number" value="0.08" step="0.01">
          </div>
          <div class="form-group">
            <label class="form-label">止盈线</label>
            <input class="form-input" type="number" value="0.15" step="0.01">
          </div>
        </div>
      </div>
    </div>
    <div class="card" style="margin-top:16px">
      <div class="card-title">系统信息</div>
      <div class="grid-4" style="margin-top:12px">
        <div><strong>版本</strong><br>QuantWeave v2.0</div>
        <div><strong>技术栈</strong><br>FastAPI + SQLAlchemy + Chart.js</div>
        <div><strong>数据源</strong><br>Tushare Pro + AKShare</div>
        <div><strong>策略数</strong><br>11种内置策略</div>
      </div>
    </div>
  `;
}
