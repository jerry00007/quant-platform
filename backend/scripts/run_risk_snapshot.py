"""
QuantWeave - 夜间全市场风控快照扫描

每天晚上执行，扫描全市场 ~5500 只活跃股票的6维度风控，
结果存 stock_risk_flags 表，供后续回测和选股直接查缓存。

运行方式:
  python -m scripts.run_risk_snapshot
  python -m scripts.run_risk_snapshot --force   # 强制重扫
"""
import sys
import time
from pathlib import Path

# 确保项目根目录在 sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from loguru import logger


def main():
    import argparse
    parser = argparse.ArgumentParser(description="全市场风控快照扫描")
    parser.add_argument("--force", action="store_true", help="强制重扫（忽略缓存）")
    parser.add_argument("--db", type=str, default=None, help="数据库路径")
    args = parser.parse_args()

    db_path = Path(args.db) if args.db else PROJECT_ROOT / "quantweave.db"
    if not db_path.exists():
        logger.error(f"数据库不存在: {db_path}")
        sys.exit(1)

    logger.info(f"🛡️ 启动全市场风控快照扫描 (force={args.force}, db={db_path})")

    from app.services.risk.risk_filter_service import RiskFilterService
    svc = RiskFilterService(db_path)

    result = svc.scan_full_market(force=args.force)

    logger.info(f"🛡️ 扫描结果: {result}")
    return result


if __name__ == "__main__":
    main()
