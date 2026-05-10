"""
QuantWeave 5大核心策略信号生成模块（共用）

回测引擎和选股 Skill 引用同一份策略逻辑，确保参数和信号一致。

输入：numpy arrays (close, high, low, vol, open_) + dates list
输出：dict {date_str: 'buy'/'sell'}

策略参数（2026-04-16 调优后最优）：
  - 布林带上轨突破: period=25, std_mult=1.8（调优: 2.0→1.8）
  - 双均线交叉: short_period=7, long_period=60（调优: 40→60）
  - 增强筹码策略: n_days=5, min_high=98, min_fall=5（保持原版）
  - 强势股回调企稳: n_days=8, min_high=95, min_fall=5（保持原版）
  - 均线趋势跟踪: ma_period=15, confirm_days=3（新增，调优验证双正）
"""

import numpy as np
import logging
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Type alias
SignalResult = Dict[str, str]


# ============================================================
# ZLCMQ 计算（通达信指标移植）
# ============================================================

def tdx_sma(x: np.ndarray, n: int, m: int) -> np.ndarray:
    """通达信 SMA 递归计算
    
    SMA(X, N, M) = (M*X + (N-M)*Y') / N
    """
    y = np.empty(len(x))
    y[0] = x[0]
    for i in range(1, len(x)):
        y[i] = (m * x[i] + (n - m) * y[i - 1]) / n
    return y


def calc_zlcmq_window(closes: np.ndarray, highs: np.ndarray, lows: np.ndarray) -> Optional[np.ndarray]:
    """计算 ZLCMQ 序列（75日窗口）

    Args:
        closes: 收盘价数组（可能含 NaN）
        highs: 最高价数组（可能含 NaN）
        lows: 最低价数组（可能含 NaN）

    Returns:
        ZLCMQ 数组（长度=实际数据点数），数据不足75返回 None
    """
    # 过滤 NaN（等效于原始代码的 None 过滤，只保留有效数据点）
    mask = ~(np.isnan(closes) | np.isnan(highs) | np.isnan(lows))
    c = closes[mask]
    h = highs[mask]
    l = lows[mask]
    if len(c) < 75:
        return None
    lo75 = np.min(l[-75:])
    hi75 = np.max(h[-75:])
    var7 = (hi75 - lo75) / 100.0
    if var7 < 1e-10:
        return None
    raw = np.nan_to_num((c[-75:] - lo75) / var7, nan=0.0)
    var8 = tdx_sma(raw, 20, 1)
    var8s = tdx_sma(var8, 15, 1)
    vara = 3.0 * var8 - 2.0 * var8s
    zlcmq = 100.0 - vara
    return zlcmq


def calc_zlcmq_full(close: np.ndarray, high: np.ndarray, low: np.ndarray) -> np.ndarray:
    """计算完整 ZLCMQ 序列（每个位置都用到当前位置的数据）

    逐日计算，每取到当前位置的75日窗口做一次计算。
    用于选股 Skill 的 pandas 向量化场景。
    NaN 值会被过滤，等效于原始代码的 None 过滤。

    Returns:
        ZLCMQ 数组，长度与输入相同，前74个值为 NaN
    """
    n = len(close)
    result = np.full(n, np.nan)
    for i in range(74, n):
        c_arr = close[:i + 1]
        h_arr = high[:i + 1]
        l_arr = low[:i + 1]
        # 过滤 NaN
        mask = ~(np.isnan(c_arr) | np.isnan(h_arr) | np.isnan(l_arr))
        c = c_arr[mask]
        h = h_arr[mask]
        l = l_arr[mask]
        if len(c) < 75:
            continue
        lo75 = np.min(l[-75:])
        hi75 = np.max(h[-75:])
        var7 = (hi75 - lo75) / 100.0
        if var7 < 1e-10:
            continue
        raw = np.nan_to_num((c[-75:] - lo75) / var7, nan=0.0)
        var8 = tdx_sma(raw, 20, 1)
        var8s = tdx_sma(var8, 15, 1)
        vara = 3.0 * var8 - 2.0 * var8s
        zlcmq = 100.0 - vara
        result[i] = zlcmq[-1]
    return result


# ============================================================
# 策略1: 布林带上轨突破
# ============================================================

def signals_bollinger_upper(
    close: np.ndarray,
    dates: List[str],
    params: Optional[dict] = None,
) -> SignalResult:
    """布林带上轨突破策略

    买入: 突破上轨 或 接近上轨<2%且在均线上方
    卖出: 跌破中轨 或 跌破下轨

    Params:
        period: 布林带周期 (default 25)
        std_mult: 标准差倍数 (default 2.0)
        near_pct: 接近上轨的阈值 (default 0.02)
    """
    p = params or {}
    period = p.get('period', 25)
    std_mult = p.get('std_mult', 1.8)
    near_pct = p.get('near_pct', 0.02)

    signals = {}
    for i in range(period + 1, len(close)):
        if np.isnan(close[i]):
            continue
        w = close[i - period:i]
        w = w[~np.isnan(w)]
        if len(w) < period:
            continue
        ma = np.mean(w)
        std = np.std(w, ddof=0)
        upper = ma + std_mult * std
        lower = ma - std_mult * std

        if np.isnan(close[i - 1]):
            continue
        # 买入：突破上轨
        if close[i - 1] <= upper and close[i] > upper:
            signals[dates[i]] = 'buy'
        # 买入：接近上轨 <2% 且在均线上方
        elif (upper - close[i]) / upper < near_pct and close[i] > ma:
            signals[dates[i]] = 'buy'
        # 卖出：跌破中轨（与买入互斥，同一交易日只产生一个信号）
        elif close[i - 1] >= ma and close[i] < ma:
            signals[dates[i]] = 'sell'
        # 卖出：跌破下轨
        elif close[i] < lower:
            signals[dates[i]] = 'sell'
    return signals


# ============================================================
# 策略2: 双均线交叉
# ============================================================

def signals_dual_ma(
    close: np.ndarray,
    dates: List[str],
    params: Optional[dict] = None,
) -> SignalResult:
    """双均线交叉策略

    买入: 短均线上穿长均线
    卖出: 短均线下穿长均线

    Params:
        short_period: 短均线周期 (default 7)
        long_period: 长均线周期 (default 60)
    """
    p = params or {}
    sp = p.get('short_period', 7)
    lp = p.get('long_period', 60)

    signals = {}
    n = len(close)

    # 计算均线
    ma_short = np.full(n, np.nan)
    ma_long = np.full(n, np.nan)
    for i in range(n):
        if np.isnan(close[i]):
            continue
        ws = close[max(0, i - sp + 1):i + 1]
        ws = ws[~np.isnan(ws)]
        if len(ws) >= sp:
            ma_short[i] = np.mean(ws)
        wl = close[max(0, i - lp + 1):i + 1]
        wl = wl[~np.isnan(wl)]
        if len(wl) >= lp:
            ma_long[i] = np.mean(wl)

    # 交叉信号
    for i in range(1, n):
        if any(np.isnan(x) for x in [close[i], ma_short[i], ma_long[i], ma_short[i - 1], ma_long[i - 1]]):
            continue
        # 金叉买入
        if ma_short[i - 1] <= ma_long[i - 1] and ma_short[i] > ma_long[i]:
            signals[dates[i]] = 'buy'
        # 死叉卖出
        elif ma_short[i - 1] >= ma_long[i - 1] and ma_short[i] < ma_long[i]:
            signals[dates[i]] = 'sell'
    return signals


# ============================================================
# 策略3: 增强筹码策略（ZLCMQ）
# ============================================================

def signals_enhanced_chip(
    close: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    vol: np.ndarray,
    open_: np.ndarray,
    dates: List[str],
    params: Optional[dict] = None,
) -> SignalResult:
    """增强筹码策略

    买入条件:
      1. ZLCMQ 近N天最高值 >= min_high
      2. ZLCMQ 从高点回落 >= min_fall
      3. 前一日 ZLCMQ >= 95 且当日 < 95（拐头确认）
      4. 当日收阳 或 收盘高于昨日
      5. 放量突破（量比 > vol_surge_mult）
      6. 站上MA60（>98%）

    卖出: ZLCMQ < chip_exit 且前一日也 < chip_exit

    Params:
        n_days: 回望天数 (default 5)
        min_high: ZLCMQ最高阈值 (default 98)
        min_fall: 回落最小幅度 (default 5)
        chip_exit: 卖出ZLCMQ阈值 (default 15)
        vol_surge_mult: 量能倍数 (default 1.5)
    """
    p = params or {}
    n_days = p.get('n_days', 5)
    min_high = p.get('min_high', 98)
    min_fall = p.get('min_fall', 5)
    chip_exit = p.get('chip_exit', 15)
    vol_mult = p.get('vol_surge_mult', 1.5)

    signals = {}
    for i in range(75, len(close)):
        if np.isnan(close[i]):
            continue
        # 计算 ZLCMQ
        c_arr = close[:i + 1]
        h_arr = high[:i + 1]
        l_arr = low[:i + 1]
        zlcmq = calc_zlcmq_window(c_arr, h_arr, l_arr)
        if zlcmq is None:
            continue

        cur_z = zlcmq[-1]
        prev_z = zlcmq[-2] if len(zlcmq) > 1 else cur_z

        # 近N天最高
        zw = zlcmq[-n_days:] if len(zlcmq) >= n_days else zlcmq
        zq_high = np.max(zw)

        # 条件检查
        if zq_high < min_high:
            continue
        if zq_high - cur_z < min_fall:
            continue
        if not (prev_z >= 95 and cur_z < 95):
            continue

        # 收阳或收盘高于昨日
        if np.isnan(open_[i]):
            continue
        is_stable = (close[i] > open_[i]) or (i > 0 and not np.isnan(close[i - 1]) and close[i] > close[i - 1])
        if not is_stable:
            continue

        # 放量
        if not np.isnan(vol[i]) and vol[i] > 0:
            rv = vol[max(0, i - 20):i]
            rv = rv[~np.isnan(rv)]
            if len(rv) > 0 and vol[i] < np.mean(rv) * vol_mult:
                continue
        else:
            continue

        # 站上MA60
        ma60w = close[max(0, i - 59):i + 1]
        ma60w = ma60w[~np.isnan(ma60w)]
        if len(ma60w) >= 30 and close[i] < np.mean(ma60w) * 0.98:
            continue

        signals[dates[i]] = 'buy'

        # 卖出：ZLCMQ 跌破退出线
        if cur_z < chip_exit and prev_z < chip_exit:
            signals[dates[i]] = 'sell'

    return signals


# ============================================================
# 策略4: 强势股回调企稳
# ============================================================

def signals_pullback_stable(
    close: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    vol: np.ndarray,
    open_: np.ndarray,
    dates: List[str],
    params: Optional[dict] = None,
) -> SignalResult:
    """强势股回调企稳策略（2年回测: +82.07%, 夏普1.459）

    买入条件:
      1. ZLCMQ 近N天曾达到 min_high 以上
      2. ZLCMQ 从高点回落 >= min_fall
      3. 企稳条件 5选3:
         - 真阳线 (C > O)
         - 收盘高于昨日 (C > REF(C,1))
         - 低点抬高 (L > REF(L,1))
         - 缩量 (VOL < MA(VOL,5))
         - 站上5日线 (C > MA(C,5))

    卖出:
      - ZLCMQ < 20
      - 跌破MA60

    Params:
        n_days: 回望天数 (default 8)
        min_high: ZLCMQ高位阈值 (default 95)
        min_fall: 回落最小幅度 (default 5)
        stable_threshold: 企稳条件阈值 (default 3, 即5选3)
    """
    p = params or {}
    n_days = p.get('n_days', 8)
    min_high = p.get('min_high', 95)
    min_fall = p.get('min_fall', 5)
    stable_thr = p.get('stable_threshold', 3)

    signals = {}
    for i in range(75, len(close)):
        if np.isnan(close[i]):
            continue
        # 计算 ZLCMQ
        c_arr = close[:i + 1]
        h_arr = high[:i + 1]
        l_arr = low[:i + 1]
        zlcmq = calc_zlcmq_window(c_arr, h_arr, l_arr)
        if zlcmq is None:
            continue

        cur_z = zlcmq[-1]
        zw = zlcmq[-n_days:] if len(zlcmq) >= n_days else zlcmq

        # 高位+回落
        if np.max(zw) < min_high:
            continue
        if np.max(zw) - cur_z < min_fall:
            continue

        # 企稳 5选3
        cl = close[i]
        op = open_[i] if not np.isnan(open_[i]) else cl
        sc = 0
        # 1. 真阳线
        if cl > op:
            sc += 1
        # 2. 收盘高于昨日
        if i > 0 and not np.isnan(close[i - 1]) and cl > close[i - 1]:
            sc += 1
        # 3. 低点抬高
        if i > 0 and not np.isnan(low[i]) and not np.isnan(low[i - 1]) and low[i] > low[i - 1]:
            sc += 1
        # 4. 缩量（低于近5日均量）
        if not np.isnan(vol[i]) and vol[i] > 0:
            rv = vol[max(0, i - 5):i]
            rv = rv[~np.isnan(rv)]
            if len(rv) > 0 and vol[i] < np.mean(rv):
                sc += 1
        # 5. 站上5日线
        m5 = close[max(0, i - 5):i]
        m5 = m5[~np.isnan(m5)]
        if len(m5) > 0 and cl > np.mean(m5):
            sc += 1

        if sc >= stable_thr:
            signals[dates[i]] = 'buy'

        # 卖出：ZLCMQ 极低
        if cur_z < 20:
            signals[dates[i]] = 'sell'
        # 卖出：跌破MA60
        else:
            ma60w = c_arr[max(0, len(c_arr) - 60):]
            ma60w = ma60w[~np.isnan(ma60w)]
            if len(ma60w) >= 30:
                ma60 = np.mean(ma60w)
                if i > 0 and not np.isnan(close[i - 1]) and close[i - 1] >= ma60 and cl < ma60:
                    signals[dates[i]] = 'sell'

    return signals


# ============================================================
# 策略5: 均线趋势跟踪（调优新增 2026-04-16）
# ============================================================

def signals_trend_ma(
    close: np.ndarray,
    dates: List[str],
    params: Optional[dict] = None,
) -> SignalResult:
    """均线趋势跟踪策略（训练+20.4%, 验证+20.7%）

    买入: 股价在均线上方连续confirm_days天 + 均线向上拐头
    卖出: 股价跌破均线

    Params:
        ma_period: 均线周期 (default 15)
        confirm_days: 确认天数 (default 3)
    """
    p = params or {}
    mp = p.get('ma_period', 15)
    cd = p.get('confirm_days', 3)

    signals = {}
    n = len(close)
    ma = np.full(n, np.nan)
    for i in range(mp - 1, n):
        w = close[i - mp + 1:i + 1]
        w = w[~np.isnan(w)]
        if len(w) >= mp:
            ma[i] = np.mean(w)

    in_pos = False
    above = 0
    for i in range(1, n):
        if np.isnan(close[i]) or np.isnan(ma[i]) or np.isnan(ma[i - 1]):
            continue
        above = above + 1 if close[i] > ma[i] else 0
        if not in_pos and above >= cd and ma[i] > ma[i - 1]:
            signals[dates[i]] = 'buy'
            in_pos = True
        elif in_pos and close[i] < ma[i]:
            signals[dates[i]] = 'sell'
            in_pos = False
    return signals


# ============================================================
# 策略6: 涨停洗盘（Limit Up Shakeout）
# ============================================================

def signals_limit_up_shakeout(
    close: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    vol: np.ndarray,
    open_: np.ndarray,
    dates: List[str],
    params: Optional[dict] = None,
) -> SignalResult:
    """涨停洗盘策略（Limit Up Shakeout）

    逻辑：主力拉涨停后次日洗盘，放量不破昨收 = 筹码稳固，短线机会。

    买入条件（全部满足）:
      1. 昨日涨停：prev_close >= prev2_close × (1 + limit_up_pct)
      2. 今日收阴：today_close < today_open
      3. 今日放量：today_vol >= prev_vol × vol_surge_mult
      4. 不破昨收：today_low >= prev_close × (1 - max_break_pct)

    卖出: 跌破买入价 stop_loss_pct（exit_config 处理止盈）

    Params:
        limit_up_pct: 涨停判定阈值 (default 0.095)
        vol_surge_mult: 放量倍数 (default 2.0)
        max_break_pct: 最大跌破昨收比例 (default 0.02)
        hold_days: 最大持仓天数 (default 7)
        stop_loss_pct: 止损比例 (default 0.05)
    """
    p = params or {}
    limit_up_pct = p.get('limit_up_pct', 0.095)
    vol_surge_mult = p.get('vol_surge_mult', 2.0)
    max_break_pct = p.get('max_break_pct', 0.02)
    hold_days = p.get('hold_days', 7)
    stop_loss_pct = p.get('stop_loss_pct', 0.05)

    signals = {}
    buy_info = {}  # date_idx -> buy_price

    for i in range(2, len(close)):
        if np.isnan(close[i]) or np.isnan(close[i - 1]) or np.isnan(close[i - 2]):
            continue
        if np.isnan(open_[i]) or np.isnan(low[i]) or np.isnan(vol[i]):
            continue
        if np.isnan(vol[i - 1]):
            continue

        # 1. 昨日涨停
        if close[i - 1] < close[i - 2] * (1 + limit_up_pct):
            continue
        # 2. 今日收阴
        if close[i] >= open_[i]:
            continue
        # 3. 今日放量
        if vol[i - 1] <= 0:
            continue
        if vol[i] < vol[i - 1] * vol_surge_mult:
            continue
        # 4. 不破昨收
        if low[i] < close[i - 1] * (1 - max_break_pct):
            continue

        signals[dates[i]] = 'buy'
        buy_info[i] = close[i]

    # 卖出信号：止损检测
    for buy_idx, buy_price in buy_info.items():
        for i in range(buy_idx + 1, min(buy_idx + hold_days + 1, len(close))):
            if np.isnan(close[i]):
                continue
            if close[i] < buy_price * (1 - stop_loss_pct):
                signals[dates[i]] = 'sell'
                break

    return signals


# ============================================================
# 策略7: 高窄旗形（High Tight Flag）
# ============================================================

def signals_high_tight_flag(
    close: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    vol: np.ndarray,
    open_: np.ndarray,
    dates: List[str],
    params: Optional[dict] = None,
) -> SignalResult:
    """高窄旗形策略（High Tight Flag）

    逻辑：暴涨后窄幅整理+缩量 = 弹簧压缩等待释放。

    买入条件（全部满足）:
      1. 强动量：momentum_period内 max(high)/min(low) > 1 + momentum_pct
      2. 极度收敛：flag_period内 max(high)/min(low) < 1 + flag_pct
      3. 高位抗跌：flag_period内 min(low) >= momentum_period max(high) × support_pct
      4. 缩量：今日量 < vol_period均量 × vol_shrink_pct

    Params:
        momentum_period: 动量计算周期 (default 40)
        momentum_pct: 动量涨幅阈值 (default 0.60, 即60%)
        flag_period: 旗形收敛周期 (default 10)
        flag_pct: 旗形振幅阈值 (default 0.15, 即15%)
        support_pct: 旗形最低支撑比例 (default 0.80)
        vol_period: 量能均值周期 (default 20)
        vol_shrink_pct: 缩量阈值 (default 0.6)
    """
    p = params or {}
    momentum_period = p.get('momentum_period', 40)
    momentum_pct = p.get('momentum_pct', 0.60)
    flag_period = p.get('flag_period', 10)
    flag_pct = p.get('flag_pct', 0.15)
    support_pct = p.get('support_pct', 0.80)
    vol_period = p.get('vol_period', 20)
    vol_shrink_pct = p.get('vol_shrink_pct', 0.6)

    signals = {}

    for i in range(momentum_period, len(close)):
        if np.isnan(close[i]) or np.isnan(vol[i]):
            continue

        # 1. 强动量
        mom_high = high[i - momentum_period:i + 1]
        mom_low = low[i - momentum_period:i + 1]
        mom_mask = ~(np.isnan(mom_high) | np.isnan(mom_low))
        if mom_mask.sum() == 0:
            continue
        if np.max(mom_high[mom_mask]) / np.min(mom_low[mom_mask]) <= 1 + momentum_pct:
            continue

        # 2. 极度收敛
        flag_start = max(i - flag_period + 1, 0)
        flag_high = high[flag_start:i + 1]
        flag_low = low[flag_start:i + 1]
        flag_mask = ~(np.isnan(flag_high) | np.isnan(flag_low))
        if flag_mask.sum() == 0:
            continue
        if np.max(flag_high[flag_mask]) / np.min(flag_low[flag_mask]) >= 1 + flag_pct:
            continue

        # 3. 高位抗跌
        mom_max_high = np.max(mom_high[mom_mask])
        flag_min_low = np.min(flag_low[flag_mask])
        if flag_min_low < mom_max_high * support_pct:
            continue

        # 4. 缩量
        vol_start = max(i - vol_period, 0)
        vol_window = vol[vol_start:i]
        vol_window = vol_window[~np.isnan(vol_window)]
        if len(vol_window) == 0:
            continue
        if vol[i] >= np.mean(vol_window) * vol_shrink_pct:
            continue

        signals[dates[i]] = 'buy'

    return signals


# ============================================================
# 策略注册表（参数 + 函数映射）
# ============================================================

CORE_STRATEGIES = {
    'bollinger_upper': {
        'name': '布林带上轨突破',
        'func': signals_bollinger_upper,
        'needs': ['close'],  # 只需 close
        'default_params': {
            'period': 25, 'std_mult': 1.8, 'near_pct': 0.02,
        },
        # 止盈配置（回测已验证）
        'exit_config': {
            'type': 'fixed',           # 固定止盈
            'take_profit_pct': 0.15,   # +15%
        },
    },
    'dual_ma': {
        'name': '双均线交叉',
        'func': signals_dual_ma,
        'needs': ['close'],
        'default_params': {
            'short_period': 7, 'long_period': 60,
        },
        # 止盈配置：固定15%最优（回测+101.44%，移动止盈反降到42-73%）
        'exit_config': {
            'type': 'fixed',
            'take_profit_pct': 0.15,   # 固定+15%止盈
        },
    },
    'enhanced_chip': {
        'name': '增强筹码策略',
        'func': signals_enhanced_chip,
        'needs': ['close', 'high', 'low', 'vol', 'open'],
        'default_params': {
            'n_days': 5, 'min_high': 98, 'min_fall': 5,
            'chip_exit': 15, 'vol_surge_mult': 1.5,
        },
        'exit_config': {
            'type': 'fixed',
            'take_profit_pct': 0.15,
        },
    },
    'pullback_stable': {
        'name': '强势股回调企稳',
        'func': signals_pullback_stable,
        'needs': ['close', 'high', 'low', 'vol', 'open'],
        'default_params': {
            'n_days': 8, 'min_high': 95, 'min_fall': 5,
            'stable_threshold': 3,
        },
        # 止盈配置：宽幅移动止盈v3最优（回测+99.55%/夏普1.591，比固定82%多赚17%）
        'exit_config': {
            'type': 'trailing',        # 移动止盈
            'tiers': [
                {'profit_pct': 0.05, 'trail_pct': 0.05},   # 赚5%启动，回撤5%卖出
                {'profit_pct': 0.15, 'trail_pct': 0.03},   # 赚15%收紧，回撤3%卖出
                {'profit_pct': 0.30, 'trail_pct': 0.02},   # 赚30%极紧，回撤2%卖出
            ],
            'min_profit_pct': 0.03,     # 最低锁定+3%
        },
    },
    'trend_ma': {
        'name': '均线趋势跟踪',
        'func': signals_trend_ma,
        'needs': ['close'],
        'default_params': {
            'ma_period': 15, 'confirm_days': 3,
        },
        'exit_config': {
            'type': 'fixed',
            'take_profit_pct': 0.15,
        },
    },
    'limit_up_shakeout': {
        'name': '涨停洗盘',
        'func': signals_limit_up_shakeout,
        'needs': ['close', 'high', 'low', 'vol', 'open'],
        'default_params': {
            'limit_up_pct': 0.095,
            'vol_surge_mult': 2.0,
            'max_break_pct': 0.02,
            'hold_days': 7,
            'stop_loss_pct': 0.05,
        },
        'exit_config': {
            'type': 'fixed',
            'take_profit_pct': 0.10,
        },
    },
    'high_tight_flag': {
        'name': '高窄旗形',
        'func': signals_high_tight_flag,
        'needs': ['close', 'high', 'low', 'vol', 'open'],
        'default_params': {
            'momentum_period': 40,
            'momentum_pct': 0.60,
            'flag_period': 10,
            'flag_pct': 0.15,
            'support_pct': 0.80,
            'vol_period': 20,
            'vol_shrink_pct': 0.6,
        },
        'exit_config': {
            'type': 'fixed',
            'take_profit_pct': 0.15,
        },
    },
}


def get_strategy(key: str) -> dict:
    """获取策略配置"""
    return CORE_STRATEGIES.get(key)


def list_strategies() -> list:
    """列出所有策略 key"""
    return list(CORE_STRATEGIES.keys())


def check_strategy_sell(key: str, df_dict: dict, ts_code: str = "") -> Optional[str]:
    """统一策略卖出信号检查

    Args:
        key: 策略key（如 'dual_ma', 'pullback_stable'）
        df_dict: 包含 close/high/low/vol/open/trade_date 的DataFrame
        ts_code: 股票代码（日志用）

    Returns:
        卖出原因字符串，无卖出信号时返回 None
    """
    cfg = CORE_STRATEGIES.get(key)
    if cfg is None:
        return None

    func = cfg["func"]
    params = cfg["default_params"]
    needs = cfg.get("needs", ["close"])

    df = df_dict.sort_values("trade_date") if "trade_date" in df_dict.columns else df_dict
    closes = df["close"].values.astype(float)
    dates = df["trade_date"].astype(str).tolist()

    try:
        if set(needs) >= {"close", "high", "low", "vol", "open"}:
            high = df["high"].values.astype(float) if "high" in df.columns else closes.copy()
            low = df["low"].values.astype(float) if "low" in df.columns else closes.copy()
            vol = df["vol"].values.astype(float) if "vol" in df.columns else np.zeros(len(df))
            open_ = df["open"].values.astype(float) if "open" in df.columns else closes.copy()
            signals = func(closes, high, low, vol, open_, dates, params)
        else:
            signals = func(closes, dates, params)
    except Exception as e:
        logger.warning(f"策略 {key} 信号计算失败 [{ts_code}]: {e}")
        return None

    # 检查最近一个交易日是否有卖出信号
    if dates and dates[-1] in signals and signals[dates[-1]] == "sell":
        return f"{cfg['name']}卖出信号"

    return None
