#!/usr/bin/env python3
"""
QuantWeave - 批量股票数据下载脚本
从 Tushare Pro + AKShare 下载全A股近一年日线数据
特点：
  - 自动限速，尊重 API 频率限制
  - 断点续传：已下载的自动跳过
  - 双数据源自动切换
  - 进度条显示
  - 错误重试机制
"""

import os
import sys
import time
import signal
import argparse
from datetime import datetime, timedelta
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from loguru import logger
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.config import get_settings
from app.models.models import Stock, StockDaily
from app.services.data.data_service import DataService


# 全局控制优雅退出
_graceful_exit = False


def signal_handler(sig, frame):
    global _graceful_exit
    if _graceful_exit:
        logger.warning("强制退出...")
        sys.exit(1)
    _graceful_exit = True
    logger.info("收到退出信号，等待当前任务完成后退出（再按一次强制退出）...")


signal.signal(signal.SIGINT, signal_handler)


def load_tushare_token() -> str:
    """加载 Tushare Token"""
    settings = get_settings()
    if settings.TUSHARE_TOKEN:
        return settings.TUSHARE_TOKEN
    
    # 尝试从 .env 文件读取
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line.startswith("TUSHARE_TOKEN="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    
    return ""


def get_date_range(years: float = 1.0):
    """获取日期范围"""
    end_date = datetime.now()
    start_date = end_date - timedelta(days=int(365 * years))
    return start_date.strftime("%Y%m%d"), end_date.strftime("%Y%m%d")


def count_existing_data(db: Session) -> dict:
    """统计已有数据量"""
    stock_count = db.query(Stock).filter(Stock.is_active == True).count()
    daily_count = db.query(StockDaily).count()
    unique_codes = db.query(StockDaily.ts_code).distinct().count()
    return {
        "stocks": stock_count,
        "daily_records": daily_count,
        "unique_codes": unique_codes,
    }


def get_stocks_to_download(db: Session, start_date: str, end_date: str) -> list:
    """
    获取需要下载数据的股票列表
    跳过已有完整数据的股票
    """
    all_stocks = db.query(Stock).filter(Stock.is_active == True).all()
    
    # 查询已有哪些股票有数据
    existing_codes_with_data = set(
        r[0] for r in db.query(StockDaily.ts_code).distinct().all()
    )
    
    # 计算预期交易日数量（约250天/年）
    days = (datetime.strptime(end_date, "%Y%m%d") - datetime.strptime(start_date, "%Y%m%d")).days
    expected_trading_days = int(days * 250 / 365)
    
    need_download = []
    already_complete = []
    
    for stock in all_stocks:
        if stock.ts_code in existing_codes_with_data:
            # 检查数据是否完整
            record_count = db.query(StockDaily).filter(
                StockDaily.ts_code == stock.ts_code,
                StockDaily.trade_date >= start_date,
                StockDaily.trade_date <= end_date,
            ).count()
            
            if record_count >= expected_trading_days * 0.9:  # 90%以上认为完整
                already_complete.append(stock.ts_code)
                continue
        
        need_download.append(stock)
    
    logger.info(f"股票统计: 总计 {len(all_stocks)} 只, 已完整 {len(already_complete)} 只, 待下载 {len(need_download)} 只")
    return need_download


def download_with_retry(service: DataService, ts_code: str, start_date: str, end_date: str, max_retries: int = 3) -> int:
    """带重试的数据下载"""
    for attempt in range(max_retries):
        try:
            df = service.fetch_daily(ts_code, start_date, end_date)
            if df is not None and not df.empty:
                saved = service.save_daily_data(df)
                return saved
            return 0
        except Exception as e:
            if attempt < max_retries - 1:
                wait = 2 ** (attempt + 1)  # 指数退避: 2, 4, 8秒
                logger.warning(f"  重试 {attempt+1}/{max_retries} {ts_code}: {e}，等待{wait}秒...")
                time.sleep(wait)
            else:
                logger.error(f"  最终失败 {ts_code}: {e}")
                return -1
    return 0


def main():
    parser = argparse.ArgumentParser(description="QuantWeave 批量股票数据下载")
    parser.add_argument("--years", type=float, default=1.0, help="下载最近N年数据（默认1年）")
    parser.add_argument("--batch-size", type=int, default=50, help="每批数量（默认50）")
    parser.add_argument("--delay", type=float, default=0.3, help="每只股票间隔秒数（默认0.3）")
    parser.add_argument("--batch-delay", type=float, default=2.0, help="每批间隔秒数（默认2.0）")
    parser.add_argument("--retries", type=int, default=3, help="失败重试次数（默认3）")
    parser.add_argument("--sync-list", action="store_true", help="先同步股票列表")
    args = parser.parse_args()
    
    logger.info("=" * 60)
    logger.info("🚀 QuantWeave 批量数据下载工具")
    logger.info("=" * 60)
    
    # 加载 Token
    token = load_tushare_token()
    if token:
        logger.info(f"📝 Tushare Token: {token[:4]}****")
    else:
        logger.warning("⚠️ 未配置 Tushare Token，将仅使用 AKShare")
    
    # 日期范围
    start_date, end_date = get_date_range(args.years)
    logger.info(f"📅 日期范围: {start_date} ~ {end_date} ({args.years}年)")
    
    db = SessionLocal()
    
    try:
        # 先同步股票列表
        if args.sync_list:
            logger.info("📋 正在同步股票列表...")
            service = DataService(db, tushare_token=token)
            count = service.sync_stock_list()
            logger.info(f"✅ 股票列表同步完成，新增 {count} 只")
        
        # 统计现有数据
        stats = count_existing_data(db)
        logger.info(f"📊 当前数据库: {stats['stocks']} 只股票, {stats['daily_records']} 条日线, {stats['unique_codes']} 只有数据")
        
        # 获取待下载列表
        stocks = get_stocks_to_download(db, start_date, end_date)
        if not stocks:
            logger.info("✅ 所有股票数据已是最新，无需下载！")
            return
        
        total = len(stocks)
        logger.info(f"🔄 开始下载 {total} 只股票的日线数据...")
        
        service = DataService(db, tushare_token=token)
        
        success_count = 0
        fail_count = 0
        skip_count = 0
        total_rows = 0
        start_time = time.time()
        
        for i, stock in enumerate(stocks):
            if _graceful_exit:
                logger.info(f"⏹️ 优雅退出，已完成 {i}/{total}")
                break
            
            ts_code = stock.ts_code
            progress = f"[{i+1}/{total}]"
            
            try:
                saved = download_with_retry(
                    service, ts_code, start_date, end_date, args.retries
                )
                
                if saved > 0:
                    success_count += 1
                    total_rows += saved
                    logger.info(f"  {progress} ✅ {ts_code} {stock.name}: +{saved}条")
                elif saved == 0:
                    skip_count += 1
                    logger.debug(f"  {progress} ⏭️ {ts_code} {stock.name}: 无新数据")
                else:
                    fail_count += 1
                    logger.warning(f"  {progress} ❌ {ts_code} {stock.name}: 失败")
                
            except Exception as e:
                fail_count += 1
                logger.error(f"  {progress} ❌ {ts_code}: {e}")
            
            # 限速控制
            time.sleep(args.delay)
            
            # 每批次暂停
            if (i + 1) % args.batch_size == 0:
                elapsed = time.time() - start_time
                speed = (i + 1) / elapsed
                eta = (total - i - 1) / speed if speed > 0 else 0
                logger.info(
                    f"📊 批次进度: {i+1}/{total} "
                    f"({(i+1)/total*100:.1f}%) | "
                    f"速度: {speed:.1f}只/秒 | "
                    f"剩余: ~{eta/60:.1f}分钟"
                )
                db.commit()  # 确保数据落盘
                time.sleep(args.batch_delay)
        
        # 汇总报告
        elapsed = time.time() - start_time
        logger.info("=" * 60)
        logger.info("📊 下载完成汇总:")
        logger.info(f"  ⏱️ 耗时: {elapsed/60:.1f} 分钟")
        logger.info(f"  ✅ 成功: {success_count} 只")
        logger.info(f"  ⏭️ 跳过: {skip_count} 只")
        logger.info(f"  ❌ 失败: {fail_count} 只")
        logger.info(f"  📈 新增数据: {total_rows} 条")
        logger.info(f"  💾 平均速度: {total/elapsed*60:.0f} 只/分钟")
        logger.info("=" * 60)
        
        # 最终统计
        final_stats = count_existing_data(db)
        logger.info(f"📊 数据库最终状态: {final_stats['daily_records']} 条日线, {final_stats['unique_codes']} 只有数据")
        
    except Exception as e:
        logger.error(f"💥 程序异常: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


if __name__ == "__main__":
    main()
