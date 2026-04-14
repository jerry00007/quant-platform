"""
QuantWeave - 测试配置和公共 fixtures
"""
import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta


@pytest.fixture
def sample_ohlcv():
    """生成模拟OHLCV数据（120天，带趋势）"""
    np.random.seed(42)
    n = 120
    dates = pd.date_range("2024-01-02", periods=n, freq="B")
    # 模拟带上涨趋势的价格
    base = 50.0
    trend = np.linspace(0, 8, n)  # 总涨8元
    noise = np.cumsum(np.random.randn(n) * 0.5)
    close = base + trend + noise
    close = np.maximum(close, 1.0)  # 不为负

    high = close * (1 + np.abs(np.random.randn(n) * 0.015))
    low = close * (1 - np.abs(np.random.randn(n) * 0.015))
    open_ = close * (1 + np.random.randn(n) * 0.005)
    vol = np.random.randint(50000, 500000, n).astype(float)
    amount = vol * close

    df = pd.DataFrame({
        "trade_date": dates.strftime("%Y%m%d"),
        "open": np.round(open_, 2),
        "high": np.round(high, 2),
        "low": np.round(low, 2),
        "close": np.round(close, 2),
        "pre_close": np.round(np.roll(close, 1), 2),
        "change_pct": np.round(np.random.randn(n) * 2, 2),
        "vol": vol,
        "amount": np.round(amount, 2),
        "turnover_rate": np.round(np.random.rand(n) * 5, 2),
        "ts_code": "000001.SZ",
    })
    df.loc[0, "pre_close"] = df.loc[0, "open"]
    return df


@pytest.fixture
def sample_flat_data():
    """生成横盘震荡数据（120天，无明显趋势）"""
    np.random.seed(100)
    n = 120
    dates = pd.date_range("2024-01-02", periods=n, freq="B")
    base = 30.0
    noise = np.cumsum(np.random.randn(n) * 0.3)
    close = base + noise
    close = np.maximum(close, 1.0)

    high = close * (1 + np.abs(np.random.randn(n) * 0.01))
    low = close * (1 - np.abs(np.random.randn(n) * 0.01))
    open_ = close * (1 + np.random.randn(n) * 0.003)
    vol = np.random.randint(30000, 300000, n).astype(float)

    df = pd.DataFrame({
        "trade_date": dates.strftime("%Y%m%d"),
        "open": np.round(open_, 2),
        "high": np.round(high, 2),
        "low": np.round(low, 2),
        "close": np.round(close, 2),
        "pre_close": np.round(np.roll(close, 1), 2),
        "change_pct": np.round(np.random.randn(n) * 1.5, 2),
        "vol": vol,
        "amount": np.round(vol * close, 2),
        "turnover_rate": np.round(np.random.rand(n) * 3, 2),
        "ts_code": "600000.SH",
    })
    df.loc[0, "pre_close"] = df.loc[0, "open"]
    return df


@pytest.fixture
def sample_downtrend_data():
    """生成下跌趋势数据（120天）"""
    np.random.seed(200)
    n = 120
    dates = pd.date_range("2024-01-02", periods=n, freq="B")
    base = 100.0
    trend = np.linspace(0, -25, n)
    noise = np.cumsum(np.random.randn(n) * 0.8)
    close = base + trend + noise
    close = np.maximum(close, 1.0)

    high = close * (1 + np.abs(np.random.randn(n) * 0.015))
    low = close * (1 - np.abs(np.random.randn(n) * 0.015))
    open_ = close * (1 + np.random.randn(n) * 0.005)
    vol = np.random.randint(100000, 800000, n).astype(float)

    df = pd.DataFrame({
        "trade_date": dates.strftime("%Y%m%d"),
        "open": np.round(open_, 2),
        "high": np.round(high, 2),
        "low": np.round(low, 2),
        "close": np.round(close, 2),
        "pre_close": np.round(np.roll(close, 1), 2),
        "change_pct": np.round(np.random.randn(n) * 2.5, 2),
        "vol": vol,
        "amount": np.round(vol * close, 2),
        "turnover_rate": np.round(np.random.rand(n) * 4, 2),
        "ts_code": "000858.SZ",
    })
    df.loc[0, "pre_close"] = df.loc[0, "open"]
    return df
