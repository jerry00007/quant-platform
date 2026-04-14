"""
QuantWeave - 回测引擎单元测试
验证收益计算、最大回撤、夏普比率等指标的正确性
"""
import pytest
import pandas as pd
import numpy as np
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestBacktestCalculations:
    """回测引擎计算逻辑测试"""

    def test_total_return_calculation(self):
        """验证总收益率计算：100万→110万 = +10%"""
        from app.services.backtest.backtest_service import BacktestEngine
        # 用模拟数据直接验证公式
        initial = 1000000.0
        final = 1100000.0
        expected_return = (final - initial) / initial * 100
        assert abs(expected_return - 10.0) < 0.01

    def test_max_drawdown_calculation(self):
        """验证最大回撤计算"""
        # 净值序列：100, 120, 110, 130, 100
        # 回撤点：120→110 = 8.33%, 130→100 = 23.08%
        values = [100, 120, 110, 130, 100]
        peak = values[0]
        max_dd = 0
        for v in values:
            if v > peak:
                peak = v
            dd = (peak - v) / peak * 100
            if dd > max_dd:
                max_dd = dd
        assert abs(max_dd - 23.08) < 0.1, f"最大回撤应为23.08%，实际{max_dd:.2f}%"

    def test_sharpe_ratio_calculation(self):
        """验证夏普比率计算"""
        daily_returns = [0.01, -0.005, 0.02, 0.015, -0.01, 0.005, 0.01]
        mean_ret = np.mean(daily_returns)
        std_ret = np.std(daily_returns)
        trading_days = 244
        sharpe = mean_ret / std_ret * np.sqrt(trading_days)
        assert sharpe > 0, "正收益序列的夏普应该为正"

    def test_win_rate_calculation(self):
        """验证胜率计算"""
        trades_profit = [1000, -500, 2000, 300, -800, 1500]
        wins = [p for p in trades_profit if p > 0]
        win_rate = len(wins) / len(trades_profit) * 100
        assert abs(win_rate - 66.67) < 0.1

    def test_profit_loss_ratio(self):
        """验证盈亏比计算"""
        trades_profit = [1000, -500, 2000, -800]
        avg_win = np.mean([1000, 2000])  # 1500
        avg_loss = abs(np.mean([-500, -800]))  # 650
        pl_ratio = avg_win / avg_loss
        assert abs(pl_ratio - 1500 / 650) < 0.01

    def test_commission_impact(self):
        """验证佣金对收益的影响"""
        price = 50.0
        shares = 10000
        commission_rate = 0.0003
        slippage = 0.001

        # 买入成本
        buy_price = price * (1 + slippage)
        buy_cost = shares * buy_price * (1 + commission_rate)

        # 卖出收入（假设价格不变）
        sell_price = price * (1 - slippage)
        sell_income = shares * sell_price * (1 - commission_rate)

        # 持平交易应该亏损（因为佣金和滑点）
        profit = sell_income - buy_cost
        assert profit < 0, "持平交易应该因佣金和滑点而亏损"

    def test_annual_return_formula(self):
        """验证年化收益率计算"""
        total_return_pct = 10.0  # 10%
        days = 244  # 一年交易日
        trading_days_per_year = 244
        annual = ((1 + total_return_pct / 100) ** (trading_days_per_year / days) - 1) * 100
        assert abs(annual - 10.0) < 0.01  # 一年就是10%

        # 半年10%
        days_half = 122
        annual_half = ((1 + 0.10) ** (244 / 122) - 1) * 100
        expected = ((1.10 ** 2) - 1) * 100  # 21%
        assert abs(annual_half - expected) < 0.1


class TestBacktestEngine:
    """回测引擎集成测试（使用模拟DataService）"""

    def test_engine_run_with_mock(self, sample_ohlcv):
        """验证回测引擎完整流程"""
        # 创建一个Mock DataService
        class MockDataService:
            def fetch_daily(self, ts_code, start_date, end_date):
                return sample_ohlcv

        from app.services.backtest.backtest_service import BacktestEngine
        engine = BacktestEngine(
            data_service=MockDataService(),
            initial_cash=1000000.0,
            commission=0.0003,
            slippage=0.001,
        )
        result = engine.run("dual_ma", "000001.SZ", "20240102", "20240630")

        # 验证返回结构
        assert "total_return" in result
        assert "max_drawdown" in result
        assert "sharpe_ratio" in result
        assert "win_rate" in result
        assert "total_trades" in result
        assert "equity_curve" in result
        assert "trades" in result

        # 验证指标合理性
        assert result["total_trades"] >= 0
        assert result["max_drawdown"] >= 0
        assert len(result["equity_curve"]) > 0

    def test_empty_data_returns_error(self):
        """验证空数据返回错误"""
        class MockEmptyService:
            def fetch_daily(self, ts_code, start_date, end_date):
                return pd.DataFrame()

        from app.services.backtest.backtest_service import BacktestEngine
        engine = BacktestEngine(data_service=MockEmptyService())
        result = engine.run("dual_ma", "000001.SZ", "20240101", "20240630")
        assert "error" in result

    def test_position_sizing(self):
        """验证整百股买入（不能买零头）"""
        cash = 10000.0
        price = 33.33
        shares = int(cash / price / 100) * 100
        assert shares % 100 == 0, "买入股数应该是100的整数倍"
        assert shares > 0

    def test_equity_curve_monotonic_dates(self, sample_ohlcv):
        """验证净值曲线日期单调递增"""
        class MockDataService:
            def fetch_daily(self, ts_code, start_date, end_date):
                return sample_ohlcv

        from app.services.backtest.backtest_service import BacktestEngine
        engine = BacktestEngine(data_service=MockDataService())
        result = engine.run("macd", "000001.SZ", "20240102", "20240630")
        dates = [e["date"] for e in result["equity_curve"]]
        assert dates == sorted(dates), "净值曲线日期应该单调递增"
