#!/usr/bin/env python3
"""QuantWeave 10策略信号生成模块（含6个新策略）"""

import numpy as np
from typing import Dict, List, Optional
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / 'app' / 'services' / 'strategy'))
from core_signals import (
    signals_bollinger_upper, signals_dual_ma, signals_enhanced_chip,
    signals_pullback_stable, calc_zlcmq_window,
)

SignalResult = Dict[str, str]


def signals_rsi(close, dates, params=None):
    """RSI超买超卖策略"""
    p = params or {}
    period = p.get('period', 14)
    oversold = p.get('oversold', 30)
    overbought = p.get('overbought', 70)
    signals = {}
    n = len(close)
    if n < period + 1:
        return signals
    deltas = np.diff(close.astype(float))
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    rsi = np.full(n, np.nan)
    for i in range(period, n):
        g = gains[i - period:i]
        l = losses[i - period:i]
        ag = np.nanmean(g) if len(g) > 0 else 0
        al = np.nanmean(l) if len(l) > 0 else 0
        rsi[i] = 100 - 100 / (1 + ag / al) if al > 0 else 100
    for i in range(1, n):
        if np.isnan(rsi[i]) or np.isnan(rsi[i-1]) or np.isnan(close[i]):
            continue
        if rsi[i-1] < oversold and rsi[i] >= oversold and close[i] > close[i-1]:
            signals[dates[i]] = 'buy'
        elif rsi[i-1] > overbought and rsi[i] <= overbought:
            signals[dates[i]] = 'sell'
    return signals


def signals_macd(close, dates, params=None):
    """MACD金叉死叉策略"""
    p = params or {}
    fast = p.get('fast_period', 12)
    slow = p.get('slow_period', 26)
    sig_p = p.get('signal_period', 9)
    signals = {}
    n = len(close)
    if n < slow + sig_p:
        return signals
    def ema(data, period):
        r = np.full(len(data), np.nan)
        mask = ~np.isnan(data)
        vd = data[mask]
        if len(vd) < period:
            return r
        fv = np.argmax(mask)
        r[fv + period - 1] = np.mean(vd[:period])
        k = 2.0 / (period + 1)
        for i in range(fv + period, len(data)):
            if not np.isnan(data[i]):
                r[i] = data[i] * k + r[i-1] * (1 - k)
        return r
    ef = ema(close, fast)
    es = ema(close, slow)
    dif = ef - es
    dea = np.full(n, np.nan)
    fd = None
    for i in range(n):
        if not np.isnan(dif[i]):
            fd = i; break
    if fd is None:
        return signals
    vd = dif[fd:]
    if len(vd) >= sig_p:
        dea[fd + sig_p - 1] = np.mean(vd[:sig_p])
        k = 2.0 / (sig_p + 1)
        for i in range(fd + sig_p, n):
            if not np.isnan(dif[i]):
                dea[i] = dif[i] * k + dea[i-1] * (1 - k)
    for i in range(1, n):
        if any(np.isnan(x) for x in [dif[i], dea[i], dif[i-1], dea[i-1]]):
            continue
        if dif[i-1] <= dea[i-1] and dif[i] > dea[i]:
            signals[dates[i]] = 'buy'
        elif dif[i-1] >= dea[i-1] and dif[i] < dea[i]:
            signals[dates[i]] = 'sell'
    return signals


def signals_chip(close, high, low, vol, open_, dates, params=None):
    """主力筹码策略（基础ZLCMQ版）"""
    p = params or {}
    n_days = p.get('n_days', 5)
    min_high = p.get('min_high', 90)
    min_fall = p.get('min_fall', 3)
    chip_exit = p.get('chip_exit', 20)
    signals = {}
    for i in range(75, len(close)):
        if np.isnan(close[i]):
            continue
        c = close[:i+1]; h = high[:i+1]; l = low[:i+1]
        zlcmq = calc_zlcmq_window(c, h, l)
        if zlcmq is None:
            continue
        cur_z = zlcmq[-1]
        zw = zlcmq[-n_days:] if len(zlcmq) >= n_days else zlcmq
        if np.max(zw) >= min_high and np.max(zw) - cur_z >= min_fall:
            if cur_z < np.max(zw) and close[i] > open_[i]:
                signals[dates[i]] = 'buy'
        if cur_z < chip_exit:
            signals[dates[i]] = 'sell'
    return signals


def signals_vol_breakout(close, high, low, vol, open_, dates, params=None):
    """爆量突破策略"""
    p = params or {}
    vm = p.get('vol_mult', 2.0)
    vp = p.get('vol_ma_period', 20)
    bp = p.get('breakout_pct', 0.03)
    signals = {}
    for i in range(vp + 1, len(close)):
        if np.isnan(close[i]) or np.isnan(vol[i]):
            continue
        rv = vol[i-vp:i]; rv = rv[~np.isnan(rv)]
        if len(rv) == 0:
            continue
        avg_vol = np.mean(rv)
        if avg_vol == 0 or vol[i] < avg_vol * vm:
            continue
        rh = np.nanmax(high[i-vp:i])
        if np.isnan(rh):
            continue
        if close[i] > rh * (1 - bp) and close[i] > open_[i]:
            signals[dates[i]] = 'buy'
        if close[i] < open_[i]:
            ma10 = close[max(0,i-10):i]; ma10 = ma10[~np.isnan(ma10)]
            if len(ma10) >= 5 and close[i] < np.mean(ma10):
                signals[dates[i]] = 'sell'
    return signals


def signals_first_yin(close, high, low, vol, open_, dates, params=None):
    """龙头首阴反弹"""
    p = params or {}
    rd = p.get('rise_days', 3)
    signals = {}
    for i in range(rd + 2, len(close)):
        if np.isnan(close[i]) or np.isnan(vol[i]) or np.isnan(open_[i]):
            continue
        all_rise = True
        for j in range(i - rd, i):
            if np.isnan(close[j]) or np.isnan(close[j-1]) or close[j] <= close[j-1]:
                all_rise = False; break
        if not all_rise:
            continue
        if np.isnan(open_[i-1]) or close[i-1] >= open_[i-1]:
            continue
        if close[i] > open_[i] and close[i] > open_[i-1]:
            signals[dates[i]] = 'buy'
        ma5 = close[max(0,i-5):i]; ma5 = ma5[~np.isnan(ma5)]
        if len(ma5) >= 3 and close[i] < np.mean(ma5) * 0.97:
            signals[dates[i]] = 'sell'
    return signals


def signals_trend_ma(close, dates, params=None):
    """均线趋势跟踪"""
    p = params or {}
    mp = p.get('ma_period', 20)
    cd = p.get('confirm_days', 2)
    signals = {}
    n = len(close)
    ma = np.full(n, np.nan)
    for i in range(mp - 1, n):
        w = close[i-mp+1:i+1]; w = w[~np.isnan(w)]
        if len(w) >= mp:
            ma[i] = np.mean(w)
    in_pos = False
    above = 0
    for i in range(1, n):
        if np.isnan(close[i]) or np.isnan(ma[i]) or np.isnan(ma[i-1]):
            continue
        above = above + 1 if close[i] > ma[i] else 0
        if not in_pos and above >= cd and ma[i] > ma[i-1]:
            signals[dates[i]] = 'buy'; in_pos = True
        elif in_pos and close[i] < ma[i]:
            signals[dates[i]] = 'sell'; in_pos = False
    return signals


def signals_top_bottom(close, high, low, vol, open_, dates, params=None):
    """顶底图（多变量系统）"""
    p = params or {}
    lb = p.get('lookback', 20)
    bp = p.get('bottom_pos', 0.2)
    tp = p.get('top_pos', 0.8)
    vr = p.get('vol_ratio', 0.7)
    signals = {}
    for i in range(lb + 1, len(close)):
        if np.isnan(close[i]) or np.isnan(vol[i]):
            continue
        w = close[i-lb:i]; w = w[~np.isnan(w)]
        if len(w) < lb:
            continue
        hh = np.max(w); ll = np.min(w); rng = hh - ll
        if rng < 1e-6:
            continue
        pos = (close[i] - ll) / rng
        rv = vol[i-10:i]; rv = rv[~np.isnan(rv)]
        avg_vol = np.mean(rv) if len(rv) > 0 else 1
        if pos <= bp and vol[i] < avg_vol * (1/vr) and close[i] > open_[i]:
            pp = (close[i-1] - ll) / rng if not np.isnan(close[i-1]) else 0.5
            if pp <= bp * 1.2:
                signals[dates[i]] = 'buy'
        if pos >= tp:
            if close[i] < open_[i] and vol[i] > avg_vol * 1.5:
                signals[dates[i]] = 'sell'
            ma5 = close[max(0,i-5):i]; ma5 = ma5[~np.isnan(ma5)]
            if len(ma5) >= 3 and close[i] < np.mean(ma5):
                signals[dates[i]] = 'sell'
    return signals
