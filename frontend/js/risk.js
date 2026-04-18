/**
 * QuantWeave 风控中心 v2.0
 * 功能：持仓排雷扫描、6维度风控详情、告警记录
 */

let riskScanData = null;

async function renderRisk() {
  const main = document.getElementById('mainContent');
  main.innerHTML = `
    <div class="page-header">
      <h2>🛡️ 风控中心</h2>
      <p>6维度风控排雷：ST检测 / 业绩预告 / 财报窗口 / 大股东减持 / 连续亏损 / 高负债率</p>
    </div>

    <!-- 排雷扫描入口 -->
    <div class="card" style="margin-bottom:20px;border:2px solid var(--color-warning)">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
        <div class="card-title" style="margin-bottom:0">🔍 持仓排雷扫描</div>
        <div style="display:flex;gap:8px">
          <button id="riskScanBtn" class="btn btn-primary" onclick="runRiskScan(false)">🛡️ 扫描持仓</button>
          <button class="btn btn-outline" onclick="runRiskScan(true)">🔄 强制刷新</button>
        </div>
      </div>
      <p style="font-size:13px;color:var(--text-muted)">
        对当前全部持仓执行6维度风控排雷检查，自动识别ST/业绩雷/减持/亏损/高负债等风险，每日缓存
      </p>
    </div>

    <!-- 全市场风控快照入口 -->
    <div class="card" style="margin-bottom:20px;border:2px solid var(--primary)">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
        <div class="card-title" style="margin-bottom:0">🌐 全市场风控快照</div>
        <div style="display:flex;gap:8px">
          <button id="riskSnapshotBtn" class="btn btn-primary" onclick="runRiskSnapshot(false)">📸 执行快照</button>
          <button class="btn btn-outline" onclick="runRiskSnapshot(true)">🔄 强制重扫</button>
        </div>
      </div>
      <p style="font-size:13px;color:var(--text-muted)">
        对全市场活跃股票执行6维度风控扫描（批量处理），结果缓存到数据库，每日自动执行。预计5-10分钟完成
      </p>
    </div>

    <!-- 快照结果 -->
    <div id="riskSnapshotResult"></div>

    <!-- 排雷结果 -->
    <div id="riskScanResult"></div>

    <!-- 风控参数 -->
    <div class="grid-3" style="margin-bottom:20px">
      <div class="card">
        <div class="card-title">单只最大仓位</div>
        <div class="stat-value">30%</div>
        <div style="font-size:12px;color:var(--text-muted)">MAX_POSITION_RATIO</div>
      </div>
      <div class="card">
        <div class="card-title">单日最大亏损</div>
        <div class="stat-value">5%</div>
        <div style="font-size:12px;color:var(--text-muted)">MAX_LOSS_RATIO</div>
      </div>
      <div class="card">
        <div class="card-title">止损线</div>
        <div class="stat-value" style="color:var(--danger)">8%</div>
        <div style="font-size:12px;color:var(--text-muted)">STOP_LOSS_RATIO</div>
      </div>
    </div>

    <!-- 6维度说明 -->
    <details class="card" style="margin-bottom:20px">
      <summary style="cursor:pointer;font-weight:600;color:var(--text-secondary)">
        📖 风控排雷6维度说明
      </summary>
      <div style="margin-top:16px">
        <table class="data-table">
          <thead>
            <tr><th>维度</th><th>检查内容</th><th>数据源</th><th>级别</th></tr>
          </thead>
          <tbody>
            <tr>
              <td><strong>🚫 ST检测</strong></td>
              <td>股票名称含ST/*ST</td>
              <td>本地数据库</td>
              <td><span class="tag tag-red">硬排除</span></td>
            </tr>
            <tr>
              <td><strong>📉 业绩预告</strong></td>
              <td>首亏/预减/续亏/增亏</td>
              <td>Tushare forecast</td>
              <td><span class="tag tag-red">硬排除</span></td>
            </tr>
            <tr>
              <td><strong>📅 财报窗口</strong></td>
              <td>未来7天有财报披露</td>
              <td>Tushare disclosure_date</td>
              <td><span class="tag tag-yellow">软警告</span></td>
            </tr>
            <tr>
              <td><strong>💸 大股东减持</strong></td>
              <td>近30天减持>1%</td>
              <td>Tushare stk_holdertrade</td>
              <td><span class="tag tag-red">硬排除</span></td>
            </tr>
            <tr>
              <td><strong>📉 连续亏损</strong></td>
              <td>连续2季净利润为负</td>
              <td>Tushare income</td>
              <td><span class="tag tag-red">硬排除</span></td>
            </tr>
            <tr>
              <td><strong>🏦 高负债率</strong></td>
              <td>资产负债率>80%（非金融）</td>
              <td>Tushare fina_indicator</td>
              <td><span class="tag tag-yellow">软警告</span></td>
            </tr>
          </tbody>
        </table>
      </div>
    </details>

    <!-- 告警记录 -->
    <div class="card">
      <div class="card-title">📋 告警记录</div>
      <div id="alertsContent"><div class="loading"><div class="spinner"></div>加载中...</div></div>
    </div>
  `;

  loadAlerts();
  // 自动加载缓存的风控数据
  loadCachedRiskScan();
}


// ========== 排雷扫描 ==========

async function loadCachedRiskScan() {
  const container = document.getElementById('riskScanResult');
  if (!container) return;

  container.innerHTML = '<div class="loading" style="padding:20px;text-align:center"><div class="spinner" style="margin:0 auto 12px"></div><div>检查缓存数据...</div></div>';

  try {
    const data = await API.scanPortfolioRisks(false);
    if (data && data.total > 0) {
      riskScanData = data;
      renderRiskScanResult(data, container);
    } else {
      container.innerHTML = `
        <div style="text-align:center;padding:30px;color:var(--text-muted)">
          <div style="font-size:36px;margin-bottom:12px">🔍</div>
          <p>暂无排雷数据，点击「扫描持仓」开始检查</p>
          <p style="font-size:12px;margin-top:4px">${data?.message || ''}</p>
        </div>
      `;
    }
  } catch (err) {
    container.innerHTML = `
      <div style="text-align:center;padding:30px;color:var(--text-muted)">
        <div style="font-size:36px;margin-bottom:12px">🔍</div>
        <p>暂无排雷数据，点击「扫描持仓」开始检查</p>
      </div>
    `;
  }
}

async function runRiskScan(force = false) {
  const btn = document.getElementById('riskScanBtn');
  const container = document.getElementById('riskScanResult');
  if (btn) { btn.disabled = true; btn.innerHTML = '⏳ 扫描中...'; }

  container.innerHTML = `
    <div class="loading" style="padding:40px;text-align:center">
      <div class="spinner" style="margin:0 auto 12px"></div>
      <div>正在执行6维度风控排雷扫描...<br>
      <span style="font-size:12px;color:var(--text-muted)">需要调用Tushare API查询业绩预告/财报窗口/减持/财务数据，预计1-3分钟</span></div>
    </div>
  `;

  try {
    const data = await API.scanPortfolioRisks(force);
    if (data && data.error) {
      container.innerHTML = `<div style="text-align:center;padding:40px;color:#EF4444"><strong>扫描失败</strong><p style="margin-top:8px">${data.error || '未知错误'}</p></div>`;
    } else if (data) {
      riskScanData = data;
      renderRiskScanResult(data, container);
    }
  } catch (err) {
    container.innerHTML = `<div style="text-align:center;padding:40px;color:#EF4444"><strong>扫描失败</strong><p style="margin-top:8px">${err.message || '未知错误'}</p></div>`;
  }

  if (btn) { btn.disabled = false; btn.innerHTML = '🛡️ 扫描持仓'; }
}

function renderRiskScanResult(data, container) {
  const { total, blocked_count, warning_count, safe_count, data: riskData } = data;

  // 按风险级别排序：blocked > warning > safe
  const entries = Object.entries(riskData || {}).sort((a, b) => {
    const getLevel = (v) => {
      const rl = v.risk_level || 'safe';
      return (rl === 'blocked' || rl === 'block') ? 0 : (rl === 'warning' ? 1 : 2);
    };
    return getLevel(a[1]) - getLevel(b[1]);
  });

  let html = `
    <div class="card" style="margin-bottom:20px">
      <div class="card-header" style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
        <div class="card-title" style="margin-bottom:0">📊 排雷扫描结果</div>
        <div style="font-size:13px;color:var(--text-muted)">
          共 ${total} 只持仓 | 
          <span style="color:#EF4444">🚫 排除 ${blocked_count}</span> | 
          <span style="color:var(--color-warning)">⚠️ 警告 ${warning_count}</span> | 
          <span style="color:#22C55E">🛡️ 安全 ${safe_count}</span>
        </div>
      </div>
  `;

  if (entries.length === 0) {
    html += `<div style="text-align:center;padding:30px;color:var(--text-muted)">暂无持仓数据</div>`;
  } else {
    // 概览统计条
    const safePct = total > 0 ? Math.round(safe_count / total * 100) : 0;
    const warnPct = total > 0 ? Math.round(warning_count / total * 100) : 0;
    const blockPct = total > 0 ? Math.round(blocked_count / total * 100) : 0;

    html += `
      <div style="display:flex;height:24px;border-radius:12px;overflow:hidden;margin-bottom:20px;background:var(--surface)">
        ${safePct > 0 ? `<div style="width:${safePct}%;background:rgba(34,197,94,0.6);display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:600;color:white">${safe_count}安全</div>` : ''}
        ${warnPct > 0 ? `<div style="width:${warnPct}%;background:rgba(245,158,11,0.6);display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:600;color:white">${warning_count}警告</div>` : ''}
        ${blockPct > 0 ? `<div style="width:${blockPct}%;background:rgba(239,68,68,0.6);display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:600;color:white">${blocked_count}排除</div>` : ''}
      </div>
    `;

    // 持仓风控卡片
    html += `<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:12px">`;

    for (const [tsCode, info] of entries) {
      const level = info.risk_level || 'safe';
      const isBlocked = (level === 'blocked' || level === 'block');
      const flags = info.flags || [];
      const summary = info.summary || '';
      const name = info.name || '';
      const raw = info.raw_data || {};

      // 卡片边框颜色
      let borderColor, levelIcon, levelLabel, levelBg;
      if (isBlocked) {
        borderColor = 'rgba(239,68,68,0.5)';
        levelIcon = '🚫';
        levelLabel = '有风险';
        levelBg = 'rgba(239,68,68,0.15)';
      } else if (level === 'warning') {
        borderColor = 'rgba(245,158,11,0.5)';
        levelIcon = '⚠️';
        levelLabel = '需关注';
        levelBg = 'rgba(245,158,11,0.15)';
      } else {
        borderColor = 'rgba(34,197,94,0.3)';
        levelIcon = '🛡️';
        levelLabel = '安全';
        levelBg = 'rgba(34,197,94,0.1)';
      }

      html += `
        <div style="padding:16px;background:var(--surface);border-radius:var(--radius);border:1px solid ${borderColor}">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
            <div>
              <strong style="font-size:15px">${name || tsCode}</strong>
              <code style="font-family:var(--font-mono);font-size:12px;color:var(--text-muted);margin-left:6px">${tsCode}</code>
            </div>
            <span style="padding:3px 10px;border-radius:4px;font-size:12px;font-weight:600;background:${levelBg};color:${isBlocked ? '#EF4444' : level === 'warning' ? 'var(--color-warning)' : '#22C55E'}">${levelIcon} ${levelLabel}</span>
          </div>
      `;

      // 风险标记详情
      if (flags.length > 0) {
        html += `<div style="margin-bottom:8px">`;
        for (const flag of flags) {
          const flagType = flag.type || flag.code || '';
          const flagMsg = flag.msg || flag.message || flag.toString();
          const flagLevel = flag.level || 'warning';
          const isCrit = (flagLevel === 'critical' || flagLevel === 'block' || flagLevel === 'blocked');
          const flagColor = isCrit ? '#EF4444' : 'var(--color-warning)';
          html += `<div style="display:flex;align-items:flex-start;gap:6px;padding:4px 0;font-size:12px">
            <span style="color:${flagColor};flex-shrink:0">${isCrit ? '🚫' : '⚠️'}</span>
            <span style="color:var(--text-secondary)"><strong>${flagType}</strong>: ${escapeHtml(flagMsg)}</span>
          </div>`;
        }
        html += `</div>`;
      } else {
        html += `<div style="font-size:12px;color:#22C55E;margin-bottom:8px">✅ 6维度检查全部通过</div>`;
      }

      // 摘要
      if (summary && level !== 'safe') {
        html += `<div style="padding:8px;background:${levelBg};border-radius:4px;font-size:12px;color:var(--text-secondary)">${escapeHtml(summary)}</div>`;
      }

      html += `</div>`;
    }

    html += `</div>`;
  }

  html += `</div>`;
  container.innerHTML = html;
}


// ========== 告警记录 ==========

async function loadAlerts() {
  const container = document.getElementById('alertsContent');
  if (!container) return;

  try {
    const data = await API.getRiskAlerts();
    const items = data?.items || [];
    if (items.length > 0) {
      container.innerHTML = `
        <table class="data-table">
          <thead><tr><th>时间</th><th>级别</th><th>类型</th><th>内容</th></tr></thead>
          <tbody>
            ${items.map(a => `
              <tr>
                <td>${a.created_at || '-'}</td>
                <td><span class="tag tag-${a.level === 'critical' ? 'red' : a.level === 'warning' ? 'yellow' : 'blue'}">${a.level || 'info'}</span></td>
                <td>${a.alert_type || '-'}</td>
                <td>${a.title || '-'}</td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      `;
    } else {
      container.innerHTML = `
        <div style="text-align:center;padding:30px;color:var(--text-muted)">
          ✅ 暂无告警记录
        </div>
      `;
    }
  } catch (err) {
    container.innerHTML = `<div style="text-align:center;padding:20px;color:var(--text-muted)">告警加载失败</div>`;
  }
}


// ========== 全市场风控快照 ==========

async function runRiskSnapshot(force = false) {
  const btn = document.getElementById('riskSnapshotBtn');
  const container = document.getElementById('riskSnapshotResult');
  if (!container) return;
  if (btn) { btn.disabled = true; btn.innerHTML = '⏳ 快照中...'; }

  container.innerHTML = `
    <div class="card" style="margin-bottom:20px">
      <div class="loading" style="padding:40px;text-align:center">
        <div class="spinner" style="margin:0 auto 12px"></div>
        <div>正在执行全市场风控快照...<br>
        <span style="font-size:12px;color:var(--text-muted)">批量扫描全市场活跃股票，预计5-10分钟</span></div>
      </div>
    </div>
  `;

  try {
    const data = await API.runRiskSnapshot(force);
    if (data && data.error) {
      container.innerHTML = `<div class="card" style="margin-bottom:20px"><div style="text-align:center;padding:40px;color:#EF4444"><strong>快照失败</strong><p style="margin-top:8px">${data.message || '未知错误'}</p></div></div>`;
    } else if (data) {
      renderSnapshotResult(data, container);
    }
  } catch (err) {
    container.innerHTML = `<div class="card" style="margin-bottom:20px"><div style="text-align:center;padding:40px;color:#EF4444"><strong>快照失败</strong><p style="margin-top:8px">${err.message || '未知错误'}</p></div></div>`;
  }

  if (btn) { btn.disabled = false; btn.innerHTML = '📸 执行快照'; }
}

function renderSnapshotResult(data, container) {
  const status = data.status || '';
  if (status === 'already_done') {
    container.innerHTML = `
      <div class="card" style="margin-bottom:20px">
        <div style="text-align:center;padding:30px;color:#22C55E">
          <div style="font-size:36px;margin-bottom:12px">✅</div>
          <p><strong>今日快照已完成</strong></p>
          <p style="font-size:13px;color:var(--text-muted)">${data.message || ''}</p>
          <p style="font-size:12px;color:var(--text-muted)">如需重新扫描，请点击「强制重扫」</p>
        </div>
      </div>
    `;
    return;
  }

  const total = data.total || 0;
  const blocked = data.blocked_count || 0;
  const warning = data.warning_count || 0;
  const safe = data.safe_count || 0;

  container.innerHTML = `
    <div class="card" style="margin-bottom:20px">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
        <div class="card-title" style="margin-bottom:0">📊 全市场风控快照结果</div>
        <div style="font-size:13px;color:var(--text-muted)">
          共 ${total} 只 | 
          <span style="color:#EF4444">🚫 排除 ${blocked}</span> | 
          <span style="color:var(--color-warning)">⚠️ 警告 ${warning}</span> | 
          <span style="color:#22C55E">🛡️ 安全 ${safe}</span>
        </div>
      </div>
      ${total > 0 ? `
        <div style="display:flex;height:24px;border-radius:12px;overflow:hidden;margin-bottom:16px;background:var(--surface)">
          ${safe > 0 ? `<div style="width:${Math.round(safe/total*100)}%;background:rgba(34,197,94,0.6);display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:600;color:white">${safe}安全</div>` : ''}
          ${warning > 0 ? `<div style="width:${Math.round(warning/total*100)}%;background:rgba(245,158,11,0.6);display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:600;color:white">${warning}警告</div>` : ''}
          ${blocked > 0 ? `<div style="width:${Math.round(blocked/total*100)}%;background:rgba(239,68,68,0.6);display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:600;color:white">${blocked}排除</div>` : ''}
        </div>
      ` : ''}
      <div style="text-align:center;padding:10px;font-size:13px;color:var(--text-muted)">
        ✅ 快照完成！风控数据已更新到数据库，选股和持仓扫描将使用最新风控结果
      </div>
    </div>
  `;
}
