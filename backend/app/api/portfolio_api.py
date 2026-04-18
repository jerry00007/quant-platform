"""
Portfolio API - 持仓管理相关接口
提供持仓、账户、交易流水等管理功能
"""

from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from ..core.database import get_db
from ..services.portfolio.portfolio_service import portfolio_service

# Pydantic模型定义
class PositionCreate(BaseModel):
    """创建持仓请求模型"""
    ts_code: str = Field(..., description="股票代码（TS格式）")
    symbol: str = Field(..., description="股票代码")
    name: str = Field(..., description="股票名称")
    direction: str = Field("long", description="方向：long/short", pattern="^(long|short)$")
    volume: int = Field(..., description="持仓数量", gt=0)
    avg_cost: float = Field(..., description="平均成本", gt=0)
    strategy_id: Optional[int] = Field(None, description="关联策略ID")
    account_name: str = Field("main", description="账户名称")

class PositionUpdate(BaseModel):
    """更新持仓价格请求模型"""
    current_price: float = Field(..., description="当前价格", gt=0)

class ClosePositionRequest(BaseModel):
    """平仓请求模型"""
    close_price: float = Field(..., description="平仓价格", gt=0)
    volume: Optional[int] = Field(None, description="平仓数量（None表示全部）")
    transaction_type: str = Field("sell", description="交易类型", pattern="^(sell|cover)$")
    strategy_id: Optional[int] = Field(None, description="关联策略ID")
    notes: str = Field("", description="备注")

class DepositRequest(BaseModel):
    """存入现金请求模型"""
    amount: float = Field(..., description="存入金额", gt=0)
    account_name: str = Field("main", description="账户名称")
    notes: str = Field("", description="备注")

class WithdrawRequest(BaseModel):
    """提取现金请求模型"""
    amount: float = Field(..., description="提取金额", gt=0)
    account_name: str = Field("main", description="账户名称")
    notes: str = Field("", description="备注")


router = APIRouter(prefix="/portfolio", tags=["portfolio"])


@router.get("/health")
async def portfolio_health(db: Session = Depends(get_db)):
    """检查持仓服务健康状态（SQLite）"""
    try:
        # 检查SQLite数据库连接
        from sqlalchemy import text
        result = db.execute(text("SELECT COUNT(*) FROM positions WHERE is_active = 1")).scalar()
        
        return {
            "status": "healthy",
            "db_type": "SQLite",
            "active_positions": result,
            "message": "Portfolio service is running"
        }
    except Exception as e:
        return {
            "status": "degraded",
            "error": str(e),
            "message": "Portfolio service running but DB check failed"
        }


@router.post("/positions", response_model=Dict[str, Any])
async def create_position(
    position_data: PositionCreate,
    db: Session = Depends(get_db)
):
    """创建持仓"""
    try:
        position = portfolio_service.add_position(
            db=db,
            ts_code=position_data.ts_code,
            symbol=position_data.symbol,
            name=position_data.name,
            direction=position_data.direction,
            volume=position_data.volume,
            avg_cost=position_data.avg_cost,
            strategy_id=position_data.strategy_id,
            account_name=position_data.account_name
        )
        
        return {
            "success": True,
            "message": "持仓创建成功",
            "data": {
                "id": position.id,
                "ts_code": position.ts_code,
                "name": position.name,
                "volume": position.volume,
                "avg_cost": position.avg_cost,
                "market_value": position.market_value
            }
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"创建持仓失败: {str(e)}"
        )


@router.get("/positions", response_model=Dict[str, Any])
async def get_positions(
    account_name: str = "main",
    db: Session = Depends(get_db)  # 改用SQLite本地数据库
):
    """获取持仓汇总"""
    try:
        summary = portfolio_service.get_position_summary(db, account_name)
        return {
            "success": True,
            "data": summary
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"获取持仓失败: {str(e)}"
        )


@router.put("/positions/{position_id}", response_model=Dict[str, Any])
async def update_position_price(
    position_id: int,
    price_data: PositionUpdate,
    db: Session = Depends(get_db)
):
    """更新持仓价格"""
    try:
        position = portfolio_service.update_position_price(
            db=db,
            position_id=position_id,
            current_price=price_data.current_price
        )
        
        return {
            "success": True,
            "message": "持仓价格更新成功",
            "data": {
                "id": position.id,
                "ts_code": position.ts_code,
                "current_price": position.current_price,
                "profit": position.profit,
                "profit_pct": position.profit_pct
            }
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"更新持仓价格失败: {str(e)}"
        )


@router.post("/positions/{position_id}/close", response_model=Dict[str, Any])
async def close_position(
    position_id: int,
    close_request: ClosePositionRequest,
    db: Session = Depends(get_db)
):
    """平仓"""
    try:
        position, transaction = portfolio_service.close_position(
            db=db,
            position_id=position_id,
            close_price=close_request.close_price,
            volume=close_request.volume,
            transaction_type=close_request.transaction_type,
            strategy_id=close_request.strategy_id,
            notes=close_request.notes
        )
        
        return {
            "success": True,
            "message": "平仓成功",
            "data": {
                "position": {
                    "id": position.id,
                    "ts_code": position.ts_code,
                    "is_active": position.is_active,
                    "remaining_volume": position.volume,
                    "market_value": position.market_value
                },
                "transaction": {
                    "id": transaction.id,
                    "net_amount": transaction.net_amount,
                    "commission": transaction.commission,
                    "tax": transaction.tax,
                    "transaction_date": transaction.transaction_date.isoformat()
                }
            }
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"平仓失败: {str(e)}"
        )


@router.post("/sync", response_model=Dict[str, Any])
async def sync_positions(
    account_name: str = "main",
    db: Session = Depends(get_db)
):
    """同步持仓与市场价格"""
    try:
        updated_positions = portfolio_service.sync_positions_with_market(db, account_name)
        
        return {
            "success": True,
            "message": f"同步完成，更新了 {len(updated_positions)} 个持仓",
            "data": {
                "updated_count": len(updated_positions),
                "positions": [
                    {
                        "id": p.id,
                        "ts_code": p.ts_code,
                        "current_price": p.current_price,
                        "profit": p.profit,
                        "profit_pct": p.profit_pct
                    }
                    for p in updated_positions
                ]
            }
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"同步持仓失败: {str(e)}"
        )


@router.get("/account/{account_name}", response_model=Dict[str, Any])
async def get_account_info(
    account_name: str = "main",
    db: Session = Depends(get_db)
):
    """获取账户信息"""
    try:
        account = portfolio_service.get_account_info(db, account_name)
        
        return {
            "success": True,
            "data": {
                "id": account.id,
                "name": account.name,
                "total_assets": account.total_assets,
                "cash_balance": account.cash_balance,
                "market_value": account.market_value,
                "profit": account.profit,
                "profit_pct": account.profit_pct,
                "max_drawdown": account.max_drawdown,
                "last_transaction_date": account.last_transaction_date.isoformat() if account.last_transaction_date else None,
                "created_at": account.created_at.isoformat() if account.created_at else None,
                "updated_at": account.updated_at.isoformat() if account.updated_at else None
            }
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"获取账户信息失败: {str(e)}"
        )


@router.post("/deposit", response_model=Dict[str, Any])
async def deposit_cash(
    deposit_data: DepositRequest,
    db: Session = Depends(get_db)
):
    """存入现金"""
    try:
        transaction = portfolio_service.deposit_cash(
            db=db,
            amount=deposit_data.amount,
            account_name=deposit_data.account_name,
            notes=deposit_data.notes
        )
        
        return {
            "success": True,
            "message": "现金存入成功",
            "data": {
                "id": transaction.id,
                "amount": transaction.amount,
                "net_amount": transaction.net_amount,
                "account_name": transaction.account_name,
                "transaction_date": transaction.transaction_date.isoformat()
            }
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"存入现金失败: {str(e)}"
        )


@router.post("/withdraw", response_model=Dict[str, Any])
async def withdraw_cash(
    withdraw_data: WithdrawRequest,
    db: Session = Depends(get_db)
):
    """提取现金"""
    try:
        transaction = portfolio_service.withdraw_cash(
            db=db,
            amount=withdraw_data.amount,
            account_name=withdraw_data.account_name,
            notes=withdraw_data.notes
        )
        
        return {
            "success": True,
            "message": "现金提取成功",
            "data": {
                "id": transaction.id,
                "amount": transaction.amount,
                "net_amount": transaction.net_amount,
                "account_name": transaction.account_name,
                "transaction_date": transaction.transaction_date.isoformat()
            }
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"提取现金失败: {str(e)}"
        )


@router.get("/transactions", response_model=Dict[str, Any])
async def get_transactions(
    account_name: str = "main",
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db)
):
    """获取交易流水"""
    try:
        from ..models.models import Transaction
        
        # 查询交易流水
        query = db.query(Transaction).filter(Transaction.account_name == account_name)
        total = query.count()
        
        transactions = query.order_by(
            Transaction.transaction_date.desc()
        ).offset(offset).limit(limit).all()
        
        return {
            "success": True,
            "data": {
                "total": total,
                "transactions": [
                    {
                        "id": t.id,
                        "transaction_type": t.transaction_type,
                        "ts_code": t.ts_code,
                        "symbol": t.symbol,
                        "name": t.name,
                        "price": t.price,
                        "volume": t.volume,
                        "amount": t.amount,
                        "commission": t.commission,
                        "tax": t.tax,
                        "net_amount": t.net_amount,
                        "account_name": t.account_name,
                        "strategy_id": t.strategy_id,
                        "position_id": t.position_id,
                        "notes": t.notes,
                        "transaction_date": t.transaction_date.isoformat() if t.transaction_date else None,
                        "created_at": t.created_at.isoformat() if t.created_at else None
                    }
                    for t in transactions
                ]
            }
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"获取交易流水失败: {str(e)}"
        )