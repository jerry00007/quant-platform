/**
 * QuantWeave 策略管理页面
 */

const STRATEGY_TYPES = [
  { key: 'dual_ma', name: '双均线交叉', type: '趋势', desc: '短均线上穿长均线买入，下穿卖出' },
  { key: 'bollinger', name: '布林带突破', type: '均值回归', desc: '价格突破上/下轨产生信号' },
  { key: 'rsi', name: 'RSI超买超卖', type: '均值回归', desc: 'RSI<25买入，RSI>80卖出（优化参数）' },
  { key: 'macd', name: 'MACD金叉死叉', type: '趋势', desc: 'DIF上穿DEA买入，下穿卖出' },
  { key: 'chip', name: '主力筹码趋向', type: '筹码', desc: '基于通达信ZLCMQ指标' },
  { key: 'enhanced_chip', name: '增强筹码策略', type: '筹码', desc: 'ZLCMQ+多因子+ATR动态风控' },
  { key: 'pullback_stable', name: '强势股回调企稳', type: '选股', desc: '5选3企稳条件+大盘过滤' },
  { key: 'vol_breakout', name: '爆量突破(锋芒)', type: '动量', desc: '低位横盘后爆量突破20日高点' },
  { key: 'first_yin', name: '龙头首阴反抽(锋芒)', type: '短线', desc: '连续涨停后首阴次日低吸博弈反抽' },
  { key: 'trend_ma', name: '均线趋势跟踪(锋芒)', type: '趋势', desc: '三阶段均线系统，多头排列起势' },
  { key: 'top_bottom', name: '顶底图策略', type: '顶底识别', desc: '通达信顶底图指标，识别超买超卖区域' },
];

function renderStrategy() {
  const main = document.getElementById('mainContent');
  main.innerHTML = `
    <div class="page-header" style="display:flex;justify-content:space-between;align-items:center">
      <div>
        <h2>🧠 策略管理</h2>
        <p>管理${STRATEGY_TYPES.length}种内置策略，创建和配置量化交易策略</p>
      </div>
      <button class="btn btn-primary" onclick="showCreateStrategy()">+ 新建策略</button>
    </div>
    <div id="strategyList"></div>
    <div id="strategyModal" style="display:none"></div>
  `;
  renderStrategyList();
}

function renderStrategyList() {
  const container = document.getElementById('strategyList');
  container.innerHTML = `
    <div class="grid-2" style="gap:16px">
      ${STRATEGY_TYPES.map(s => `
        <div class="card" style="cursor:pointer" onclick="showStrategyDetail('${s.key}')">
          <div style="display:flex;justify-content:space-between;align-items:start">
            <div>
              <h3 style="font-size:16px;font-weight:700;margin-bottom:4px">${s.name}</h3>
              <span class="tag tag-blue" style="margin-bottom:8px">${s.type}</span>
              <p style="color:var(--text-secondary);font-size:13px;margin-top:8px">${s.desc}</p>
            </div>
            <span class="tag tag-green">可用</span>
          </div>
          <div style="margin-top:12px;display:flex;gap:8px">
            <button class="btn btn-sm btn-outline" onclick="event.stopPropagation();quickBacktest('${s.key}')">
              🔬 快速回测
            </button>
            <button class="btn btn-sm btn-outline" onclick="event.stopPropagation();showParams('${s.key}')">
              📋 参数
            </button>
          </div>
        </div>
      `).join('')}
    </div>
  `;
}

function showStrategyDetail(key) {
  const s = STRATEGY_TYPES.find(x => x.key === key);
  if (!s) return;
  const modal = document.getElementById('strategyModal');
  modal.style.display = 'block';
  modal.innerHTML = `
    <div style="position:fixed;inset:0;background:rgba(0,0,0,0.3);z-index:50;display:flex;justify-content:center;align-items:center"
         onclick="this.parentElement.style.display='none'">
      <div class="card" style="width:500px;max-width:90vw" onclick="event.stopPropagation()">
        <h3 style="font-size:20px;font-weight:700;margin-bottom:12px">${s.name}</h3>
        <span class="tag tag-blue">${s.type}</span>
        <p style="color:var(--text-secondary);margin:16px 0">${s.desc}</p>
        <div style="display:flex;gap:8px;justify-content:flex-end">
          <button class="btn btn-outline" onclick="this.closest('#strategyModal').style.display='none'">关闭</button>
          <button class="btn btn-primary" onclick="quickBacktest('${s.key}')">🔬 回测</button>
        </div>
      </div>
    </div>
  `;
}

function showParams(key) {
  showStrategyDetail(key);
}

function quickBacktest(key) {
  document.getElementById('strategyModal').style.display = 'none';
  navigateTo('backtest');
  setTimeout(() => {
    const select = document.getElementById('backtestStrategy');
    if (select) select.value = key;
  }, 100);
}

function showCreateStrategy() {
  showToast('请选择一个策略类型进行配置', 'info');
}
