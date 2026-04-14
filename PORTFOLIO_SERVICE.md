# Portfolio Service 实现文档

> **🦊 狐探产品经理报告** | 持仓管理模块完整实现

## 📋 执行摘要

已成功实现 **PortfolioService（持仓管理模块）**，这是 QuantWeave 量化交易平台的核心功能之一。模块现已支持：

1. **完整持仓管理**（CRUD操作、盈亏计算）
2. **交易流水记录**（买卖、存取款、手续费计算）
3. **账户资金管理**（多账户支持、资金流水）
4. **NAS数据库支持**（家庭服务器 MySQL + Redis）
5. **完整API接口**（RESTful设计，与前端无缝集成）
6. **演示前端界面**（交互式Web UI）

## 🏗️ 核心架构

### 数据结构
```python
# 三张核心表
1. Position（持仓）      # 跟踪持仓状态和盈亏
2. Transaction（交易流水） # 记录所有资金流动
3. Account（账户）      # 管理现金余额和总资产

# 关键关系
Account 1:n Transaction
Position 1:n Transaction
```

### 技术要点
- **双数据库支持**: SQLite（本地开发）+ MySQL（NAS生产环境）
- **Redis缓存**: 用于高频查询（持仓汇总、价格缓存）
- **完全类型提示**: Pydantic模型保障API数据安全
- **异常处理**: 全面的事务回滚和错误日志

## 🚀 已实现功能

### 1. 持仓管理 (`PositionService`)
- **添加持仓**: 支持股票/ETF，自动计算市值
- **价格更新**: 实时计算浮动盈亏和比例
- **平仓操作**: 支持部分/全部平仓，自动计算手续费
- **持仓汇总**: 按账户分组，盈亏排序展示
- **自动同步**: 与行情数据对接，更新最新价格

### 2. 账户管理 (`AccountService`)
- **资金操作**: 存入/提取现金，自动更新余额
- **账户概览**: 总资产 = 现金 + 持仓市值
- **盈亏分析**: 实时计算总盈亏和比例
- **交易历史**: 记录所有资金流动

### 3. 交易流水 (`TransactionService`)
- **完整记录**: 记录买卖、存取款、手续费、印花税
- **净额计算**: 自动计算交易净额（考虑成本）
- **关联查询**: 可追溯到具体持仓和账户

## 🔌 NAS数据库集成

### 配置详情
```python
# MySQL配置
主机: 192.168.0.222
端口: 3306
数据库: quantweave
用户: root

# Redis配置
主机: 192.168.0.222
端口: 6379
```

### 连接检查
```bash
# 测试连接
python backend/init_nas_db.py

# 健康检查API
GET /api/v1/portfolio/health
```

### 故障转移
- **主数据库**: NAS MySQL（生产环境）
- **备用数据库**: 本地SQLite（开发/测试）
- **自动切换**: 通过配置环境变量

## 📊 API接口设计

### 接口概览
| 端点 | 方法 | 功能 | 认证 |
|------|------|------|------|
| `/portfolio/health` | GET | 服务健康检查 | 无 |
| `/portfolio/positions` | GET | 获取持仓汇总 | 无 |
| `/portfolio/positions` | POST | 添加持仓 | 无 |
| `/portfolio/positions/{id}` | PUT | 更新持仓价格 | 无 |
| `/portfolio/positions/{id}/close` | POST | 平仓操作 | 无 |
| `/portfolio/sync` | POST | 同步持仓价格 | 无 |
| `/portfolio/account/{name}` | GET | 获取账户信息 | 无 |
| `/portfolio/deposit` | POST | 存入现金 | 无 |
| `/portfolio/withdraw` | POST | 提取现金 | 无 |
| `/portfolio/transactions` | GET | 获取交易流水 | 无 |

### 请求示例
```json
// 添加持仓
POST /api/v1/portfolio/positions
{
  "ts_code": "000001.SZ",
  "symbol": "000001",
  "name": "平安银行",
  "direction": "long",
  "volume": 1000,
  "avg_cost": 12.50,
  "account_name": "main"
}

// 存入现金
POST /api/v1/portfolio/deposit
{
  "amount": 100000.00,
  "account_name": "main",
  "notes": "入金"
}
```

## 🎨 前端演示界面

### 功能特色
- **实时仪表盘**: 账户概览与持仓汇总
- **交互表格**: 持仓列表，支持排序和筛选
- **模拟操作**: 添加持仓、平仓、同步价格
- **移动适配**: 响应式设计，支持多设备
- **可视化图表**: 盈亏可视化（待实现）

### 访问方式
```bash
# 本地访问
open frontend/portfolio.html

# 或通过浏览器打开
file:///Users/liujianyu/WorkBuddy/Claw/quant-platform/frontend/portfolio.html
```

## 🧪 测试与验证

### 单元测试
```bash
# 运行测试脚本
python backend/test_portfolio_service.py

# 测试输出
✅ 数据库初始化完成
💰 存入现金: ¥1,000,000.00
📈 添加5个示例持仓
📊 更新持仓价格（模拟涨跌）
📋 计算持仓汇总（总盈亏、比例）
💱 测试平仓操作（手续费计算）
🏦 验证账户余额更新
```

### API测试
```bash
# 启动服务
cd backend && python run.py

# 测试API
curl -X GET "http://localhost:8000/api/v1/portfolio/health"
curl -X GET "http://localhost:8000/api/v1/portfolio/positions"
```

## 🔧 安装与部署

### 依赖安装
```bash
# 安装MySQL和Redis驱动
cd backend
pip install -r requirements.txt

# 确保以下包已安装
- pymysql>=1.1.0
- mysql-connector-python>=8.3.0
- redis>=5.0.0
```

### 数据库初始化
```bash
# 本地开发环境（SQLite）
python -c "from app.core.database import init_db; init_db()"

# NAS生产环境（MySQL）
python backend/init_nas_db.py
```

### 服务启动
```bash
# 开发模式
cd backend
python run.py
# 访问: http://localhost:8000/docs

# 生产模式（需要配置）
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

## 🚨 注意事项与限制

### 已知限制
1. **网络依赖**: NAS数据库需要内网访问
2. **权限管理**: 当前为单用户模式
3. **行情集成**: 需要对接行情服务获取实时价格
4. **税收政策**: 暂只支持A股千一印花税

### 安全考虑
- **⚠️ MySQL密码明文存储**: 应使用环境变量或密钥管理
- **⚠️ 无API认证**: 生产环境需要添加Token验证
- **⚠️ 无HTTPS**: 内网使用可接受，公网需要SSL

## 📈 下一步计划

### P0（本周完成）
1. **价格服务集成**: 连接Tushare获取实时行情
2. **晨报功能升级**: 整合持仓数据生成晨报
3. **风控巡检实现**: 监控持仓风险

### P1（两周内）
1. **多账户支持**: 支持家人/朋友共同管理
2. **ETF特殊处理**: 支持ETF特有的指标计算
3. **数据迁移工具**: SQLite ↔ MySQL 双向同步

### P2（月度规划）
1. **实时行情推送**: WebSocket推送价格变动
2. **AI持仓建议**: 基于市场情绪推荐调仓
3. **API认证系统**: OAuth2/JWT 用户认证

## 🤝 协作指南

### 前端集成
1. **页面位置**: `frontend/portfolio.html`
2. **API基址**: `http://localhost:8000/api/v1`
3. **响应格式**: 统一JSON格式，包含`success`字段

### 后端扩展
1. **添加模型**: 在`app/models/models.py`定义
2. **创建服务**: 继承`PortfolioService`基类
3. **注册API**: 在`app/api/__init__.py`添加路由

### 数据库迁移
1. **新增字段**: 使用SQLAlchemy Alembic迁移
2. **数据转换**: 编写数据迁移脚本
3. **回滚计划**: 确保有数据备份

---

## 📞 技术支持

### 问题排查
1. **连接失败**: 检查NAS服务器和网络
2. **导入错误**: 确认依赖包已安装
3. **数据库错误**: 检查MySQL用户权限

### 调试建议
```python
# 调试模式
DEBUG = True  # 在config.py中设置

# 日志查看
python -c "from app.core.nas_config import check_nas_connection; print(check_nas_connection())"
```

---

**文档版本**: v1.0.0  
**最后更新**: 2026-04-12  
**负责人**: 🦊 狐探（产品经理）  
**状态**: ✅ 已上线（开发完成）

> **后续建议**: 建议优先测试`test_portfolio_service.py`脚本，然后使用前端界面进行交互测试，最后集成到主应用中。