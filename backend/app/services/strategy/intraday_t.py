"""
日内做T策略模块

A股T+1制度下只能做正T（先卖后买）：
1. 冲高回落卖 → 低点买回
2. 均价线偏离回归
3. 放量异动

信号类型：
- SELL_FIRST: 先卖出（正T），等低点买回
- BUY_BACK: 已卖出，建议买回价位

风控：
- 每笔不超过底仓10%
- 止损0.5%（卖出的票涨了超过0.5%就买回止损）
- 不在尾盘14:30后开新仓
"""

import logging
from dataclasses import dataclass
from typing import Optional
from enum import Enum

from app.services.data.intraday_data import (
    get_intraday_summary, get_minute_bars, get_realtime_snapshot
)

logger = logging.getLogger(__name__)


class TSignalType(Enum):
    SELL_FIRST = "sell_first"     # 正T：先卖
    BUY_BACK = "buy_back"         # 正T：买回
    STOP_LOSS = "stop_loss"       # 止损买回
    HOLD = "hold"                 # 继续持有等待


@dataclass
class TSignal:
    """做T信号"""
    ts_code: str
    name: str
    signal_type: TSignalType
    price: float           # 建议操作价格
    target_price: float    # 目标买回/卖出价
    quantity: int          # 建议数量
    reason: str            # 信号原因
    confidence: float      # 信心度 0-1
    deviation: float       # 当前偏离均价百分比
    rsi: float             # 分钟级RSI
    vol_ratio: float       # 量比
    amplitude: float       # 日内振幅
    change_pct: float      # 当日涨跌幅


def _calc_quantity(position_shares: int, available: int, price: float) -> int:
    """计算做T数量：取底仓10%，按100股取整"""
    qty = int(position_shares * 0.10)
    qty = max(qty // 100 * 100, 100)  # 至少100股
    qty = min(qty, available)          # 不超过可用
    return qty


def check_sell_first_signals(
    ts_code: str,
    name: str,
    shares: int,
    available: int,
    cost: float,
) -> Optional[TSignal]:
    """
    检测正T卖出信号（先卖后买）
    
    触发条件（满足任一）：
    1. 偏离均价线 > 1.5% + RSI > 75 → 冲高卖出
    2. 急速拉升（5分钟涨>1.5%）+ 放量（量比>2）→ 卖出
    3. 日内涨幅 > 3% + RSI > 70 → 高位卖出
    """
    summary = get_intraday_summary(ts_code)
    if "error" in summary or summary.get("bar_count", 0) < 10:
        return None
    
    current = summary["current"]
    deviation = summary["deviation"]
    rsi = summary["rsi"]
    vol_ratio = summary["vol_ratio"]
    amplitude = summary["amplitude"]
    change_pct = summary["change_pct"]
    avg_price = summary["avg_price"]
    day_high = summary["day_high"]
    day_low = summary["day_low"]
    bars = summary["bars"]
    
    # 不在尾盘14:30后开新T
    last_time = bars[-1].time if bars else ""
    if last_time >= "14:30":
        return None
    
    signal_reason = ""
    confidence = 0.0
    target_buyback = 0.0
    
    # 条件1：偏离均价线 > 1.5% + RSI > 75
    if deviation > 1.5 and rsi > 75:
        signal_reason = f"偏离均价{deviation:+.1f}%+RSI{rsi:.0f}超买"
        confidence = 0.7
        target_buyback = avg_price  # 回到均价买回
    
    # 条件2：急速拉升 + 放量
    if len(bars) >= 5:
        recent_5min_change = (bars[-1].close / bars[-5].close - 1) * 100
        if recent_5min_change > 1.5 and vol_ratio > 2.0:
            signal_reason = f"5分钟拉升{recent_5min_change:.1f}%+量比{vol_ratio:.1f}"
            confidence = max(confidence, 0.75)
            target_buyback = current * 0.985  # 回落1.5%买回
    
    # 条件3：涨幅 > 3% + RSI > 70
    if change_pct > 3.0 and rsi > 70:
        signal_reason = f"日涨{change_pct:.1f}%+RSI{rsi:.0f}"
        confidence = max(confidence, 0.65)
        target_buyback = current * 0.98
    
    if not signal_reason:
        return None
    
    # 计算买回价：均价线 或 当前价-1.5%，取较高者
    if target_buyback == 0:
        target_buyback = max(avg_price, current * 0.985)
    
    qty = _calc_quantity(shares, available, current)
    if qty < 100:
        return None
    
    return TSignal(
        ts_code=ts_code,
        name=name,
        signal_type=TSignalType.SELL_FIRST,
        price=current,
        target_price=round(target_buyback, 2),
        quantity=qty,
        reason=signal_reason,
        confidence=min(confidence, 0.95),
        deviation=deviation,
        rsi=rsi,
        vol_ratio=vol_ratio,
        amplitude=amplitude,
        change_pct=change_pct,
    )


def check_buy_back_signals(
    ts_code: str,
    name: str,
    sold_price: float,
    sold_quantity: int,
) -> Optional[TSignal]:
    """
    检测买回信号（已卖出后，检测低点）
    
    触发条件（满足任一）：
    1. 偏离均价线 < -1.5% → 超跌回归
    2. RSI < 25 → 分钟级超卖
    3. 到达目标买回价
    4. 止损：价格比卖出价涨了超过0.5%
    """
    summary = get_intraday_summary(ts_code)
    if "error" in summary or summary.get("bar_count", 0) < 5:
        return None
    
    current = summary["current"]
    deviation = summary["deviation"]
    rsi = summary["rsi"]
    avg_price = summary["avg_price"]
    
    signal_reason = ""
    confidence = 0.0
    
    # 止损：价格涨超过0.5%
    if current > sold_price * 1.005:
        return TSignal(
            ts_code=ts_code, name=name,
            signal_type=TSignalType.STOP_LOSS,
            price=current,
            target_price=0,
            quantity=sold_quantity,
            reason=f"⚠️止损：卖出价{sold_price}，现价{current}已涨{(current/sold_price-1)*100:.1f}%",
            confidence=0.95,
            deviation=deviation, rsi=rsi,
            vol_ratio=summary["vol_ratio"],
            amplitude=summary["amplitude"],
            change_pct=summary["change_pct"],
        )
    
    # 条件1：超跌回归
    if deviation < -1.5:
        signal_reason = f"偏离均价{deviation:.1f}%超跌回归"
        confidence = 0.7
    
    # 条件2：RSI超卖
    if rsi < 25:
        signal_reason = f"RSI={rsi:.0f}分钟级超卖"
        confidence = max(confidence, 0.75)
    
    # 条件3：接近均价线下方
    if current < avg_price and deviation < -0.5:
        signal_reason = f"价格{current}低于均价{avg_price:.2f}"
        confidence = max(confidence, 0.6)
    
    if not signal_reason:
        return None
    
    return TSignal(
        ts_code=ts_code, name=name,
        signal_type=TSignalType.BUY_BACK,
        price=current,
        target_price=0,
        quantity=sold_quantity,
        reason=signal_reason,
        confidence=min(confidence, 0.9),
        deviation=deviation, rsi=rsi,
        vol_ratio=summary["vol_ratio"],
        amplitude=summary["amplitude"],
        change_pct=summary["change_pct"],
    )


def scan_intraday_t_opportunities(positions: list[dict]) -> list[TSignal]:
    """
    扫描所有持仓的做T机会
    
    Args:
        positions: [{ts_code, name, shares, available, cost}, ...]
    
    Returns:
        list[TSignal]: 做T信号列表
    """
    signals = []
    
    for pos in positions:
        ts_code = pos["ts_code"]
        name = pos["name"]
        shares = pos["shares"]
        available = pos.get("available", 0)
        cost = pos["cost"]
        
        # 可用数量不够做T（至少100股）
        if available < 100:
            continue
        
        try:
            signal = check_sell_first_signals(ts_code, name, shares, available, cost)
            if signal:
                signals.append(signal)
        except Exception as e:
            logger.error(f"扫描做T信号失败 {ts_code}: {e}")
    
    # 按信心度排序
    signals.sort(key=lambda s: s.confidence, reverse=True)
    return signals


def format_t_signal(signal: TSignal) -> str:
    """格式化做T信号为可读文本"""
    emoji = {
        TSignalType.SELL_FIRST: "🔴卖出",
        TSignalType.BUY_BACK: "🟢买回",
        TSignalType.STOP_LOSS: "⛔止损买回",
        TSignalType.HOLD: "⏸️持有",
    }
    
    lines = [
        f"{emoji.get(signal.signal_type, '?')} {signal.name}({signal.ts_code})",
        f"  信号: {signal.reason}",
        f"  信心: {signal.confidence:.0%} | 建议数量: {signal.quantity}股",
    ]
    
    if signal.signal_type == TSignalType.SELL_FIRST:
        lines.append(f"  卖出价: {signal.price:.2f} → 目标买回: {signal.target_price:.2f}")
        profit = (signal.price - signal.target_price) * signal.quantity
        lines.append(f"  预期收益: {profit:+.0f}元")
    elif signal.signal_type in (TSignalType.BUY_BACK, TSignalType.STOP_LOSS):
        lines.append(f"  操作价: {signal.price:.2f}")
    
    lines.append(
        f"  数据: 偏离={signal.deviation:+.1f}% RSI={signal.rsi:.0f} "
        f"量比={signal.vol_ratio:.1f} 振幅={signal.amplitude:.1f}%"
    )
    
    return "\n".join(lines)


if __name__ == "__main__":
    # 测试：用菜百股份
    test_positions = [
        {"ts_code": "605599.SH", "name": "菜百股份", "shares": 26600, "available": 24300, "cost": 23.06},
        {"ts_code": "603986.SH", "name": "兆易创新", "shares": 3200, "available": 3200, "cost": 278.692},
        {"ts_code": "002020.SZ", "name": "京新药业", "shares": 11500, "available": 6300, "cost": 16.044},
    ]
    
    signals = scan_intraday_t_opportunities(test_positions)
    if signals:
        print(f"发现 {len(signals)} 个做T信号:\n")
        for s in signals:
            print(format_t_signal(s))
            print()
    else:
        print("当前无做T信号")
