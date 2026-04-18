#!/usr/bin/env python3
"""
盘中做T监控脚本
用法: python intraday_monitor.py [--scan | --watch]
  --scan  单次扫描所有持仓做T机会
  --watch 持续监控模式（每5分钟扫描一次）
"""

import sys
import os
import time
import json
import sqlite3
import logging
from datetime import datetime

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.services.data.intraday_data import get_intraday_summary, get_realtime_snapshot
from app.services.strategy.intraday_t import (
    scan_intraday_t_opportunities,
    check_buy_back_signals,
    format_t_signal,
    TSignalType,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "quantweave.db")


def get_active_positions() -> list[dict]:
    """从数据库获取活跃持仓"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("""
        SELECT ts_code, name, volume as shares, avg_cost as cost, volume as available
        FROM positions WHERE is_active = 1
    """)
    positions = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return positions


def get_positions_with_realtime_availability() -> list[dict]:
    """获取持仓（含真实可用数量）"""
    # 数据库里没有单独的available字段，简化处理：
    # 正T需要底仓，假设全部可用（实际T+1可能有部分冻结）
    positions = get_active_positions()
    for p in positions:
        # 兆易创新全仓可用，京新药业只有6300股可用
        # 这个信息暂时从数据库取，后续可手动维护
        p["available"] = p["shares"]  # 简化：默认全部可用
    return positions


def generate_intraday_report() -> str:
    """生成盘中扫描报告"""
    now = datetime.now()
    lines = [
        f"⚡ QuantWeave 日内做T扫描",
        f"⏰ {now.strftime('%Y-%m-%d %H:%M')}",
        "",
    ]
    
    positions = get_positions_with_realtime_availability()
    if not positions:
        lines.append("📭 当前无活跃持仓")
        return "\n".join(lines)
    
    # 1. 持仓实时概况
    lines.append("📊 持仓实时概况:")
    total_mkv = 0
    total_pnl = 0
    
    for p in positions:
        snap = get_realtime_snapshot(p["ts_code"])
        if snap:
            mkv = snap.current * p["shares"]
            pnl = (snap.current - p["cost"]) * p["shares"]
            pnl_pct = (snap.current / p["cost"] - 1) * 100
            total_mkv += mkv
            total_pnl += pnl
            chg = snap.amplitude  # 用振幅显示波动
            arrow = "🔴" if snap.current >= p["cost"] else "🟢"
            lines.append(
                f"  {arrow} {p['name']}({p['ts_code']}) "
                f"{snap.current:.2f}({snap.amplitude:.1f}%) "
                f"盈亏{pnl:+,.0f}({pnl_pct:+.1f}%)"
            )
        else:
            lines.append(f"  ⚠️ {p['name']}({p['ts_code']}) 行情获取失败")
    
    lines.append(f"\n  总市值: {total_mkv:,.0f} | 总盈亏: {total_pnl:+,.0f}")
    
    # 2. 做T信号扫描
    lines.append("")
    lines.append("🎯 做T信号:")
    
    signals = scan_intraday_t_opportunities(positions)
    if signals:
        for s in signals:
            lines.append("")
            lines.append(format_t_signal(s))
    else:
        lines.append("  当前无做T信号，继续监控")
        # 给出每只票的日内数据摘要
        lines.append("")
        lines.append("📋 日内数据摘要:")
        for p in positions[:7]:
            summary = get_intraday_summary(p["ts_code"])
            if "error" not in summary and summary.get("bar_count", 0) > 0:
                lines.append(
                    f"  {p['name']} 现价{summary['current']:.2f} "
                    f"偏离={summary['deviation']:+.1f}% "
                    f"RSI={summary['rsi']:.0f} "
                    f"振幅={summary['amplitude']:.1f}% "
                    f"量比={summary['vol_ratio']:.1f}"
                )
    
    # 3. 操作提醒
    lines.append("")
    lines.append("💡 操作提醒:")
    lines.append("  - 正T: 先卖后买，需要底仓可用")
    lines.append("  - 每笔不超过底仓10%，止损0.5%")
    lines.append("  - 14:30后不开新T仓")
    
    return "\n".join(lines)


def run_scan():
    """单次扫描"""
    report = generate_intraday_report()
    print(report)
    return report


def run_watch(interval: int = 300):
    """
    持续监控模式
    interval: 扫描间隔（秒），默认5分钟
    """
    logger.info(f"启动盘中监控，每{interval//60}分钟扫描一次")
    logger.info("按 Ctrl+C 退出")
    
    # 记录已发出的信号避免重复提醒
    sent_signals = set()
    
    while True:
        now = datetime.now()
        # 只在交易时间运行 (9:30-11:30, 13:00-15:00)
        current_time = now.strftime("%H:%M")
        if not (
            ("09:30" <= current_time <= "11:30") or
            ("13:00" <= current_time <= "15:00")
        ):
            logger.info(f"非交易时间 {current_time}，等待...")
            time.sleep(60)
            continue
        
        try:
            positions = get_positions_with_realtime_availability()
            signals = scan_intraday_t_opportunities(positions)
            
            for s in signals:
                key = f"{s.ts_code}_{s.signal_type.value}"
                if key not in sent_signals:
                    sent_signals.add(key)
                    logger.info(f"\n{format_t_signal(s)}")
            
            # 每30分钟重置一次信号记录
            if now.minute % 30 == 0:
                sent_signals.clear()
            
            logger.info(f"[{current_time}] 扫描完成，发现{len(signals)}个信号")
            
        except Exception as e:
            logger.error(f"扫描出错: {e}")
        
        time.sleep(interval)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        if sys.argv[1] == "--watch":
            run_watch()
        elif sys.argv[1] == "--scan":
            run_scan()
        else:
            print("用法: python intraday_monitor.py [--scan | --watch]")
    else:
        # 默认单次扫描
        run_scan()
