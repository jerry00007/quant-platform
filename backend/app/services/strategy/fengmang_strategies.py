"""
QuantWeave 锋芒波段策略模块 — 基于锋芒课程3层架构重写

三层架构：
  Layer 1 - 趋势判定（周期3）：MA(5,10,20,30) 判定酝势/起势/趋势
  Layer 2 - 信号确认：起势策略 + 10均模型（ZLCMQ/顶底图作为辅助确认，非独立信号）
  Layer 3 - 卖出纪律：均线趋势保利（5均破位→减仓，10均破位→清盘，绝不降阶）

核心规则来源（锋芒波段目录22万字）：
  - 周期3定义：line 1183-1187（5/10/20/30，趋势生命周期）
  - 起势定义：line 3284-3287（MA5>10>20>30 多头排列，股价上行，均线拐头）
  - 3条件买入：line 3479-3487（空头做多头+短期多头+中期临界）
  - 趋势特征：line 3493-3498（加速/震荡/衰落，30均破位=趋势结束）
  - 均线保利：line 4451-4484（5均不破10均不丢，延三踏五做主升）
  - 10均模型：line 2136-2161（5均-10均区域带，优先做第一次，开口大最佳）
  - 首阴模型：line 2379-2397（市场龙头，>=4连板，微幅平开或高开）
  - 操作路径：line 3379（打板→首阴→10均→周期4）
  - 大盘环境：line 2041-2055（多头多强头，空头做多头）

输入：numpy arrays (close, high, low, vol, open_) + dates list
输出：dict {date_str: 'buy'/'sell'}

兼容：与 backtest_all_strategies.py 回测引擎接口一致
"""

import numpy as np
from typing import Dict, List, Optional, Tuple
from core_signals import calc_zlcmq_window, calc_zlcmq_full

# Type alias
SignalResult = Dict[str, str]


# ============================================================
# 辅助函数：均线计算
# ============================================================

def _sma(arr: np.ndarray, period: int) -> np.ndarray:
    """简单移动平均，处理NaN"""
    n = len(arr)
    result = np.full(n, np.nan)
    for i in range(period - 1, n):
        w = arr[i - period + 1:i + 1]
        w = w[~np.isnan(w)]
        if len(w) >= period:
            result[i] = np.mean(w)
    return result


def _is_ma_going_up(ma: np.ndarray, i: int, lookback: int = 3) -> bool:
    """判断均线是否向上拐头（近lookback天内持续上行或触底回升）"""
    if i < lookback or np.isnan(ma[i]):
        return False
    # 当前值比lookback前高 = 整体向上
    if np.isnan(ma[i - lookback]):
        return False
    return ma[i] > ma[i - lookback]


# ============================================================
# Layer 1: 趋势判定（周期3）
# ============================================================

def detect_trend_state(close: np.ndarray, i: int,
                       ma5: np.ndarray = None, ma10: np.ndarray = None,
                       ma20: np.ndarray = None, ma30: np.ndarray = None) -> str:
    """判定第i天的周期3趋势状态

    Returns:
        'acceleration' - 加速区：股价>MA5，MA5之上
        'oscillation'  - 震荡区：MA5和MA10之间
        'bounce'       - 反弹区：MA10和MA20之间（10均反复）
        'weak'         - 衰弱区：MA20和MA30之间
        'trend_end'    - 趋势结束：MA30之下
        'unknown'      - 数据不足
    """
    if i < 30:
        return 'unknown'

    if ma5 is None:
        ma5 = _sma(close, 5)
    if ma10 is None:
        ma10 = _sma(close, 10)
    if ma20 is None:
        ma20 = _sma(close, 20)
    if ma30 is None:
        ma30 = _sma(close, 30)

    c = close[i]
    v5, v10, v20, v30 = ma5[i], ma10[i], ma20[i], ma30[i]

    if any(np.isnan(x) for x in [c, v5, v10, v20, v30]):
        return 'unknown'

    if c < v30:
        return 'trend_end'
    elif c < v20:
        return 'weak'
    elif c < v10:
        return 'bounce'
    elif c < v5:
        return 'oscillation'
    else:
        return 'acceleration'


def is_qishi(close: np.ndarray, i: int, require_turning: bool = True,
             ma5: np.ndarray = None, ma10: np.ndarray = None,
             ma20: np.ndarray = None, ma30: np.ndarray = None) -> bool:
    """判定第i天是否满足"起势"条件

    起势定义（line 3284-3287）：
    - MA5 > MA10 > MA20 > MA30 多头排列
    - 股价在MA5之上（股价上行）
    - 均线向上拐头（至少MA5和MA10向上）

    Args:
        close: 收盘价序列
        i: 当前位置
        require_turning: 是否要求均线拐头（首次起势判定时要求）
        ma5/ma10/ma20/ma30: 预计算的均线（避免重复计算，显著提速）
    """
    if i < 30:
        return False

    # 如果没有传入预计算均线，则现场计算
    if ma5 is None:
        ma5 = _sma(close, 5)
    if ma10 is None:
        ma10 = _sma(close, 10)
    if ma20 is None:
        ma20 = _sma(close, 20)
    if ma30 is None:
        ma30 = _sma(close, 30)

    c = close[i]
    v5, v10, v20, v30 = ma5[i], ma10[i], ma20[i], ma30[i]

    # 数据有效性
    if any(np.isnan(x) for x in [c, v5, v10, v20, v30]):
        return False

    # 条件1：多头排列 MA5 > MA10 > MA20 > MA30
    if not (v5 > v10 > v20 > v30):
        return False

    # 条件2：股价在MA5之上（股价上行）
    if c < v5:
        return False

    # 条件3：均线向上拐头
    if require_turning:
        if not _is_ma_going_up(ma5, i, 3):
            return False
        if not _is_ma_going_up(ma10, i, 3):
            return False

    return True


def is_first_qishi(close: np.ndarray, i: int, lookback: int = 20,
                   ma5: np.ndarray = None, ma10: np.ndarray = None,
                   ma20: np.ndarray = None, ma30: np.ndarray = None) -> bool:
    """判定第i天是否是近lookback天内首次起势

    首次起势 = 当前满足起势，但之前一段时间不满足（酝势→起势的拐点）
    """
    # 如果没有传入预计算均线，则现场计算
    if ma5 is None:
        ma5 = _sma(close, 5)
    if ma10 is None:
        ma10 = _sma(close, 10)
    if ma20 is None:
        ma20 = _sma(close, 20)
    if ma30 is None:
        ma30 = _sma(close, 30)

    if not is_qishi(close, i, True, ma5, ma10, ma20, ma30):
        return False

    # 检查之前lookback天内是否已经持续多头排列（如果是则不是首次）
    for j in range(max(30, i - lookback), i):
        if not any(np.isnan(x) for x in [ma5[j], ma10[j], ma20[j], ma30[j]]):
            if ma5[j] > ma10[j] > ma20[j] > ma30[j]:
                return False  # 已经在多头排列中，不是首次
    return True


# ============================================================
# Layer 2 策略1: 起势策略（酝势→起势拐点）
# ============================================================

def signals_fengmang_qishi(
    close: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    vol: np.ndarray,
    open_: np.ndarray,
    dates: List[str],
    params: Optional[dict] = None,
) -> SignalResult:
    """锋芒起势策略（酝势→起势拐点入场）

    入场条件：
      1. Layer1 - 趋势：周期3首次起势（MA5>10>20>30 多头排列首次形成 + 拐头）
      2. Layer2 - 辅助确认（至少满足1个）：
         a. ZLCMQ >= zlcmq_min（筹码集中，主力控盘）
         b. 放量确认（量比 >= vol_ratio_min）
         c. 收阳线（收盘>开盘）
      3. 大盘环境过滤（需要外部传入，此处用成交量代理）

    卖出条件（Layer 3 均线趋势保利）：
      - 跌破MA10 → 清仓卖出
      - 固定止损 stop_loss_pct

    Params:
        zlcmq_min: ZLCMQ辅助确认最低值 (default 70)
        vol_ratio_min: 量能倍数最低值 (default 1.0，即不放量也行)
        stop_loss_pct: 固定止损比例 (default -0.08)
        require_qishi_first: 是否要求首次起势 (default True)
        ma_exit_period: 均线保利止损用的MA周期 (default 10, 即MA10跌破卖出)
    """
    p = params or {}
    zlcmq_min = p.get('zlcmq_min', 70)
    vol_ratio_min = p.get('vol_ratio_min', 1.0)
    stop_loss_pct = p.get('stop_loss_pct', -0.08)
    require_first = p.get('require_qishi_first', True)
    ma_exit_period = p.get('ma_exit_period', 10)

    signals = {}
    n = len(close)

    # 预计算均线
    ma5 = _sma(close, 5)
    ma10 = _sma(close, 10)
    ma20 = _sma(close, 20)
    ma30 = _sma(close, 30)
    ma_exit = _sma(close, ma_exit_period)  # 保利止损线

    # 持仓跟踪（用于止损和均线保利）
    holding = False
    buy_price = 0.0
    buy_idx = -1

    for i in range(75, n):  # 75起步因为要算ZLCMQ
        if np.isnan(close[i]):
            continue

        # --- 卖出判定（Layer 3） ---
        if holding:
            c = close[i]

            # 固定止损
            pnl = (c - buy_price) / buy_price
            if pnl <= stop_loss_pct:
                signals[dates[i]] = 'sell'
                holding = False
                continue

            # 均线趋势保利：跌破MA止损线 → 清仓
            if not np.isnan(ma_exit[i]) and c < ma_exit[i]:
                # 前一天还在MA止损线之上（跌破确认）
                if buy_idx > 0 and not np.isnan(close[i - 1]) and not np.isnan(ma_exit[i - 1]):
                    if close[i - 1] >= ma_exit[i - 1]:
                        signals[dates[i]] = 'sell'
                        holding = False
                        continue

        # --- 买入判定（Layer 1 + Layer 2） ---
        if holding:
            continue

        # Layer 1: 起势判定（传入预计算均线，避免O(n)重复计算）
        if require_first:
            trend_ok = is_first_qishi(close, i, lookback=15,
                                       ma5=ma5, ma10=ma10, ma20=ma20, ma30=ma30)
        else:
            trend_ok = is_qishi(close, i, True, ma5=ma5, ma10=ma10, ma20=ma20, ma30=ma30)

        if not trend_ok:
            continue

        # Layer 2: 辅助确认（ZLCMQ / 放量 / 收阳，满足任一即可）
        confirmed = False

        # 确认条件A：ZLCMQ >= zlcmq_min
        c_arr = close[:i + 1]
        h_arr = high[:i + 1]
        l_arr = low[:i + 1]
        zlcmq = calc_zlcmq_window(c_arr, h_arr, l_arr)
        if zlcmq is not None and zlcmq[-1] >= zlcmq_min:
            confirmed = True

        # 确认条件B：放量（量比 >= vol_ratio_min）
        if not confirmed and not np.isnan(vol[i]) and vol[i] > 0:
            rv = vol[max(0, i - 20):i]
            rv = rv[~np.isnan(rv)]
            if len(rv) > 0:
                avg_vol = np.mean(rv)
                if avg_vol > 0 and vol[i] / avg_vol >= vol_ratio_min:
                    confirmed = True

        # 确认条件C：收阳线
        if not confirmed and not np.isnan(open_[i]):
            if close[i] > open_[i]:
                confirmed = True

        if confirmed:
            signals[dates[i]] = 'buy'
            holding = True
            buy_price = close[i]
            buy_idx = i

    return signals


# ============================================================
# Layer 2 策略2: 10均模型策略
# ============================================================

def signals_fengmang_10jun(
    close: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    vol: np.ndarray,
    open_: np.ndarray,
    dates: List[str],
    params: Optional[dict] = None,
) -> SignalResult:
    """锋芒10均模型策略

    核心思路（line 2136-2161, 4010-4027）：
    - 股价位于MA5和MA10之间（震荡区）
    - 5均和10均开口大（刚发散，不是收敛）
    - 优先做第一次（MA5下穿到MA5上穿之间的第一次回调）
    - 整体趋势多头（周期3 MA5>10>20>30）

    入场条件：
      1. Layer1 - 趋势：周期3多头排列（MA5>10>20>30，不要求首次）
      2. Layer2 - 信号：
         a. 股价在MA5和MA10之间（跌破MA5但未破MA10）
         b. 5均10均开口大（MA5-MA10差值在扩大 or 刚刚开始发散）
         c. 优先只做第一次（近N天内没有出现过MA10以下的情况）
         d. ZLCMQ辅助 >= zlcmq_min 或 收阳确认
      3. 量能：成交额 >= amount_min（中军标的，资金容量够大）

    卖出（Layer 3 均线趋势保利）：
      - 跌破MA10 → 清仓（"10均不破不清盘"的反面）
      - 绝不降阶：周期3的10均止损就是10均，不看周期4

    Params:
        zlcmq_min: ZLCMQ辅助阈值 (default 50)
        gap_min_pct: MA5和MA10最小发散百分比 (default 0.01, 即1%)
        first_only_lookback: 首次判定的回看天数 (default 15)
        stop_loss_pct: 固定止损 (default -0.08)
        amount_min: 最低成交额（万元），用于筛选中军标的 (default 0, 不过滤)
        ma_exit_period: 保利止损MA周期 (default 10)
    """
    p = params or {}
    zlcmq_min = p.get('zlcmq_min', 50)
    gap_min_pct = p.get('gap_min_pct', 0.01)
    first_lookback = p.get('first_only_lookback', 15)
    stop_loss_pct = p.get('stop_loss_pct', -0.08)
    amount_min = p.get('amount_min', 0)
    ma_exit_period = p.get('ma_exit_period', 10)

    signals = {}
    n = len(close)

    # 预计算均线
    ma5 = _sma(close, 5)
    ma10 = _sma(close, 10)
    ma20 = _sma(close, 20)
    ma30 = _sma(close, 30)
    ma_exit = _sma(close, ma_exit_period)  # 保利止损线

    holding = False
    buy_price = 0.0
    buy_idx = -1

    for i in range(75, n):
        if np.isnan(close[i]):
            continue

        c = close[i]

        # --- 卖出判定（Layer 3） ---
        if holding:
            # 固定止损
            pnl = (c - buy_price) / buy_price
            if pnl <= stop_loss_pct:
                signals[dates[i]] = 'sell'
                holding = False
                continue

            # 均线趋势保利：跌破MA止损线 → 清仓
            if not np.isnan(ma_exit[i]) and c < ma_exit[i]:
                if buy_idx > 0 and not np.isnan(close[i - 1]) and not np.isnan(ma_exit[i - 1]):
                    if close[i - 1] >= ma_exit[i - 1]:
                        signals[dates[i]] = 'sell'
                        holding = False
                        continue

        # --- 买入判定 ---
        if holding:
            continue

        # Layer 1: 周期3多头排列（MA5>10>20>30）
        v5, v10, v20, v30 = ma5[i], ma10[i], ma20[i], ma30[i]
        if any(np.isnan(x) for x in [v5, v10, v20, v30]):
            continue
        if not (v5 > v10 > v20 > v30):
            continue

        # Layer 2a: 股价在MA5和MA10之间（跌破5均，未破10均）
        if not (v10 <= c <= v5):
            continue

        # Layer 2b: 5均和10均开口大（发散，MA5比MA10高gap_min_pct以上）
        gap_pct = (v5 - v10) / v10 if v10 > 0 else 0
        if gap_pct < gap_min_pct:
            continue

        # Layer 2c: 优先做第一次（近first_lookback天内没有跌破MA10的情况）
        is_first = True
        for j in range(max(75, i - first_lookback), i):
            if np.isnan(close[j]) or np.isnan(ma10[j]):
                continue
            if close[j] < ma10[j]:
                is_first = False
                break
        if not is_first:
            continue

        # Layer 2d: 辅助确认（ZLCMQ >= zlcmq_min 或 收阳）
        confirmed = False

        # ZLCMQ确认
        c_arr = close[:i + 1]
        h_arr = high[:i + 1]
        l_arr = low[:i + 1]
        zlcmq = calc_zlcmq_window(c_arr, h_arr, l_arr)
        if zlcmq is not None and zlcmq[-1] >= zlcmq_min:
            confirmed = True

        # 收阳确认
        if not confirmed and not np.isnan(open_[i]):
            if close[i] > open_[i]:
                confirmed = True

        if not confirmed:
            continue

        # 量能过滤（可选）
        # 这里用 vol 数据做简单判断，不硬性要求

        signals[dates[i]] = 'buy'
        holding = True
        buy_price = c
        buy_idx = i

    return signals


# ============================================================
# Layer 2 策略3: 回调企稳策略（锋芒版重写）
# ============================================================

def signals_fengmang_pullback(
    close: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    vol: np.ndarray,
    open_: np.ndarray,
    dates: List[str],
    params: Optional[dict] = None,
) -> SignalResult:
    """锋芒回调企稳策略（原"强势股回调企稳"的锋芒版重写）

    核心改进：
    1. 不再把ZLCMQ作为独立买卖信号，而是作为Layer2辅助确认
    2. 加入Layer1趋势判定：必须在周期3多头趋势中
    3. 加入Layer3均线保利卖出（替代原来的ZLCMQ<20卖出）

    入场条件：
      1. Layer1 - 趋势：周期3起势或多头（MA5>10>20>30，均线向上）
      2. Layer2 - 信号：
         a. ZLCMQ近N天曾达到min_high以上（筹码高位 = 主力控盘）
         b. ZLCMQ从高点回落 >= min_fall（回调到位）
         c. 企稳条件5选3：
            - 真阳线 (C > O)
            - 收盘高于昨日 (C > REF(C,1))
            - 低点抬高 (L > REF(L,1))
            - 缩量 (VOL < MA(VOL,5))
            - 站上5日线 (C > MA(C,5))
      3. 趋势确认：股价在MA30之上（短期趋势未结束）

    卖出（Layer 3 均线趋势保利）：
      - 跌破MA10 → 清仓（趋势保利核心法则）
      - 跌破MA30 → 清仓（短期趋势结束）
      - 固定止损 stop_loss_pct

    Params:
        n_days: ZLCMQ回望天数 (default 8)
        min_high: ZLCMQ高位阈值 (default 95)
        min_fall: ZLCMQ回落幅度 (default 5)
        stable_threshold: 企稳条件数 (default 3)
        stop_loss_pct: 固定止损 (default -0.08)
        ma_exit_period: 保利止损MA周期 (default 10)
    """
    p = params or {}
    n_days = p.get('n_days', 8)
    min_high = p.get('min_high', 95)
    min_fall = p.get('min_fall', 5)
    stable_thr = p.get('stable_threshold', 3)
    stop_loss_pct = p.get('stop_loss_pct', -0.08)
    ma_exit_period = p.get('ma_exit_period', 10)

    signals = {}
    n = len(close)

    # 预计算均线
    ma5 = _sma(close, 5)
    ma10 = _sma(close, 10)
    ma20 = _sma(close, 20)
    ma30 = _sma(close, 30)
    ma_exit = _sma(close, ma_exit_period)  # 保利止损线

    holding = False
    buy_price = 0.0
    buy_idx = -1

    for i in range(75, n):
        if np.isnan(close[i]):
            continue

        c = close[i]

        # --- 卖出判定（Layer 3 均线趋势保利） ---
        if holding:
            # 固定止损
            pnl = (c - buy_price) / buy_price
            if pnl <= stop_loss_pct:
                signals[dates[i]] = 'sell'
                holding = False
                continue

            # 均线趋势保利：跌破MA止损线 → 清仓
            if not np.isnan(ma_exit[i]) and c < ma_exit[i]:
                if not np.isnan(close[i - 1]) and not np.isnan(ma_exit[i - 1]):
                    if close[i - 1] >= ma_exit[i - 1]:
                        signals[dates[i]] = 'sell'
                        holding = False
                        continue

            # 趋势结束：跌破MA30 → 清仓（30均破位=趋势不成立）
            if not np.isnan(ma30[i]) and c < ma30[i]:
                if not np.isnan(close[i - 1]) and not np.isnan(ma30[i - 1]):
                    if close[i - 1] >= ma30[i - 1]:
                        signals[dates[i]] = 'sell'
                        holding = False
                        continue

        # --- 买入判定 ---
        if holding:
            continue

        # Layer 1: 趋势确认 — 必须在周期3多头中
        v5, v10, v20, v30 = ma5[i], ma10[i], ma20[i], ma30[i]
        if any(np.isnan(x) for x in [v5, v10, v20, v30]):
            continue
        # 宽松多头：MA5>MA10>MA30（不强制MA20在中间，因为回调时MA5可能已下来）
        # 核心要求：MA30之上（趋势未结束）+ MA10 > MA30（大趋势多头）
        if c < v30:
            continue  # 30均之下=趋势结束
        if v10 < v30:
            continue  # 10均在30均之下=不是多头结构

        # Layer 2: ZLCMQ 高位回落 + 企稳
        c_arr = close[:i + 1]
        h_arr = high[:i + 1]
        l_arr = low[:i + 1]
        zlcmq = calc_zlcmq_window(c_arr, h_arr, l_arr)
        if zlcmq is None:
            continue

        cur_z = zlcmq[-1]
        zw = zlcmq[-n_days:] if len(zlcmq) >= n_days else zlcmq

        # ZLCMQ高位 + 回落
        if np.max(zw) < min_high:
            continue
        if np.max(zw) - cur_z < min_fall:
            continue

        # 企稳 5选3
        cl = c
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
            holding = True
            buy_price = c
            buy_idx = i

    return signals


# ============================================================
# Layer 2 策略4: 增强筹码策略（锋芒版重写）
# ============================================================

def signals_fengmang_chip(
    close: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    vol: np.ndarray,
    open_: np.ndarray,
    dates: List[str],
    params: Optional[dict] = None,
) -> SignalResult:
    """锋芒增强筹码策略（精确控制版ZLCMQ的锋芒框架重写）

    核心改进：
    1. ZLCMQ从独立信号降级为Layer2辅助确认
    2. 必须在周期3多头趋势中（Layer1强制）
    3. 卖出用均线保利替代ZLCMQ阈值卖出

    入场条件：
      1. Layer1 - 趋势：周期3多头（MA5>10>20>30 或 MA10>20>30+股价在MA10上）
      2. Layer2 - ZLCMQ精确控制：
         a. ZLCMQ近N天最高 >= min_high（筹码高度集中）
         b. ZLCMQ从高点回落 >= min_fall（主力洗盘回调）
         c. 前一日ZLCMQ >= 95 且当日 < 95（拐头确认）
         d. 当日收阳或收盘高于昨日
         e. 放量确认（量比 > vol_surge_mult）
      3. 趋势确认：股价在MA30之上

    卖出（Layer 3 均线趋势保利）：
      - 跌破MA10 → 清仓
      - 跌破MA30 → 清仓（趋势结束）
      - 固定止损

    Params:
        n_days: 回望天数 (default 5)
        min_high: ZLCMQ高位阈值 (default 98)
        min_fall: 回落最小幅度 (default 5)
        vol_surge_mult: 量能倍数 (default 1.5)
        stop_loss_pct: 固定止损 (default -0.08)
        ma_exit_period: 保利止损MA周期 (default 10)
    """
    p = params or {}
    n_days = p.get('n_days', 5)
    min_high = p.get('min_high', 98)
    min_fall = p.get('min_fall', 5)
    vol_mult = p.get('vol_surge_mult', 1.5)
    stop_loss_pct = p.get('stop_loss_pct', -0.08)
    ma_exit_period = p.get('ma_exit_period', 10)

    signals = {}
    n = len(close)

    # 预计算均线
    ma5 = _sma(close, 5)
    ma10 = _sma(close, 10)
    ma20 = _sma(close, 20)
    ma30 = _sma(close, 30)
    ma_exit = _sma(close, ma_exit_period)  # 保利止损线

    holding = False
    buy_price = 0.0
    buy_idx = -1

    for i in range(75, n):
        if np.isnan(close[i]):
            continue

        c = close[i]

        # --- 卖出判定（Layer 3） ---
        if holding:
            pnl = (c - buy_price) / buy_price
            if pnl <= stop_loss_pct:
                signals[dates[i]] = 'sell'
                holding = False
                continue

            # 跌破MA止损线 → 清仓
            if not np.isnan(ma_exit[i]) and c < ma_exit[i]:
                if not np.isnan(close[i - 1]) and not np.isnan(ma_exit[i - 1]):
                    if close[i - 1] >= ma_exit[i - 1]:
                        signals[dates[i]] = 'sell'
                        holding = False
                        continue

            # 跌破MA30 → 清仓（趋势结束）
            if not np.isnan(ma30[i]) and c < ma30[i]:
                if not np.isnan(close[i - 1]) and not np.isnan(ma30[i - 1]):
                    if close[i - 1] >= ma30[i - 1]:
                        signals[dates[i]] = 'sell'
                        holding = False
                        continue

        # --- 买入判定 ---
        if holding:
            continue

        # Layer 1: 趋势确认
        v10, v30 = ma10[i], ma30[i]
        if any(np.isnan(x) for x in [v10, v30]):
            continue
        # 10均>30均（大趋势多头） + 股价在30均之上
        if v10 < v30 or c < v30:
            continue

        # Layer 2: ZLCMQ精确控制
        c_arr = close[:i + 1]
        h_arr = high[:i + 1]
        l_arr = low[:i + 1]
        zlcmq = calc_zlcmq_window(c_arr, h_arr, l_arr)
        if zlcmq is None:
            continue

        cur_z = zlcmq[-1]
        prev_z = zlcmq[-2] if len(zlcmq) > 1 else cur_z

        # ZLCMQ高位 + 回落
        zw = zlcmq[-n_days:] if len(zlcmq) >= n_days else zlcmq
        zq_high = np.max(zw)
        if zq_high < min_high:
            continue
        if zq_high - cur_z < min_fall:
            continue

        # 拐头确认（前一日>=95，当日<95）
        if not (prev_z >= 95 and cur_z < 95):
            continue

        # 收阳或收盘高于昨日
        if np.isnan(open_[i]):
            continue
        is_stable = (close[i] > open_[i]) or (i > 0 and not np.isnan(close[i - 1]) and close[i] > close[i - 1])
        if not is_stable:
            continue

        # 放量确认
        if not np.isnan(vol[i]) and vol[i] > 0:
            rv = vol[max(0, i - 20):i]
            rv = rv[~np.isnan(rv)]
            if len(rv) > 0 and vol[i] < np.mean(rv) * vol_mult:
                continue
        else:
            continue

        signals[dates[i]] = 'buy'
        holding = True
        buy_price = c
        buy_idx = i

    return signals


# ============================================================
# 策略注册表（锋芒框架策略）
# ============================================================

FENGMANG_STRATEGIES = {
    'fengmang_qishi': {
        'name': '锋芒·起势策略',
        'func': signals_fengmang_qishi,
        'needs': ['close', 'high', 'low', 'vol', 'open'],
        'default_params': {
            'zlcmq_min': 70,
            'vol_ratio_min': 1.0,
            'stop_loss_pct': -0.08,
            'require_qishi_first': True,
            'ma_exit_period': 10,
        },
        'description': '酝势→起势拐点入场，均线趋势保利止损',
        'source': '锋芒 line 3284-3287（起势定义）+ line 4451-4484（均线保利）',
    },
    'fengmang_10jun': {
        'name': '锋芒·10均模型',
        'func': signals_fengmang_10jun,
        'needs': ['close', 'high', 'low', 'vol', 'open'],
        'default_params': {
            'zlcmq_min': 50,
            'gap_min_pct': 0.01,
            'first_only_lookback': 15,
            'stop_loss_pct': -0.08,
            'ma_exit_period': 10,
        },
        'description': '多头趋势中MA5-MA10震荡区首次入场，10均止损',
        'source': '锋芒 line 2136-2161（10均定义）+ line 4010-4027（10均分类）',
    },
    'fengmang_pullback': {
        'name': '锋芒·回调企稳',
        'func': signals_fengmang_pullback,
        'needs': ['close', 'high', 'low', 'vol', 'open'],
        'default_params': {
            'n_days': 8,
            'min_high': 95,
            'min_fall': 5,
            'stable_threshold': 3,
            'stop_loss_pct': -0.08,
            'ma_exit_period': 10,
        },
        'description': '多头趋势中ZLCMQ高位回落企稳，均线保利止损（原回调企稳锋芒版）',
        'source': '锋芒 line 1183-1187（周期3）+ line 4451-4484（均线保利）',
    },
    'fengmang_chip': {
        'name': '锋芒·精确筹码',
        'func': signals_fengmang_chip,
        'needs': ['close', 'high', 'low', 'vol', 'open'],
        'default_params': {
            'n_days': 5,
            'min_high': 98,
            'min_fall': 5,
            'vol_surge_mult': 1.5,
            'stop_loss_pct': -0.08,
            'ma_exit_period': 10,
        },
        'description': '多头趋势中ZLCMQ精确控制拐头，均线保利止损（原增强筹码锋芒版）',
        'source': '锋芒 line 1183-1187（周期3）+ line 4451-4484（均线保利）',
    },
}


def get_fengmang_strategy(key: str) -> dict:
    """获取锋芒策略配置"""
    return FENGMANG_STRATEGIES.get(key)


def list_fengmang_strategies() -> list:
    """列出所有锋芒策略 key"""
    return list(FENGMANG_STRATEGIES.keys())
