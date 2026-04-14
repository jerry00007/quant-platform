# QuantWeave 个人量化交易平台

> 🏠 三视角协同打造的量化交易系统 — 🦊狐探（产品）· 🦅鹰眼（架构）· 🦉夜枭（测试）

## 🚀 快速开始

### 后端启动

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env   # 编辑 .env 填写配置
python run.py
```

后端运行在 `http://localhost:8000`，API 文档：`http://localhost:8000/docs`

### 前端启动

直接浏览器打开 `frontend/index.html` 即可（无需构建工具）。

前端会自动连接后端 API，如果后端未启动则进入演示模式。

## 📋 功能模块

| 模块 | 说明 |
|------|------|
| 📊 交易仪表盘 | 总资产、收益曲线、策略状态、告警概览 |
| ⚡ 策略管理 | 4种内置策略（双均线/布林带/RSI/MACD）|
| 🔬 回测中心 | 完整回测引擎，支持自定义参数 |
| 📈 市场行情 | 实时A股行情（AKShare/Tushare双数据源）|
| 🛡️ 风控中心 | 告警管理、风险指标 |
| ⚙️ 系统设置 | API配置、通知配置 |

## 🏗️ 技术架构

```
Frontend (纯JS SPA)     Backend (FastAPI)
├── index.html           ├── app/
├── app.js               │   ├── core/       # 配置+数据库
                         │   ├── models/     # 数据模型
                         │   ├── api/        # 5个API模块
                         │   └── services/   # 5个服务模块
                         ├── run.py
                         └── requirements.txt
```

### 后端技术栈
- **FastAPI** — 高性能异步Web框架
- **SQLAlchemy** — ORM + SQLite
- **AKShare** — 免费A股数据源
- **Tushare Pro** — 备用数据源（需Token）
- **APScheduler** — 定时任务
- **Chart.js** — 前端图表

### 内置策略
| 策略 | 说明 | 参数 |
|------|------|------|
| 双均线交叉 | MA金叉买入、死叉卖出 | short_period, long_period |
| 布林带突破 | 突破下轨买入、上轨卖出 | period, std_dev |
| RSI超买超卖 | RSI<30买入、>70卖出 | period, oversold, overbought |
| MACD金叉死叉 | DIF上穿DEA买入 | fast_period, slow_period, signal_period |

## ⚠️ 风险提示

本系统仅供学习研究使用，不构成任何投资建议。量化交易存在风险，请谨慎使用。
