"""
QuantWeave — 全流程交易助手

每天自动执行：
1. 盘前速递（隔夜新闻+大盘预判+热点板块）
2. 全市场5策略选股
3. 选股结果自动入跟踪池 + 生成操作指南
4. 跟踪池卖出信号检测 + 提醒
5. 生成交易日报

使用方式:
    # 完整流程
    /opt/anaconda3/envs/quant-platform/bin/python trading_workflow.py

    # 只跑选股+入池
    /opt/anaconda3/envs/quant-platform/bin/python trading_workflow.py --scan-only

    # 只检测卖出信号
    /opt/anaconda3/envs/quant-platform/bin/python trading_workflow.py --sell-check

    # 只生成盘前速递
    /opt/anaconda3/envs/quant-platform/bin/python trading_workflow.py --morning
"""
import sys
import os
import json
import argparse
import sqlite3
from datetime import datetime, timedelta
from collections import Counter

# 添加路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "app"))
sys.path.insert(0, os.path.expanduser("~/.workbuddy/skills/quant-daily-picks/scripts"))

import pandas as pd
from loguru import logger

from app.services.tracking.tracking_pool_service import TrackingPoolService

# 雪球实时行情（可选）
try:
    from app.services.data.xueqiu_data import (
        get_realtime_quote, batch_realtime_quotes, get_index_quotes, format_quote_brief, INDEX_MAP
    )
    _HAS_XUEQIU = True
except ImportError:
    _HAS_XUEQIU = False

# 股票名称映射（常见蓝筹+热门股，不够的从数据库补）
STOCK_NAMES = {
    "600519.SH": "贵州茅台", "000858.SZ": "五粮液", "601318.SH": "中国平安",
    "600036.SH": "招商银行", "000001.SZ": "平安银行", "000333.SZ": "美的集团",
    "601398.SH": "工商银行", "000651.SZ": "格力电器", "600900.SH": "长江电力",
    "601012.SH": "隆基绿能", "300750.SZ": "宁德时代", "002594.SZ": "比亚迪",
    "600809.SH": "山西汾酒", "000568.SZ": "泸州老窖", "601899.SH": "紫金矿业",
    "600276.SH": "恒瑞医药", "002475.SZ": "立讯精密", "300059.SZ": "东方财富",
    "603259.SH": "药明康德", "688981.SH": "中芯国际",
}


def get_stock_name(ts_code: str, conn) -> str:
    """获取股票名称"""
    if ts_code in STOCK_NAMES:
        return STOCK_NAMES[ts_code]
    row = conn.execute(
        "SELECT name FROM stocks WHERE ts_code=?", (ts_code,)
    ).fetchone()
    if row and row[0]:
        return row[0]
    return ts_code


# ============================================================
# 1. 盘前速递
# ============================================================

def generate_morning_brief(db_path: str = "quantweave.db") -> str:
    """生成盘前速递"""
    logger.info("🌤️ 生成盘前速递...")
    conn = sqlite3.connect(db_path)

    lines = [
        "=" * 45,
        f"☀️ QuantWeave 盘前速递 | {datetime.now().strftime('%Y-%m-%d %A')}",
        "=" * 45,
        "",
    ]

    # 0) 我的持仓（最重要，放最前面）
    try:
        pos_rows = conn.execute(
            "SELECT ts_code, name, volume, avg_cost, market_value, strategy_id "
            "FROM positions WHERE is_active = 1"
        ).fetchall()
        if pos_rows:
            lines.append("💼 我的持仓")
            total_mv = 0
            total_cost = 0
            pos_quotes = {}
            # 获取实时行情
            if _HAS_XUEQIU:
                try:
                    codes = [r[0] for r in pos_rows]
                    pos_quotes = batch_realtime_quotes(codes)
                except Exception:
                    pass
            for ts_code, name, vol, avg_cost, mv, strategy in pos_rows:
                if not ts_code or not vol:
                    continue
                cost_val = avg_cost * vol if avg_cost and vol else 0
                q = pos_quotes.get(ts_code, {})
                cur_price = q.get("current", 0)
                chg = q.get("percent", 0)
                if cur_price > 0:
                    cur_mv = cur_price * vol
                    pnl_pct = (cur_price - avg_cost) / avg_cost * 100 if avg_cost else 0
                    arrow = "🔴" if chg > 0 else "🟢" if chg < 0 else "⚪"
                    pnl_arrow = "🔴" if pnl_pct > 0 else "🟢"
                    lines.append(
                        f"  {arrow} {name}({ts_code}) {cur_price:.2f} ({chg:+.2f}%) "
                        f"| 成本{avg_cost:.2f} {pnl_arrow}持仓{pnl_pct:+.2f}%"
                    )
                    total_mv += cur_mv
                    total_cost += cost_val
                else:
                    # 没有实时行情，用数据库市值
                    lines.append(f"  ⚪ {name}({ts_code}) | 成本{avg_cost:.2f} | 市值{mv:.0f}")
                    total_mv += mv or 0
                    total_cost += cost_val
            if total_cost > 0:
                total_pnl = total_mv - total_cost
                total_pnl_pct = total_pnl / total_cost * 100
                pnl_arrow = "🔴" if total_pnl > 0 else "🟢"
                lines.append(f"  {'─'*35}")
                lines.append(f"  💰 总市值{total_mv/10000:.2f}万 {pnl_arrow}总盈亏{total_pnl/10000:+.2f}万({total_pnl_pct:+.2f}%)")
            lines.append("")
    except Exception as e:
        logger.debug(f"持仓信息获取失败: {e}")

    # 1) 大盘概况（优先用雪球实时数据）
    indices = {
        "000001.SH": "上证指数", "399001.SZ": "深证成指",
        "399006.SZ": "创业板指", "000300.SH": "沪深300",
    }
    realtime_ok = False
    if _HAS_XUEQIU:
        try:
            idx_quotes = get_index_quotes()
            if idx_quotes:
                lines.append("📊 大盘实时行情")
                realtime_ok = True
                for code, name in indices.items():
                    if code in idx_quotes:
                        q = idx_quotes[code]
                        chg = q.get("percent", 0)
                        arrow = "🔴" if chg > 0 else "🟢" if chg < 0 else "⚪"
                        lines.append(f"  {arrow} {name}: {q['current']:.2f} ({chg:+.2f}%)")
                    else:
                        # fallback到数据库
                        row = conn.execute(
                            "SELECT close, pre_close, change_pct FROM stock_daily "
                            "WHERE ts_code=? ORDER BY trade_date DESC LIMIT 1",
                            (code,),
                        ).fetchone()
                        if row and row[0]:
                            close, pre_close, chg = row
                            chg = chg if chg else ((close - pre_close) / pre_close * 100) if pre_close else 0
                            arrow = "🔴" if chg > 0 else "🟢" if chg < 0 else "⚪"
                            lines.append(f"  {arrow} {name}: {close:.2f} ({chg:+.2f}%) [收盘]")
                lines.append("")
        except Exception:
            pass

    if not realtime_ok:
        lines.append("📊 大盘概况（最近交易日）")
        for code, name in indices.items():
            row = conn.execute(
                "SELECT close, pre_close, change_pct FROM stock_daily "
                "WHERE ts_code=? ORDER BY trade_date DESC LIMIT 1",
                (code,),
            ).fetchone()
            if row and row[0]:
                close, pre_close, chg = row
                chg = chg if chg else ((close - pre_close) / pre_close * 100) if pre_close else 0
                arrow = "🔴" if chg > 0 else "🟢" if chg < 0 else "⚪"
                lines.append(f"  {arrow} {name}: {close:.2f} ({chg:+.2f}%)")
        lines.append("")

    # 1.1) 隔夜外盘（美股三大指数 + 金龙指数）
    try:
        lines.append("🌍 隔夜外盘")
        us_data_fetched = False

        # 方法1: Tushare 获取美股指数
        try:
            import tushare as ts
            from dotenv import load_dotenv
            load_dotenv()
            token = os.getenv("TUSHARE_TOKEN", "")
            if token:
                pro = ts.pro_api(token)
                us_indices = {
                    ".DJI": "道琼斯",
                    ".IXIC": "纳斯达克",
                    ".INX": "标普500",
                    ".HXC": "🇨🇳金龙指数",
                }
                for ts_code, name in us_indices.items():
                    try:
                        df = pro.index_daily(ts_code=ts_code, start_date=latest_date, end_date=latest_date)
                        if df is not None and len(df) > 0:
                            row = df.iloc[0]
                            close = row.get("close", 0)
                            pct = row.get("pct_chg", 0)
                            arrow = "🔴" if pct > 0 else "🟢" if pct < 0 else "⚪"
                            lines.append(f"  {arrow} {name}: {close:,.2f} ({pct:+.2f}%)")
                            us_data_fetched = True
                        else:
                            df = pro.index_daily(ts_code=ts_code).head(1)
                            if df is not None and len(df) > 0:
                                row = df.iloc[0]
                                close = row.get("close", 0)
                                pct = row.get("pct_chg", 0)
                                arrow = "🔴" if pct > 0 else "🟢" if pct < 0 else "⚪"
                                lines.append(f"  {arrow} {name}: {close:,.2f} ({pct:+.2f}%) [{row.get('trade_date','')}]")
                                us_data_fetched = True
                    except Exception:
                        pass
        except Exception:
            pass

        # 方法2: AKShare 兜底（新浪美股指数）
        if not us_data_fetched:
            try:
                import akshare as ak
                ak_us_map = {
                    ".DJI": "道琼斯",
                    ".IXIC": "纳斯达克",
                    ".INX": "标普500",
                    ".HXC": "🇨🇳金龙指数",
                }
                for symbol, name in ak_us_map.items():
                    try:
                        df = ak.index_us_stock_sina(symbol=symbol)
                        if df is not None and len(df) >= 2:
                            row_today = df.iloc[-1]
                            row_yesterday = df.iloc[-2]
                            close = float(row_today["close"])
                            pre_close = float(row_yesterday["close"])
                            pct = ((close - pre_close) / pre_close * 100) if pre_close else 0
                            arrow = "🔴" if pct > 0 else "🟢" if pct < 0 else "⚪"
                            date_str = str(row_today["date"])[:10]
                            lines.append(f"  {arrow} {name}: {close:,.2f} ({pct:+.2f}%)")
                            us_data_fetched = True
                    except Exception:
                        pass
            except ImportError:
                pass

        if not us_data_fetched:
            lines.append("  (美股数据获取失败)")
        lines.append("")
    except Exception as e:
        logger.debug(f"美股数据获取失败: {e}")

    # 1.2) 重大财经新闻（持仓相关板块优先）
    try:
        lines.append("📰 今日财经要闻")
        # 获取持仓相关行业
        portfolio_industries = set()
        try:
            pool_svc_temp = TrackingPoolService(db_path)
            pool = pool_svc_temp.get_tracking_pool("tracking")
            for t in pool[:20]:
                tc = t.get("ts_code", "")
                if tc:
                    ind_row = conn.execute(
                        "SELECT industry FROM stocks WHERE ts_code=?", (tc,)
                    ).fetchone()
                    if ind_row and ind_row[0]:
                        portfolio_industries.add(ind_row[0])
        except Exception:
            pass

        # 通过 AKShare 获取财经新闻（优先今天，回退昨天）
        try:
            import akshare as ak
            news_df = None
            for offset_days in range(3):  # 尝试最近3天
                d = datetime.now() - timedelta(days=offset_days)
                try:
                    news_df = ak.news_cctv(date=d.strftime("%Y%m%d"))
                    if news_df is not None and len(news_df) > 0:
                        break
                except Exception:
                    continue
            if news_df is not None and len(news_df) > 0:
                # 优先筛选持仓相关新闻
                finance_keywords = ["GDP", "经济", "消费", "投资", "出口", "进口", "制造业",
                                    "降息", "加息", "利率", "LPR", "降准", "通胀", "CPI", "PPI",
                                    "贸易", "关税", "制裁", "谈判", "协议", "政策", "改革",
                                    "股市", "债市", "期货", "原油", "黄金", "美元", "人民币",
                                    "IPO", "注册制", "退市", "回购", "增持", "减持"]
                industry_keywords = list(portfolio_industries) + ["存储芯片", "半导体", "芯片",
                                    "科技", "AI", "人工智能", "新能源", "光伏", "锂电", "军工"]
                all_keywords = finance_keywords + industry_keywords
                related_news = []
                other_news = []
                for _, row in news_df.head(15).iterrows():
                    title = str(row.get("title", ""))
                    content = str(row.get("content", ""))[:200]
                    is_industry = any(kw in title or kw in content for kw in industry_keywords)
                    is_finance = any(kw in title or kw in content for kw in finance_keywords)
                    if is_industry:
                        related_news.append(f"  ⭐ {title}")
                    elif is_finance:
                        related_news.append(f"  🔔 {title}")
                    else:
                        other_news.append(f"  • {title}")

                if related_news:
                    lines.append("  【持仓相关】")
                    lines.extend(related_news[:5])
                if other_news:
                    lines.append("  【其他要闻】")
                    lines.extend(other_news[:3])
            else:
                lines.append("  (今日暂无新闻数据)")
        except ImportError:
            lines.append("  (AKShare未安装，跳过新闻)")
        lines.append("")
    except Exception as e:
        logger.debug(f"新闻获取失败: {e}")

    # 1.5) 市场环境评估（趋势+宽度+板块动量综合评估）
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "app", "services", "analysis"))
        from market_context import evaluate_index_trend, evaluate_market_breadth

        index_trend = evaluate_index_trend(db_path)
        if index_trend:
            lines.append("📊 大盘趋势评估")
            for name, info in index_trend.items():
                trend_emoji = "🔴" if "多" in info["trend"] else "🟢" if "空" in info["trend"] else "⚪"
                lines.append(
                    f"  {trend_emoji} {name}: {info['trend']} | "
                    f"5日{info['recent_change_5d']:+.2f}% 20日{info['recent_change_20d']:+.2f}%"
                )
            lines.append("")
    except Exception:
        pass

    # 2) 涨跌家数
    latest_date = conn.execute(
        "SELECT MAX(trade_date) FROM stock_daily WHERE ts_code='000001.SZ'"
    ).fetchone()[0]
    if latest_date:
        up_count = conn.execute(
            "SELECT COUNT(*) FROM stock_daily WHERE trade_date=? AND change_pct > 0",
            (latest_date,),
        ).fetchone()[0]
        down_count = conn.execute(
            "SELECT COUNT(*) FROM stock_daily WHERE trade_date=? AND change_pct < 0",
            (latest_date,),
        ).fetchone()[0]
        flat_count = conn.execute(
            "SELECT COUNT(*) FROM stock_daily WHERE trade_date=? AND (change_pct IS NULL OR change_pct = 0)",
            (latest_date,),
        ).fetchone()[0]
        lines.append(f"📈 涨跌家数: 上涨{up_count} 下跌{down_count} 平盘{flat_count}")
        if up_count > down_count * 1.5:
            lines.append("  → 市场情绪偏多，短线可适当积极")
        elif down_count > up_count * 1.5:
            lines.append("  → 市场情绪偏弱，注意控制仓位")
        else:
            lines.append("  → 市场分化，精选个股为主")
        lines.append("")

    # 3) 板块涨跌（从行业分类中统计）
    try:
        sector_sql = """
            SELECT s.industry, COUNT(*) as cnt, AVG(d.change_pct) as avg_chg
            FROM stock_daily d
            JOIN stocks s ON d.ts_code = s.ts_code
            WHERE d.trade_date = ?
            AND s.industry IS NOT NULL AND s.industry != ''
            GROUP BY s.industry
            ORDER BY avg_chg DESC
            LIMIT 5
        """
        hot_sectors = conn.execute(sector_sql, (latest_date,)).fetchall()
        cold_sql = sector_sql.replace("DESC", "ASC").replace("LIMIT 5", "LIMIT 5")
        cold_sectors = conn.execute(cold_sql, (latest_date,)).fetchall()

        if hot_sectors:
            lines.append("🔥 热门行业TOP5:")
            for sector, cnt, avg_chg in hot_sectors:
                lines.append(f"  🔴 {sector}: +{avg_chg:.2f}% ({cnt}只)")
            lines.append("")

        if cold_sectors:
            lines.append("❄️ 冷门行业TOP5:")
            for sector, cnt, avg_chg in cold_sectors:
                lines.append(f"  🟢 {sector}: {avg_chg:.2f}% ({cnt}只)")
            lines.append("")
    except Exception:
        pass

    # 4) 成交额
    total_amount = conn.execute(
        "SELECT SUM(amount) FROM stock_daily WHERE trade_date=?",
        (latest_date,),
    ).fetchone()[0]
    if total_amount:
        total_yi = total_amount / 100000  # 千元转亿元
        lines.append(f"💰 两市成交额: {total_yi:.0f}亿")
        if total_yi < 8000:
            lines.append("  ⚠️ 成交额偏低，市场交投清淡")
        elif total_yi > 15000:
            lines.append("  ✅ 成交额充足，市场活跃")
        lines.append("")

    # 5) 跟踪池提醒（用实时价格）
    try:
        pool_svc = TrackingPoolService(db_path)
        tracking = pool_svc.get_tracking_pool("tracking")

        # 尝试获取跟踪池股票实时行情
        tracking_quotes = {}
        if _HAS_XUEQIU and tracking:
            try:
                codes = [t["ts_code"] for t in tracking]
                tracking_quotes = batch_realtime_quotes(codes)
            except Exception:
                pass

        # 卖出检测也用实时价格
        sell_signals = pool_svc.detect_sell_signals(latest_date, use_realtime=True)

        lines.append(f"📋 跟踪池: {len(tracking)}只在跟踪")
        if sell_signals:
            lines.append(f"  🔴 {len(sell_signals)}只需卖出！")
            for s in sell_signals[:5]:
                lines.append(f"     {s['stock_name']}({s['ts_code']}) {s['sell_reason']}")

        # 显示实时行情（top 10，去重）
        if tracking_quotes:
            lines.append("")
            lines.append("📡 跟踪池实时行情:")
            shown_codes = set()
            for t in tracking:
                tc = t["ts_code"]
                if tc in shown_codes:
                    continue
                shown_codes.add(tc)
                if tc in tracking_quotes:
                    q = tracking_quotes[tc]
                    chg = q.get("percent", 0)
                    arrow = "🔴" if chg > 0 else "🟢" if chg < 0 else "⚪"
                    pnl = t.get("current_pnl_pct", 0)
                    lines.append(f"  {arrow} {t['stock_name']}({tc}) {q['current']:.2f} ({chg:+.2f}%) 持仓{pnl:+.2f}%")
                if len(shown_codes) >= 10:
                    break
        lines.append("")
    except Exception as e:
        logger.warning(f"跟踪池提醒生成失败: {e}")

    # 6) 今日策略建议
    lines.append("🎯 今日操作建议:")
    if total_yi and total_yi < 6000:
        lines.append("  • 成交额偏低，低吸为主，不追高")
    elif sell_signals and len(sell_signals) >= 3:
        lines.append("  • 多只跟踪股需卖出，先处理持仓")
    elif tracking and len(tracking) < 5:
        lines.append("  • 跟踪池未满，关注今日选股信号")
        lines.append("  • 可从新出信号的票中选入跟踪池")
    else:
        lines.append("  • 跟踪池已满，以持仓管理为主")
        lines.append("  • 关注卖出信号，及时止盈止损")

    lines.append("")
    lines.append("⚠️ 以上为量化信号参考，不构成投资建议")

    conn.close()
    return "\n".join(lines)


# ============================================================
# 2. 选股 + 入池
# ============================================================

def _save_to_scan_results(conn, report: dict, latest_date: str, total_stocks: int):
    """将选股结果保存到 scan_results 表，供前端页面读取"""
    from datetime import datetime
    import json as _json

    try:
        # 确保表存在
        conn.execute("""
            CREATE TABLE IF NOT EXISTS scan_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scan_time TEXT NOT NULL,
                data_date TEXT NOT NULL,
                result_json TEXT NOT NULL,
                total_stocks INTEGER DEFAULT 0,
                total_signals INTEGER DEFAULT 0,
                resonance_count INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)

        # 构建 result JSON（兼容前端 quick_picks 格式）
        result = {
            "scan_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "data_date": latest_date,
            "total_stocks_scanned": total_stocks,
            "total_signals_found": sum(
                v.get("count", 0) for v in report.get("strategies", {}).values()
            ),
            "resonance": [
                {
                    "ts_code": r["code"],
                    "name": r["name"],
                    "hit_count": r["count"],
                    "strategies": [],
                    "price": 0,
                }
                for r in report.get("resonant", [])
            ],
            "strategies": {
                sk: {
                    "name": sv.get("name", sk),
                    "total_signals": sv.get("count", 0),
                    "top_picks": [
                        {
                            "ts_code": s.get("code", ""),
                            "name": s.get("name", ""),
                            "industry": "",
                            "signal": {
                                "price": s.get("close", 0),
                                "date": s.get("date", ""),
                                "reason": s.get("reason", ""),
                            },
                        }
                        for s in sv.get("stocks", [])
                    ],
                }
                for sk, sv in report.get("strategies", {}).items()
            },
            "industry_distribution": {},
        }

        total_signals = result["total_signals_found"]
        resonance_count = len(result["resonance"])

        conn.execute(
            """INSERT INTO scan_results (scan_time, data_date, result_json, total_stocks, total_signals, resonance_count)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                result["scan_time"],
                latest_date,
                _json.dumps(result, ensure_ascii=False, default=str),
                total_stocks,
                total_signals,
                resonance_count,
            ),
        )
        conn.commit()
        logger.info(f"📊 选股结果已保存到 scan_results 表 ({total_signals}只信号, {resonance_count}只共振)")
    except Exception as e:
        logger.warning(f"保存 scan_results 失败: {e}")


def run_scan_and_track(db_path: str = "quantweave.db") -> dict:
    """运行5策略选股并自动入池"""
    from daily_picks import STRATEGIES

    logger.info("📡 开始5策略全市场选股...")
    conn = sqlite3.connect(db_path)
    pool_svc = TrackingPoolService(db_path)

    latest_date = pd.read_sql(
        "SELECT MAX(trade_date) as d FROM stock_daily", conn
    )["d"][0]
    logger.info(f"数据最新日期: {latest_date}")

    stocks = pd.read_sql(
        "SELECT DISTINCT ts_code FROM stock_daily ORDER BY ts_code", conn
    )["ts_code"].tolist()
    logger.info(f"股票总数: {len(stocks)}")

    all_sigs = {}
    for sk, strat in STRATEGIES.items():
        sigs_found = []
        for idx, code in enumerate(stocks):
            df = pd.read_sql(
                "SELECT trade_date, open, high, low, close, vol FROM stock_daily "
                "WHERE ts_code=? ORDER BY trade_date",
                conn, params=(code,),
            )
            if len(df) < 60:
                continue
            try:
                signals = strat.generate_signals(df, code)
            except Exception:
                continue
            for sig in signals:
                if sig.signal_type == "buy" and str(sig.date) == latest_date:
                    name = get_stock_name(code, conn)
                    last_close = float(df["close"].iloc[-1])
                    sigs_found.append({
                        "code": code,
                        "name": name,
                        "date": str(sig.date),
                        "close": round(last_close, 2),
                        "reason": sig.reason,
                        "strategy": sk,
                    })
            if (idx + 1) % 1000 == 0:
                print(f"  [{strat.name}] {idx+1}/{len(stocks)}...", flush=True)

        all_sigs[sk] = sigs_found
        logger.info(f"{strat.name}: {len(sigs_found)}只出新信号")

    # 入池
    added = 0
    for sk, sigs in all_sigs.items():
        for sig in sigs:
            try:
                pool_id = pool_svc.add_to_pool(
                    ts_code=sig["code"],
                    strategy=sk,
                    signal_date=latest_date,
                    signal_price=sig["close"],
                    stock_name=sig["name"],
                    reason=sig["reason"],
                )
                if pool_id:
                    added += 1
            except Exception as e:
                logger.debug(f"入池跳过 {sig['code']}: {e}")

    # 生成选股报告
    report = {
        "date": latest_date,
        "strategies": {},
        "total_added_to_pool": added,
    }
    for sk, sigs in all_sigs.items():
        report["strategies"][sk] = {
            "name": STRATEGIES[sk].name,
            "count": len(sigs),
            "stocks": sigs[:20],
        }

    # 多策略共振（从 tracking_pool 直接查询，确保结果准确）
    code_counter = Counter()
    for sk, sigs in all_sigs.items():
        for s in sigs:
            code_counter[s["code"]] += 1
    # 内存计算的共振
    mem_resonant = {c for c, n in code_counter.items() if n >= 2}
    # 数据库中的真实共振（同一天同策略的股票交集）
    try:
        strategy_codes = {}
        for sk in all_sigs.keys():
            rows = conn.execute(
                "SELECT DISTINCT ts_code FROM tracking_pool WHERE strategy=? AND signal_date=?",
                (sk, latest_date),
            ).fetchall()
            strategy_codes[sk] = {r[0] for r in rows}
        if len(strategy_codes) >= 2:
            db_resonant = set.intersection(*strategy_codes.values())
        else:
            db_resonant = mem_resonant
        # 合并两种来源，取并集
        all_resonant = mem_resonant | db_resonant
        # 构建共振列表
        resonant = [
            {"code": c, "name": get_stock_name(c, conn), "count": code_counter.get(c, len(strategy_codes))}
            for c in sorted(all_resonant)
        ]
    except Exception:
        resonant = [{"code": c, "name": get_stock_name(c, conn), "count": n}
                    for c, n in code_counter.most_common() if n >= 2]
    report["resonant"] = resonant

    # 保存到 scan_results 表供前端读取
    _save_to_scan_results(conn, report, latest_date, len(stocks))

    conn.close()

    logger.info(f"✅ 选股完成: {added}只入池, {len(resonant)}只共振")
    return report


def generate_scan_report_text(report: dict, pool_svc: TrackingPoolService) -> str:
    """生成选股报告文本"""
    lines = [
        "=" * 45,
        f"📡 QuantWeave 每日选股 | {report['date']}",
        "=" * 45,
        "",
    ]

    # 持仓盈亏速览
    try:
        conn = sqlite3.connect(pool_svc.db_path if hasattr(pool_svc, 'db_path') else "quantweave.db")
        pos_rows = conn.execute(
            "SELECT ts_code, name, volume, avg_cost FROM positions WHERE is_active = 1"
        ).fetchall()
        conn.close()
        if pos_rows:
            lines.append("💼 持仓速览:")
            if _HAS_XUEQIU:
                try:
                    codes = [r[0] for r in pos_rows]
                    pos_quotes = batch_realtime_quotes(codes)
                    for ts_code, name, vol, avg_cost in pos_rows:
                        if not ts_code or not vol:
                            continue
                        q = pos_quotes.get(ts_code, {})
                        cur_price = q.get("current", 0)
                        chg = q.get("percent", 0)
                        if cur_price > 0 and avg_cost > 0:
                            pnl_pct = (cur_price - avg_cost) / avg_cost * 100
                            arrow = "🔴" if chg > 0 else "🟢" if chg < 0 else "⚪"
                            lines.append(f"  {arrow} {name} {cur_price:.2f}({chg:+.2f}%) 持仓{pnl_pct:+.2f}%")
                except Exception:
                    for ts_code, name, vol, avg_cost in pos_rows:
                        lines.append(f"  ⚪ {name}({ts_code})")
            lines.append("")
    except Exception:
        pass

    for sk, strat_data in report["strategies"].items():
        lines.append(f"📌 {strat_data['name']} ({strat_data['count']}只)")
        for s in strat_data["stocks"][:10]:
            lines.append(f"  • {s['name']}({s['code']}) | {s['close']:.2f}")
        if strat_data["count"] > 10:
            lines.append(f"  ... 共{strat_data['count']}只")
        lines.append("")

    if report.get("resonant"):
        lines.append(f"🔥 多策略共振 ({len(report['resonant'])}只)")
        for r in report["resonant"][:10]:
            lines.append(f"  ⭐ {r['name']}({r['code']}) | {r['count']}策略共振")
        lines.append("")

    # 操作指南（为共振股生成）
    lines.append("📝 重点个股操作指南:")
    for r in report.get("resonant", [])[:5]:
        guide = pool_svc.generate_operation_guide_report(r["code"])
        lines.append(guide)
        lines.append("─" * 40)
        lines.append("")

    lines.append(f"📊 今日新增入池: {report['total_added_to_pool']}只")
    lines.append("")
    lines.append("⚠️ 以上为量化信号参考，不构成投资建议")

    return "\n".join(lines)


# ============================================================
# 3. 卖出信号检测 + 提醒
# ============================================================

def run_sell_check(db_path: str = "quantweave.db") -> str:
    """检测卖出信号并生成提醒"""
    logger.info("🔴 检测卖出信号...")

    lines = [
        "=" * 45,
        f"🔴 QuantWeave 卖出扫描 | {datetime.now().strftime('%Y-%m-%d')}",
        "=" * 45,
        "",
    ]

    # 先展示持仓概况
    conn = sqlite3.connect(db_path)
    try:
        pos_rows = conn.execute(
            "SELECT ts_code, name, volume, avg_cost FROM positions WHERE is_active = 1"
        ).fetchall()
        if pos_rows:
            lines.append("💼 当前持仓:")
            if _HAS_XUEQIU:
                try:
                    codes = [r[0] for r in pos_rows]
                    pos_quotes = batch_realtime_quotes(codes)
                    for ts_code, name, vol, avg_cost in pos_rows:
                        if not ts_code or not vol:
                            continue
                        q = pos_quotes.get(ts_code, {})
                        cur_price = q.get("current", 0)
                        chg = q.get("percent", 0)
                        if cur_price > 0 and avg_cost > 0:
                            pnl_pct = (cur_price - avg_cost) / avg_cost * 100
                            arrow = "🔴" if chg > 0 else "🟢" if chg < 0 else "⚪"
                            lines.append(f"  {arrow} {name}({ts_code}) {cur_price:.2f}({chg:+.2f}%) 成本{avg_cost:.2f} 持仓{pnl_pct:+.2f}%")
                        else:
                            lines.append(f"  ⚪ {name}({ts_code}) 成本{avg_cost:.2f}")
                except Exception:
                    for ts_code, name, vol, avg_cost in pos_rows:
                        lines.append(f"  ⚪ {name}({ts_code}) 成本{avg_cost:.2f}")
            else:
                for ts_code, name, vol, avg_cost in pos_rows:
                    lines.append(f"  ⚪ {name}({ts_code}) 成本{avg_cost:.2f}")
            lines.append("")
    except Exception:
        pass
    finally:
        conn.close()

    # 卖出信号检测
    pool_svc = TrackingPoolService(db_path)
    sell_signals = pool_svc.detect_sell_signals()

    if not sell_signals:
        lines.append("✅ 无卖出信号，所有持仓继续持有。")
        return "\n".join(lines)

    lines.append(f"⚠️ 共检测到 {len(sell_signals)} 个卖出信号：")
    lines.append("")

    for i, s in enumerate(sell_signals, 1):
        pnl_color = "🔴" if s["pnl_pct"] > 0 else "🟢"
        lines.append(f"{i}. {s['stock_name']}({s['ts_code']})")
        lines.append(f"   策略:{s['strategy']} | 持有{s['hold_days']}天")
        lines.append(f"   信号价:{s['signal_price']:.2f} → 当前:{s['current_price']:.2f} ({pnl_color}{s['pnl_pct']:+.2f}%)")
        lines.append(f"   ⚡ {s['sell_reason']}")
        lines.append("")

    lines.append("⚠️ 请及时处理以上卖出信号！")
    return "\n".join(lines)


# ============================================================
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="QuantWeave 交易助手")
    parser.add_argument("--morning", action="store_true", help="只生成盘前速递")
    parser.add_argument("--scan-only", action="store_true", help="只跑选股")
    parser.add_argument("--sell-check", action="store_true", help="只检测卖出信号")
    parser.add_argument("--db", default="quantweave.db", help="数据库路径")
    args = parser.parse_args()

    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    if args.morning:
        text = generate_morning_brief(args.db)
        print(text)
        # 微信推送
        try:
            from app.utils.wechat_notify import send_trading_report
            send_trading_report("盘前速递", text)
        except Exception as e:
            logger.debug(f"微信推送失败: {e}")
        return

    if args.sell_check:
        text = run_sell_check(args.db)
        print(text)
        # 微信推送
        try:
            from app.utils.wechat_notify import send_trading_report
            send_trading_report("卖出扫描", text)
        except Exception as e:
            logger.debug(f"微信推送失败: {e}")
        return

    if args.scan_only:
        report = run_scan_and_track(args.db)
        pool_svc = TrackingPoolService(args.db)
        text = generate_scan_report_text(report, pool_svc)
        print(text)
        # 微信推送
        try:
            from app.utils.wechat_notify import send_trading_report
            send_trading_report("每日选股", text)
        except Exception as e:
            logger.debug(f"微信推送失败: {e}")
        return

    # 完整流程
    # Step 1: 盘前速递
    print("\n" + "=" * 60)
    print("Step 1: 盘前速递")
    print("=" * 60)
    morning_text = generate_morning_brief(args.db)
    print(morning_text)

    # Step 2: 选股+入池
    print("\n" + "=" * 60)
    print("Step 2: 5策略选股 + 入池")
    print("=" * 60)
    report = run_scan_and_track(args.db)
    pool_svc = TrackingPoolService(args.db)
    scan_text = generate_scan_report_text(report, pool_svc)
    print(scan_text)

    # Step 3: 卖出检测
    print("\n" + "=" * 60)
    print("Step 3: 卖出信号检测")
    print("=" * 60)
    sell_text = run_sell_check(args.db)
    print(sell_text)

    # 保存完整报告
    full_report = f"{morning_text}\n\n{scan_text}\n\n{sell_text}"
    report_path = f"reports/daily_workflow_{datetime.now().strftime('%Y%m%d')}.txt"
    os.makedirs("reports", exist_ok=True)
    with open(report_path, "w") as f:
        f.write(full_report)
    print(f"\n💾 完整报告已保存: {report_path}")

    # 微信推送完整报告
    try:
        from app.utils.wechat_notify import send_trading_report
        send_trading_report("每日完整报告", full_report)
    except Exception as e:
        logger.debug(f"微信推送失败: {e}")


if __name__ == "__main__":
    main()
