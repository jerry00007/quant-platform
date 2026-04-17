"""
QuantWeave — 市场环境评估模块

在选股报告中提供大盘趋势、市场宽度、板块动量等环境信息。
仅作为参考信息展示，不用于过滤选股信号（回测已验证：过滤降低收益）。

数据源：
  - 雪球实时行情：大盘指数、行业ETF
  - 本地 SQLite：历史日线（计算均线趋势）
"""
import sqlite3
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from loguru import logger

try:
    from app.services.data.xueqiu_data import (
        get_index_quotes, batch_realtime_quotes, ts_to_xq, INDEX_MAP
    )
    _HAS_XUEQIU = True
except ImportError:
    _HAS_XUEQIU = False


# ============================================================
# 行业ETF映射（用于板块动量）
# ============================================================

SECTOR_ETF_MAP = {
    "SH512000": ("券商ETF", "证券"),
    "SH512010": ("医药ETF", "医药生物"),
    "SH512660": ("军工ETF", "国防军工"),
    "SH512690": ("白酒ETF", "食品饮料"),
    "SZ159995": ("芯片ETF", "电子"),
    "SZ159766": ("旅游ETF", "休闲服务"),
    "SH512170": ("医疗ETF", "医疗器械"),
    "SZ159825": ("农业ETF", "农林牧渔"),
    "SH512480": ("半导体ETF", "半导体"),
    "SZ159790": ("碳中和ETF", "环保"),
    "SH515030": ("新能源车ETF", "新能源汽车"),
    "SH515790": ("光伏ETF", "光伏"),
    "SZ159992": ("创新药ETF", "创新药"),
    "SH512100": ("中证1000ETF", "中证1000"),
    "SH510300": ("沪深300ETF", "沪深300"),
    "SZ159919": ("沪深300ETF", "沪深300"),
}


# ============================================================
# 大盘趋势评估
# ============================================================

def evaluate_index_trend(db_path: str = "quantweave.db") -> Dict:
    """评估主要指数趋势（基于本地日线数据）

    Returns:
        {
            "上证指数": {
                "trend": "多头" / "震荡" / "空头",
                "ma_status": "站上MA20" / "跌破MA20",
                "recent_change_5d": +1.5,
                "recent_change_20d": +3.2,
                "current": 3200.50,
            },
            ...
        }
    """
    result = {}

    index_codes = {
        "000001.SH": "上证指数",
        "399001.SZ": "深证成指",
        "399006.SZ": "创业板指",
        "000300.SH": "沪深300",
    }

    try:
        conn = sqlite3.connect(db_path)
    except Exception:
        return result

    try:
        for ts_code, name in index_codes.items():
            df = pd.read_sql(
                "SELECT trade_date, close FROM stock_daily "
                "WHERE ts_code=? ORDER BY trade_date DESC LIMIT 60",
                conn, params=(ts_code,)
            )
            if df.empty or len(df) < 20:
                continue

            df = df.sort_values("trade_date").reset_index(drop=True)
            closes = df["close"].values.astype(float)
            current = closes[-1]

            ma5 = np.mean(closes[-5:])
            ma10 = np.mean(closes[-10:])
            ma20 = np.mean(closes[-20:])

            # 趋势判定
            if current > ma5 > ma10 > ma20:
                trend = "多头排列"
            elif current < ma5 < ma10 < ma20:
                trend = "空头排列"
            elif current > ma20:
                trend = "偏多震荡"
            else:
                trend = "偏空震荡"

            ma_status = "站上MA20" if current > ma20 else "跌破MA20"

            # 近期涨跌幅
            chg_5d = (current / closes[-6] - 1) * 100 if len(closes) >= 6 else 0
            chg_20d = (current / closes[-21] - 1) * 100 if len(closes) >= 21 else 0

            result[name] = {
                "trend": trend,
                "ma_status": ma_status,
                "recent_change_5d": round(chg_5d, 2),
                "recent_change_20d": round(chg_20d, 2),
                "current": round(current, 2),
            }
    finally:
        conn.close()

    return result


# ============================================================
# 市场宽度评估
# ============================================================

def evaluate_market_breadth(db_path: str = "quantweave.db") -> Dict:
    """评估市场宽度（上涨家数/下跌家数/涨停/跌停）

    Returns:
        {
            "total_stocks": 5000,
            "up_count": 3000,
            "down_count": 1800,
            "flat_count": 200,
            "limit_up": 50,
            "limit_down": 10,
            "up_ratio": 0.60,      # 上涨占比
            "sentiment": "偏多",    # 偏多/偏空/中性
        }
    """
    try:
        conn = sqlite3.connect(db_path)
    except Exception:
        return {}

    try:
        # 获取最新交易日
        latest = pd.read_sql(
            "SELECT MAX(trade_date) as d FROM stock_daily", conn
        )
        if latest.empty:
            return {}
        latest_date = latest["d"].iloc[0]

        # 获取当日所有股票行情
        df = pd.read_sql(
            "SELECT ts_code, close, pre_close, change_pct FROM stock_daily "
            "WHERE trade_date=? AND ts_code NOT LIKE '%.BJ'",
            conn, params=(latest_date,)
        )

        if df.empty:
            return {}

        # 过滤北交所
        df = df[~df["ts_code"].str.startswith(("8", "4"))]

        # 计算涨跌
        pct_chg = df["change_pct"].astype(float)
        up = (pct_chg > 0).sum()
        down = (pct_chg < 0).sum()
        flat = (pct_chg == 0).sum()
        limit_up = (pct_chg >= 9.8).sum()
        limit_down = (pct_chg <= -9.8).sum()
        total = len(df)

        up_ratio = up / total if total > 0 else 0

        if up_ratio > 0.6:
            sentiment = "偏多"
        elif up_ratio < 0.4:
            sentiment = "偏空"
        else:
            sentiment = "中性"

        return {
            "date": latest_date,
            "total_stocks": total,
            "up_count": int(up),
            "down_count": int(down),
            "flat_count": int(flat),
            "limit_up": int(limit_up),
            "limit_down": int(limit_down),
            "up_ratio": round(up_ratio, 3),
            "sentiment": sentiment,
        }
    except Exception as e:
        logger.warning(f"市场宽度计算失败: {e}")
        return {}
    finally:
        conn.close()


# ============================================================
# 板块动量评估
# ============================================================

def evaluate_sector_momentum(db_path: str = "quantweave.db") -> List[Dict]:
    """评估行业板块动量（基于当日涨跌幅排名）

    Returns:
        [
            {"sector": "电子", "avg_change": +2.5, "stock_count": 200},
            ...
        ]
    """
    try:
        conn = sqlite3.connect(db_path)
    except Exception:
        return []

    try:
        latest = pd.read_sql(
            "SELECT MAX(trade_date) as d FROM stock_daily", conn
        )
        if latest.empty:
            return []
        latest_date = latest["d"].iloc[0]

        df = pd.read_sql(
            "SELECT ts_code, change_pct, amount FROM stock_daily "
            "WHERE trade_date=? AND ts_code NOT LIKE '%.BJ'",
            conn, params=(latest_date,)
        )

        if df.empty:
            return []

        # 获取股票行业信息（从stock表）
        stocks = pd.read_sql(
            "SELECT ts_code, industry FROM stock", conn
        )

        if stocks.empty:
            return []

        merged = df.merge(stocks, on="ts_code", how="left")
        merged = merged[merged["industry"].notna() & (merged["industry"] != "")]
        merged["change_pct"] = merged["change_pct"].astype(float)

        sector_stats = merged.groupby("industry").agg(
            avg_change=("change_pct", "mean"),
            stock_count=("ts_code", "count"),
            total_amount=("amount", "sum"),
        ).reset_index()

        sector_stats = sector_stats.rename(columns={"industry": "sector"})
        sector_stats = sector_stats.sort_values("avg_change", ascending=False)
        sector_stats["avg_change"] = sector_stats["avg_change"].round(2)

        return sector_stats.head(15).to_dict("records")
    except Exception as e:
        logger.warning(f"板块动量计算失败: {e}")
        return []
    finally:
        conn.close()


# ============================================================
# 综合市场环境报告
# ============================================================

def generate_market_context_report(db_path: str = "quantweave.db") -> str:
    """生成市场环境综合报告（纯文本，可直接嵌入选股报告）

    Returns:
        格式化的文本报告
    """
    lines = []
    lines.append("=" * 50)
    lines.append("🌍 市场环境评估（仅供参考，不影响选股）")
    lines.append("=" * 50)

    # 1. 大盘趋势
    lines.append("")
    lines.append("📊 【大盘趋势】")
    index_trend = evaluate_index_trend(db_path)
    if index_trend:
        for name, info in index_trend.items():
            trend_emoji = "🔴" if "多" in info["trend"] else "🟢" if "空" in info["trend"] else "⚪"
            lines.append(
                f"  {trend_emoji} {name}: {info['current']:.2f} | "
                f"{info['trend']} | {info['ma_status']}"
            )
            lines.append(
                f"     5日: {info['recent_change_5d']:+.2f}% | "
                f"20日: {info['recent_change_20d']:+.2f}%"
            )
    else:
        lines.append("  ⚠️ 暂无数据")

    # 2. 市场宽度
    lines.append("")
    lines.append("📈 【市场宽度】")
    breadth = evaluate_market_breadth(db_path)
    if breadth:
        sent_emoji = "🔴" if breadth["sentiment"] == "偏多" else "🟢" if breadth["sentiment"] == "偏空" else "⚪"
        lines.append(
            f"  {sent_emoji} {breadth['sentiment']} | "
            f"上涨{breadth['up_count']} / 下跌{breadth['down_count']} / "
            f"涨停{breadth['limit_up']} / 跌停{breadth['limit_down']}"
        )
        lines.append(
            f"     上涨占比: {breadth['up_ratio']*100:.1f}% | "
            f"日期: {breadth['date']}"
        )
    else:
        lines.append("  ⚠️ 暂无数据")

    # 3. 板块动量
    lines.append("")
    lines.append("🔥 【板块动量 TOP10】")
    sectors = evaluate_sector_momentum(db_path)
    if sectors:
        for i, s in enumerate(sectors[:10]):
            chg = s["avg_change"]
            emoji = "🔴" if chg > 0 else "🟢"
            lines.append(
                f"  {emoji} {i+1}. {s['sector']}: "
                f"均涨{chg:+.2f}% ({s['stock_count']}只)"
            )
    else:
        lines.append("  ⚠️ 暂无数据")

    # 4. 实时指数（雪球）
    if _HAS_XUEQIU:
        lines.append("")
        lines.append("📡 【实时指数】")
        try:
            idx_quotes = get_index_quotes()
            for code, q in idx_quotes.items():
                name = INDEX_MAP.get(code, code)
                chg = q.get("percent", 0)
                emoji = "🔴" if chg > 0 else "🟢" if chg < 0 else "⚪"
                lines.append(
                    f"  {emoji} {name}: {q['current']:.2f} ({chg:+.2f}%)"
                )
        except Exception as e:
            lines.append(f"  ⚠️ 雪球接口暂不可用: {e}")

    lines.append("")
    lines.append("⚠️ 以上信息仅供参考，不作为选股过滤条件")
    lines.append("=" * 50)

    return "\n".join(lines)


# ============================================================
# 测试
# ============================================================

if __name__ == "__main__":
    import os

    # 尝试找到数据库
    db_path = "quantweave.db"
    if not os.path.exists(db_path):
        db_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "..", "quantweave.db"
        )

    print("=== 市场环境评估 ===")
    print(generate_market_context_report(db_path))
