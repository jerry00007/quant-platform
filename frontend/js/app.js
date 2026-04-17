/**
 * QuantWeave 主应用入口
 * 路由管理 + 全局工具函数
 */

let currentPage = 'dashboard';

// ========== 工具函数 ==========
function formatNumber(num) {
  if (num === null || num === undefined) return '0';
  return Number(num).toLocaleString('zh-CN', { maximumFractionDigits: 0 });
}

/**
 * HTML 转义（防 XSS）— 全局定义
 */
function escapeHtml(str) {
  if (!str) return '';
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function showToast(msg, type = 'info') {
  const container = document.getElementById('toastContainer');
  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.textContent = msg;
  container.appendChild(toast);
  setTimeout(() => toast.remove(), 3000);
}

// ========== 路由 ==========
function navigateTo(page) {
  // 页面离开时的清理
  if (currentPage === 'market' && page !== 'market') {
    if (typeof destroyMarket === 'function') destroyMarket();
  }

  currentPage = page;
  renderSidebar();
  const renderers = {
    dashboard: renderDashboard,
    'data-center': renderDataCenter,
    watchlist: renderWatchlist,
    portfolio: renderPortfolio,
    screening: renderScreening,
    signals: renderSignals,
    strategy: renderStrategy,
    backtest: renderBacktest,
    market: renderMarket,
    risk: renderRisk,
    settings: renderSettings,
  };
  const renderer = renderers[page];
  if (renderer) renderer();
}

// ========== 初始化 ==========
document.addEventListener('DOMContentLoaded', () => {
  renderSidebar();
  renderDashboard();
});
