"""
QuantWeave - Pydantic 请求/响应模型
用于 API 端点的请求体验证
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any


# ========== 策略管理 ==========

class StrategyCreate(BaseModel):
    """创建策略请求"""
    name: str = Field(..., min_length=1, max_length=100, description="策略名称")
    description: Optional[str] = Field("", max_length=500, description="策略描述")
    strategy_type: str = Field(..., min_length=1, description="策略类型，如 dual_ma")
    params: Optional[Dict[str, Any]] = Field(default_factory=dict, description="策略参数")
    stock_pool: Optional[List[str]] = Field(default_factory=list, description="股票池")


class StrategyUpdate(BaseModel):
    """更新策略请求"""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    strategy_type: Optional[str] = None
    params: Optional[Dict[str, Any]] = None
    stock_pool: Optional[List[str]] = None


class StrategyStatusUpdate(BaseModel):
    """切换策略状态请求"""
    status: str = Field(..., pattern=r"^(draft|running|paused|stopped)$", description="目标状态")


# ========== 回测 ==========

class BacktestRequest(BaseModel):
    """执行回测请求"""
    mode: Optional[str] = Field("single", pattern=r"^(single|market|quick_picks)$", description="回测模式")
    strategy: Optional[str] = Field(None, description="单股票模式的策略类型")
    strategy_type: Optional[str] = Field(None, description="策略类型（备用字段）")
    ts_code: Optional[str] = Field(None, description="单股票模式的股票代码")
    strategies: Optional[List[str]] = Field(None, description="全市场模式的策略列表")
    start_date: str = Field(..., min_length=8, max_length=8, description="开始日期 YYYYMMDD")
    end_date: str = Field(..., min_length=8, max_length=8, description="结束日期 YYYYMMDD")
    initial_cash: Optional[float] = Field(1000000, gt=0, description="初始资金")
    position_ratio: Optional[float] = Field(1.0, gt=0, le=1.0, description="仓位比例")
    max_positions: Optional[int] = Field(10, ge=1, le=50, description="最大持仓数")
    position_per_stock: Optional[float] = Field(0.2, gt=0, le=1.0, description="单只仓位")
    stop_loss: Optional[str] = Field(None, description="止损比例")
    take_profit: Optional[str] = Field(None, description="止盈比例")
    stop_loss_pct: Optional[float] = Field(-0.08, description="全市场止损")
    take_profit_pct: Optional[float] = Field(0.15, description="全市场止盈")
    stock_limit: Optional[int] = Field(200, ge=1, le=5000, description="扫描股票数")
    strategy_params: Optional[Dict[str, Any]] = None
    strategy_id: Optional[int] = Field(0, description="关联策略ID")
    commission: Optional[float] = Field(0.0003, ge=0)
    slippage: Optional[float] = Field(0.001, ge=0)
    rebalance_interval: Optional[int] = Field(1, ge=1)
    max_hold_days: Optional[int] = Field(None, ge=5, le=120, description="一键选股最大持仓天数")


# ========== 报告导出 ==========

class ExportRequest(BaseModel):
    """导出报告请求"""
    results: Optional[Dict[str, Any]] = Field(None, description="直接传入回测结果")
    backtest_ids: Optional[List[int]] = Field(default_factory=list, description="从数据库拉取的回测ID")
    filename: Optional[str] = Field(None, max_length=200, description="自定义文件名")
