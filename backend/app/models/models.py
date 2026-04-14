"""
QuantWeave - 数据模型：股票、策略、交易记录、回测结果
"""
from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Text, JSON
from sqlalchemy.sql import func
from ..core.database import Base


class Stock(Base):
    """股票信息"""
    __tablename__ = "stocks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ts_code = Column(String(20), unique=True, nullable=False, index=True, comment="股票代码 TS")
    symbol = Column(String(10), nullable=False, comment="股票代码")
    name = Column(String(50), nullable=False, comment="股票名称")
    industry = Column(String(30), comment="所属行业")
    market = Column(String(10), comment="市场类型:主板/创业板/科创板")
    list_date = Column(String(20), comment="上市日期")
    is_active = Column(Boolean, default=True, comment="是否活跃")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class StockDaily(Base):
    """日线行情数据"""
    __tablename__ = "stock_daily"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ts_code = Column(String(20), nullable=False, index=True, comment="股票代码")
    trade_date = Column(String(10), nullable=False, index=True, comment="交易日期 YYYYMMDD")
    open = Column(Float, comment="开盘价")
    high = Column(Float, comment="最高价")
    low = Column(Float, comment="最低价")
    close = Column(Float, comment="收盘价")
    pre_close = Column(Float, comment="昨收价")
    change_pct = Column(Float, comment="涨跌幅%")
    vol = Column(Float, comment="成交量(手)")
    amount = Column(Float, comment="成交额(千元)")
    turnover_rate = Column(Float, comment="换手率%")
    ma5 = Column(Float, comment="5日均线")
    ma10 = Column(Float, comment="10日均线")
    ma20 = Column(Float, comment="20日均线")
    ma60 = Column(Float, comment="60日均线")


class Strategy(Base):
    """策略配置"""
    __tablename__ = "strategies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, comment="策略名称")
    description = Column(Text, comment="策略描述")
    strategy_type = Column(String(30), nullable=False, comment="策略类型:趋势/均值回归/动量/多因子")
    params = Column(JSON, default={}, comment="策略参数")
    status = Column(String(20), default="draft", comment="状态:draft/running/paused/stopped")
    stock_pool = Column(JSON, default=[], comment="股票池")
    run_schedule = Column(String(50), comment="运行时间: cron表达式")
    total_return = Column(Float, default=0.0, comment="累计收益率%")
    max_drawdown = Column(Float, default=0.0, comment="最大回撤%")
    win_rate = Column(Float, default=0.0, comment="胜率%")
    sharpe_ratio = Column(Float, default=0.0, comment="夏普比率")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class Trade(Base):
    """交易记录"""
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    strategy_id = Column(Integer, nullable=False, index=True, comment="策略ID")
    ts_code = Column(String(20), nullable=False, index=True, comment="股票代码")
    direction = Column(String(10), nullable=False, comment="方向:buy/sell")
    price = Column(Float, nullable=False, comment="成交价格")
    volume = Column(Integer, nullable=False, comment="成交数量")
    amount = Column(Float, comment="成交金额")
    commission = Column(Float, default=0.0, comment="手续费")
    profit = Column(Float, comment="盈亏金额")
    profit_pct = Column(Float, comment="盈亏比例%")
    signal = Column(String(50), comment="触发信号")
    trade_time = Column(DateTime, comment="交易时间")
    is_backtest = Column(Boolean, default=False, comment="是否回测交易")
    created_at = Column(DateTime, server_default=func.now())


class BacktestResult(Base):
    """回测结果"""
    __tablename__ = "backtest_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    strategy_id = Column(Integer, nullable=False, index=True)
    start_date = Column(String(10), nullable=False, comment="回测开始日期")
    end_date = Column(String(10), nullable=False, comment="回测结束日期")
    initial_cash = Column(Float, default=1000000.0, comment="初始资金")
    final_value = Column(Float, comment="最终资产")
    total_return = Column(Float, comment="总收益率%")
    annual_return = Column(Float, comment="年化收益率%")
    max_drawdown = Column(Float, comment="最大回撤%")
    sharpe_ratio = Column(Float, comment="夏普比率")
    win_rate = Column(Float, comment="胜率%")
    profit_loss_ratio = Column(Float, comment="盈亏比")
    total_trades = Column(Integer, comment="总交易次数")
    daily_returns = Column(JSON, comment="每日收益率序列")
    equity_curve = Column(JSON, comment="净值曲线")
    drawdown_curve = Column(JSON, comment="回撤曲线")
    created_at = Column(DateTime, server_default=func.now())


class Watchlist(Base):
    """关注列表"""
    __tablename__ = "watchlist"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ts_code = Column(String(20), nullable=False, unique=True, index=True, comment="股票/ETF代码")
    name = Column(String(50), comment="名称")
    asset_type = Column(String(10), default="stock", comment="类型:stock/etf")
    group_name = Column(String(30), default="默认", comment="分组名称")
    notes = Column(String(200), comment="备注")
    is_active = Column(Boolean, default=True, comment="是否关注")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class DailySignal(Base):
    """每日交易信号"""
    __tablename__ = "daily_signals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    signal_date = Column(String(10), nullable=False, index=True, comment="信号日期")
    ts_code = Column(String(20), nullable=False, index=True, comment="股票/ETF代码")
    action = Column(String(10), nullable=False, comment="操作:buy/sell/hold")
    price = Column(Float, comment="当前价格")
    stop_loss = Column(Float, comment="止损价")
    take_profit = Column(Float, comment="止盈价")
    strategies = Column(JSON, comment="触发策略列表")
    reasons = Column(JSON, comment="信号原因")
    urgency = Column(String(10), default="low", comment="紧急度:high/medium/low")
    score = Column(Float, default=0.0, comment="综合评分")
    is_executed = Column(Boolean, default=False, comment="是否已执行")
    created_at = Column(DateTime, server_default=func.now())


class ETFInfo(Base):
    """ETF基本信息"""
    __tablename__ = "etf_info"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ts_code = Column(String(20), unique=True, nullable=False, index=True, comment="ETF代码")
    name = Column(String(50), nullable=False, comment="ETF名称")
    fund_type = Column(String(20), comment="类型:指数/行业/商品/债券")
    tracking_index = Column(String(20), comment="跟踪指数代码")
    management_fee = Column(Float, comment="管理费率%")
    is_active = Column(Boolean, default=True, comment="是否活跃")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class RiskAlert(Base):
    """风控告警"""
    __tablename__ = "risk_alerts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    alert_type = Column(String(30), nullable=False, comment="告警类型:止损/仓位/波动/异常")
    level = Column(String(10), nullable=False, comment="级别:info/warning/critical")
    title = Column(String(200), nullable=False, comment="告警标题")
    detail = Column(Text, comment="告警详情")
    ts_code = Column(String(20), comment="关联股票")
    strategy_id = Column(Integer, comment="关联策略")
    is_read = Column(Boolean, default=False, comment="是否已读")
    is_resolved = Column(Boolean, default=False, comment="是否已处理")
    created_at = Column(DateTime, server_default=func.now())


class Position(Base):
    """持仓记录"""
    __tablename__ = "positions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ts_code = Column(String(20), nullable=False, index=True, comment="股票/ETF代码")
    symbol = Column(String(10), nullable=False, comment="股票代码")
    name = Column(String(50), comment="股票名称")
    direction = Column(String(10), nullable=False, comment="方向:long/short")
    volume = Column(Integer, nullable=False, comment="持仓数量")
    avg_cost = Column(Float, nullable=False, comment="平均成本")
    market_value = Column(Float, comment="市值")
    profit = Column(Float, default=0.0, comment="浮动盈亏")
    profit_pct = Column(Float, default=0.0, comment="盈亏比例%")
    current_price = Column(Float, comment="当前价格")
    strategy_id = Column(Integer, comment="关联策略ID")
    account_name = Column(String(50), default="main", comment="账户名称")
    is_active = Column(Boolean, default=True, comment="是否持仓中")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class Transaction(Base):
    """交易流水（实际买卖记录）"""
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    transaction_type = Column(String(20), nullable=False, comment="交易类型:buy/sell/deposit/withdraw")
    ts_code = Column(String(20), comment="股票/ETF代码")
    symbol = Column(String(10), comment="股票代码")
    name = Column(String(50), comment="股票名称")
    price = Column(Float, comment="成交价格")
    volume = Column(Integer, comment="成交数量")
    amount = Column(Float, nullable=False, comment="成交金额")
    commission = Column(Float, default=0.0, comment="手续费")
    tax = Column(Float, default=0.0, comment="印花税")
    net_amount = Column(Float, nullable=False, comment="净额")
    account_name = Column(String(50), default="main", comment="账户名称")
    strategy_id = Column(Integer, comment="关联策略ID")
    position_id = Column(Integer, comment="关联持仓ID")
    notes = Column(String(200), comment="备注")
    transaction_date = Column(DateTime, nullable=False, server_default=func.now(), comment="交易日期时间")
    created_at = Column(DateTime, server_default=func.now())


class Account(Base):
    """账户资金"""
    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50), nullable=False, unique=True, comment="账户名称")
    total_assets = Column(Float, nullable=False, comment="总资产")
    cash_balance = Column(Float, nullable=False, comment="现金余额")
    market_value = Column(Float, default=0.0, comment="市值")
    profit = Column(Float, default=0.0, comment="浮动盈亏")
    profit_pct = Column(Float, default=0.0, comment="盈亏比例%")
    max_drawdown = Column(Float, default=0.0, comment="最大回撤%")
    last_transaction_date = Column(DateTime, comment="最后交易日期")
    notes = Column(String(200), comment="备注")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
