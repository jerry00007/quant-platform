"""
QuantWeave - 公众号文章生成服务

从 scan_results 表读取最新选股数据，生成合规脱敏的微信公众号 HTML 文章。
使用 Jade & Ink 设计系统，支持合规脱敏（股票名称/代码/价格/建议词）。
"""

import sqlite3
import json
import os
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

from loguru import logger
from sqlalchemy.orm import Session

from ...models.models import Stock


# ── 路径常量 ──
DB_PATH = Path(__file__).resolve().parent.parent.parent.parent / "quantweave.db"
OUTPUT_DIR = Path(__file__).resolve().parent.parent.parent.parent.parent / "output"

# ── scan_results DDL ──
SCAN_RESULTS_DDL = """
CREATE TABLE IF NOT EXISTS scan_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_time TEXT NOT NULL,
    data_date TEXT NOT NULL,
    result_json TEXT NOT NULL,
    total_stocks INTEGER DEFAULT 0,
    total_signals INTEGER DEFAULT 0,
    resonance_count INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);
"""


def _ensure_scan_results_table(db_path: Path):
    """确保 scan_results 表存在"""
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(SCAN_RESULTS_DDL)
        conn.commit()
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════════════════════════
# ArticleService
# ══════════════════════════════════════════════════════════════════════════════


class ArticleService:
    """公众号文章生成服务"""

    def __init__(self, db: Session):
        self.db = db

    # ── 公开接口 ──────────────────────────────────────────────────────────

    def get_preview(self) -> dict:
        """获取最新选股数据摘要（不生成文章）"""
        scan = self._read_latest_scan()
        if not scan:
            return {"error": "请先在智能选股页面执行一键选股"}

        data = scan["result"]
        data_date = scan["data_date"]
        resonance = data.get("resonance", [])

        # 按 score.total 降序取 Top3
        top3 = sorted(resonance, key=lambda x: x.get("score", {}).get("total", 0), reverse=True)[:3]

        preview_top3 = []
        for item in top3:
            ts_code = item.get("ts_code", "")
            stock = self.db.query(Stock).filter(Stock.ts_code == ts_code).first()
            name = str(stock.name) if stock else item.get("name", "")
            industry = str(stock.industry) if stock else ""
            score = item.get("score", {})
            preview_top3.append({
                "ts_code": self._desensitize_code(ts_code),
                "name": self._desensitize_name(str(name)),
                "industry": industry,
                "total_score": score.get("total", 0),
                "advice": self._sanitize_advice(score.get("advice", "")),
                "risk_level": item.get("risk_level", ""),
            })

        return {
            "data_date": data_date,
            "total_stocks_scanned": data.get("total_stocks_scanned", 0),
            "total_signals_found": data.get("total_signals_found", 0),
            "resonance_count": len(resonance),
            "top3": preview_top3,
        }

    def generate(self) -> dict:
        """生成完整 HTML + Markdown 文章"""
        scan = self._read_latest_scan()
        if not scan:
            return {"error": "请先在智能选股页面执行一键选股"}

        data = scan["result"]
        data_date = scan["data_date"]
        scan_id = scan["id"]
        issue_number = scan_id

        resonance = data.get("resonance", [])
        top3 = sorted(resonance, key=lambda x: x.get("score", {}).get("total", 0), reverse=True)[:3]

        # 为 Top3 补充 stock 信息 + 脱敏
        top3_enriched = []
        for rank, item in enumerate(top3, 1):
            ts_code = item.get("ts_code", "")
            stock = self.db.query(Stock).filter(Stock.ts_code == ts_code).first()
            name = str(stock.name) if stock else item.get("name", "")
            industry = str(stock.industry) if stock else ""

            score = item.get("score", {})
            risk = item.get("risk", {})

            top3_enriched.append({
                "rank": rank,
                "ts_code_raw": ts_code,
                "ts_code": self._desensitize_code(ts_code),
                "name_raw": name,
                "name": self._desensitize_name(str(name)),
                "industry": industry,
                "score": score,
                "risk": risk,
                "strategies": item.get("strategies", []),
                "hit_count": item.get("hit_count", 0),
                "risk_level": item.get("risk_level", ""),
                "risk_summary": item.get("risk_summary", ""),
                "entry_points": item.get("entry_points", {}),
                "advice_safe": self._sanitize_advice(score.get("advice", "")),
            })

        # 全部 resonance 用于风控参考
        resonance_all = []
        for item in resonance:
            ts_code = item.get("ts_code", "")
            stock = self.db.query(Stock).filter(Stock.ts_code == ts_code).first()
            name = str(stock.name) if stock else item.get("name", "")
            resonance_all.append({
                "ts_code": self._desensitize_code(ts_code),
                "name": self._desensitize_name(str(name)),
                "score_total": item.get("score", {}).get("total", 0),
                "risk_level": item.get("risk_level", ""),
                "hit_count": item.get("hit_count", 0),
            })

        template_data = {
            "issue_number": issue_number,
            "data_date": data_date,
            "data_date_fmt": self._fmt_date(data_date),
            "total_stocks_scanned": data.get("total_stocks_scanned", 0),
            "total_signals_found": data.get("total_signals_found", 0),
            "resonance_count": len(resonance),
            "top3": top3_enriched,
            "resonance_all": resonance_all,
            "strategies": data.get("strategies", {}),
        }

        html_content = self._render_html(template_data)
        md_content = self._render_markdown(template_data)

        # 保存到文件
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename_base = f"quantweave_wechat_{data_date}_{timestamp}"
        html_path = OUTPUT_DIR / f"{filename_base}.html"
        md_path = OUTPUT_DIR / f"{filename_base}.md"

        html_path.write_text(html_content, encoding="utf-8")
        md_path.write_text(md_content, encoding="utf-8")

        logger.info(f"文章已生成: {html_path.name}")

        return {
            "html_content": html_content,
            "md_content": md_content,
            "filename": html_path.name,
            "data_date": data_date,
            "issue_number": issue_number,
        }

    def get_history(self) -> list:
        """列出已生成的文章"""
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        files = sorted(
            OUTPUT_DIR.glob("quantweave_wechat_*.html"),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )
        result = []
        for f in files[:20]:
            st = f.stat()
            result.append({
                "filename": f.name,
                "date": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                "size": st.st_size,
            })
        return result

    # ── 内部方法 ──────────────────────────────────────────────────────────

    def _read_latest_scan(self) -> Optional[dict]:
        """从 scan_results 读取最新扫描结果"""
        _ensure_scan_results_table(DB_PATH)
        conn = sqlite3.connect(str(DB_PATH))
        try:
            row = conn.execute(
                "SELECT id, scan_time, data_date, result_json, total_stocks, total_signals, resonance_count "
                "FROM scan_results ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if not row:
                return None
            return {
                "id": row[0],
                "scan_time": row[1],
                "data_date": row[2],
                "result": json.loads(row[3]),
                "total_stocks": row[4],
                "total_signals": row[5],
                "resonance_count": row[6],
            }
        finally:
            conn.close()

    # ── 合规脱敏 ──────────────────────────────────────────────────────────

    @staticmethod
    def _desensitize_name(name: str) -> str:
        """股票名称：保留前2字 + **"""
        if not name or len(name) <= 2:
            return name
        return name[:2] + "**"

    @staticmethod
    def _desensitize_code(ts_code: str) -> str:
        """股票代码：保留前3位 + ***.XX"""
        if not ts_code:
            return ts_code
        parts = ts_code.split(".")
        return parts[0][:3] + "***" + ("." + parts[1] if len(parts) > 1 else "")

    @staticmethod
    def _desensitize_price(price) -> str:
        """价格：显示为 ±3% 范围"""
        if not price:
            return "—"
        try:
            p = float(price)
        except (TypeError, ValueError):
            return "—"
        low = p * 0.97
        high = p * 1.03
        return f"{low:.2f} - {high:.2f}"

    @staticmethod
    def _sanitize_advice(advice: str) -> str:
        """替换禁用词"""
        replacements = {
            "强烈买入": "策略信号强烈",
            "买入/加仓": "信号积极，可持续关注",
            "持有观望": "信号中性，持续跟踪",
            "减仓": "注意风险变化",
            "卖出": "信号转弱",
        }
        return replacements.get(advice, advice)

    @staticmethod
    def _fmt_date(data_date: str) -> str:
        """格式化日期 YYYYMMDD → YYYY年MM月DD日"""
        if not data_date or len(data_date) != 8:
            return data_date
        return f"{data_date[:4]}年{data_date[4:6]}月{data_date[6:8]}日"

    # ── 评级颜色辅助 ─────────────────────────────────────────────────────

    @staticmethod
    def _risk_level_color(level: str) -> str:
        mapping = {
            "safe": "#059669",
            "warning": "#D97706",
            "danger": "#DC2626",
        }
        return mapping.get(level, "#6B7280")

    @staticmethod
    def _risk_level_text(level: str) -> str:
        mapping = {
            "safe": "低风险",
            "warning": "中等风险",
            "danger": "高风险",
        }
        return mapping.get(level, "未评估")

    # ── HTML 渲染（Jade & Ink 设计系统）───────────────────────────────────

    def _render_html(self, d: dict) -> str:
        """渲染完整 HTML 文章"""
        top3_cards = self._build_top3_cards(d["top3"])
        comparison_table = self._build_comparison_table(d["top3"])
        risk_section = self._build_risk_section(d["resonance_all"])

        return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>策略信号解读 · Issue #{d["issue_number"]}</title>
<link href="https://fonts.googleapis.com/css2?family=Libre+Baskerville:wght@400;700&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
/* ── Reset & Base ── */
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#E8E6E1;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;color:#2C2C2C;line-height:1.7;-webkit-font-smoothing:antialiased}}
.container{{max-width:680px;margin:0 auto;background:#FAFAF8;min-height:100vh}}

/* ── Hero ── */
.hero{{background:linear-gradient(135deg,#1B3A2D,#0D2818);padding:48px 32px 40px;color:#fff;position:relative;overflow:hidden}}
.hero::after{{content:'';position:absolute;top:-60px;right:-60px;width:200px;height:200px;border-radius:50%;background:rgba(5,150,105,0.1)}}
.hero .overline{{font-family:"DM Mono",monospace;font-size:12px;letter-spacing:2px;text-transform:uppercase;color:rgba(255,255,255,0.5);margin-bottom:12px}}
.hero .title{{font-family:"Libre Baskerville",serif;font-size:28px;font-weight:700;line-height:1.3;margin-bottom:16px}}
.hero .meta{{display:flex;gap:20px;flex-wrap:wrap;font-family:"DM Mono",monospace;font-size:13px;color:rgba(255,255,255,0.6)}}
.hero .stat{{display:inline-flex;align-items:center;gap:6px;background:rgba(255,255,255,0.08);padding:6px 14px;border-radius:20px;font-size:13px}}

/* ── Sections ── */
.section{{padding:32px 24px;border-bottom:1px solid #E8E6E1}}
.section-label{{font-family:"DM Mono",monospace;font-size:11px;letter-spacing:2px;text-transform:uppercase;color:#9CA3AF;margin-bottom:4px}}
.section-title{{font-family:"Libre Baskerville",serif;font-size:22px;font-weight:700;color:#1F2937;margin-bottom:20px}}

/* ── Callout ── */
.callout{{background:#F0FDF4;border:1px solid #BBF7D0;border-radius:12px;padding:20px 24px}}
.callout-grid{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px;margin-top:12px}}
.callout-item .num{{font-family:"DM Mono",monospace;font-size:24px;font-weight:700;color:#059669}}
.callout-item .label{{font-size:13px;color:#6B7280;margin-top:2px}}

/* ── Stock Card ── */
.stock-card{{background:#fff;border:1px solid #E5E7EB;border-radius:12px;padding:24px;margin-bottom:20px;position:relative}}
.stock-card .rank-badge{{position:absolute;top:-1px;left:24px;padding:4px 14px;border-radius:0 0 8px 8px;font-family:"DM Mono",monospace;font-size:13px;font-weight:700;color:#fff}}
.rank-1{{background:#059669}}
.rank-2{{background:#3B82F6}}
.rank-3{{background:#9333EA}}
.stock-card .card-header{{display:flex;align-items:flex-start;justify-content:space-between;padding-top:20px;margin-bottom:16px}}
.stock-card .stock-name{{font-family:"Libre Baskerville",serif;font-size:20px;font-weight:700;color:#1F2937}}
.stock-card .stock-code{{font-family:"DM Mono",monospace;font-size:13px;color:#9CA3AF;margin-top:2px}}

/* ── Score Ring ── */
.score-ring{{position:relative;width:80px;height:80px;flex-shrink:0}}
.score-ring svg{{transform:rotate(-90deg)}}
.score-ring .score-text{{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);font-family:"DM Mono",monospace;font-size:20px;font-weight:700;color:#1F2937}}

/* ── Data Grid ── */
.dg{{display:grid;grid-template-columns:1fr 1fr;gap:8px 16px;margin:16px 0}}
.dg-item{{display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid #F3F4F6;font-size:14px}}
.dg-item .lbl{{color:#9CA3AF}}
.dg-item .val{{font-family:"DM Mono",monospace;font-weight:500;color:#1F2937}}

/* ── Strategy Tags ── */
.tags{{display:flex;flex-wrap:wrap;gap:6px;margin:12px 0}}
.tag{{display:inline-block;padding:3px 10px;border-radius:20px;font-size:12px;font-weight:500;background:#ECFDF5;color:#059669;border:1px solid #A7F3D0}}

/* ── Score Bars ── */
.score-bars{{margin:16px 0}}
.bar-row{{display:flex;align-items:center;gap:10px;margin-bottom:8px;font-size:13px}}
.bar-row .bar-label{{width:50px;color:#9CA3AF;text-align:right;flex-shrink:0}}
.bar-row .bar-track{{flex:1;height:8px;background:#F3F4F6;border-radius:4px;overflow:hidden}}
.bar-row .bar-fill{{height:100%;border-radius:4px;transition:width .3s}}
.bar-row .bar-val{{width:36px;font-family:"DM Mono",monospace;font-size:12px;color:#6B7280}}

/* ── Interpretation / Risk Box ── */
.interp-box{{border-left:3px solid #059669;background:#F0FDF4;padding:12px 16px;border-radius:0 8px 8px 0;margin:12px 0;font-size:14px;color:#065F46}}
.risk-box{{border-left:3px solid #D97706;background:#FFFBEB;padding:12px 16px;border-radius:0 8px 8px 0;margin:12px 0;font-size:14px;color:#92400E}}

/* ── Comparison Table ── */
.cmp-table{{width:100%;border-collapse:collapse;font-size:13px;margin-top:8px}}
.cmp-table th{{background:#F9FAFB;padding:10px 8px;text-align:left;font-weight:600;color:#6B7280;border-bottom:2px solid #E5E7EB;font-size:12px}}
.cmp-table td{{padding:10px 8px;border-bottom:1px solid #F3F4F6;font-family:"DM Mono",monospace;color:#374151}}
.cmp-table tr:last-child td{{border-bottom:none}}

/* ── Risk List ── */
.risk-list{{margin-top:8px}}
.risk-row{{display:flex;align-items:center;justify-content:space-between;padding:10px 0;border-bottom:1px solid #F3F4F6}}
.risk-row:last-child{{border-bottom:none}}
.risk-row .risk-name{{font-weight:500}}
.risk-row .risk-badge{{padding:3px 10px;border-radius:20px;font-size:12px;color:#fff;font-weight:500}}

/* ── Stats Grid ── */
.stats-grid{{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:16px 0}}
.stat-card{{background:#F9FAFB;border-radius:10px;padding:16px;text-align:center}}
.stat-card .stat-num{{font-family:"DM Mono",monospace;font-size:22px;font-weight:700}}
.stat-card .stat-label{{font-size:12px;color:#9CA3AF;margin-top:4px}}
.positive{{color:#059669}}
.negative{{color:#DC2626}}

/* ── Disclaimer ── */
.disclaimer{{background:#FEF2F2;border:1px solid #FECACA;border-radius:10px;padding:20px;margin-top:20px}}
.disclaimer .disc-title{{font-weight:700;color:#991B1B;margin-bottom:10px;font-size:15px}}
.disclaimer ul{{padding-left:20px;font-size:13px;color:#991B1B;line-height:2}}

/* ── Footer ── */
.footer{{padding:24px;text-align:center;font-size:12px;color:#9CA3AF;font-family:"DM Mono",monospace;border-top:1px solid #E8E6E1}}

/* ── Copy Button ── */
.copy-btn{{position:fixed;bottom:20px;left:50%;transform:translateX(-50%);background:#059669;color:#fff;border:none;padding:12px 28px;border-radius:30px;font-size:15px;font-weight:600;cursor:pointer;box-shadow:0 4px 20px rgba(5,150,105,0.35);z-index:1000;transition:all .2s}}
.copy-btn:hover{{background:#047857;transform:translateX(-50%) translateY(-2px)}}
.copy-btn.copied{{background:#10B981}}
.copy-toast{{position:fixed;bottom:80px;left:50%;transform:translateX(-50%);background:#1F2937;color:#fff;padding:10px 24px;border-radius:8px;font-size:14px;z-index:1001;display:none}}
</style>
</head>
<body>

<div class="container" id="article-content">

<!-- ═══ Hero ═══ -->
<div class="hero">
  <div class="overline">策略信号解读 · Issue #{d["issue_number"]}</div>
  <div class="title">市场信号观察</div>
  <div class="meta">
    <span>📅 {d["data_date_fmt"]}</span>
    <span class="stat">📊 扫描 {d["total_stocks_scanned"]} 只</span>
    <span class="stat">🔔 信号 {d["total_signals_found"]} 个</span>
    <span class="stat">⚡ 共振 {d["resonance_count"]} 只</span>
  </div>
</div>

<!-- ═══ 01 大盘回顾与展望 ═══ -->
<div class="section">
  <div class="section-label">01</div>
  <div class="section-title">大盘回顾与展望</div>
  <div class="callout">
    <div style="font-size:14px;color:#374151;margin-bottom:8px">
      截至 <strong>{d["data_date_fmt"]}</strong>，策略扫描覆盖全市场 <strong>{d["total_stocks_scanned"]}</strong> 只股票，
      共产生 <strong>{d["total_signals_found"]}</strong> 个策略信号，其中 <strong style="color:#059669">{d["resonance_count"]}</strong> 只获得多策略共振。
    </div>
    <div class="callout-grid">
      <div class="callout-item">
        <div class="num">{d["total_stocks_scanned"]}</div>
        <div class="label">扫描股票数</div>
      </div>
      <div class="callout-item">
        <div class="num">{d["total_signals_found"]}</div>
        <div class="label">策略信号数</div>
      </div>
      <div class="callout-item">
        <div class="num" style="color:#059669">{d["resonance_count"]}</div>
        <div class="label">共振标的数</div>
      </div>
    </div>
  </div>
</div>

<!-- ═══ 02 Top3 策略信号 ═══ -->
<div class="section">
  <div class="section-label">02</div>
  <div class="section-title">Top3 策略信号</div>
  {top3_cards}
</div>

<!-- ═══ 03 信号对比 ═══ -->
<div class="section">
  <div class="section-label">03</div>
  <div class="section-title">信号对比</div>
  {comparison_table}
</div>

<!-- ═══ 04 风控参考 ═══ -->
<div class="section">
  <div class="section-label">04</div>
  <div class="section-title">风控参考</div>
  {risk_section}
</div>

<!-- ═══ 05 关于本策略 ═══ -->
<div class="section">
  <div class="section-label">05</div>
  <div class="section-title">关于本策略</div>
  <p style="font-size:14px;color:#6B7280;margin-bottom:16px">
    本信号由双均线交叉 + 回调企稳双策略共振筛选，经过技术/基本面/消息/资金四维评分体系综合评定。
  </p>
  <div class="stats-grid">
    <div class="stat-card">
      <div class="stat-num positive">+58.49%</div>
      <div class="stat-label">2年总收益</div>
    </div>
    <div class="stat-card">
      <div class="stat-num positive">+26.07%</div>
      <div class="stat-label">年化收益</div>
    </div>
    <div class="stat-card">
      <div class="stat-num negative">-11.46%</div>
      <div class="stat-label">最大回撤</div>
    </div>
    <div class="stat-card">
      <div class="stat-num" style="color:#3B82F6">1.28</div>
      <div class="stat-label">夏普比率</div>
    </div>
  </div>
  <div style="font-size:12px;color:#9CA3AF;text-align:center;margin-top:8px">
    以上为历史回测表现，不代表未来收益。回测区间 2024.04 - 2026.04
  </div>
  <div class="disclaimer">
    <div class="disc-title">⚠️ 风险提示</div>
    <ul>
      <li>本内容仅为量化策略信号展示，不构成任何投资建议</li>
      <li>历史回测收益不代表未来实际表现</li>
      <li>股市有风险，投资需谨慎，请根据自身风险承受能力做出决策</li>
      <li>策略信号基于公开市场数据，可能存在延迟或偏差</li>
      <li>请勿将本内容作为买卖依据，投资决策需独立判断</li>
    </ul>
  </div>
</div>

<!-- ═══ Footer ═══ -->
<div class="footer">
  策略信号解读 · 数据截至 {d["data_date_fmt"]}
</div>

</div><!-- end .container -->

<!-- ═══ 复制按钮 ═══ -->
<button class="copy-btn" onclick="copyToEditor()">复制到公众号编辑器</button>
<div class="copy-toast" id="copyToast">复制成功 ✓</div>

<script>
function copyToEditor() {{
  // 1. 克隆内容
  var clone = document.querySelector('.container').cloneNode(true);

  // 2. 移除复制按钮（如有）
  clone.querySelectorAll('.copy-btn').forEach(function(el) {{ el.remove(); }});

  // 3. 收集所有样式表规则，内联到克隆元素
  var allStyles = '';
  for (var i = 0; i < document.styleSheets.length; i++) {{
    try {{
      var rules = document.styleSheets[i].cssRules || document.styleSheets[i].rules;
      for (var j = 0; j < rules.length; j++) {{
        allStyles += rules[j].cssText + '\\n';
      }}
    }} catch(e) {{ /* cross-origin */ }}
  }}

  // 4. 将 CSS Grid 布局转为 table（公众号兼容）
  // callout-grid → table
  clone.querySelectorAll('.callout-grid').forEach(function(grid) {{
    var table = document.createElement('table');
    table.setAttribute('width', '100%');
    table.setAttribute('cellspacing', '0');
    table.setAttribute('cellpadding', '8');
    var tr = document.createElement('tr');
    grid.querySelectorAll('.callout-item').forEach(function(item) {{
      var td = document.createElement('td');
      td.setAttribute('style', 'text-align:center;padding:8px;');
      td.innerHTML = item.innerHTML;
      tr.appendChild(td);
    }});
    table.appendChild(tr);
    grid.replaceWith(table);
  }});

  // dg (data grid) → table
  clone.querySelectorAll('.dg').forEach(function(grid) {{
    var table = document.createElement('table');
    table.setAttribute('width', '100%');
    table.setAttribute('cellspacing', '0');
    table.setAttribute('cellpadding', '0');
    grid.querySelectorAll('.dg-item').forEach(function(item) {{
      var tr = document.createElement('tr');
      var td1 = document.createElement('td');
      td1.setAttribute('style', 'padding:6px 0;border-bottom:1px solid #F3F4F6;font-size:14px;color:#9CA3AF;');
      var td2 = document.createElement('td');
      td2.setAttribute('style', 'padding:6px 0;border-bottom:1px solid #F3F4F6;font-size:14px;font-family:DM Mono,monospace;font-weight:500;color:#1F2937;text-align:right;');
      var lbl = item.querySelector('.lbl');
      var val = item.querySelector('.val');
      td1.textContent = lbl ? lbl.textContent : '';
      td2.textContent = val ? val.textContent : '';
      tr.appendChild(td1);
      tr.appendChild(td2);
      table.appendChild(tr);
    }});
    grid.replaceWith(table);
  }});

  // stats-grid → table
  clone.querySelectorAll('.stats-grid').forEach(function(grid) {{
    var table = document.createElement('table');
    table.setAttribute('width', '100%');
    table.setAttribute('cellspacing', '0');
    table.setAttribute('cellpadding', '0');
    var items = grid.querySelectorAll('.stat-card');
    for (var k = 0; k < items.length; k += 2) {{
      var tr = document.createElement('tr');
      for (var m = k; m < Math.min(k + 2, items.length); m++) {{
        var td = document.createElement('td');
        td.setAttribute('style', 'background:#F9FAFB;border-radius:10px;padding:16px;text-align:center;width:50%;');
        if (m > k) td.setAttribute('style', td.getAttribute('style') + 'margin-left:6px;');
        td.innerHTML = items[m].innerHTML;
        tr.appendChild(td);
      }}
      table.appendChild(tr);
    }}
    grid.replaceWith(table);
  }});

  // 5. 替换 SVG 环形图 → 简单圆形 + 数字
  clone.querySelectorAll('.score-ring').forEach(function(ring) {{
    var score = ring.querySelector('.score-text');
    var scoreVal = score ? score.textContent : '0';
    var div = document.createElement('div');
    div.setAttribute('style', 'width:80px;height:80px;border-radius:50%;border:4px solid #059669;display:flex;align-items:center;justify-content:center;font-family:DM Mono,monospace;font-size:20px;font-weight:700;color:#1F2937;');
    div.textContent = scoreVal;
    ring.replaceWith(div);
  }});

  // 6. 构建完整 HTML
  var html = '<!DOCTYPE html><html><head><meta charset="UTF-8">' +
    '<link href="https://fonts.googleapis.com/css2?family=Libre+Baskerville:wght@400;700&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">' +
    '<style>' + allStyles + '</style></head><body>' + clone.outerHTML + '</body></html>';

  // 7. 复制到剪贴板
  var plainText = clone.innerText || clone.textContent;

  if (navigator.clipboard && navigator.clipboard.write) {{
    var htmlBlob = new Blob([html], {{ type: 'text/html' }});
    var textBlob = new Blob([plainText], {{ type: 'text/plain' }});
    navigator.clipboard.write([
      new ClipboardItem({{
        'text/html': htmlBlob,
        'text/plain': textBlob
      }})
    ]).then(function() {{
      showCopySuccess();
    }}).catch(function(err) {{
      // fallback
      fallbackCopy(html);
    }});
  }} else {{
    fallbackCopy(html);
  }}
}}

function fallbackCopy(html) {{
  var ta = document.createElement('textarea');
  ta.value = html;
  document.body.appendChild(ta);
  ta.select();
  document.execCommand('copy');
  document.body.removeChild(ta);
  showCopySuccess();
}}

function showCopySuccess() {{
  var btn = document.querySelector('.copy-btn');
  var toast = document.getElementById('copyToast');
  btn.textContent = '复制成功 ✓';
  btn.classList.add('copied');
  toast.style.display = 'block';
  setTimeout(function() {{
    btn.textContent = '复制到公众号编辑器';
    btn.classList.remove('copied');
    toast.style.display = 'none';
  }}, 2000);
}}
</script>

</body>
</html>'''

    # ── 子模板构建 ────────────────────────────────────────────────────────

    def _build_top3_cards(self, top3: list) -> str:
        cards = []
        for item in top3:
            rank = item["rank"]
            score = item["score"]
            risk = item["risk"]
            total_score = score.get("total", 0)

            # SVG 环形进度
            circumference = 138.2
            stroke_offset = circumference * (1 - total_score / 100)
            ring_color = "#059669" if total_score >= 60 else "#D97706" if total_score >= 40 else "#DC2626"

            # 策略标签
            strategy_tags = ""
            for s in item.get("strategies", []):
                strategy_tags += f'<span class="tag">{s.get("strategy", "")}</span>'

            # 四维评分条
            bar_sections = self._build_score_bars(score)

            # 信号解读
            advice_safe = item.get("advice_safe", "")
            interp_html = f'''<div class="interp-box">
      💡 <strong>信号解读：</strong>{advice_safe}（综合评分 {total_score:.0f}/100）
    </div>'''

            # 风险提示
            risk_html = ""
            warnings = risk.get("warnings", [])
            if warnings:
                warn_text = "；".join(str(w) for w in warnings)
                risk_html = f'''<div class="risk-box">
      ⚠️ <strong>风险提示：</strong>{warn_text}
    </div>'''

            cards.append(f'''<div class="stock-card">
  <div class="rank-badge rank-{rank}">Top {rank}</div>
  <div class="card-header">
    <div>
      <div class="stock-name">{item["name"]}</div>
      <div class="stock-code">{item["ts_code"]} · {item["industry"]}</div>
    </div>
    <div class="score-ring">
      <svg width="80" height="80" viewBox="0 0 80 80">
        <circle cx="40" cy="40" r="22" fill="none" stroke="#E5E7EB" stroke-width="4"/>
        <circle cx="40" cy="40" r="22" fill="none" stroke="{ring_color}" stroke-width="4"
          stroke-dasharray="{circumference}" stroke-dashoffset="{stroke_offset:.1f}"
          stroke-linecap="round"/>
      </svg>
      <div class="score-text">{total_score:.0f}</div>
    </div>
  </div>

  <div class="dg">
    <div class="dg-item"><span class="lbl">策略评分</span><span class="val">{total_score:.0f}/100</span></div>
    <div class="dg-item"><span class="lbl">RSI</span><span class="val">{score.get("rsi", "—")}</span></div>
    <div class="dg-item"><span class="lbl">量能</span><span class="val">{score.get("vol_ratio", "—")}</span></div>
    <div class="dg-item"><span class="lbl">MA状态</span><span class="val">{score.get("ma_status", "—")}</span></div>
    <div class="dg-item"><span class="lbl">MACD</span><span class="val">{score.get("macd", "—")}</span></div>
    <div class="dg-item"><span class="lbl">行业</span><span class="val">{item["industry"]}</span></div>
  </div>

  <div class="tags">{strategy_tags}</div>

  {bar_sections}

  {interp_html}
  {risk_html}
</div>''')

        return "\n".join(cards)

    @staticmethod
    def _build_score_bars(score: dict) -> str:
        dims = [
            ("技术", score.get("tech", 0), "#059669"),
            ("基本", score.get("base", 0), "#3B82F6"),
            ("消息", score.get("news", 0), "#F59E0B"),
            ("资金", score.get("fund", 0), "#8B5CF6"),
        ]
        rows = []
        for label, val, color in dims:
            width = min(val, 100)
            rows.append(
                f'<div class="bar-row">'
                f'<span class="bar-label">{label}</span>'
                f'<div class="bar-track"><div class="bar-fill" style="width:{width}%;background:{color}"></div></div>'
                f'<span class="bar-val">{val}</span>'
                f'</div>'
            )
        return f'<div class="score-bars">{"".join(rows)}</div>'

    def _build_comparison_table(self, top3: list) -> str:
        header = (
            "<tr>"
            "<th>标的</th><th>策略评分</th><th>行业</th>"
            "<th>RSI</th><th>量能</th><th>MA状态</th><th>估值</th>"
            "</tr>"
        )
        rows = []
        for item in top3:
            score = item["score"]
            valuation = "—"  # scan data doesn't include explicit valuation
            rows.append(
                f"<tr>"
                f'<td style="font-weight:600">{item["name"]}</td>'
                f'<td><strong>{score.get("total", 0):.0f}</strong></td>'
                f'<td>{item["industry"]}</td>'
                f'<td>{score.get("rsi", "—")}</td>'
                f'<td>{score.get("vol_ratio", "—")}</td>'
                f'<td>{score.get("ma_status", "—")}</td>'
                f'<td>{valuation}</td>'
                f"</tr>"
            )
        return f'<table class="cmp-table">{header}{"".join(rows)}</table>'

    def _build_risk_section(self, resonance_all: list) -> str:
        if not resonance_all:
            return '<div style="font-size:14px;color:#9CA3AF">暂无共振标的</div>'

        rows = []
        for item in resonance_all:
            level = item.get("risk_level", "")
            color = self._risk_level_color(level)
            text = self._risk_level_text(level)
            rows.append(
                f'<div class="risk-row">'
                f'<div class="risk-name">{item["name"]} <span style="color:#9CA3AF;font-size:12px">{item["ts_code"]}</span></div>'
                f'<span class="risk-badge" style="background:{color}">{text}</span>'
                f'</div>'
            )
        return f'<div class="risk-list">{"".join(rows)}</div>'

    # ── Markdown 渲染 ─────────────────────────────────────────────────────

    def _render_markdown(self, d: dict) -> str:
        lines = [
            f"# 策略信号解读 · Issue #{d['issue_number']}",
            f"",
            f"📅 {d['data_date_fmt']}",
            f"",
            f"## 01 大盘回顾与展望",
            f"",
            f"截至 {d['data_date_fmt']}，策略扫描覆盖全市场 **{d['total_stocks_scanned']}** 只股票，",
            f"共产生 **{d['total_signals_found']}** 个策略信号，其中 **{d['resonance_count']}** 只获得多策略共振。",
            f"",
            f"| 指标 | 数值 |",
            f"|------|------|",
            f"| 扫描股票数 | {d['total_stocks_scanned']} |",
            f"| 策略信号数 | {d['total_signals_found']} |",
            f"| 共振标的数 | {d['resonance_count']} |",
            f"",
            f"## 02 Top3 策略信号",
            f"",
        ]

        for item in d["top3"]:
            score = item["score"]
            lines.append(f"### Top{item['rank']} {item['name']}（{item['ts_code']}）")
            lines.append(f"")
            lines.append(f"- 行业：{item['industry']}")
            lines.append(f"- 策略评分：**{score.get('total', 0):.0f}/100**")
            lines.append(f"- RSI：{score.get('rsi', '—')}")
            lines.append(f"- 量能：{score.get('vol_ratio', '—')}")
            lines.append(f"- MA状态：{score.get('ma_status', '—')}")
            lines.append(f"- MACD：{score.get('macd', '—')}")
            lines.append(f"- 信号解读：{item['advice_safe']}")
            lines.append(f"")

        lines.append("## 03 信号对比")
        lines.append("")
        lines.append("| 标的 | 评分 | 行业 | RSI | 量能 | MA状态 |")
        lines.append("|------|------|------|-----|------|--------|")
        for item in d["top3"]:
            score = item["score"]
            lines.append(
                f"| {item['name']} | {score.get('total', 0):.0f} | {item['industry']} "
                f"| {score.get('rsi', '—')} | {score.get('vol_ratio', '—')} "
                f"| {score.get('ma_status', '—')} |"
            )
        lines.append("")

        lines.append("## 04 风控参考")
        lines.append("")
        for item in d["resonance_all"]:
            level = item.get("risk_level", "")
            text = self._risk_level_text(level)
            lines.append(f"- {item['name']}（{item['ts_code']}）：{text}")
        lines.append("")

        lines.extend([
            "## 05 关于本策略",
            "",
            "本信号由双均线交叉 + 回调企稳双策略共振筛选，经过技术/基本面/消息/资金四维评分体系综合评定。",
            "",
            "| 指标 | 数值 |",
            "|------|------|",
            "| 2年总收益 | +58.49% |",
            "| 年化收益 | +26.07% |",
            "| 最大回撤 | -11.46% |",
            "| 夏普比率 | 1.28 |",
            "",
            "以上为历史回测表现，不代表未来收益。回测区间 2024.04 - 2026.04",
            "",
            "⚠️ **风险提示**",
            "- 本内容仅为量化策略信号展示，不构成任何投资建议",
            "- 历史回测收益不代表未来实际表现",
            "- 股市有风险，投资需谨慎，请根据自身风险承受能力做出决策",
            "- 策略信号基于公开市场数据，可能存在延迟或偏差",
            "- 请勿将本内容作为买卖依据，投资决策需独立判断",
            "",
            f"---",
            f"*策略信号解读 · 数据截至 {d['data_date_fmt']}*",
        ])

        return "\n".join(lines)
