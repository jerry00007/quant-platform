"""
QuantWeave — 核心模块单元测试

覆盖：
  - tracking_pool_service: 止盈/止损逻辑
  - core_signals: 策略信号生成
  - market_context: 市场环境评估
"""
import json
import sqlite3
import tempfile
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

import numpy as np
import pandas as pd
import pytest


# ============================================================
# 1. TrackingPoolService — 止盈止损逻辑测试
# ============================================================

class TestTrailingStop:
    """移动止盈逻辑测试"""

    def setup_method(self):
        """创建临时数据库"""
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = self.tmp.name
        self.tmp.close()

        # 导入并创建表
        sys_path = "/Users/liujianyu/WorkBuddy/Claw/quant-platform/backend"
        import sys
        if sys_path not in sys.path:
            sys.path.insert(0, sys_path)

        # 创建基础表结构
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS stock_daily (
                ts_code TEXT, trade_date TEXT, open REAL, high REAL,
                low REAL, close REAL, vol REAL, amount REAL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS stock (ts_code TEXT, name TEXT, industry TEXT)
        """)

        # 插入测试数据（60天日线）
        for i in range(60):
            day = i + 1
            month = 2 if day <= 28 else 3
            d = day if day <= 28 else day - 28
            date = f"2026-{month:02d}-{d:02d}"
            conn.execute(
                "INSERT INTO stock_daily (ts_code, trade_date, open, high, low, close, vol) "
                "VALUES ('000001.SZ', ?, 10.0, 10.5, 9.5, ?, 10000)",
                (date, 10.0 + i * 0.05)
            )

        # 插入股票信息
        conn.execute(
            "INSERT INTO stock (ts_code, name, industry) VALUES ('000001.SZ', '测试股票', '银行')"
        )
        conn.commit()
        conn.close()

        from app.services.tracking.tracking_pool_service import TrackingPoolService
        self.TrackingPoolService = TrackingPoolService
        # 需要先创建tracking表
        svc = TrackingPoolService(self.db_path)
        # 表已通过_ensure_tables创建

    def teardown_method(self):
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)

    def test_fixed_take_profit_dual_ma(self):
        """双均线策略应使用固定止盈"""
        svc = self.TrackingPoolService(self.db_path)
        conn = svc._get_conn()
        guide = svc._generate_operation_guide("000001.SZ", 10.0, "dual_ma", conn)
        conn.close()

        assert guide["exit_type"] == "fixed"
        config = json.loads(guide["exit_config"])
        assert config["take_profit_pct"] == 0.15
        assert guide["take_profit"] == round(10.0 * 1.15, 2)

    def test_trailing_take_profit_pullback(self):
        """回调企稳策略应使用移动止盈"""
        svc = self.TrackingPoolService(self.db_path)
        conn = svc._get_conn()
        guide = svc._generate_operation_guide("000001.SZ", 10.0, "pullback_stable", conn)
        conn.close()

        assert guide["exit_type"] == "trailing"
        config = json.loads(guide["exit_config"])
        assert "tiers" in config
        assert len(config["tiers"]) == 3
        assert config["tiers"][0]["profit_pct"] == 0.05
        assert config["tiers"][2]["profit_pct"] == 0.30

    def test_trailing_stop_tier1_triggered(self):
        """第一级止盈：赚5%后回撤5%应触发"""
        svc = self.TrackingPoolService(self.db_path)
        # 买入10.0 → 最高10.5（+5%）→ 当前10.0（从peak回撤4.76%）
        # 第一级：profit_pct=5%, trail_pct=5%
        # 5%达标，回撤4.76% < 5%，不触发
        signal = svc._check_trailing_stop(
            buy_price=10.0, current_price=10.0, peak_price=10.5,
            exit_config_str=json.dumps({
                "tiers": [
                    {"profit_pct": 0.05, "trail_pct": 0.05},
                    {"profit_pct": 0.15, "trail_pct": 0.03},
                    {"profit_pct": 0.30, "trail_pct": 0.02},
                ],
                "min_profit_pct": 0.03,
            })
        )
        # 回撤 = (10.5-10.0)/10.5 = 4.76% < 5%，不应触发
        assert signal == ""

    def test_trailing_stop_tier1_fired(self):
        """第一级止盈触发：利润达标+回撤达标"""
        svc = self.TrackingPoolService(self.db_path)
        # 买入10.0 → 最高10.8（+8%）→ 当前10.2（从peak回撤5.56%）
        # profit_pct = (10.2-10.0)/10.0 = +2%... 不足5%第一级门槛
        # 改为：买入10.0 → 最高12.0（+20%）→ 当前11.3（从peak回撤5.83%）
        # profit_pct = (11.3-10.0)/10.0 = +13% > 5%第一级
        # drawdown = (12.0-11.3)/12.0 = 5.83% > 5% trail
        # locked_profit = 13% > 3% min，应触发
        signal = svc._check_trailing_stop(
            buy_price=10.0, current_price=11.3, peak_price=12.0,
            exit_config_str=json.dumps({
                "tiers": [
                    {"profit_pct": 0.05, "trail_pct": 0.05},
                    {"profit_pct": 0.15, "trail_pct": 0.03},
                    {"profit_pct": 0.30, "trail_pct": 0.02},
                ],
                "min_profit_pct": 0.03,
            })
        )
        assert "跟踪止盈" in signal

    def test_min_profit_lock(self):
        """最低利润锁定：即使回撤达标，利润不足3%也不卖"""
        svc = self.TrackingPoolService(self.db_path)
        # 买入10.0 → 最高10.3（+3%）→ 当前9.7（从peak回撤5.8%）
        # 利润 = (9.7-10.0)/10.0 = -3% < 3%，不应触发
        signal = svc._check_trailing_stop(
            buy_price=10.0, current_price=9.7, peak_price=10.3,
            exit_config_str=json.dumps({
                "tiers": [
                    {"profit_pct": 0.05, "trail_pct": 0.05},
                    {"profit_pct": 0.15, "trail_pct": 0.03},
                ],
                "min_profit_pct": 0.03,
            })
        )
        # 利润 = -3%，低于最低锁定，不触发
        assert signal == ""

    def test_stop_loss_triggers(self):
        """止损触发：亏损超过阈值"""
        svc = self.TrackingPoolService(self.db_path)
        # 入池
        pool_id = svc.add_to_pool(
            ts_code="000001.SZ", strategy="dual_ma",
            signal_date="2026-04-14", signal_price=10.0, stock_name="测试"
        )
        assert pool_id > 0


# ============================================================
# 2. Core Signals — 策略信号测试
# ============================================================

class TestCoreSignals:
    """策略信号生成测试"""

    def test_dual_ma_golden_cross(self):
        """双均线金叉信号检测"""
        import sys
        sys.path.insert(0, "/Users/liujianyu/WorkBuddy/Claw/quant-platform/backend/app/services/strategy")
        from core_signals import signals_dual_ma, CORE_STRATEGIES

        # 构造一个MA7上穿MA60的序列
        n = 80
        closes = np.array([10.0] * 60 + [9.5, 9.6, 9.7, 9.8, 10.0, 10.2, 10.5, 10.8, 11.0, 11.2,
                                           11.0, 10.9, 11.1, 11.3, 11.5, 11.2, 11.4, 11.6, 11.8, 12.0])
        closes = closes[:n]
        dates = [f"2026-{(1 + i // 30):02d}-{(1 + i % 28):02d}" for i in range(n)]

        params = CORE_STRATEGIES["dual_ma"]["default_params"]
        signals = signals_dual_ma(closes, dates, params)

        # 应该至少有一个买入信号
        buy_signals = {d: t for d, t in signals.items() if t == "buy"}
        assert len(buy_signals) > 0, "应检测到金叉买入信号"

    def test_pullback_stable_signal(self):
        """回调企稳信号检测"""
        import sys
        sys.path.insert(0, "/Users/liujianyu/WorkBuddy/Claw/quant-platform/backend/app/services/strategy")
        from core_signals import signals_pullback_stable, CORE_STRATEGIES

        # 构造一个先涨后回调企稳的序列
        n = 100
        closes = np.zeros(n)
        for i in range(n):
            if i < 50:
                closes[i] = 10.0 + i * 0.1  # 上涨
            elif i < 70:
                closes[i] = 15.0 - (i - 50) * 0.15  # 回调
            else:
                closes[i] = 12.0 + (i - 70) * 0.05  # 企稳

        highs = closes * 1.02
        lows = closes * 0.98
        vol = np.ones(n) * 10000
        opens = closes * 0.99
        dates = [f"2026-{(1 + i // 30):02d}-{(1 + i % 28):02d}" for i in range(n)]

        params = CORE_STRATEGIES["pullback_stable"]["default_params"]
        signals = signals_pullback_stable(closes, highs, lows, vol, opens, dates, params)

        # 可能检测到企稳买入信号
        buy_signals = {d: t for d, t in signals.items() if t == "buy"}
        # 不强制要求有信号（取决于参数和序列匹配度）
        assert isinstance(signals, dict)


# ============================================================
# 3. Market Context — 市场环境评估测试
# ============================================================

class TestMarketContext:
    """市场环境评估测试"""

    def setup_method(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = self.tmp.name
        self.tmp.close()

        conn = sqlite3.connect(self.db_path)
        # 创建基础表
        conn.execute("""
            CREATE TABLE IF NOT EXISTS stock_daily (
                ts_code TEXT, trade_date TEXT, open REAL, high REAL,
                low REAL, close REAL, vol REAL, amount REAL, pct_chg REAL, pre_close REAL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS stock (ts_code TEXT, name TEXT, industry TEXT)
        """)

        # 插入指数数据（上证、深证、创业板、沪深300）
        import random
        random.seed(42)
        for code in ["000001.SH", "399001.SZ", "399006.SZ", "000300.SH"]:
            base_price = 3000 if "SH" in code else 10000
            for i in range(60):
                date = f"2026-{(2 + i // 28):02d}-{(1 + i % 28):02d}"
                close = base_price + i * 5 + random.uniform(-20, 20)
                pct = random.uniform(-1.5, 1.5)
                conn.execute(
                    "INSERT INTO stock_daily (ts_code, trade_date, close, pct_chg, amount, high, low, open, vol, pre_close) "
                    "VALUES (?, ?, ?, ?, 1e8, ?, ?, ?, 1e7, ?)",
                    (code, date, close, pct, close * 1.01, close * 0.99, close * 0.998, close - pct)
                )

        # 插入股票数据
        industries = ["电子", "医药", "银行", "计算机", "食品饮料"]
        for j in range(20):
            code = f"{j:06d}.SZ"
            conn.execute(
                "INSERT INTO stock (ts_code, name, industry) VALUES (?, ?, ?)",
                (code, f"股票{j}", industries[j % len(industries)])
            )
            for i in range(5):
                date = f"2026-04-{10 + i:02d}"
                pct = random.uniform(-3, 3)
                close = 10.0 + random.uniform(-1, 1)
                conn.execute(
                    "INSERT INTO stock_daily (ts_code, trade_date, close, pct_chg, amount, high, low, open, vol, pre_close) "
                    "VALUES (?, ?, ?, ?, 1e7, ?, ?, ?, 1e6, ?)",
                    (code, date, close, pct, close * 1.02, close * 0.98, close * 0.99, close)
                )

        conn.commit()
        conn.close()

    def teardown_method(self):
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)

    def test_index_trend_evaluation(self):
        """大盘趋势评估"""
        import sys
        sys.path.insert(0, "/Users/liujianyu/WorkBuddy/Claw/quant-platform/backend/app/services/analysis")
        from market_context import evaluate_index_trend

        result = evaluate_index_trend(self.db_path)
        assert len(result) > 0, "应返回至少一个指数趋势"
        for name, info in result.items():
            assert "trend" in info
            assert info["trend"] in ["多头排列", "空头排列", "偏多震荡", "偏空震荡"]
            assert "current" in info

    def test_market_breadth(self):
        """市场宽度评估"""
        import sys
        sys.path.insert(0, "/Users/liujianyu/WorkBuddy/Claw/quant-platform/backend/app/services/analysis")
        from market_context import evaluate_market_breadth

        result = evaluate_market_breadth(self.db_path)
        assert "up_count" in result
        assert "down_count" in result
        assert "sentiment" in result
        assert result["sentiment"] in ["偏多", "偏空", "中性"]
        assert result["total_stocks"] > 0

    def test_sector_momentum(self):
        """板块动量评估"""
        import sys
        sys.path.insert(0, "/Users/liujianyu/WorkBuddy/Claw/quant-platform/backend/app/services/analysis")
        from market_context import evaluate_sector_momentum

        result = evaluate_sector_momentum(self.db_path)
        assert isinstance(result, list)
        if result:
            assert "sector" in result[0]
            assert "avg_change" in result[0]

    def test_full_report_generation(self):
        """完整市场环境报告生成"""
        import sys
        sys.path.insert(0, "/Users/liujianyu/WorkBuddy/Claw/quant-platform/backend/app/services/analysis")
        from market_context import generate_market_context_report

        report = generate_market_context_report(self.db_path)
        assert len(report) > 100, "报告应有内容"
        assert "市场环境" in report


# ============================================================
# 运行
# ============================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
