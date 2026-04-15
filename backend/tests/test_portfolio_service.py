#!/usr/bin/env python3
"""
PortfolioService 测试脚本
用于测试持仓管理基本功能（本地SQLite版本）
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta
import random
import logging

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from sqlalchemy.orm import Session
from app.core.database import engine, SessionLocal
from app.models.models import Base, Position, Transaction, Account
from app.services.portfolio.portfolio_service import PortfolioService

def init_test_database():
    """初始化测试数据库"""
    print("🔧 初始化测试数据库...")
    Base.metadata.create_all(bind=engine)
    
def create_sample_account(db: Session, service: PortfolioService):
    """创建示例账户"""
    print("\n💰 创建示例账户...")
    
    # 创建账户
    account = Account(
        name="main",
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
    
    print(f"   账户 '{account.name}' 已创建")
    return account

def test_deposit_cash(db: Session, service: PortfolioService):
    """测试存入现金"""
    print("\n💵 测试存入现金...")
    
    # 存入初始现金
    transaction = service.deposit_cash(
        db=db,
        amount=1000000.0,  # 100万
        account_name="main",
        notes="初始资金"
    )
    
    print(f"   存入: ¥{transaction.amount:,.2f}")
    print(f"   交易ID: {transaction.id}")
    print(f"   时间: {transaction.transaction_date}")
    
    return transaction

def test_add_positions(db: Session, service: PortfolioService):
    """测试添加持仓"""
    print("\n📈 测试添加持仓...")
    
    # 创建几个示例持仓
    sample_stocks = [
        {"ts_code": "000001.SZ", "symbol": "000001", "name": "平安银行", "price": 12.5},
        {"ts_code": "000002.SZ", "symbol": "000002", "name": "万科A", "price": 8.7},
        {"ts_code": "600519.SH", "symbol": "600519", "name": "贵州茅台", "price": 1680.0},
        {"ts_code": "000858.SZ", "symbol": "000858", "name": "五粮液", "price": 140.5},
        {"ts_code": "002475.SZ", "symbol": "002475", "name": "立讯精密", "price": 32.8},
    ]
    
    positions = []
    for stock in sample_stocks:
        volume = random.randint(100, 5000)  # 随机数量
        position = service.add_position(
            db=db,
            ts_code=stock["ts_code"],
            symbol=stock["symbol"],
            name=stock["name"],
            direction="long",
            volume=volume,
            avg_cost=stock["price"] * random.uniform(0.9, 1.1),  # 随机成本
            account_name="main"
        )
        positions.append(position)
        print(f"   {stock['name']}({stock['symbol']}): {volume}股, 成本: ¥{position.avg_cost:.2f}")
    
    return positions

def test_update_prices(db: Session, service: PortfolioService, positions):
    """测试更新持仓价格"""
    print("\n📊 测试更新持仓价格...")
    
    updated_positions = []
    for position in positions:
        # 随机涨跌 0-5%
        price_change = random.uniform(0.95, 1.05)
        new_price = position.avg_cost * price_change
        
        updated = service.update_position_price(
            db=db,
            position_id=position.id,
            current_price=new_price
        )
        updated_positions.append(updated)
        
        profit_colored = f"+¥{updated.profit:,.2f}" if updated.profit >= 0 else f"-¥{abs(updated.profit):,.2f}"
        profit_pct_colored = f"+{updated.profit_pct:.2f}%" if updated.profit_pct >= 0 else f"{updated.profit_pct:.2f}%"
        
        print(f"   {updated.name}: ¥{updated.avg_cost:.2f} → ¥{new_price:.2f} ({profit_colored}, {profit_pct_colored})")
    
    return updated_positions

def test_get_summary(db: Session, service: PortfolioService):
    """测试获取持仓汇总"""
    print("\n📋 测试获取持仓汇总...")
    
    summary = service.get_position_summary(db, "main")
    
    print(f"   总持仓数量: {summary['total_positions']}")
    print(f"   总市值: ¥{summary['total_market_value']:,.2f}")
    print(f"   总成本: ¥{summary['total_cost']:,.2f}")
    print(f"   总盈亏: ¥{summary['total_profit']:,.2f}")
    print(f"   总盈亏比例: {summary['total_profit_pct']:.2f}%")
    
    print("\n   持仓详情:")
    for i, pos in enumerate(summary['positions'][:5], 1):  # 显示前5个
        profit_sign = "+" if pos['profit'] >= 0 else ""
        print(f"   {i}. {pos['name']}({pos['symbol']}): {pos['volume']}股, 盈亏: {profit_sign}{pos['profit']:,.2f} ({pos['profit_pct']:.2f}%)")
    
    return summary

def test_close_position(db: Session, service: PortfolioService, position_id: int):
    """测试平仓"""
    print(f"\n💱 测试平仓 (持仓ID: {position_id})...")
    
    # 获取当前持仓
    position = db.query(Position).filter(Position.id == position_id).first()
    if not position:
        print("   未找到持仓")
        return None
    
    # 平仓价格（稍微高于当前价）
    close_price = position.current_price * 1.03  # 涨3%卖出
    
    position, transaction = service.close_position(
        db=db,
        position_id=position_id,
        close_price=close_price,
        volume=None,  # 全部平仓
        transaction_type="sell",
        notes="测试卖出"
    )
    
    print(f"   {position.name}: {transaction.volume}股 @ ¥{close_price:.2f}")
    print(f"   成交金额: ¥{transaction.amount:,.2f}")
    print(f"   手续费: ¥{transaction.commission:,.2f}")
    print(f"   印花税: ¥{transaction.tax:,.2f}")
    print(f"   净额: ¥{transaction.net_amount:,.2f}")
    
    return transaction

def test_account_info(db: Session, service: PortfolioService):
    """测试账户信息"""
    print("\n🏦 测试账户信息...")
    
    account = service.get_account_info(db, "main")
    
    print(f"   账户名称: {account.name}")
    print(f"   总资产: ¥{account.total_assets:,.2f}")
    print(f"   现金余额: ¥{account.cash_balance:,.2f}")
    print(f"   持仓市值: ¥{account.market_value:,.2f}")
    print(f"   浮动盈亏: ¥{account.profit:,.2f}")
    print(f"   盈亏比例: {account.profit_pct:.2f}%")
    
    return account

def main():
    """主测试函数"""
    print("=" * 60)
    print("📦 PortfolioService 功能测试")
    print("=" * 60)
    
    # 初始化数据库
    init_test_database()
    
    # 创建服务实例
    service = PortfolioService()
    
    # 创建数据库会话
    db = SessionLocal()
    
    try:
        # 测试顺序
        test_deposit_cash(db, service)
        positions = test_add_positions(db, service)
        test_update_prices(db, service, positions)
        summary = test_get_summary(db, service)
        account = test_account_info(db, service)
        
        # 如果有关仓，测试一个持仓
        if positions:
            test_close_position(db, service, positions[0].id)
        
        # 测试后再次获取汇总
        summary_after = test_get_summary(db, service)
        account_after = test_account_info(db, service)
        
        print("\n" + "=" * 60)
        print("✅ 所有测试完成！")
        print("=" * 60)
        
    finally:
        db.close()

if __name__ == "__main__":
    main()