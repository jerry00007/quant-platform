"""
QuantWeave — 雪球实时行情数据源

通过雪球公开接口获取A股实时行情数据。
无需Token，免费使用，适合盘中实时场景。

使用场景：
  - 盘前速递：获取大盘指数实时数据
  - 盘中卖出扫描：用实时价格检测止损/止盈
  - 盘后复盘：补充当日收盘数据
  - 个股分析：获取最新价格和技术指标

接口说明：
  - 实时行情: /v5/stock/realtime/quotec.json?symbol=SH605599
  - 批量行情: /v5/stock/realtime/quotec.json?symbol=SH605599,SZ000001,...（逗号分隔）
  - K线数据: /v6/stock/quote/kline.json?symbol=SH605599&begin=...&period=day

注意：
  - 需带 Referer: https://xueqiu.com/ 请求头
  - 高频调用可能有风控，建议间隔 > 1秒
  - ts_code 格式转换: 605599.SH → SH605599
"""
import re
import time
import json
import requests
from typing import Dict, List, Optional
from loguru import logger


# ============================================================
# 工具函数
# ============================================================

def ts_to_xq(ts_code: str) -> str:
    """Tushare代码转雪球代码: 605599.SH → SH605599"""
    parts = ts_code.split(".")
    if len(parts) == 2:
        return parts[1] + parts[0]
    return ts_code


def xq_to_ts(xq_code: str) -> str:
    """雪球代码转Tushare代码: SH605599 → 605599.SH"""
    m = re.match(r"^([A-Z]{2})(\d+)$", xq_code)
    if m:
        return m.group(2) + "." + m.group(1)
    return xq_code


# ============================================================
# 雪球实时行情
# ============================================================

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://xueqiu.com/",
    "Origin": "https://xueqiu.com",
}

# 简易缓存，避免短时间内重复请求
_cache: Dict[str, dict] = {}
_cache_ts: Dict[str, float] = {}
_CACHE_TTL = 30  # 30秒缓存

# 频率控制：全局请求间隔
_last_request_ts: float = 0
_MIN_INTERVAL = 0.5  # 两次请求间最小间隔（秒）


def _rate_limit():
    """请求频率控制，确保两次请求间隔 >= _MIN_INTERVAL"""
    global _last_request_ts
    now = time.time()
    elapsed = now - _last_request_ts
    if elapsed < _MIN_INTERVAL:
        time.sleep(_MIN_INTERVAL - elapsed)
    _last_request_ts = time.time()


def get_realtime_quote(ts_code: str, use_cache: bool = True) -> Optional[Dict]:
    """获取单只股票实时行情

    Args:
        ts_code: Tushare格式代码，如 605599.SH
        use_cache: 是否使用缓存（默认True）

    Returns:
        dict or None:
        {
            "ts_code": "605599.SH",
            "name": "",           # 雪球不返回名称
            "current": 22.52,
            "percent": -1.66,     # 涨跌幅%
            "chg": -0.38,         # 涨跌额
            "open": 22.89,
            "last_close": 22.90,
            "high": 23.20,
            "low": 22.29,
            "volume": 3042200,    # 成交量（股）
            "amount": 6.89e7,     # 成交额
            "turnover_rate": 0.39,# 换手率%
            "amplitude": 3.97,    # 振幅%
            "avg_price": 22.664,  # 均价
            "market_capital": 1.75e10,  # 总市值
            "is_trade": True,     # 是否交易中
            "current_year_percent": 37.57,  # 年涨幅%
            "timestamp": 1776308441600,     # 行情时间戳ms
        }
    """
    xq_code = ts_to_xq(ts_code)

    # 缓存检查
    now = time.time()
    if use_cache and xq_code in _cache:
        if now - _cache_ts.get(xq_code, 0) < _CACHE_TTL:
            return _cache[xq_code]

    try:
        _rate_limit()
        url = f"https://stock.xueqiu.com/v5/stock/realtime/quotec.json?symbol={xq_code}"
        resp = requests.get(url, headers=_HEADERS, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        if data.get("error_code") != 0:
            logger.warning(f"雪球接口返回错误: {data}")
            return None

        items = data.get("data", [])
        if not items:
            return None

        item = items[0]
        item["ts_code"] = ts_code
        item["xq_code"] = xq_code

        # 更新缓存
        _cache[xq_code] = item
        _cache_ts[xq_code] = now

        return item

    except requests.RequestException as e:
        logger.warning(f"雪球行情请求失败 {ts_code}: {e}")
        return None


def batch_realtime_quotes(ts_codes: List[str]) -> Dict[str, Dict]:
    """批量获取实时行情

    雪球支持逗号分隔的批量查询，一次最多约50只。

    Args:
        ts_codes: Tushare格式代码列表

    Returns:
        dict: {ts_code: quote_data}
    """
    result = {}
    # 雪球批量接口，每批最多50只
    batch_size = 50

    for i in range(0, len(ts_codes), batch_size):
        batch = ts_codes[i : i + batch_size]
        xq_codes = [ts_to_xq(c) for c in batch]
        symbols = ",".join(xq_codes)

        try:
            _rate_limit()
            url = f"https://stock.xueqiu.com/v5/stock/realtime/quotec.json?symbol={symbols}"
            resp = requests.get(url, headers=_HEADERS, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            if data.get("error_code") != 0:
                logger.warning(f"雪球批量接口错误: {data}")
                continue

            for item in data.get("data", []):
                tc = xq_to_ts(item.get("symbol", ""))
                item["ts_code"] = tc
                result[tc] = item

        except requests.RequestException as e:
            logger.warning(f"雪球批量行情失败: {e}")

        # 批次间间隔，避免风控
        if i + batch_size < len(ts_codes):
            time.sleep(0.5)

    return result


# ============================================================
# 指数实时行情
# ============================================================

INDEX_MAP = {
    "000001.SH": "上证指数",
    "399001.SZ": "深证成指",
    "399006.SZ": "创业板指",
    "000300.SH": "沪深300",
    "000016.SH": "上证50",
    "399005.SZ": "中小板指",
}


def get_index_quotes() -> Dict[str, Dict]:
    """获取主要指数实时行情"""
    return batch_realtime_quotes(list(INDEX_MAP.keys()))


# ============================================================
# 格式化工具
# ============================================================

def format_quote_brief(ts_code: str, name: str = "") -> str:
    """获取格式化的实时行情简要文本

    Returns:
        "🔴 菜百股份(605599.SH) 22.52 (-1.66%)"
    """
    q = get_realtime_quote(ts_code)
    if not q:
        return f"⚠️ {name or ts_code} 暂无数据"

    chg = q.get("percent", 0)
    arrow = "🔴" if chg > 0 else "🟢" if chg < 0 else "⚪"
    display_name = name or ts_code
    return f"{arrow} {display_name}({ts_code}) {q['current']:.2f} ({chg:+.2f}%)"


def format_quote_detail(ts_code: str, name: str = "", cost_price: float = 0) -> str:
    """获取格式化的详细行情文本"""
    q = get_realtime_quote(ts_code)
    if not q:
        return f"⚠️ {name or ts_code} 暂无数据"

    lines = []
    display_name = name or ts_code
    chg = q.get("percent", 0)
    arrow = "🔴" if chg > 0 else "🟢" if chg < 0 else "⚪"

    lines.append(f"{arrow} {display_name}({ts_code})")
    lines.append(f"  现价: {q['current']:.2f} ({chg:+.2f}%)")
    lines.append(f"  开: {q.get('open', 0):.2f} 高: {q.get('high', 0):.2f} 低: {q.get('low', 0):.2f}")
    lines.append(f"  成交量: {q.get('volume', 0)/10000:.1f}万手")
    lines.append(f"  成交额: {q.get('amount', 0)/1e8:.2f}亿")
    lines.append(f"  换手率: {q.get('turnover_rate', 0):.2f}%")

    if cost_price > 0:
        pnl = (q["current"] - cost_price) / cost_price * 100
        pnl_tag = "🟢赚" if pnl > 0 else "🔴亏"
        lines.append(f"  成本: {cost_price:.2f} | {pnl_tag}{pnl:+.2f}%")

    return "\n".join(lines)


# ============================================================
# 测试
# ============================================================

if __name__ == "__main__":
    print("=== 单只股票 ===")
    q = get_realtime_quote("605599.SH")
    if q:
        print(json.dumps(q, indent=2, ensure_ascii=False))

    print("\n=== 批量行情 ===")
    qs = batch_realtime_quotes(["605599.SH", "000001.SZ", "300750.SZ"])
    for code, item in qs.items():
        chg = item.get("percent", 0)
        arrow = "🔴" if chg > 0 else "🟢"
        print(f"  {arrow} {code}: {item['current']:.2f} ({chg:+.2f}%)")

    print("\n=== 指数行情 ===")
    idxs = get_index_quotes()
    for code, item in idxs.items():
        chg = item.get("percent", 0)
        arrow = "🔴" if chg > 0 else "🟢"
        name = INDEX_MAP.get(code, code)
        print(f"  {arrow} {name}: {item['current']:.2f} ({chg:+.2f}%)")

    print("\n=== 格式化 ===")
    print(format_quote_brief("605599.SH", "菜百股份"))
    print(format_quote_detail("605599.SH", "菜百股份", cost_price=23.11))
