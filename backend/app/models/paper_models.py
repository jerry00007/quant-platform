"""
QuantWeave — 模拟盘数据模型

完全独立的表结构，与真实交易的 positions / transactions 零耦合。
表名前缀 paper_ 确保不会与任何现有代码冲突。
"""
from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Text
from sqlalchemy.sql import func
from ..core.database import Base


class PaperAccount(Base):
    """模拟盘账户资金"""
    __tablename__ = "paper_account"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50), nullable=False, unique=True, default="ultra_short", comment="账户标识")
    total_assets = Column(Float, nullable=False, default=700000.0, comment="总资产")
    cash_balance = Column(Float, nullable=False, default=700000.0, comment="可用现金")
    initial_capital = Column(Float, nullable=False, default=700000.0, comment="初始资金")
    total_profit = Column(Float, default=0.0, comment="累计盈亏")
    total_profit_pct = Column(Float, default=0.0, comment="累计收益率%")
    max_drawdown = Column(Float, default=0.0, comment="最大回撤%")
    peak_assets = Column(Float, default=700000.0, comment="历史最高总资产")
    total_trades = Column(Integer, default=0, comment="总交易次数")
    win_trades = Column(Integer, default=0, comment="盈利次数")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class PaperPosition(Base):
    """模拟盘持仓"""
    __tablename__ = "paper_positions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ts_code = Column(String(20), nullable=False, index=True, comment="股票代码")
    name = Column(String(50), comment="股票名称")
    volume = Column(Integer, nullable=False, comment="持仓数量")
    avg_cost = Column(Float, nullable=False, comment="买入均价")
    current_price = Column(Float, comment="当前价格")
    market_value = Column(Float, comment="市值")
    profit = Column(Float, default=0.0, comment="浮动盈亏")
    profit_pct = Column(Float, default=0.0, comment="盈亏比例%")
    mode = Column(String(20), nullable=False, comment="选股模式: mode1/mode2/mode3")
    mode_name = Column(String(30), comment="模式中文名")
    score = Column(Integer, default=0, comment="选股评分")
    limit_up_close = Column(Float, default=0.0, comment="涨停日收盘价(止损参考)")
    limit_up_low = Column(Float, default=0.0, comment="涨停日最低价(破位止损)")
    peak_price = Column(Float, comment="持仓期间最高价(移动止盈)")
    partial_sold = Column(Boolean, default=False, comment="是否已分批卖出")
    entry_date = Column(String(10), comment="建仓日期 YYYYMMDD")
    hold_days = Column(Integer, default=0, comment="持有天数")
    is_active = Column(Boolean, default=True, index=True, comment="是否持仓中")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class PaperTrade(Base):
    """模拟盘交易记录"""
    __tablename__ = "paper_trades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ts_code = Column(String(20), nullable=False, index=True, comment="股票代码")
    name = Column(String(50), comment="股票名称")
    direction = Column(String(10), nullable=False, comment="方向: buy/sell")
    price = Column(Float, nullable=False, comment="成交价格")
    volume = Column(Integer, nullable=False, comment="成交数量")
    amount = Column(Float, comment="成交金额")
    commission = Column(Float, default=0.0, comment="手续费")
    tax = Column(Float, default=0.0, comment="印花税")
    net_amount = Column(Float, comment="净额")
    profit = Column(Float, comment="盈亏金额(卖出时)")
    profit_pct = Column(Float, comment="盈亏比例%(卖出时)")
    mode = Column(String(20), comment="选股模式")
    mode_name = Column(String(30), comment="模式中文名")
    score = Column(Integer, comment="选股评分")
    reason = Column(String(200), comment="交易原因/信号")
    trade_date = Column(String(10), comment="交易日期 YYYYMMDD")
    created_at = Column(DateTime, server_default=func.now())
