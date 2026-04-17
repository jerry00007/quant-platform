"""
日内分时数据源模块
- 东方财富分时线（1分钟粒度，含均价）
- 新浪5分钟K线（开高低收量）
- 雪球实时快照（配合监控）

数据源优先级：东财分时 > 新浪5分钟K线
"""

import json
import time
import logging
import urllib.request
from typing import Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class MinuteBar:
    """1分钟K线"""
    time: str          # "09:30"
    open: float
    close: float
    high: float
    low: float
    volume: int
    amount: float = 0  # 成交额
    avg_price: float = 0  # 分时均价


@dataclass
class IntradaySnapshot:
    """盘中快照"""
    ts_code: str
    current: float
    open: float
    high: float
    low: float
    pre_close: float
    volume: int
    amount: float
    turnover_rate: float = 0
    amplitude: float = 0
    avg_price: float = 0  # 分时均价
    timestamp: int = 0


def _ts_to_eastmoney_code(ts_code: str) -> str:
    """ts_code -> 东财secid (如 605599.SH -> 1.605599)"""
    code, market = ts_code.split(".")
    prefix = "1" if market == "SH" else "0"
    return f"{prefix}.{code}"


def _ts_to_sina_code(ts_code: str) -> str:
    """ts_code -> 新浪代码 (如 605599.SH -> sh605599)"""
    code, market = ts_code.split(".")
    prefix = "sh" if market == "SH" else "sz"
    return f"{prefix}{code}"


def _fetch_json(url: str, headers: dict = None, timeout: int = 10) -> dict:
    """通用JSON请求"""
    default_headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Referer": "https://quote.eastmoney.com/",
    }
    if headers:
        default_headers.update(headers)
    req = urllib.request.Request(url, headers=default_headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw)


def get_minute_bars(ts_code: str, days: int = 1) -> list[MinuteBar]:
    """
    获取1分钟分时数据（东方财富）
    
    Args:
        ts_code: 股票代码 (605599.SH)
        days: 天数 (1=今天, 5=最近5天)
    
    Returns:
        list[MinuteBar]: 分钟K线列表
    """
    secid = _ts_to_eastmoney_code(ts_code)
    url = (
        f"https://push2his.eastmoney.com/api/qt/stock/trends2/get"
        f"?secid={secid}"
        f"&fields1=f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13"
        f"&fields2=f51,f52,f53,f54,f55,f56,f57,f58"
        f"&iscr=0&ndays={days}"
    )
    try:
        data = _fetch_json(url)
        if not data.get("data") or not data["data"].get("trends"):
            return []
        
        pre_close = data["data"].get("preClose", 0)
        bars = []
        for t in data["data"]["trends"]:
            parts = t.split(",")
            # parts: datetime, open, close, high, low, volume, amount, avg_price
            time_str = parts[0].split()[1] if " " in parts[0] else parts[0]
            bars.append(MinuteBar(
                time=time_str,
                open=float(parts[1]),
                close=float(parts[2]),
                high=float(parts[3]),
                low=float(parts[4]),
                volume=int(parts[5]),
                amount=float(parts[6]),
                avg_price=float(parts[7]),
            ))
        return bars
    except Exception as e:
        logger.error(f"获取分时数据失败 {ts_code}: {e}")
        return []


def get_5min_klines(ts_code: str, count: int = 48) -> list[dict]:
    """
    获取5分钟K线（新浪）
    
    Args:
        ts_code: 股票代码
        count: K线条数
    
    Returns:
        list[dict]: [{day, open, high, low, close, volume}, ...]
    """
    sina_code = _ts_to_sina_code(ts_code)
    url = (
        f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php"
        f"/CN_MarketData.getKLineData?symbol={sina_code}"
        f"&scale=5&ma=no&datalen={count}"
    )
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://finance.sina.com.cn/",
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8")
            data = json.loads(raw)
            return [{
                "time": d["day"],
                "open": float(d["open"]),
                "high": float(d["high"]),
                "low": float(d["low"]),
                "close": float(d["close"]),
                "volume": int(d["volume"]),
            } for d in data]
    except Exception as e:
        logger.error(f"获取5分钟K线失败 {ts_code}: {e}")
        return []


def get_realtime_snapshot(ts_code: str) -> Optional[IntradaySnapshot]:
    """获取实时快照（雪球）"""
    code, market = ts_code.split(".")
    prefix = market  # SH/SZ
    xq_code = f"{prefix}{code}"
    url = f"https://stock.xueqiu.com/v5/stock/realtime/quotec.json?symbol={xq_code}"
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Referer": "https://xueqiu.com/",
            "Accept-Encoding": "gzip",
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read()
            try:
                import gzip
                raw = gzip.decompress(raw)
            except Exception:
                pass
            data = json.loads(raw.decode())
            item = data["data"][0]
            return IntradaySnapshot(
                ts_code=ts_code,
                current=item.get("current", 0),
                open=item.get("open", 0),
                high=item.get("high", 0),
                low=item.get("low", 0),
                pre_close=item.get("last_close", 0),
                volume=item.get("volume", 0),
                amount=item.get("amount", 0),
                turnover_rate=item.get("turnover_rate", 0),
                amplitude=item.get("amplitude", 0),
                avg_price=item.get("avg_price", 0),
                timestamp=item.get("timestamp", 0),
            )
    except Exception as e:
        logger.error(f"获取实时快照失败 {ts_code}: {e}")
        return None


def get_intraday_summary(ts_code: str) -> dict:
    """
    获取日内综合数据（用于策略计算）
    合并分时数据 + 实时快照
    """
    bars = get_minute_bars(ts_code)
    snap = get_realtime_snapshot(ts_code)
    
    if not bars and not snap:
        return {"error": f"无法获取 {ts_code} 数据"}
    
    summary = {
        "ts_code": ts_code,
        "bars": bars,
        "snapshot": snap,
    }
    
    if bars:
        # 计算日内技术指标
        closes = [b.close for b in bars]
        volumes = [b.volume for b in bars]
        highs = [b.high for b in bars]
        lows = [b.low for b in bars]
        
        current = closes[-1] if closes else 0
        pre_close = snap.pre_close if snap else bars[0].open
        avg_price = bars[-1].avg_price if bars else 0
        
        # 偏离均价
        deviation = (current / avg_price - 1) * 100 if avg_price > 0 else 0
        
        # 日内最高最低
        day_high = max(highs) if highs else 0
        day_low = min(lows) if lows else 0
        amplitude = (day_high / day_low - 1) * 100 if day_low > 0 else 0
        
        # 最近30分钟均价
        recent_closes = closes[-30:] if len(closes) >= 30 else closes
        ma30min = sum(recent_closes) / len(recent_closes) if recent_closes else 0
        
        # 量比（最近5分钟 / 前25分钟均值）
        if len(volumes) > 5:
            recent_vol = sum(volumes[-5:])
            avg_vol = sum(volumes[:-5]) / max(len(volumes) - 5, 1)
            vol_ratio = recent_vol / max(avg_vol, 1) / 5 * len(volumes[:-5])
        else:
            vol_ratio = 1.0
        
        # RSI(14) on minute bars
        if len(closes) > 14:
            deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
            gains = [max(d, 0) for d in deltas]
            losses = [-min(d, 0) for d in deltas]
            avg_gain = sum(gains[-14:]) / 14
            avg_loss = sum(losses[-14:]) / 14
            if avg_loss == 0:
                rsi = 100
            else:
                rs = avg_gain / avg_loss
                rsi = 100 - 100 / (1 + rs)
        else:
            rsi = 50
        
        # 涨跌幅
        change_pct = (current / pre_close - 1) * 100 if pre_close > 0 else 0
        
        summary.update({
            "current": current,
            "pre_close": pre_close,
            "avg_price": avg_price,
            "deviation": deviation,       # 偏离均价百分比
            "day_high": day_high,
            "day_low": day_low,
            "amplitude": amplitude,
            "ma30min": ma30min,
            "vol_ratio": vol_ratio,        # 量比
            "rsi": rsi,                    # 分钟级RSI
            "change_pct": change_pct,
            "bar_count": len(bars),
        })
    
    return summary


if __name__ == "__main__":
    # 测试
    import sys
    code = sys.argv[1] if len(sys.argv) > 1 else "605599.SH"
    
    print(f"=== 日内数据测试: {code} ===\n")
    
    # 分时数据
    bars = get_minute_bars(code)
    print(f"分时数据: {len(bars)}条")
    if bars:
        last = bars[-1]
        print(f"  最新: {last.time} 收={last.close} 均={last.avg_price}")
    
    # 5分钟K线
    klines = get_5min_klines(code)
    print(f"\n5分钟K线: {len(klines)}条")
    if klines:
        print(f"  最新: {klines[-1]['time']} 收={klines[-1]['close']}")
    
    # 综合数据
    summary = get_intraday_summary(code)
    print(f"\n=== 综合数据 ===")
    for k, v in summary.items():
        if k not in ("bars", "snapshot"):
            print(f"  {k}: {v}")
