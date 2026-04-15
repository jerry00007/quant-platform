"""
同步4大核心策略的最优参数到数据库。

策略参数来源：全量2年回测验证（2024.04~2026.04）
运行方式：python sync_strategies.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from app.core.database import SessionLocal, init_db
from app.models.models import Strategy
from loguru import logger

# 4大核心策略 — 经过2年回测验证的最优参数
CORE_STRATEGIES = [
    {
        "name": "布林带上轨突破",
        "description": "布林带上轨突破策略：检测股价突破布林带上轨或接近上轨的信号。"
                       "2年回测收益-9.82%，作为市场热度指标参考，不建议单独使用。",
        "strategy_type": "均值回归",
        "params": {
            "period": 25,
            "std_mult": 2.0,
            "near_pct": 0.02,
        },
        "status": "running",
        "total_return": -9.82,
        "max_drawdown": 31.11,
        "win_rate": 29.0,
        "sharpe_ratio": -0.170,
    },
    {
        "name": "双均线交叉",
        "description": "双均线交叉策略：短期均线上穿长期均线买入，下穿卖出。"
                       "2年回测收益+52.53%，夏普0.729，回撤28.21%。",
        "strategy_type": "趋势",
        "params": {
            "short_period": 7,
            "long_period": 40,
        },
        "status": "running",
        "total_return": 52.53,
        "max_drawdown": 28.21,
        "win_rate": 38.4,
        "sharpe_ratio": 0.729,
    },
    {
        "name": "增强筹码策略",
        "description": "增强筹码策略：基于ZLCMQ筹码指标，结合量能放大和趋势确认。"
                       "2年回测收益+17.57%，夏普0.388，回撤13.23%，风险收益比较优。",
        "strategy_type": "TDX指标",
        "params": {
            "n_days": 5,
            "min_high": 98,
            "min_fall": 5,
        },
        "status": "running",
        "total_return": 17.57,
        "max_drawdown": 13.23,
        "win_rate": 44.6,
        "sharpe_ratio": 0.388,
    },
    {
        "name": "强势股回调企稳",
        "description": "强势股回调企稳策略：ZLCMQ达到高位后回调，满足5选3企稳条件买入。"
                       "2年回测收益+82.07%，夏普1.459，回撤15.35%，综合排名第一。",
        "strategy_type": "TDX指标",
        "params": {
            "n_days": 8,
            "min_high": 95,
            "min_fall": 5,
        },
        "status": "running",
        "total_return": 82.07,
        "max_drawdown": 15.35,
        "win_rate": 48.8,
        "sharpe_ratio": 1.459,
    },
]


def sync_strategies():
    """同步策略参数到数据库"""
    init_db()
    db = SessionLocal()

    try:
        synced = 0
        updated = 0

        for s in CORE_STRATEGIES:
            existing = db.query(Strategy).filter(Strategy.name == s["name"]).first()

            if existing:
                # 更新已有策略的参数和绩效
                existing.params = s["params"]
                existing.total_return = s["total_return"]
                existing.max_drawdown = s["max_drawdown"]
                existing.win_rate = s["win_rate"]
                existing.sharpe_ratio = s["sharpe_ratio"]
                existing.description = s["description"]
                existing.status = s["status"]
                updated += 1
                logger.info(f"  ✅ 更新策略: {s['name']}")
            else:
                # 创建新策略
                new_strategy = Strategy(
                    name=s["name"],
                    description=s["description"],
                    strategy_type=s["strategy_type"],
                    params=s["params"],
                    status=s["status"],
                    total_return=s["total_return"],
                    max_drawdown=s["max_drawdown"],
                    win_rate=s["win_rate"],
                    sharpe_ratio=s["sharpe_ratio"],
                )
                db.add(new_strategy)
                synced += 1
                logger.info(f"  🆕 新增策略: {s['name']}")

        db.commit()
        logger.info(f"\n策略同步完成: 新增 {synced} 个, 更新 {updated} 个")

        # 打印确认
        all_strategies = db.query(Strategy).all()
        logger.info(f"\n数据库中共有 {len(all_strategies)} 个策略:")
        for st in all_strategies:
            logger.info(f"  [{st.id}] {st.name} | {st.strategy_type} | "
                       f"收益{st.total_return:+.1f}% | 夏普{st.sharpe_ratio:.3f} | "
                       f"参数: {st.params}")

    except Exception as e:
        db.rollback()
        logger.error(f"策略同步失败: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    sync_strategies()
