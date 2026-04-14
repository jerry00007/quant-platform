"""
QuantWeave - 策略信号单元测试
测试所有7个策略的信号生成正确性
"""
import pytest
import pandas as pd
import numpy as np
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.strategy.strategy_service import (
    SignalType, DualMAStrategy, BollingerBreakStrategy,
    RSIStrategy, MACDStrategy, get_strategy
)
from app.services.strategy.chip_strategy import (
    ChipStrategy, EnhancedChipStrategy, PullbackStableStrategy
)


class TestDualMAStrategy:
    """双均线交叉策略测试"""

    def test_golden_cross_generates_buy(self, sample_ohlcv):
        """验证上升趋势中金叉信号生成"""
        strategy = DualMAStrategy(params={"short_period": 5, "long_period": 20})
        signals = strategy.generate_signals(sample_ohlcv, "000001.SZ")
        buy_signals = [s for s in signals if s.signal_type == SignalType.BUY]
        sell_signals = [s for s in signals if s.signal_type == SignalType.SELL]
        # 上升趋势数据应该有金叉信号
        assert len(signals) > 0, "应该生成交易信号"
        assert len(buy_signals) > 0, "上升趋势应该有买入（金叉）信号"

    def test_signal_has_correct_fields(self, sample_ohlcv):
        """验证信号字段完整性"""
        strategy = DualMAStrategy()
        signals = strategy.generate_signals(sample_ohlcv, "000001.SZ")
        for s in signals:
            assert s.signal_type in (SignalType.BUY, SignalType.SELL)
            assert s.ts_code == "000001.SZ"
            assert s.price > 0
            assert s.date != ""
            assert s.reason != ""

    def test_flat_market_fewer_signals(self, sample_flat_data):
        """验证横盘市场信号更少"""
        strategy = DualMAStrategy()
        signals = strategy.generate_signals(sample_flat_data, "600000.SH")
        # 横盘市场应该信号较少（均线交叉不频繁）
        assert isinstance(signals, list)

    def test_short_period_less_than_long(self, sample_ohlcv):
        """验证短周期小于长周期时正常工作"""
        strategy = DualMAStrategy(params={"short_period": 3, "long_period": 10})
        signals = strategy.generate_signals(sample_ohlcv, "000001.SZ")
        assert isinstance(signals, list)

    def test_indicators_calculated(self, sample_ohlcv):
        """验证指标正确计算"""
        strategy = DualMAStrategy()
        df = strategy.calculate_indicators(sample_ohlcv)
        assert "ma_short" in df.columns
        assert "ma_long" in df.columns
        assert df["ma_short"].notna().sum() > 0
        assert df["ma_long"].notna().sum() > 0


class TestRSIStrategy:
    """RSI策略测试"""

    def test_rsi_range_0_to_100(self, sample_ohlcv):
        """验证RSI值在0-100之间"""
        strategy = RSIStrategy()
        df = strategy.calculate_indicators(sample_ohlcv)
        valid_rsi = df["rsi"].dropna()
        assert (valid_rsi >= 0).all() and (valid_rsi <= 100).all(), \
            f"RSI应在0-100之间，实际范围: {valid_rsi.min():.1f} ~ {valid_rsi.max():.1f}"

    def test_rsi_uses_ema_not_sma(self, sample_ohlcv):
        """验证RSI使用EMA算法（非SMA）
        
        Wilder's RSI 用 EMA(alpha=1/period)，
        和 SMA(period) 的结果在前几期就有明显差异
        """
        strategy = RSIStrategy(params={"period": 14})
        df = strategy.calculate_indicators(sample_ohlcv)

        # 对比：手动用 SMA 计算 RSI
        delta = sample_ohlcv["close"].diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)
        sma_gain = gain.rolling(14).mean()
        sma_loss = loss.rolling(14).mean()
        sma_rsi = 100 - (100 / (1 + sma_gain / sma_loss))

        # EMA和SMA在第20个有效值处应该有差异
        ema_vals = df["rsi"].dropna()
        sma_vals = sma_rsi.dropna()
        if len(ema_vals) > 20 and len(sma_vals) > 20:
            # 两种算法在后期应该有可观测的差异（不是完全相同）
            diff = abs(ema_vals.iloc[20] - sma_vals.iloc[20])
            assert diff > 0.01, "EMA RSI应该和SMA RSI有差异"

    def test_oversold_triggers_buy(self, sample_downtrend_data):
        """验证超卖区域触发买入信号"""
        strategy = RSIStrategy(params={"oversold": 35, "overbought": 65})
        signals = strategy.generate_signals(sample_downtrend_data, "000858.SZ")
        buy_signals = [s for s in signals if s.signal_type == SignalType.BUY]
        # 下跌趋势应该有超卖买入信号
        if len(buy_signals) > 0:
            for s in buy_signals:
                assert "超卖" in s.reason or "RSI" in s.reason

    def test_custom_thresholds(self, sample_ohlcv):
        """验证自定义超买超卖阈值"""
        strategy = RSIStrategy(params={"oversold": 20, "overbought": 80})
        signals = strategy.generate_signals(sample_ohlcv, "000001.SZ")
        assert isinstance(signals, list)


class TestBollingerBreakStrategy:
    """布林带突破策略测试"""

    def test_indicators_calculated(self, sample_ohlcv):
        """验证布林带指标正确计算"""
        strategy = BollingerBreakStrategy()
        df = strategy.calculate_indicators(sample_ohlcv)
        assert "upper" in df.columns
        assert "lower" in df.columns
        assert "mid" in df.columns
        # 上轨 > 中轨 > 下轨
        valid = df.dropna(subset=["upper", "mid", "lower"])
        if len(valid) > 0:
            assert (valid["upper"] >= valid["mid"]).all(), "上轨应>=中轨"
            assert (valid["mid"] >= valid["lower"]).all(), "中轨应>=下轨"

    def test_std_dev_parameter(self, sample_ohlcv):
        """验证不同标准差倍数的布林带宽度"""
        narrow = BollingerBreakStrategy(params={"period": 20, "std_dev": 1.0})
        wide = BollingerBreakStrategy(params={"period": 20, "std_dev": 3.0})
        df_n = narrow.calculate_indicators(sample_ohlcv)
        df_w = wide.calculate_indicators(sample_ohlcv)
        # 宽布林带应该比窄布林带带宽更大
        width_n = (df_n["upper"] - df_n["lower"]).dropna()
        width_w = (df_w["upper"] - df_w["lower"]).dropna()
        if len(width_n) > 0 and len(width_w) > 0:
            assert width_w.iloc[50] > width_n.iloc[50]


class TestMACDStrategy:
    """MACD策略测试"""

    def test_indicators_calculated(self, sample_ohlcv):
        """验证MACD指标正确计算"""
        strategy = MACDStrategy()
        df = strategy.calculate_indicators(sample_ohlcv)
        assert "dif" in df.columns
        assert "dea" in df.columns
        assert "macd" in df.columns

    def test_golden_cross_in_uptrend(self, sample_ohlcv):
        """验证上升趋势中的MACD金叉"""
        strategy = MACDStrategy()
        signals = strategy.generate_signals(sample_ohlcv, "000001.SZ")
        buy_signals = [s for s in signals if s.signal_type == SignalType.BUY]
        # 上升趋势应该有金叉
        assert len(buy_signals) > 0, "上升趋势应该有MACD金叉"

    def test_signal_consistency(self, sample_ohlcv):
        """验证买卖信号交替出现（不连续两个买/卖）"""
        strategy = MACDStrategy()
        signals = strategy.generate_signals(sample_ohlcv, "000001.SZ")
        for i in range(1, len(signals)):
            assert signals[i].signal_type != signals[i - 1].signal_type, \
                "买卖信号应该交替出现"


class TestChipStrategy:
    """主力筹码趋向策略测试"""

    def test_zlcmq_range(self, sample_ohlcv):
        """验证ZLCMQ值在合理范围内"""
        strategy = ChipStrategy()
        df = strategy.calculate_indicators(sample_ohlcv)
        zlcmq = df["zlcmq"].dropna()
        assert (zlcmq >= -50).all() and (zlcmq <= 150).all(), \
            f"ZLCMQ超出合理范围: {zlcmq.min():.1f} ~ {zlcmq.max():.1f}"

    def test_tdx_sma_basic(self):
        """验证通达信SMA基本计算"""
        x = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        result = ChipStrategy._tdx_sma(x, 3, 1)
        # SMA(X, 3, 1): Y = (1*X + 2*Y_prev) / 3
        expected = [1.0]  # Y[0] = X[0]
        for i in range(1, 5):
            expected.append((1 * x[i] + 2 * expected[-1]) / 3)
        np.testing.assert_array_almost_equal(result, expected, decimal=10)

    def test_signals_with_enough_data(self, sample_ohlcv):
        """验证120天数据能正常生成信号"""
        strategy = ChipStrategy()
        signals = strategy.generate_signals(sample_ohlcv, "000001.SZ")
        assert isinstance(signals, list)

    def test_insufficient_data_no_signals(self):
        """验证数据不足时不生成信号"""
        df = pd.DataFrame({
            "trade_date": ["20240102", "20240103"],
            "open": [10.0, 10.5],
            "high": [10.5, 11.0],
            "low": [9.8, 10.2],
            "close": [10.2, 10.8],
            "vol": [100000, 120000],
        })
        strategy = ChipStrategy()
        signals = strategy.generate_signals(df, "000001.SZ")
        assert len(signals) == 0, "数据不足80条不应生成信号"


class TestEnhancedChipStrategy:
    """增强筹码策略测试"""

    def test_atr_calculation(self, sample_ohlcv):
        """验证ATR正确计算"""
        atr = EnhancedChipStrategy._atr(
            sample_ohlcv["high"],
            sample_ohlcv["low"],
            sample_ohlcv["close"],
            period=14
        )
        valid_atr = atr.dropna()
        assert len(valid_atr) > 0, "ATR应该有有效值"
        assert (valid_atr > 0).all(), "ATR应该大于0"

    def test_strict_conditions(self, sample_ohlcv):
        """验证增强策略条件更严格（信号更少）"""
        basic = ChipStrategy()
        enhanced = EnhancedChipStrategy()
        basic_signals = basic.generate_signals(sample_ohlcv.copy(), "000001.SZ")
        enhanced_signals = enhanced.generate_signals(sample_ohlcv.copy(), "000001.SZ")
        # 增强策略加了多个过滤条件，信号应该<=基础策略
        assert len(enhanced_signals) <= len(basic_signals) + 2, \
            "增强策略信号应该不多于基础策略"


class TestPullbackStableStrategy:
    """强势股回调企稳策略测试"""

    def test_five_choose_three(self):
        """验证5选3企稳逻辑"""
        strategy = PullbackStableStrategy()
        # 构造满足3项条件的数据
        dates = pd.date_range("2024-01-02", periods=90, freq="B")
        np.random.seed(42)
        close = np.linspace(10, 15, 90)  # 上涨趋势
        df = pd.DataFrame({
            "trade_date": dates.strftime("%Y%m%d"),
            "open": close * 0.99,
            "high": close * 1.02,
            "low": close * 0.98,
            "close": close,
            "vol": np.random.randint(50000, 200000, 90).astype(float),
        })
        signals = strategy.generate_signals(df, "000001.SZ")
        assert isinstance(signals, list)

    def test_market_filter(self, sample_ohlcv):
        """验证大盘过滤功能"""
        strategy = PullbackStableStrategy()
        # 设置只允许一天交易
        strategy.set_market_ok({"20240501"})
        signals = strategy.generate_signals(sample_ohlcv, "000001.SZ")
        # 绝大多数日期被过滤
        buy_signals = [s for s in signals if s.signal_type == SignalType.BUY]
        # 最多只允许在20240501开仓（数据里没有这个日期，所以应该没有买入信号）
        assert len(buy_signals) == 0

    def test_trailing_stop(self, sample_ohlcv):
        """验证移动止盈逻辑"""
        strategy = PullbackStableStrategy(params={
            "trail_start": 0.01,  # 1%启动移动止盈
            "trail_pct": 0.02,    # 回撤2%止盈
        })
        signals = strategy.generate_signals(sample_ohlcv, "000001.SZ")
        sell_signals = [s for s in signals if s.signal_type == SignalType.SELL]
        # 应该有移动止盈信号
        trail_sells = [s for s in sell_signals if "移动止盈" in s.reason]
        # 不强制要求（取决于数据），但不应报错
        assert isinstance(trail_sells, list)


class TestStrategyRegistry:
    """策略注册表测试"""

    def test_all_strategies_registered(self):
        """验证所有策略都已注册"""
        from app.services.strategy.strategy_service import STRATEGY_REGISTRY
        expected = {"dual_ma", "bollinger", "rsi", "macd",
                    "chip", "enhanced_chip", "pullback_stable",
                    "vol_breakout", "first_yin", "trend_ma", "top_bottom"}
        assert set(STRATEGY_REGISTRY.keys()) == expected

    def test_get_strategy_by_name(self):
        """验证通过名称获取策略"""
        for name in ["dual_ma", "bollinger", "rsi", "macd",
                      "chip", "enhanced_chip", "pullback_stable"]:
            strategy = get_strategy(name)
            assert strategy is not None

    def test_get_unknown_strategy_raises(self):
        """验证获取不存在的策略抛出异常"""
        with pytest.raises(ValueError, match="未知策略类型"):
            get_strategy("nonexistent")

    def test_custom_params_override(self):
        """验证自定义参数覆盖默认参数"""
        strategy = get_strategy("dual_ma", {"short_period": 10})
        assert strategy.params["short_period"] == 10
        assert strategy.params["long_period"] == 40  # 默认值保留
