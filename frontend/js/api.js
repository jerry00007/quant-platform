/**
 * QuantWeave API 客户端
 * 统一管理所有后端 API 调用
 */
const API = {
  BASE: 'http://localhost:8000/api/v1',

  async request(path, options = {}) {
    const url = `${this.BASE}${path}`;
    try {
      const resp = await fetch(url, {
        headers: { 'Content-Type': 'application/json', ...options.headers },
        ...options,
      });
      if (!resp.ok) throw new Error(`API ${resp.status}: ${resp.statusText}`);
      return await resp.json();
    } catch (err) {
      console.warn(`API请求失败: ${path}`, err);
      return null;
    }
  },

  // ========== 仪表盘 ==========
  async getDashboard() {
    return this.request('/system/dashboard');
  },

  // ========== 策略 ==========
  async getStrategies() {
    return this.request('/strategies');
  },
  async createStrategy(data) {
    return this.request('/strategies', { method: 'POST', body: JSON.stringify(data) });
  },
  async updateStrategy(id, data) {
    return this.request(`/strategies/${id}`, { method: 'PUT', body: JSON.stringify(data) });
  },
  async deleteStrategy(id) {
    return this.request(`/strategies/${id}`, { method: 'DELETE' });
  },
  async getStrategyTypes() {
    return this.request('/strategies/types');
  },

  // ========== 回测 ==========
  async runBacktest(data) {
    return this.request('/backtest/run', { method: 'POST', body: JSON.stringify(data) });
  },
  async getBacktestHistory() {
    return this.request('/backtest/results');
  },
  async getBacktestResult(id) {
    return this.request(`/backtest/results?strategy_id=${id}`);
  },

  // ========== 行情 ==========
  async getRealtimeQuotes(codes) {
    return this.request(`/data/realtime?codes=${codes.join(',')}`);
  },
  async getStockList() {
    return this.request('/data/stocks');
  },

  // ========== 自选股 / 关注列表 ==========
  async getWatchlist(group = null) {
    const query = group ? `?group=${encodeURIComponent(group)}` : '';
    return this.request(`/screening/watchlist${query}`);
  },
  async addToWatchlist(tsCode, name = '', assetType = 'stock', group = '默认', notes = '') {
    const params = new URLSearchParams({ ts_code: tsCode, name, asset_type: assetType, group, notes });
    return this.request(`/screening/watchlist?${params.toString()}`, { method: 'POST' });
  },
  async removeFromWatchlist(tsCode) {
    return this.request(`/screening/watchlist/${tsCode}`, { method: 'DELETE' });
  },

  // ========== 风控 ==========
  async getRiskAlerts() {
    return this.request('/risk/alerts');
  },
  async getRiskSummary() {
    return this.request('/risk/dashboard');
  },

  // ========== 系统 ==========
  async getHealth() {
    return this.request('/system/health');
  },

  // ========== 智能选股 ==========
  async scanMarket(preset = "all", strategies = null, stocks = null, days = 120, top_n = 20) {
    let params = [`preset=${preset}`, `days=${days}`, `top_n=${top_n}`];
    if (strategies) params.push(`strategies=${strategies}`);
    if (stocks) params.push(`stocks=${stocks}`);
    return this.request(`/screening/scan?${params.join('&')}`);
  },

  async analyzeStock(ts_code, days = 250) {
    return this.request(`/screening/analyze/${ts_code}?days=${days}`);
  },

  async getScreeningPresets() {
    return this.request('/screening/presets');
  },

  // ========== 每日信号 ==========
  async getDailySignals(stocks = null, strategies = null) {
    let params = [];
    if (stocks) params.push(`stocks=${stocks}`);
    if (strategies) params.push(`strategies=${strategies}`);
    const query = params.length ? `?${params.join('&')}` : '';
    return this.request(`/screening/signals${query}`);
  },

  async getMorningBrief(stocks = null) {
    let params = stocks ? `?stocks=${stocks}` : '';
    return this.request(`/screening/morning-brief${params}`);
  },

  // ========== ETF ==========
  async getETFList(keyword = null, page = 1, size = 20) {
    let params = [`page=${page}`, `size=${size}`];
    if (keyword) params.push(`keyword=${encodeURIComponent(keyword)}`);
    return this.request(`/screening/etf/list?${params.join('&')}`);
  },

  async syncETFList() {
    return this.request('/screening/etf/sync', { method: 'POST' });
  },

  async getETFDaily(ts_code, start_date, end_date) {
    return this.request(`/screening/etf/daily/${ts_code}?start_date=${start_date}&end_date=${end_date}`);
  },

  // ========== 数据中心 ==========
  async syncStockList() {
    return this.request('/data/stocks/sync', { method: 'POST' });
  },
  async getStocks(keyword = null, page = 1, size = 20) {
    let params = [`page=${page}`, `size=${size}`];
    if (keyword) params.push(`keyword=${encodeURIComponent(keyword)}`);
    return this.request(`/data/stocks?${params.join('&')}`);
  },
  async getStockDaily(tsCode, startDate, endDate) {
    return this.request(`/data/daily/${tsCode}?start_date=${startDate}&end_date=${endDate}`);
  },
  async getRealtime(codes) {
    return this.request(`/data/realtime?codes=${codes}`);
  },
  async batchSyncDaily(tsCodes, startDate, endDate) {
    return this.request('/data/batch-sync', { 
      method: 'POST', 
      body: JSON.stringify({ ts_codes: tsCodes, start_date: startDate, end_date: endDate }) 
    });
  },
  async syncAllDaily(startDate, endDate, limit = 50) {
    return this.request(`/data/sync-all-daily?start_date=${startDate}&end_date=${endDate}&limit=${limit}`, { method: 'POST' });
  },
  async getDataStatus() {
    return this.request('/data/status');
  },

  // ========== 持仓管理 ==========
  async getPositions(accountName = 'main') {
    return this.request(`/portfolio/positions?account_name=${accountName}`);
  },
  async createPosition(data) {
    return this.request('/portfolio/positions', { method: 'POST', body: JSON.stringify(data) });
  },
  async updatePositionPrice(positionId, currentPrice) {
    return this.request(`/portfolio/positions/${positionId}`, { method: 'PUT', body: JSON.stringify({ current_price: currentPrice }) });
  },
  async closePosition(positionId, data) {
    return this.request(`/portfolio/positions/${positionId}/close`, { method: 'POST', body: JSON.stringify(data) });
  },
  async syncPositions(accountName = 'main') {
    return this.request(`/portfolio/sync?account_name=${accountName}`, { method: 'POST' });
  },
  async getAccountInfo(accountName = 'main') {
    return this.request(`/portfolio/account/${accountName}`);
  },
  async depositCash(data) {
    return this.request('/portfolio/deposit', { method: 'POST', body: JSON.stringify(data) });
  },
  async withdrawCash(data) {
    return this.request('/portfolio/withdraw', { method: 'POST', body: JSON.stringify(data) });
  },
  async getTransactions(accountName = 'main', limit = 100, offset = 0) {
    return this.request(`/portfolio/transactions?account_name=${accountName}&limit=${limit}&offset=${offset}`);
  },
  async getPortfolioHealth() {
    return this.request('/portfolio/health');
  },
};
