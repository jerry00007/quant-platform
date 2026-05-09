let articlePreviewData = null;
let articleHtmlContent = null;
let articleMdContent = null;
let articleActiveTab = 'html';
let articleHistoryOpen = false;

async function renderArticle() {
  const content = document.getElementById('mainContent');
  content.innerHTML = `
    <div class="page-header">
      <h2>📝 公众号文章</h2>
      <p class="page-subtitle">量化选股策略信号解读 · 自动生成合规脱敏文章</p>
    </div>

    <div id="articleSummary"></div>

    <div id="articlePreviewSection" style="display:none">
      <div class="article-tab-bar" id="articleTabBar">
        <button class="article-tab active" data-tab="html" onclick="articleSwitchTab('html')">HTML 预览</button>
        <button class="article-tab" data-tab="markdown" onclick="articleSwitchTab('markdown')">Markdown 预览</button>
      </div>
      <div class="article-preview-wrapper" id="articlePreviewWrapper"></div>
      <div class="article-actions" id="articleActions"></div>
    </div>

    <div class="article-history-section">
      <button class="btn btn-outline btn-sm" onclick="articleToggleHistory()" id="articleHistoryToggle">
        📂 历史记录 ▸
      </button>
      <div id="articleHistoryList" style="display:none"></div>
    </div>
  `;

  await loadArticlePreview();
  loadArticleHistory();
}

async function loadArticlePreview() {
  const container = document.getElementById('articleSummary');
  container.innerHTML = '<div class="spinner" style="margin:40px auto"></div>';

  const data = await API.getArticlePreview();
  if (!data || data.error) {
    container.innerHTML = renderNoDataCard(data?.message || '无法连接到后端服务');
    return;
  }

  articlePreviewData = data;
  container.innerHTML = renderSummaryCard(data);
}

function renderNoDataCard(msg) {
  return `
    <div class="card" style="text-align:center;padding:48px 24px">
      <div style="font-size:48px;margin-bottom:16px">📭</div>
      <p style="color:var(--text-secondary);font-size:16px;margin-bottom:12px">${escapeHtml(msg)}</p>
      <p style="color:var(--text-muted);font-size:13px">请先在 <a href="#" onclick="navigateTo('screening');return false" style="color:var(--color-warning)">智能选股</a> 页面执行一键选股</p>
    </div>
  `;
}

function renderSummaryCard(data) {
  const topStocks = data.top_stocks || [];
  const rankBadges = ['🥇', '🥈', '🥉'];
  const tagColors = ['tag-red', 'tag-green', 'tag-blue'];

  let stockListHtml = '';
  if (topStocks.length > 0) {
    stockListHtml = `
      <div class="article-top-stocks">
        ${topStocks.map((s, i) => `
          <div class="article-stock-item">
            <span class="article-rank-badge">${rankBadges[i] || (i + 1)}</span>
            <span class="article-stock-name">${escapeHtml(s.name || '***')}</span>
            <span class="tag ${tagColors[i] || 'tag-gray'}">${s.total_score ? s.total_score.toFixed(1) : '-'}分</span>
          </div>
        `).join('')}
      </div>
    `;
  }

  return `
    <div class="card">
      <div class="article-summary-grid">
        <div class="article-stat-item">
          <div class="article-stat-label">数据日期</div>
          <div class="article-stat-value">${escapeHtml(data.data_date || '-')}</div>
        </div>
        <div class="article-stat-item">
          <div class="article-stat-label">扫描股票数</div>
          <div class="article-stat-value">${formatNumber(data.total_stocks_scanned)}</div>
        </div>
        <div class="article-stat-item">
          <div class="article-stat-label">共振信号数</div>
          <div class="article-stat-value" style="color:var(--color-up)">${data.resonance_count || 0}</div>
        </div>
      </div>
      ${stockListHtml}
      <div style="text-align:right;margin-top:16px">
        <button class="btn btn-primary" onclick="generateArticle()" id="articleGenerateBtn">
          🔄 生成文章
        </button>
      </div>
    </div>
  `;
}

async function generateArticle() {
  const btn = document.getElementById('articleGenerateBtn');
  if (btn) { btn.disabled = true; btn.textContent = '⏳ 生成中...'; }

  const previewSection = document.getElementById('articlePreviewSection');
  const wrapper = document.getElementById('articlePreviewWrapper');
  const actionsBar = document.getElementById('articleActions');

  previewSection.style.display = 'block';
  wrapper.innerHTML = `
    <div style="text-align:center;padding:60px 20px">
      <div class="spinner" style="margin:0 auto 16px"></div>
      <p style="color:var(--text-secondary)">正在生成文章，请稍候...</p>
      <p style="color:var(--text-muted);font-size:12px;margin-top:8px">AI 撰写 + 排版约需 30-60 秒</p>
    </div>
  `;
  actionsBar.innerHTML = '';

  const result = await API.generateArticle();
  if (btn) { btn.disabled = false; btn.textContent = '🔄 生成文章'; }

  if (!result || result.error) {
    wrapper.innerHTML = `
      <div style="text-align:center;padding:40px">
        <div style="font-size:36px;margin-bottom:12px">❌</div>
        <p style="color:#EF4444">${escapeHtml(result?.message || '生成失败，请重试')}</p>
      </div>
    `;
    return;
  }

  articleHtmlContent = result.html_content || '';
  articleMdContent = result.md_content || '';
  articleActiveTab = 'html';
  renderPreviewContent();
  renderActionButtons();
}

function renderPreviewContent() {
  const wrapper = document.getElementById('articlePreviewWrapper');

  if (articleActiveTab === 'html') {
    wrapper.innerHTML = `
      <iframe id="articlePreviewFrame"
        style="width:100%;min-height:650px;border:none;border-radius:var(--radius);background:#fff;box-shadow:0 4px 24px rgba(0,0,0,0.3)"
        sandbox="allow-scripts allow-same-origin"
        srcdoc="${escapeAttr(articleHtmlContent)}">
      </iframe>
    `;
  } else {
    const escaped = escapeHtml(articleMdContent || '(无 Markdown 内容)');
    wrapper.innerHTML = `
      <div class="article-md-preview">
        <pre style="margin:0;white-space:pre-wrap;word-break:break-word;font-family:var(--font-mono);font-size:13px;line-height:1.7;color:var(--text-primary)">${escaped}</pre>
      </div>
    `;
  }

  updateTabBar();
}

function renderActionButtons() {
  const bar = document.getElementById('articleActions');
  bar.innerHTML = `
    <button class="btn btn-primary" onclick="copyArticleToClipboard()">📋 复制到公众号</button>
    <button class="btn btn-outline" onclick="downloadArticleHtml()">💾 下载 HTML</button>
    <button class="btn btn-outline" onclick="downloadArticleMd()">📄 下载 Markdown</button>
  `;
}

function articleSwitchTab(tab) {
  articleActiveTab = tab;
  renderPreviewContent();
}

function updateTabBar() {
  document.querySelectorAll('.article-tab').forEach(t => {
    t.classList.toggle('active', t.dataset.tab === articleActiveTab);
  });
}

async function copyArticleToClipboard() {
  const iframe = document.getElementById('articlePreviewFrame');
  if (!iframe || !iframe.contentDocument) {
    showToast('⚠️ 无法访问预览内容', 'error');
    return;
  }

  if (iframe.contentWindow.copyToEditor) {
    await iframe.contentWindow.copyToEditor();
    showToast('✅ 已复制到剪贴板，可粘贴到公众号编辑器', 'success');
    return;
  }

  try {
    const html = iframe.contentDocument.documentElement.outerHTML;
    await navigator.clipboard.write([
      new ClipboardItem({
        'text/html': new Blob([html], { type: 'text/html' }),
        'text/plain': new Blob([articleMdContent || html], { type: 'text/plain' }),
      })
    ]);
    showToast('✅ 已复制到剪贴板', 'success');
  } catch (e) {
    showToast('⚠️ 复制失败: ' + e.message, 'error');
  }
}

function downloadArticleHtml() {
  if (!articleHtmlContent) return;
  const date = articlePreviewData?.data_date || new Date().toISOString().slice(0, 10);
  downloadFile(articleHtmlContent, `quant-article-${date}.html`, 'text/html');
}

function downloadArticleMd() {
  if (!articleMdContent) return;
  const date = articlePreviewData?.data_date || new Date().toISOString().slice(0, 10);
  downloadFile(articleMdContent, `quant-article-${date}.md`, 'text/markdown');
}

function downloadFile(content, filename, type) {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

async function loadArticleHistory() {
  const data = await API.getArticleHistory();
  if (!data || data.error) return;
  window._articleHistoryData = data.items || [];
}

async function articleToggleHistory() {
  articleHistoryOpen = !articleHistoryOpen;
  const list = document.getElementById('articleHistoryList');
  const toggle = document.getElementById('articleHistoryToggle');

  if (articleHistoryOpen) {
    toggle.innerHTML = '📂 历史记录 ▾';
    const items = window._articleHistoryData || [];
    if (items.length === 0) {
      list.innerHTML = '<p style="color:var(--text-muted);padding:12px;font-size:13px">暂无历史记录</p>';
    } else {
      list.innerHTML = `
        <div class="article-history-list">
          ${items.map((item, i) => `
            <div class="article-history-item">
              <span class="article-history-date">${escapeHtml(item.date || '-')}</span>
              <span class="article-history-filename">${escapeHtml(item.filename || '-')}</span>
              <span class="article-history-size">${item.size ? (item.size / 1024).toFixed(1) + 'KB' : '-'}</span>
              <button class="btn btn-sm btn-outline" onclick="articleLoadHistory(${i})">查看</button>
            </div>
          `).join('')}
        </div>
      `;
    }
    list.style.display = 'block';
  } else {
    toggle.innerHTML = '📂 历史记录 ▸';
    list.style.display = 'none';
  }
}

async function articleLoadHistory(index) {
  const items = window._articleHistoryData || [];
  const item = items[index];
  if (!item) return;

  showToast('📂 加载历史文章...', 'info');

  const resp = await fetch(item.url || `${API.BASE}/article/history/${item.filename}`);
  if (!resp.ok) {
    showToast('❌ 加载失败', 'error');
    return;
  }

  articleHtmlContent = await resp.text();
  articleMdContent = '';
  articleActiveTab = 'html';

  document.getElementById('articlePreviewSection').style.display = 'block';
  renderPreviewContent();
  renderActionButtons();
  document.getElementById('articlePreviewSection').scrollIntoView({ behavior: 'smooth' });
}

function escapeAttr(str) {
  if (!str) return '';
  return str
    .replace(/&/g, '&amp;')
    .replace(/"/g, '&quot;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}
