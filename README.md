# QuantWeave — 个人量化交易平台 v4.0

> 🏠 从零到一的 A 股量化交易系统 — 策略研究 · 回测验证 · 实盘管理 · 微信推送
>
> 🦊狐探（产品）· 🦅鹰眼（架构）· 🦉夜枭（测试）三视角协同打造

---

## ✨ 项目亮点

- **5大核心策略**，全市场2年回测正收益（实盘使用双均线+回调企稳）
- **三数据源架构**：Tushare（历史日线）+ 雪球（实时行情，免费无Token）+ AKShare（美股/备用）
- **一键选股**：全市场5500只股票双策略扫描 → AI评分 → 微信推送
- **日内做T**：实时分时数据 + 技术指标分析 → 做T操作建议
- **微信推送**：盘前速递/卖出扫描/每日选股自动推送到微信
- **纯 JS SPA 前端**：11个功能页面，无框架无构建，打开即用

---

## 🚀 快速开始

### 1. 环境准备

```bash
# 克隆项目
git clone https://github.com/your-repo/quant-platform.git
cd quant-platform

# 创建 Python 环境（推荐 3.11）
conda create -n quant-platform python=3.11
conda activate quant-platform

# 安装依赖
cd backend
pip install -r requirements.txt
```

### 2. 配置

```bash
cp .env.example .env
# 编辑 .env，填写：
# TUSHARE_TOKEN=xxx          （Tushare Pro 数据源）
# SERVERCHAN_KEY=xxx         （Server酱微信推送，可选）
```

### 3. 启动

```bash
# 后端（默认 http://localhost:8000）
python run.py

# 前端 — 直接浏览器打开 frontend/index.html
# API 文档：http://localhost:8000/docs
```

---

## 📋 功能模块

| 模块 | 页面 | 说明 |
|------|------|------|
| 📊 交易仪表盘 | dashboard | 真实持仓展示 + 账户概览 + 点击个股分析 + 快捷操作 |
| 📈 实时行情 | market | 指数速览 + 持仓盈亏 + 涨跌分布 + 市场温度，30秒自动刷新 |
| 🔬 智能筛选 | screening | 一键选股（异步）+ 全市场扫描 + 个股深度分析 |
| 📡 信号中心 | signals | 持仓信号 + 5种股票池类型 + 微信通知文本 |
| 🧪 回测中心 | backtest | 单股/全市场回测 + 多策略对比 + Chart.js 图表 |
| 💼 持仓管理 | portfolio | 持仓 CRUD + 账户管理 + 交易流水 |
| 📦 数据中心 | data-center | 股票/ETF 同步 + 分页浏览 + 批量历史同步 |
| ⭐ 关注列表 | watchlist | 分组管理 + 搜索添加 + 实时行情 |
| ⚡ 策略管理 | strategy | 5种核心策略 + 参数配置 + 快速回测入口 |
| 🛡️ 风控中心 | risk | 风险参数 + 告警记录 |
| ⚙️ 系统设置 | settings | 数据源配置 + 系统信息 |

---

## 🏗️ 技术架构

```
┌──────────────────────────────────────────────────────┐
│         前端（纯 JS SPA，无构建步骤）                    │
│  index.html + 14个JS模块 + Chart.js v4                │
│  11个页面 · 暗色主题 · 响应式 · 30s自动刷新              │
└────────────────┬─────────────────────────────────────┘
                 │ REST API (/api/v1)
┌────────────────▼─────────────────────────────────────┐
│                  后端（FastAPI）                        │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐            │
│  │ 9个API   │  │ 14个服务 │  │ SQLite   │            │
│  │ 模块     │→│ 模块     │→│ ~464MB   │            │
│  └──────────┘  └──────────┘  └──────────┘            │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐            │
│  │ 6个定时  │  │ 微信推送 │  │ 5大策略  │            │
│  │ 任务     │  │ Server酱 │  │ 引擎     │            │
│  └──────────┘  └──────────┘  └──────────┘            │
└──────────────────────────────────────────────────────┘
                    │
       ┌────────────┼────────────┐
       ▼            ▼            ▼
  Tushare Pro    雪球实时      AKShare
  （历史日线）   （盘中行情）   （美股/备用）
```

### 技术栈

| 层面 | 技术 | 说明 |
|------|------|------|
| 后端 | FastAPI + SQLAlchemy 2.0 | 异步高性能 + ORM |
| 数据库 | SQLite（WAL模式，~464MB） | 零配置，开箱即用 |
| 数据源 | Tushare + 雪球 + AKShare | 三源自动切换 |
| 数据处理 | Pandas + NumPy + ta | 技术指标计算 |
| 定时任务 | WorkBuddy Automations | 6个定时任务 |
| 通知 | Server酱 | 微信推送 |
| 前端 | 纯 JavaScript SPA + Chart.js v4 | 无框架，零依赖构建 |
| 配置 | Pydantic Settings + .env | 环境变量管理 |
| 日志 | Loguru | 轮转10MB/保留30天 |

---

## ⚡ 策略体系

5大核心策略，统一由 `core_signals.py` 提供：

| # | 策略 | 类型 | 2年回测收益 | 夏普比率 |
|---|------|------|:----------:|:--------:|
| 1 | 双均线交叉 (7/60) | 趋势 | +101.44% | 1.240 |
| 2 | 强势股回调企稳 (8/95/5) | TDX指标 | +82.07% | 1.459 |
| 3 | 布林带上轨突破 (25/1.8) | 均值回归 | +20.16% | 0.383 |
| 4 | 均线趋势跟踪 (MA15/3) | 趋势 | +19.01% | 0.348 |
| 5 | 增强筹码策略 (5/98/5) | TDX指标 | +17.57% | 0.388 |

**实盘策略**：双均线 + 回调企稳（好大哥确认）

**核心洞察**：分散化效应是策略核心，不加排序/过滤/趋势框架。全市场5500只扫描，靠概率和分散化取胜。

---

## ⏰ 自动化任务

| 任务 | 时间 | 说明 |
|------|------|------|
| 🌅 盘前速递 | 7:30 | 数据同步 + 大盘概览 + 卖出信号 + 外盘+新闻 → 微信推送 |
| 📊 做T上午 | 10:00 | 7只持仓做T信号扫描 |
| 🔔 卖出扫描 | 11:30 | 持仓止损/止盈检测 → 微信推送 |
| 📊 做T下午 | 13:30 | 7只持仓做T信号扫描 |
| 🎯 每日选股 | 15:30 | 全市场双策略扫描 → 入池 → 微信推送 |
| 📝 盘后复盘 | 18:00 | 跟踪池批量卖出检测 + 报告 |

---

## 📁 项目结构

```
quant-platform/
├── backend/
│   ├── app/
│   │   ├── api/             # 9个API模块
│   │   │   ├── market_api.py      # 🆕 行情API（指数/涨跌/板块/总览）
│   │   │   ├── screening_api.py   # 选股/扫描/一键选股
│   │   │   ├── backtest_api.py    # 回测引擎
│   │   │   ├── portfolio_api.py   # 持仓管理
│   │   │   ├── data_api.py        # 数据同步
│   │   │   ├── strategy_api.py    # 策略管理
│   │   │   ├── report_api.py      # 报告导出
│   │   │   ├── risk_api.py        # 风控中心
│   │   │   └── system_api.py      # 系统设置
│   │   ├── services/
│   │   │   ├── strategy/          # 策略引擎
│   │   │   │   ├── core_signals.py     # 5策略共用模块（核心）
│   │   │   │   └── intraday_t.py       # 日内做T信号
│   │   │   ├── data/              # 数据层
│   │   │   │   ├── data_service.py     # 三数据源切换
│   │   │   │   ├── xueqiu_data.py      # 雪球实时行情
│   │   │   │   ├── intraday_data.py    # 分时线/5分钟K线
│   │   │   │   └── data_cache.py       # SQLite缓存
│   │   │   ├── tracking/          # 跟踪池
│   │   │   ├── backtest/          # 回测引擎
│   │   │   ├── screening/         # 选股服务
│   │   │   │   └── quick_picks_service.py  # 🆕 一键选股
│   │   │   ├── market/            # 市场分析
│   │   │   ├── portfolio/         # 持仓管理
│   │   │   ├── workflow/          # 交易工作流
│   │   │   └── ...                # 通知/报告/调度等
│   │   ├── core/                  # 配置+数据库
│   │   ├── models/                # 数据模型
│   │   └── utils/                 # 工具
│   │       └── wechat_notify.py   # 🆕 Server酱微信推送
│   ├── run.py                     # 启动入口
│   └── quantweave.db              # SQLite数据库 (~464MB)
│
├── frontend/
│   ├── index.html                 # SPA入口
│   └── js/                        # 14个JS模块
│       ├── app.js                 # 路由 + 页面管理
│       ├── api.js                 # 统一API客户端
│       ├── market.js              # 🆕 实时行情（5大板块）
│       ├── screening.js           # 🆕 一键选股 + 扫描
│       ├── dashboard.js           # 交易仪表盘
│       ├── backtest.js            # 回测中心
│       └── ...                    # 其他页面
│
├── quantweave.db → backend/quantweave.db  # symlink
└── README.md
```

---

## 🔌 WorkBuddy Skills

本项目配套3个 AI Skill，通过 WorkBuddy 自动调用：

| Skill | 触发词 | 功能 |
|-------|--------|------|
| **intraday-t** | "做T"/"盘中建议" | 日内做T操作建议（分时数据+RSI+偏离度） |
| **quant-daily-picks** | "选股"/"每日选股" | 全市场双策略扫描 + AI评分 |
| **stock-sense-ai** | "分析XX股票" | 6维度股票分析（技术/基本/消息/资金） |

---

## 📈 数据流

```
数据采集层
  Tushare(日线) ──→ DataService ──→ SQLite缓存 ──→ 策略引擎
  雪球(实时)   ──→ XueqiuData ──→ 30s缓存 ──→ 前端行情页
  AKShare(美股) ──→ IntradayData ──→ 分时线 ──→ 做T分析

策略计算层
  core_signals.py ──→ 5策略信号 ──→ 跟踪池(入池) ──→ 卖出检测

执行输出层
  TradingWorkflow ──→ 盘前/卖出/选股/复盘 ──→ 微信推送
  QuickPicksService ──→ 一键选股 ──→ scan_results ──→ 前端展示
```

---

## ⚠️ 风险提示

本系统仅供学习研究使用，不构成任何投资建议。量化交易存在风险，请谨慎使用。

---

## 📄 License

MIT License

---

*QuantWeave v4.0 · 2026-04-17*
