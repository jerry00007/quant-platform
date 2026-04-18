"""
一键选股策略回测 — 独立运行脚本

用法:
  cd quant-platform/backend
  python -m scripts.run_quick_picks_backtest
"""
import sys
import json
from pathlib import Path

# 确保 backend 目录在 path 中
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.services.backtest.quick_picks_backtest import QuickPicksBacktestEngine

DB_PATH = backend_dir / "quantweave.db"


def main():
    print("=" * 60)
    print("一键选股策略回测 — 最近2年")
    print("=" * 60)

    engine = QuickPicksBacktestEngine(
        db_path=str(DB_PATH),
        initial_cash=1_000_000,
        max_positions=10,
        top_n=5,
        commission=0.0003,
        slippage=0.001,
        scan_interval=1,
    )

    result = engine.run(
        start_date="20240417",
        end_date="20260417",
    )

    if "error" in result:
        print(f"\n❌ 回测失败: {result['error']}")
        return

    # 打印核心指标
    print("\n" + "=" * 60)
    print("📊 回测结果摘要")
    print("=" * 60)
    print(f"策略: {result['strategy_name']}")
    print(f"区间: {result['start_date']} → {result['end_date']}")
    print(f"初始资金: ¥{result['initial_cash']:,.0f}")
    print(f"最终资产: ¥{result['final_value']:,.0f}")
    print(f"总收益率: {result['total_return']:+.2f}%")
    print(f"年化收益: {result['annual_return']:+.2f}%")
    print(f"最大回撤: {result['max_drawdown']:.2f}%")
    print(f"夏普比率: {result['sharpe_ratio']:.3f}")
    print(f"胜率: {result['win_rate']:.1f}%")
    print(f"盈亏比: {result['profit_loss_ratio']:.2f}")
    print(f"总交易次数: {result['total_trades']}")
    print(f"平均持仓数: {result['avg_positions']}")
    print(f"最大持仓数: {result['max_positions_held']}")
    print(f"平均持仓天数: {result['avg_hold_days']}")

    if result.get("sell_reason_stats"):
        print("\n📋 卖出原因分布:")
        for reason, count in sorted(result["sell_reason_stats"].items(), key=lambda x: -x[1]):
            print(f"  {reason}: {count}次")

    # 保存详细结果
    output_path = backend_dir / "quick_picks_backtest_result.json"
    # 去掉大字段
    save_result = {k: v for k, v in result.items() if k not in ("equity_curve", "daily_returns", "trades")}
    save_result["trades_count"] = len(result.get("trades", []))
    save_result["sample_trades"] = result.get("trades", [])[:20]  # 前20笔交易

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(save_result, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n💾 详细结果已保存: {output_path}")


if __name__ == "__main__":
    main()
