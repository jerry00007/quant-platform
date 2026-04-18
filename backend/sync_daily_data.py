"""
QuantWeave — 日线数据同步脚本
收盘后执行，同步当日全市场日线数据到 stock_daily 表

用法:
    /opt/anaconda3/envs/quant-platform/bin/python sync_daily_data.py
    /opt/anaconda3/envs/quant-platform/bin/python sync_daily_data.py --date 20260417
    /opt/anaconda3/envs/quant-platform/bin/python sync_daily_data.py --dry-run

数据源优先级：
1. Tushare pro.daily(trade_date=X) — 一次拉全市场，最快
2. AKShare stock_zh_a_spot_em() — 东方财富实时行情，收盘后可用
"""
import sys
import os
import sqlite3
import argparse
import time
from datetime import datetime, timedelta

import pandas as pd
from loguru import logger

os.chdir(os.path.dirname(os.path.abspath(__file__)))

DB_PATH = "quantweave.db"


def get_tushare_pro():
    """初始化 Tushare Pro"""
    try:
        from dotenv import load_dotenv
        load_dotenv()
        import tushare as ts
        token = os.getenv("TUSHARE_TOKEN")
        if not token:
            logger.warning("TUSHARE_TOKEN 未配置")
            return None
        pro = ts.pro_api(token)
        return pro
    except Exception as e:
        logger.warning(f"Tushare 初始化失败: {e}")
        return None


def find_trade_date(conn):
    """找到需要同步的交易日（stock_daily 中最新日期的下个交易日）"""
    latest = conn.execute("SELECT MAX(trade_date) FROM stock_daily").fetchone()[0]
    if latest:
        logger.info(f"数据库最新日期: {latest}")
    return latest


def sync_via_tushare(trade_date, conn, dry_run=False):
    """方式1: Tushare pro.daily(trade_date=X) 一次拉全市场"""
    pro = get_tushare_pro()
    if not pro:
        return 0

    try:
        logger.info(f"📡 尝试 Tushare 同步 {trade_date}...")
        df = pro.daily(trade_date=trade_date)
        if df is None or df.empty:
            logger.warning(f"Tushare 无 {trade_date} 数据（可能收盘后才有）")
            return 0

        logger.info(f"Tushare 获取 {len(df)} 条记录")
        if dry_run:
            print(f"[DRY RUN] 将写入 {len(df)} 条 {trade_date} 数据")
            return len(df)

        count = _save_to_db(df, conn)
        logger.info(f"✅ Tushare 同步完成: {count} 条新记录")
        return count

    except Exception as e:
        logger.warning(f"Tushare 同步失败: {e}")
        return 0


def sync_via_akshare(trade_date, conn, dry_run=False):
    """方式2: AKShare 东方财富实时行情（收盘后包含当日数据）"""
    try:
        import akshare as ak
    except ImportError:
        logger.warning("AKShare 未安装")
        return 0

    try:
        logger.info(f"📡 尝试 AKShare 同步（东方财富行情）...")
        df = ak.stock_zh_a_spot_em()
        if df is None or df.empty:
            logger.warning("AKShare 返回空数据")
            return 0

        logger.info(f"AKShare 获取 {len(df)} 条记录")

        # AKShare 返回字段: 代码,名称,最新价,涨跌幅,涨跌额,成交量,成交额,振幅,最高,最低,今开,昨收,...
        # 需要映射到 stock_daily 格式
        import re
        records = []
        for _, row in df.iterrows():
            code = str(row.get("代码", ""))
            if not code:
                continue
            # 转换为 ts_code 格式
            if code.startswith(("6",)):
                ts_code = f"{code}.SH"
            elif code.startswith(("0", "3")):
                ts_code = f"{code}.SZ"
            elif code.startswith(("4", "8")):
                ts_code = f"{code}.BJ"
            else:
                continue

            close = row.get("最新价", 0)
            if not close or (isinstance(close, float) and pd.isna(close)):
                continue

            records.append({
                "ts_code": ts_code,
                "trade_date": trade_date,
                "open": _safe_float(row.get("今开", 0)),
                "high": _safe_float(row.get("最高", 0)),
                "low": _safe_float(row.get("最低", 0)),
                "close": _safe_float(close),
                "pre_close": _safe_float(row.get("昨收", 0)),
                "change_pct": _safe_float(row.get("涨跌幅", 0)),
                "vol": _safe_float(row.get("成交量", 0)),
                "amount": _safe_float(row.get("成交额", 0)) / 1000 if _safe_float(row.get("成交额", 0)) > 1e10 else _safe_float(row.get("成交额", 0)),
            })

        if dry_run:
            print(f"[DRY RUN] 将写入 {len(records)} 条 {trade_date} 数据")
            return len(records)

        # 批量写入
        count = 0
        for r in records:
            try:
                conn.execute("""
                    INSERT OR IGNORE INTO stock_daily 
                    (ts_code, trade_date, open, high, low, close, pre_close, change_pct, vol, amount)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (r["ts_code"], r["trade_date"], r["open"], r["high"], r["low"],
                      r["close"], r["pre_close"], r["change_pct"], r["vol"], r["amount"]))
                count += 1
            except Exception:
                pass
        conn.commit()
        logger.info(f"✅ AKShare 同步完成: {count} 条记录")
        return count

    except Exception as e:
        logger.warning(f"AKShare 同步失败: {e}")
        return 0


def _save_to_db(df, conn):
    """将 Tushare DataFrame 写入 stock_daily"""
    count = 0
    for _, r in df.iterrows():
        try:
            conn.execute("""
                INSERT OR IGNORE INTO stock_daily 
                (ts_code, trade_date, open, high, low, close, pre_close, change_pct, vol, amount)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                r["ts_code"],
                str(r["trade_date"]),
                _safe_float(r.get("open", 0)),
                _safe_float(r.get("high", 0)),
                _safe_float(r.get("low", 0)),
                _safe_float(r.get("close", 0)),
                _safe_float(r.get("pre_close", 0)),
                _safe_float(r.get("pct_chg", 0)),
                _safe_float(r.get("vol", 0)),
                _safe_float(r.get("amount", 0)),
            ))
            count += 1
        except Exception:
            pass
    conn.commit()
    return count


def _safe_float(val):
    """安全转换为 float"""
    try:
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return 0.0
        return float(val)
    except (ValueError, TypeError):
        return 0.0


def main():
    parser = argparse.ArgumentParser(description="QuantWeave 日线数据同步")
    parser.add_argument("--date", help="指定日期 YYYYMMDD，默认今天")
    parser.add_argument("--dry-run", action="store_true", help="只测试不写入")
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)

    # 确定要同步的日期
    if args.date:
        target_date = args.date
    else:
        # 默认同步今天
        target_date = datetime.now().strftime("%Y%m%d")

    # 检查是否已有该日数据
    existing = conn.execute(
        "SELECT COUNT(*) FROM stock_daily WHERE trade_date=?", (target_date,)
    ).fetchone()[0]

    if existing > 0:
        print(f"⚠️ {target_date} 已有 {existing} 条数据，跳过同步")
        conn.close()
        return

    print(f"🔄 开始同步 {target_date} 日线数据...")
    print(f"   数据库当前最新日期: {find_trade_date(conn)}")

    # 方式1: Tushare（最快，一次拉全市场）
    count = sync_via_tushare(target_date, conn, dry_run=args.dry_run)

    # 方式2: AKShare 兜底
    if count == 0:
        logger.info("Tushare 同步失败，尝试 AKShare...")
        count = sync_via_akshare(target_date, conn, dry_run=args.dry_run)

    if count > 0:
        # 验证
        total = conn.execute(
            "SELECT COUNT(*) FROM stock_daily WHERE trade_date=?", (target_date,)
        ).fetchone()[0]
        print(f"\n✅ 同步完成！{target_date} 共 {total} 条记录")
    else:
        print(f"\n❌ 同步失败：{target_date} 数据暂不可用")
        print("   可能原因：1) 收盘数据尚未发布（通常16:00后） 2) 今天非交易日")
        print("   建议：稍后重试，或等18:00自动重试")

    conn.close()


if __name__ == "__main__":
    main()
