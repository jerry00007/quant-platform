# QuantWeave 量化交易平台 - 项目知识库

> 状态：稳定 v2.0 | 最后更新：2026-04-15

## 项目概述

QuantWeave 是一个个人量化交易平台，面向 A 股市场，提供策略管理、回测引擎、实时行情、持仓管理、信号扫描、风控告警等完整功能。

**技术栈**: Python 3.11 + FastAPI + SQLAlchemy + SQLite/MySQL + 纯 JavaScript SPA 前端

**启动方式**:
- 后端: `cd backend && python run.py` → `http://localhost:8000`
- 前端: 浏览器直接打开 `frontend/index.html`（无构建步骤）
- Docker: `docker compose up`（开发模式）/ `docker compose --profile prod up -d`（生产模式）
- API 文档: `http://localhost:8000/docs`

---

## 项目结构

```
quant-platform/
├── backend/                    # FastAPI 后端
│   ├── app/
│   │   ├── main.py            # 入口：FastAPI app、生命周期、定时任务
│   │   ├── core/              # 核心基础设施
│   │   │   ├── config.py      # Pydantic Settings 配置（环境变量 + .env）
│   │   │   ├── database.py    # SQLAlchemy 引擎 + Session + Base
│   │   │   ├── nas_config.py  # NAS MySQL/Redis 连接配置
│   │   │   └── logging_config.py
│   │   ├── models/
│   │   │   └── models.py      # 所有 SQLAlchemy ORM 模型（13 张表）
│   │   ├── api/               # 8 个 API 路由模块
│   │   │   ├── data_api.py        # 数据管理（股票列表、行情、关注列表）
│   │   │   ├── strategy_api.py    # 策略 CRUD + 参数管理
│   │   │   ├── backtest_api.py    # 回测执行 + 结果查询
│   │   │   ├── portfolio_api.py   # 持仓/账户/交易流水
│   │   │   ├── screening_api.py   # 股票筛选
│   │   │   ├── report_api.py      # 报告导出
│   │   │   ├── risk_api.py        # 风控告警
│   │   │   └── system_api.py      # 系统健康检查、配置
│   │   └── services/          # 14 个业务服务模块
│   │       ├── backtest/          # 回测引擎
│   │       │   ├── backtest_service.py    # 核心回测逻辑
│   │       │   └── market_backtest.py     # 市场级回测
│   │       ├── data/              # 数据服务
│   │       │   ├── data_service.py        # 股票/ETF 数据获取（AKShare + Tushare）
│   │       │   ├── data_cache.py          # 数据缓存
│   │       │   └── neodata_service.py     # 新数据服务（腾讯 NeoData）
│   │       ├── strategy/          # 策略引擎
│   │       │   ├── strategy_service.py    # 策略注册表 + 基础框架
│   │       │   ├── chip_strategy.py       # 筹码策略
│   │       │   ├── fengmang_strategy.py    # 风芒策略
│   │       │   ├── top_bottom_strategy.py  # 顶底策略
│   │       │   └── position_sizer.py      # 仓位计算器
│   │       ├── signal/            # 信号服务
│   │       │   └── signal_service.py      # 信号生成 + 早盘提醒
│   │       ├── portfolio/         # 持仓管理
│   │       │   └── portfolio_service.py   # 持仓/账户/交易流水 CRUD
│   │       ├── market/            # 市场情绪
│   │       │   └── market_sentiment_service.py
│   │       ├── sector/            # 板块分析
│   │       │   └── sector_service.py      # 板块轮动/相关性/聚类
│   │       ├── screening/         # 股票筛选
│   │       │   └── screening_service.py
│   │       ├── morning/           # 早盘服务
│   │       │   └── morning_brief_service.py
│   │       ├── news/              # 新闻服务
│   │       │   └── news_service.py
│   │       ├── report/            # 报告导出
│   │       │   └── report_exporter.py
│   │       ├── scheduler/         # 定时任务
│   │       │   └── scheduler_service.py   # APScheduler 封装
│   │       └── notify/            # 通知服务
│   │           └── notify_service.py      # Server酱/钉钉/邮件/企业微信
│   ├── tests/                 # 测试
│   │   ├── conftest.py
│   │   ├── test_backtest.py
│   │   └── test_strategy.py
│   ├── requirements.txt       # Python 依赖
│   ├── run.py                 # 启动脚本
│   ├── .env / .env.example    # 环境变量
│   └── quantweave.db          # SQLite 数据库文件
├── frontend/                   # 纯 JavaScript SPA
│   ├── index.html             # 主页面（SPA 入口）
│   ├── portfolio.html         # [遗留] 独立持仓管理页面（非主 SPA）
│   ├── app.js                 # [遗留] 旧版单文件 SPA（非活跃入口）
│   └── js/                    # 14 个功能模块
│       ├── api.js             # API 通信层（fetch 封装）
│       ├── app.js             # 应用状态管理
│       ├── dashboard.js       # 仪表盘
│       ├── backtest.js        # 回测中心
│       ├── strategy.js        # 策略管理
│       ├── market.js          # 市场行情
│       ├── portfolio.js       # 持仓管理
│       ├── risk.js            # 风控中心
│       ├── screening.js       # 股票筛选
│       ├── signals.js         # 信号中心
│       ├── watchlist.js       # 关注列表
│       ├── data-center.js     # 数据中心
│       ├── settings.js        # 系统设置
│       └── nav.js             # 导航栏
├── docker-compose.yml         # Docker 编排（backend + MySQL + Redis）
├── Dockerfile                 # 多阶段构建（development/production）
├── data_cache/                # 数据缓存目录
├── reports/                   # 报告输出目录
└── PORTFOLIO_SERVICE.md       # 持仓服务详细文档
```

---

## 数据模型（13 张表）

| 模型 | 表名 | 用途 |
|------|------|------|
| `Stock` | stocks | 股票基本信息（代码、名称、行业、市场） |
| `StockDaily` | stock_daily | 日线行情（OHLCV + 均线） |
| `ETFInfo` | etf_info | ETF 基本信息及跟踪指数 |
| `Strategy` | strategies | 策略配置（参数JSON、状态、绩效指标） |
| `Trade` | trades | 交易记录（策略关联、方向、盈亏） |
| `BacktestResult` | backtest_results | 回测结果（净值曲线、回撤曲线JSON） |
| `Watchlist` | watchlist | 关注列表（股票/ETF、分组、备注） |
| `DailySignal` | daily_signals | 每日信号（买卖操作、触发策略、评分） |
| `RiskAlert` | risk_alerts | 风控告警（级别、状态） |
| `Position` | positions | 持仓记录（成本、市值、盈亏） |
| `Transaction` | transactions | 交易流水（买卖/存取款、手续费、印花税） |
| `Account` | accounts | 账户资金（总资产、现金、市值） |

---

## API 路由（前缀 `/api/v1`）

| 模块 | 主要端点 |
|------|----------|
| data | `/data/stocks`, `/data/stock/{code}/daily`, `/data/watchlist`, `/data/etf` |
| strategy | `/strategy/`, `/strategy/{id}`, `/strategy/types` |
| backtest | `/backtest/run`, `/backtest/results`, `/backtest/result/{id}` |
| portfolio | `/portfolio/positions`, `/portfolio/account/{name}`, `/portfolio/transactions`, `/portfolio/sync` |
| screening | `/screening/` |
| report | `/report/` |
| risk | `/risk/alerts`, `/risk/check` |
| system | `/system/health`, `/system/config` |

---

## 策略引擎

内置 11 种策略，通过 `STRATEGY_REGISTRY` 注册表管理，在 `strategy_service.py` 中定义：

| 注册键 | 策略名称 | 类型 | 来源文件 |
|--------|----------|------|----------|
| dual_ma | 双均线交叉 | 趋势 | strategy_service.py |
| bollinger | 布林带突破 | 均值回归 | strategy_service.py |
| rsi | RSI 超买超卖 | 均值回归 | strategy_service.py |
| macd | MACD 金叉死叉 | 趋势 | strategy_service.py |
| chip | 主力筹码趋势（ZLCMQ） | TDX 指标 | chip_strategy.py |
| enhanced_chip | 增强筹码+多因子+ATR | TDX 指标 | chip_strategy.py |
| pullback_stable | 强势股回调企稳（5-3稳定） | TDX 指标 | chip_strategy.py |
| vol_breakout | 爆量突破 | 动量 | fengmang_strategy.py |
| first_yin | 龙头首阴反弹 | 动量 | fengmang_strategy.py |
| trend_ma | 均线趋势跟踪 | 趋势 | fengmang_strategy.py |
| top_bottom | 顶底图（多变量系统） | TDX 指标 | top_bottom_strategy.py |

仓位管理：`position_sizer.py` 提供 `TopBottomScorer`（市场评分 0-100）+ `GridPositionManager`（网格仓位：90+满仓、75-90重仓、60-75半仓、40-60轻仓、<40空仓），最多分配 5 只股票。

---

## 定时任务（APScheduler）

| 任务 | 触发时间 | 功能 |
|------|----------|------|
| 数据同步 | 工作日 9:15 | 同步股票/ETF 列表和行情 |
| 早盘提醒 | 工作日 9:30 | 聚合市场/板块/信号/持仓生成早盘报告并推送通知 |
| 信号扫描 | 工作日 15:05 | 扫描关注列表生成交易信号（收盘后） |
| 风控巡检 | 工作日每 30 分钟 | 检查持仓风险（待完善） |

在 `main.py` 的 `lifespan` 中初始化调度器。

---

## 通知系统

支持 4 种通知渠道，在 `notify_service.py` 中统一管理：
- **Server酱** — 推送到个人微信（`SERVERCHAN_KEY`）
- **钉钉** — 钉钉群机器人 Webhook
- **企业微信** — 企业微信群机器人 Webhook
- **邮件** — SMTP 邮件通知

---

## 数据源

| 数据源 | 用途 | 配置 |
|--------|------|------|
| AKShare | 免费A股数据（主要） | 无需 Token |
| Tushare Pro | 备用数据源 | `TUSHARE_TOKEN`（.env） |

数据服务在 `data_service.py` 中，支持双数据源自动切换。

---

## 部署架构

### 开发模式
- SQLite 本地数据库
- `uvicorn --reload` 热重载
- Docker 开发阶段（挂载卷）

### 生产模式（Docker Compose --profile prod）
- MySQL 8.0（NAS 192.168.0.222:3306）
- Redis 7（NAS 192.168.0.222:6379）用于缓存
- 非 root 用户运行
- 多 worker（`--workers 2`）
- 健康检查（`/api/v1/system/health`）

---

## 配置管理

所有配置通过 `core/config.py` 的 `Settings` 类管理（Pydantic BaseSettings）：
- 环境变量优先 → `.env` 文件回退
- API 前缀: `/api/v1`
- CORS 允许 localhost 多端口
- 风控参数: 最大仓位 30%、日最大亏损 5%、止损 8%、止盈 15%
- 回测默认: 初始资金 100 万、佣金万三、滑点千一

---

## 开发约定

### 后端
- 所有服务类接收 `db: Session` 作为第一个参数
- API 路由使用 `Depends(get_db)` 获取数据库会话
- 新增模型 → `models/models.py`，新增服务 → `services/` 下新建目录，新增 API → `api/` 下新建文件并在 `api/__init__.py` 注册
- 日志使用 `loguru`
- 类型提示通过 Pydantic 模型保障

### 前端
- 纯 JavaScript SPA，无框架、无构建步骤
- 每个功能模块一个 JS 文件，共 14 个 JS 模块
- API 通信通过 `js/api.js` 统一封装（`http://localhost:8000/api/v1`）
- 后端未启动时自动进入演示模式
- Chart.js v4（CDN）用于图表渲染，Canvas 2D 用于仪表盘绘图
- 暗色主题（深蓝底 `#0F172A` + 琥珀强调色 `#F59E0B`），响应式布局
- 11 个页面：仪表盘、数据中心、关注列表、持仓管理、智能筛选、信号中心、策略管理、回测中心、实时行情、风控中心、系统设置
- 无正式状态管理，各模块通过模块级变量管理局部状态
- `portfolio.html` 和根目录 `app.js` 为遗留/原型文件，非主 SPA 的一部分

### 数据库
- 默认 SQLite（开发），可选 MySQL（生产/NAS）
- 数据库迁移建议使用 Alembic
- Redis 可选，用于高频数据缓存

---

## 关键文件速查

| 需要 | 看这里 |
|------|--------|
| 添加新策略 | `backend/app/services/strategy/strategy_service.py` + 新建策略文件 |
| 添加新 API | `backend/app/api/` 下新建文件 → `__init__.py` 注册 router |
| 添加新数据模型 | `backend/app/models/models.py` → `init_db()` 自动建表 |
| 修改配置 | `backend/app/core/config.py` + `.env` |
| 修改前端页面 | `frontend/index.html` + `frontend/js/*.js` |
| 定时任务调整 | `backend/app/main.py` 的 `lifespan()` + `services/scheduler/` |
| 通知渠道配置 | `.env` 中的 SERVERCHAN_KEY / DINGTALK_WEBHOOK 等 |
| Docker 部署 | `Dockerfile` + `docker-compose.yml` |
| 数据库迁移 | `cd backend && alembic revision --autogenerate -m "desc"` |
| 策略参数同步 | `cd backend && python sync_strategies.py` |
| 运行测试 | `cd backend && python -m pytest tests/ -v` |

---

## v2.0 工程化改进（2026-04-15）

- **Alembic 数据库迁移**：`backend/alembic/`，支持 schema 版本管理
- **4核心策略参数入库**：`sync_strategies.py` 将回测验证的最优参数写入 strategies 表
- **风控巡检**：持仓止损/止盈监控，自动生成 RiskAlert 并推送通知
- **GitHub Actions CI**：`.github/workflows/ci.yml`，lint + pytest 自动化
- **代码修复**：Pydantic V2 ConfigDict、去重 get_db()、版本号更新 2.0.0
- **测试整理**：所有测试文件归入 `tests/`，39 个测试通过
- **旧脚本归档**：14 个遗留脚本移入 `archive/`
- **全量回测锁定**：`backtest_all_strategies.py` + `bt_html.py` 不再改动
