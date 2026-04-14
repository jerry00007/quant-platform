"""
PortfolioService - 持仓管理服务
负责持仓管理、交易流水、账户资金、盈亏计算等核心功能
"""

from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, date
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func, desc
import pandas as pd
import numpy as np

from app.models.models import Position, Transaction, Account
from app.models.models import StockDaily
from app.core.nas_config import get_nas_db, get_nas_redis

import logging
logger = logging.getLogger(__name__)


class PortfolioService:
    """持仓管理服务"""
    
    def __init__(self):
        self._redis = None
    
    @property
    def redis(self):
        """获取Redis连接（懒加载）"""
        if self._redis is None:
            self._redis = get_nas_redis()
        return self._redis
    
    def add_position(
        self, 
        db: Session,
        ts_code: str,
        symbol: str,
        name: str,
        direction: str,
        volume: int,
        avg_cost: float,
        strategy_id: Optional[int] = None,
        account_name: str = "main"
    ) -> Position:
        """
        添加持仓
        
        Args:
            db: 数据库会话
            ts_code: 股票代码（TS格式）
            symbol: 股票代码
            name: 股票名称
            direction: 方向（long/short）
            volume: 持仓数量
            avg_cost: 平均成本
            strategy_id: 关联策略ID
            account_name: 账户名称
        
        Returns:
            Position: 创建的持仓记录
        """
        try:
            position = Position(
                ts_code=ts_code,
                symbol=symbol,
                name=name,
                direction=direction,
                volume=volume,
                avg_cost=avg_cost,
                market_value=volume * avg_cost,
                profit=0.0,
                profit_pct=0.0,
                current_price=avg_cost,
                strategy_id=strategy_id,
                account_name=account_name,
                is_active=True
            )
            
            db.add(position)
            db.commit()
            db.refresh(position)
            
            # 更新账户市值
            self._update_account_market_value(db, account_name)
            
            logger.info(f"持仓添加成功: {ts_code} {name}, 数量: {volume}, 成本: {avg_cost}")
            return position
            
        except Exception as e:
            db.rollback()
            logger.error(f"添加持仓失败: {str(e)}")
            raise
    
    def update_position_price(
        self,
        db: Session,
        position_id: int,
        current_price: float
    ) -> Position:
        """
        更新持仓价格并计算盈亏
        
        Args:
            db: 数据库会话
            position_id: 持仓ID
            current_price: 当前价格
        
        Returns:
            Position: 更新后的持仓记录
        """
        try:
            position = db.query(Position).filter(
                Position.id == position_id,
                Position.is_active == True
            ).first()
            
            if not position:
                raise ValueError(f"未找到持仓记录 ID: {position_id}")
            
            position.current_price = current_price
            position.market_value = position.volume * current_price
            
            # 计算盈亏
            if position.direction == "long":
                position.profit = (current_price - position.avg_cost) * position.volume
                if position.avg_cost > 0:
                    position.profit_pct = (position.profit / (position.avg_cost * position.volume)) * 100
                else:
                    position.profit_pct = 0.0
            else:
                # 空头持仓（暂不支持）
                position.profit = 0.0
                position.profit_pct = 0.0
            
            position.updated_at = datetime.utcnow()
            
            db.commit()
            db.refresh(position)
            
            # 更新账户盈亏
            self._update_account_profit(db, position.account_name)
            
            logger.info(f"持仓价格更新: {position.ts_code}, 当前价: {current_price}, 盈亏: {position.profit:.2f}")
            return position
            
        except Exception as e:
            db.rollback()
            logger.error(f"更新持仓价格失败: {str(e)}")
            raise
    
    def close_position(
        self,
        db: Session,
        position_id: int,
        close_price: float,
        volume: Optional[int] = None,
        transaction_type: str = "sell",
        strategy_id: Optional[int] = None,
        notes: str = ""
    ) -> Tuple[Position, Transaction]:
        """
        平仓（全部或部分）
        
        Args:
            db: 数据库会话
            position_id: 持仓ID
            close_price: 平仓价格
            volume: 平仓数量（None表示全部平仓）
            transaction_type: 交易类型（sell）
            strategy_id: 关联策略ID
            notes: 备注
        
        Returns:
            Tuple[Position, Transaction]: (更新后的持仓记录, 交易流水)
        """
        try:
            position = db.query(Position).filter(
                Position.id == position_id,
                Position.is_active == True
            ).first()
            
            if not position:
                raise ValueError(f"未找到持仓记录 ID: {position_id}")
            
            # 确定平仓数量
            if volume is None or volume >= position.volume:
                close_volume = position.volume
                position.is_active = False
                position.volume = 0
            else:
                close_volume = volume
                position.volume -= volume
            
            # 计算成交金额
            amount = close_volume * close_price
            commission = amount * 0.0003  # 万三手续费
            tax = amount * 0.001 if transaction_type == "sell" else 0.0  # 卖出千一印花税
            net_amount = amount - commission - tax
            
            # 创建交易流水
            transaction = Transaction(
                transaction_type=transaction_type,
                ts_code=position.ts_code,
                symbol=position.symbol,
                name=position.name,
                price=close_price,
                volume=close_volume,
                amount=amount,
                commission=commission,
                tax=tax,
                net_amount=net_amount,
                account_name=position.account_name,
                strategy_id=strategy_id or position.strategy_id,
                position_id=position_id,
                notes=notes,
                transaction_date=datetime.utcnow()
            )
            
            # 更新持仓
            if position.volume == 0:
                position.is_active = False
                position.market_value = 0
                position.profit = 0
                position.profit_pct = 0
            else:
                # 部分平仓，重新计算平均成本（先进先出法简化）
                remaining_cost = position.avg_cost * position.volume
                position.market_value = position.volume * close_price
                position.profit = (close_price - position.avg_cost) * position.volume
                if remaining_cost > 0:
                    position.profit_pct = (position.profit / remaining_cost) * 100
            
            position.updated_at = datetime.utcnow()
            
            # 更新账户现金余额
            self._update_account_cash(db, position.account_name, net_amount, transaction_type)
            
            # 保存更改
            db.add(transaction)
            db.commit()
            db.refresh(position)
            db.refresh(transaction)
            
            logger.info(f"持仓平仓: {position.ts_code}, 数量: {close_volume}, 价格: {close_price}, 净额: {net_amount:.2f}")
            return position, transaction
            
        except Exception as e:
            db.rollback()
            logger.error(f"平仓失败: {str(e)}")
            raise
    
    def get_position_summary(self, db: Session, account_name: str = "main") -> Dict[str, Any]:
        """
        获取持仓汇总
        
        Args:
            db: 数据库会话
            account_name: 账户名称
        
        Returns:
            Dict[str, Any]: 持仓汇总信息
        """
        try:
            # 获取活跃持仓
            positions = db.query(Position).filter(
                Position.account_name == account_name,
                Position.is_active == True
            ).all()
            
            if not positions:
                return {
                    "total_positions": 0,
                    "total_market_value": 0,
                    "total_profit": 0,
                    "total_profit_pct": 0,
                    "positions": []
                }
            
            # 计算汇总
            total_market_value = sum(p.market_value or 0 for p in positions)
            total_cost = sum(p.avg_cost * p.volume for p in positions)
            total_profit = sum(p.profit or 0 for p in positions)
            
            if total_cost > 0:
                total_profit_pct = (total_profit / total_cost) * 100
            else:
                total_profit_pct = 0.0
            
            # 按盈亏排序
            positions_sorted = sorted(positions, key=lambda x: x.profit_pct or 0, reverse=True)
            
            return {
                "total_positions": len(positions),
                "total_market_value": total_market_value,
                "total_cost": total_cost,
                "total_profit": total_profit,
                "total_profit_pct": total_profit_pct,
                "positions": [
                    {
                        "id": p.id,
                        "ts_code": p.ts_code,
                        "symbol": p.symbol,
                        "name": p.name,
                        "direction": p.direction,
                        "volume": p.volume,
                        "avg_cost": p.avg_cost,
                        "current_price": p.current_price,
                        "market_value": p.market_value,
                        "profit": p.profit,
                        "profit_pct": p.profit_pct,
                        "strategy_id": p.strategy_id,
                        "created_at": p.created_at.isoformat() if p.created_at else None
                    }
                    for p in positions_sorted
                ]
            }
            
        except Exception as e:
            logger.error(f"获取持仓汇总失败: {str(e)}")
            raise
    
    def sync_positions_with_market(self, db: Session, account_name: str = "main") -> List[Position]:
        """
        同步持仓与市场价格
        
        Args:
            db: 数据库会话
            account_name: 账户名称
        
        Returns:
            List[Position]: 更新后的持仓列表
        """
        try:
            positions = db.query(Position).filter(
                Position.account_name == account_name,
                Position.is_active == True
            ).all()
            
            if not positions:
                return []
            
            updated_positions = []
            ts_codes = [p.ts_code for p in positions]
            
            # 获取最新价格（这里需要调用行情服务，暂时使用占位逻辑）
            for position in positions:
                try:
                    # TODO: 这里需要集成行情服务获取实时价格
                    # 暂时使用最近一个交易日的收盘价
                    daily_data = db.query(StockDaily).filter(
                        StockDaily.ts_code == position.ts_code
                    ).order_by(desc(StockDaily.trade_date)).first()
                    
                    if daily_data:
                        current_price = daily_data.close
                        updated_position = self.update_position_price(db, position.id, current_price)
                        updated_positions.append(updated_position)
                    else:
                        logger.warning(f"未找到 {position.ts_code} 的行情数据")
                
                except Exception as e:
                    logger.error(f"同步持仓 {position.ts_code} 价格失败: {str(e)}")
                    continue
            
            logger.info(f"已同步 {len(updated_positions)} 个持仓的价格")
            return updated_positions
            
        except Exception as e:
            logger.error(f"同步持仓价格失败: {str(e)}")
            raise
    
    def get_account_info(self, db: Session, account_name: str = "main") -> Account:
        """
        获取账户信息（不存在则创建）
        
        Args:
            db: 数据库会话
            account_name: 账户名称
        
        Returns:
            Account: 账户信息
        """
        try:
            account = db.query(Account).filter(Account.name == account_name).first()
            
            if not account:
                # 创建默认账户
                account = Account(
                    name=account_name,
                    total_assets=0.0,
                    cash_balance=0.0,
                    market_value=0.0,
                    profit=0.0,
                    profit_pct=0.0,
                    max_drawdown=0.0
                )
                db.add(account)
                db.commit()
                db.refresh(account)
            
            # 更新账户数据
            self._update_account_summary(db, account_name)
            
            return account
            
        except Exception as e:
            db.rollback()
            logger.error(f"获取账户信息失败: {str(e)}")
            raise
    
    def deposit_cash(self, db: Session, amount: float, account_name: str = "main", notes: str = "") -> Transaction:
        """
        存入现金
        
        Args:
            db: 数据库会话
            amount: 存入金额
            account_name: 账户名称
            notes: 备注
        
        Returns:
            Transaction: 交易流水
        """
        try:
            # 创建存款交易
            transaction = Transaction(
                transaction_type="deposit",
                amount=amount,
                net_amount=amount,
                account_name=account_name,
                notes=notes,
                transaction_date=datetime.utcnow()
            )
            
            # 更新账户现金余额
            account = self.get_account_info(db, account_name)
            account.cash_balance += amount
            account.total_assets += amount
            account.updated_at = datetime.utcnow()
            
            db.add(transaction)
            db.commit()
            db.refresh(transaction)
            
            logger.info(f"现金存入: {amount:.2f}, 账户: {account_name}")
            return transaction
            
        except Exception as e:
            db.rollback()
            logger.error(f"存入现金失败: {str(e)}")
            raise
    
    def withdraw_cash(self, db: Session, amount: float, account_name: str = "main", notes: str = "") -> Transaction:
        """
        提取现金
        
        Args:
            db: 数据库会话
            amount: 提取金额
            account_name: 账户名称
            notes: 备注
        
        Returns:
            Transaction: 交易流水
        """
        try:
            account = self.get_account_info(db, account_name)
            
            if account.cash_balance < amount:
                raise ValueError(f"账户余额不足: {account.cash_balance:.2f} < {amount:.2f}")
            
            # 创建取款交易
            transaction = Transaction(
                transaction_type="withdraw",
                amount=amount,
                net_amount=-amount,
                account_name=account_name,
                notes=notes,
                transaction_date=datetime.utcnow()
            )
            
            # 更新账户现金余额
            account.cash_balance -= amount
            account.total_assets -= amount
            account.updated_at = datetime.utcnow()
            
            db.add(transaction)
            db.commit()
            db.refresh(transaction)
            
            logger.info(f"现金提取: {amount:.2f}, 账户: {account_name}")
            return transaction
            
        except Exception as e:
            db.rollback()
            logger.error(f"提取现金失败: {str(e)}")
            raise
    
    def _update_account_market_value(self, db: Session, account_name: str):
        """更新账户市值"""
        try:
            account = db.query(Account).filter(Account.name == account_name).first()
            if not account:
                return
            
            positions = db.query(Position).filter(
                Position.account_name == account_name,
                Position.is_active == True
            ).all()
            
            market_value = sum(p.market_value or 0 for p in positions)
            account.market_value = market_value
            account.total_assets = account.cash_balance + market_value
            account.updated_at = datetime.utcnow()
            
            db.commit()
            
        except Exception as e:
            logger.error(f"更新账户市值失败: {str(e)}")
    
    def _update_account_profit(self, db: Session, account_name: str):
        """更新账户盈亏"""
        try:
            account = db.query(Account).filter(Account.name == account_name).first()
            if not account:
                return
            
            positions = db.query(Position).filter(
                Position.account_name == account_name,
                Position.is_active == True
            ).all()
            
            total_profit = sum(p.profit or 0 for p in positions)
            total_cost = sum(p.avg_cost * p.volume for p in positions)
            
            account.profit = total_profit
            if total_cost > 0:
                account.profit_pct = (total_profit / total_cost) * 100
            else:
                account.profit_pct = 0.0
            
            account.updated_at = datetime.utcnow()
            db.commit()
            
        except Exception as e:
            logger.error(f"更新账户盈亏失败: {str(e)}")
    
    def _update_account_cash(self, db: Session, account_name: str, net_amount: float, transaction_type: str):
        """更新账户现金"""
        try:
            account = db.query(Account).filter(Account.name == account_name).first()
            if not account:
                return
            
            if transaction_type == "buy":
                account.cash_balance -= net_amount  # 买入花钱
            elif transaction_type == "sell":
                account.cash_balance += net_amount  # 卖出入账
            elif transaction_type == "deposit":
                account.cash_balance += net_amount
            elif transaction_type == "withdraw":
                account.cash_balance -= net_amount
            
            account.updated_at = datetime.utcnow()
            db.commit()
            
        except Exception as e:
            logger.error(f"更新账户现金失败: {str(e)}")
    
    def _update_account_summary(self, db: Session, account_name: str):
        """更新账户汇总信息"""
        try:
            account = db.query(Account).filter(Account.name == account_name).first()
            if not account:
                return
            
            # 更新市值和盈亏
            self._update_account_market_value(db, account_name)
            self._update_account_profit(db, account_name)
            
            # 更新最后交易日期
            last_transaction = db.query(Transaction).filter(
                Transaction.account_name == account_name
            ).order_by(desc(Transaction.transaction_date)).first()
            
            if last_transaction:
                account.last_transaction_date = last_transaction.transaction_date
            
            account.updated_at = datetime.utcnow()
            db.commit()
            
        except Exception as e:
            logger.error(f"更新账户汇总失败: {str(e)}")


# 全局服务实例
portfolio_service = PortfolioService()