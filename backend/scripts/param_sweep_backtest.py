"""
一键选股参数扫描脚本

策略：
  1. 数据加载 + 信号预计算只做一次（~150s）
  2. 多组参数复用预计算结果，只重跑每日循环（~26s/次）
  3. 两轮扫描：粗扫描(top_n × max_positions) → 细扫描(hold_days × scan_interval)

用法:
  cd quant-platform/backend
  python -m scripts.param_sweep_backtest
"""
import sys
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd
from loguru import logger

backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.services.backtest.quick_picks_backtest import (
    QuickPicksBacktestEngine,
    ACTIVE_STRATEGIES,
    UNIVERSAL_STOP_LOSS,
    MAX_HOLD_DAYS,
    _calc_score,
)

DB_PATH = str(backend_dir / "quantweave.db")
START_DATE = "20240417"
END_DATE = "20260417"


class ParamSweepRunner:
    """参数扫描运行器 — 复用预计算数据"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.stock_data = None
        self.stock_info = None
        self.trading_dates = None
        self.buy_idx = None
        self.sell_idx = None
        self.date_price_map = None
        self._ready = False

    def prepare(self):
        """一次性准备所有数据（~150s）"""
        t0 = time.time()
        logger.info("🚀 参数扫描: 预加载阶段")

        # 复用 engine 的数据加载方法
        tmp_engine = QuickPicksBacktestEngine(db_path=self.db_path)
        self.stock_data, self.stock_info = tmp_engine._preload_all_data(START_DATE, END_DATE)
        logger.info(f"  加载 {len(self.stock_data)} 只股票, {time.time()-t0:.1f}s")

        # 交易日
        self.trading_dates = tmp_engine._get_trading_dates(START_DATE, END_DATE)
        logger.info(f"  交易日 {len(self.trading_dates)} 天")

        # 信号预计算
        t1 = time.time()
        all_signals = tmp_engine._precompute_signals(self.stock_data)
        self.buy_idx, self.sell_idx = tmp_engine._build_signal_index(all_signals)
        logger.info(f"  信号预计算完成, {time.time()-t1:.1f}s")

        # 行情索引
        t2 = time.time()
        self.date_price_map = tmp_engine._build_date_price_map(self.stock_data)
        logger.info(f"  行情索引构建完成, {time.time()-t2:.1f}s")

        self._ready = True
        logger.info(f"✅ 预加载完成, 总耗时 {time.time()-t0:.1f}s")

    def run_single(self, top_n=5, max_positions=10, max_hold_days=30,
                   scan_interval=1, stop_loss=-0.08) -> dict:
        """运行单次回测（复用预计算数据）"""
        assert self._ready, "请先调用 prepare()"

        cash = 1_000_000
        commission = 0.0003
        slippage = 0.001
        positions = {}
        trades = []
        equity_curve = []
        daily_returns = []
        daily_pos_count = []

        for day_i, cur_date in enumerate(self.trading_dates):
            ds = cur_date.strftime("%Y%m%d")
            dp = self.date_price_map.get(ds, {})
            if not dp:
                continue

            # --- 退出检查 ---
            to_close = []
            for tc, pos in list(positions.items()):
                if tc not in dp:
                    continue
                p = dp[tc]["close"]
                h = dp[tc]["high"]
                pnl = (p - pos["cost"]) / pos["cost"]
                hold = day_i - pos["entry_day"]
                reason = self._check_exit(tc, pos, p, h, pnl, hold, ds,
                                          max_hold_days, stop_loss)
                if reason:
                    to_close.append((tc, reason, pnl))

            for tc, reason, pnl in to_close:
                pos = positions[tc]
                price = dp[tc]["close"] * (1 - slippage)
                amt = pos["shares"] * price
                comm = amt * commission
                profit = amt - pos["cost"] * pos["shares"] - comm
                cash += amt - comm
                trades.append({
                    "date": ds, "direction": "sell", "ts_code": tc,
                    "price": round(price, 2), "volume": pos["shares"],
                    "amount": round(amt, 2), "commission": round(comm, 2),
                    "profit": round(profit, 2),
                    "signal": f"{reason} ({pnl*100:+.1f}%)",
                })
                del positions[tc]

            # --- 扫描建仓 ---
            if day_i % scan_interval == 0 and len(positions) < max_positions:
                cands = self._scan_and_score(ds, day_i, top_n, positions)
                slots = max_positions - len(positions)
                for c in cands[:slots]:
                    tc = c["ts_code"]
                    if tc not in dp:
                        continue
                    price = dp[tc]["close"] * (1 + slippage)
                    budget = cash / max(slots, 1) * 0.95
                    shares = int(budget / price / 100) * 100
                    if shares <= 0:
                        continue
                    cost = shares * price
                    comm = cost * commission
                    if cost + comm > cash:
                        continue
                    cash -= cost + comm
                    positions[tc] = {
                        "shares": shares, "cost": price, "entry_day": day_i,
                        "entry_date": ds, "strategy": c.get("strategy", "dual_ma"),
                        "peak_price": price, "score": c.get("score", 0),
                    }
                    trades.append({
                        "date": ds, "direction": "buy", "ts_code": tc,
                        "price": round(price, 2), "volume": shares,
                        "amount": round(cost, 2), "commission": round(comm, 2),
                        "signal": f"{c.get('strategy_name','')} 评分={c.get('score',0):.0f}",
                    })

            # 更新峰值
            for tc, pos in positions.items():
                if tc in dp:
                    pos["peak_price"] = max(pos["peak_price"], dp[tc]["high"])

            # 净值
            mv = sum(positions[tc]["shares"] * dp.get(tc, {}).get("close", 0)
                     for tc in positions if tc in dp)
            tv = cash + mv
            equity_curve.append({"date": ds, "value": tv})
            daily_pos_count.append(len(positions))
            dr = (tv - equity_curve[-2]["value"]) / equity_curve[-2]["value"] if len(equity_curve) > 1 else 0
            daily_returns.append({"date": ds, "return": dr})

        # 强制平仓
        fds = self.trading_dates[-1].strftime("%Y%m%d")
        fp = self.date_price_map.get(fds, {})
        for tc, pos in list(positions.items()):
            if tc in fp:
                price = fp[tc]["close"] * (1 - slippage)
                amt = pos["shares"] * price
                comm = amt * commission
                profit = amt - pos["cost"] * pos["shares"] - comm
                cash += amt - comm
                pnl = price / pos["cost"] - 1
                trades.append({
                    "date": fds, "direction": "sell", "ts_code": tc,
                    "price": round(price, 2), "volume": pos["shares"],
                    "signal": f"回测结束 ({pnl*100:+.1f}%)",
                })
        positions.clear()
        final_value = cash

        # 指标计算
        return self._calc_metrics(trades, equity_curve, daily_returns,
                                  len(self.trading_dates), daily_pos_count,
                                  top_n, max_positions, max_hold_days, scan_interval,
                                  stop_loss, final_value)

    def _check_exit(self, tc, pos, cur_price, high_price, pnl_pct, hold_days,
                    date_str, max_hold_days, stop_loss):
        strategy = pos.get("strategy", "dual_ma")
        exit_cfg = ACTIVE_STRATEGIES.get(strategy, {}).get("exit_config", {})
        peak = pos.get("peak_price", pos["cost"])

        # 1. 止损
        if pnl_pct <= stop_loss:
            return "止损"

        # 2. 超时
        if hold_days >= max_hold_days:
            return f"超时({hold_days}天)"

        # 3. 策略止盈
        et = exit_cfg.get("type", "fixed")
        if et == "fixed":
            if pnl_pct >= exit_cfg.get("take_profit_pct", 0.15):
                return "止盈"
        elif et == "trailing":
            tiers = exit_cfg.get("tiers", [])
            min_profit = exit_cfg.get("min_profit_pct", 0.03)
            peak_pnl = (peak - pos["cost"]) / pos["cost"]
            if peak_pnl >= min_profit:
                trail_pct = 0.05
                for tier in sorted(tiers, key=lambda t: t["profit_pct"]):
                    if peak_pnl >= tier["profit_pct"]:
                        trail_pct = tier["trail_pct"]
                dd = (peak - cur_price) / peak if peak > 0 else 0
                if dd >= trail_pct:
                    return "移动止盈"

        # 4. 策略卖出信号
        day_sells = self.sell_idx.get(date_str, {})
        if tc in day_sells:
            return "策略卖出"

        return None

    def _scan_and_score(self, date_str, day_idx, top_n, cur_positions):
        day_buys = self.buy_idx.get(date_str, {})
        if not day_buys:
            return []

        candidates = []
        for tc, strats_hit in day_buys.items():
            if tc in cur_positions:
                continue
            df = self.stock_data.get(tc)
            if df is None:
                continue
            df_slice = df[df["trade_date"].astype(str) <= date_str].copy()
            if len(df_slice) < 60:
                continue

            score_data = _calc_score(df_slice, "")
            total_score = score_data.get("total", 0)
            if len(strats_hit) >= 2:
                total_score += 10

            candidates.append({
                "ts_code": tc,
                "name": self.stock_info.get(tc, ""),
                "score": total_score,
                "strategy": strats_hit[0],
                "strategy_name": ", ".join(ACTIVE_STRATEGIES.get(s, {}).get("name", s) for s in strats_hit),
                "resonance": len(strats_hit) >= 2,
            })

        candidates.sort(key=lambda x: x["score"], reverse=True)
        return candidates[:top_n]

    @staticmethod
    def _calc_metrics(trades, equity_curve, daily_returns, trading_days,
                      daily_pos_count, top_n, max_positions, max_hold_days,
                      scan_interval, stop_loss, final_value):
        initial_cash = 1_000_000
        fv = equity_curve[-1]["value"] if equity_curve else initial_cash
        tr = (fv - initial_cash) / initial_cash * 100
        tdpy = 244
        ar = ((1 + tr / 100) ** (tdpy / max(trading_days, 1)) - 1) * 100 if trading_days > 0 else 0

        vals = [e["value"] for e in equity_curve]
        pk = vals[0] if vals else initial_cash
        mdd = 0
        for v in vals:
            if v > pk:
                pk = v
            dd = (pk - v) / pk * 100 if pk > 0 else 0
            if dd > mdd:
                mdd = dd

        rets = [d["return"] for d in daily_returns]
        sharpe = np.mean(rets) / np.std(rets) * np.sqrt(tdpy) if len(rets) > 1 and np.std(rets) > 0 else 0

        sells = [t for t in trades if t["direction"] == "sell" and "profit" in t]
        wins = [t for t in sells if t["profit"] > 0]
        losses = [t for t in sells if t["profit"] <= 0]
        wr = len(wins) / len(sells) * 100 if sells else 0
        aw = np.mean([t["profit"] for t in wins]) if wins else 0
        al = abs(np.mean([t["profit"] for t in losses])) if losses else 1
        plr = aw / al if al > 0 else 0

        hold_days_list = []
        pairs = {}
        for t in trades:
            if t["direction"] == "buy":
                pairs[t["ts_code"]] = t["date"]
            elif t["direction"] == "sell" and t["ts_code"] in pairs:
                try:
                    d1 = datetime.strptime(pairs[t["ts_code"]], "%Y%m%d")
                    d2 = datetime.strptime(t["date"], "%Y%m%d")
                    hold_days_list.append((d2 - d1).days)
                except Exception:
                    pass
                del pairs[t["ts_code"]]

        return {
            "total_return": round(tr, 2),
            "annual_return": round(ar, 2),
            "max_drawdown": round(mdd, 2),
            "sharpe_ratio": round(sharpe, 3),
            "win_rate": round(wr, 2),
            "profit_loss_ratio": round(plr, 2),
            "total_trades": len(trades),
            "final_value": round(fv, 2),
            "avg_positions": round(np.mean(daily_pos_count), 1) if daily_pos_count else 0,
            "avg_hold_days": round(np.mean(hold_days_list), 1) if hold_days_list else 0,
            # 参数标记
            "top_n": top_n,
            "max_positions": max_positions,
            "max_hold_days": max_hold_days,
            "scan_interval": scan_interval,
            "stop_loss": stop_loss,
        }


def main():
    print("=" * 70)
    print("🔬 一键选股参数扫描")
    print(f"   区间: {START_DATE} → {END_DATE} (2年)")
    print("=" * 70)

    runner = ParamSweepRunner(DB_PATH)
    runner.prepare()

    # ==========================================
    # 第一轮: 粗扫描 — top_n × max_positions
    # ==========================================
    print("\n" + "=" * 70)
    print("📊 第一轮: 粗扫描 top_n × max_positions")
    print("=" * 70)

    top_n_list = [3, 5, 7, 10]
    max_pos_list = [5, 8, 10, 15, 20]
    round1_results = []

    t_start = time.time()
    for top_n in top_n_list:
        for max_pos in max_pos_list:
            t1 = time.time()
            result = runner.run_single(
                top_n=top_n,
                max_positions=max_pos,
                max_hold_days=30,  # 默认
                scan_interval=1,   # 默认
                stop_loss=-0.08,   # 默认
            )
            elapsed = time.time() - t1
            round1_results.append(result)
            print(f"  top_n={top_n:>2} max_pos={max_pos:>2} | "
                  f"收益={result['total_return']:+7.2f}% 年化={result['annual_return']:+6.2f}% "
                  f"回撤={result['max_drawdown']:5.2f}% 夏普={result['sharpe_ratio']:.3f} "
                  f"胜率={result['win_rate']:5.1f}% 交易={result['total_trades']:>3} "
                  f"({elapsed:.1f}s)")

    print(f"\n第一轮耗时: {time.time()-t_start:.1f}s ({len(round1_results)}组)")

    # 找出最优组合（按夏普排序，要求收益>0）
    valid_r1 = [r for r in round1_results if r["total_return"] > 0]
    if valid_r1:
        best_r1 = sorted(valid_r1, key=lambda x: x["sharpe_ratio"], reverse=True)[0]
        print(f"\n🏆 第一轮最优（夏普）: top_n={best_r1['top_n']} max_pos={best_r1['max_positions']} "
              f"收益={best_r1['total_return']:+.2f}% 夏普={best_r1['sharpe_ratio']:.3f}")
        best_r1_by_return = sorted(valid_r1, key=lambda x: x["total_return"], reverse=True)[0]
        print(f"💰 第一轮最优（收益）: top_n={best_r1_by_return['top_n']} max_pos={best_r1_by_return['max_positions']} "
              f"收益={best_r1_by_return['total_return']:+.2f}% 回撤={best_r1_by_return['max_drawdown']:.2f}%")
    else:
        best_r1 = round1_results[0]
        print("\n⚠️ 所有组合收益<=0, 取第一组继续")

    # ==========================================
    # 第二轮: 细扫描 — max_hold_days × scan_interval
    # 用第一轮最优的 top_n 和 max_positions
    # ==========================================
    print("\n" + "=" * 70)
    print("📊 第二轮: 细扫描 max_hold_days × scan_interval")
    print(f"   固定: top_n={best_r1['top_n']} max_positions={best_r1['max_positions']}")
    print("=" * 70)

    hold_days_list = [10, 15, 20, 25, 30, 40, 50, 60]
    scan_interval_list = [1, 2, 3, 5]
    round2_results = []

    t_start = time.time()
    for hd in hold_days_list:
        for si in scan_interval_list:
            t1 = time.time()
            result = runner.run_single(
                top_n=best_r1["top_n"],
                max_positions=best_r1["max_positions"],
                max_hold_days=hd,
                scan_interval=si,
                stop_loss=-0.08,
            )
            elapsed = time.time() - t1
            round2_results.append(result)
            print(f"  hold={hd:>2}天 scan={si}天/次 | "
                  f"收益={result['total_return']:+7.2f}% 年化={result['annual_return']:+6.2f}% "
                  f"回撤={result['max_drawdown']:5.2f}% 夏普={result['sharpe_ratio']:.3f} "
                  f"胜率={result['win_rate']:5.1f}% 交易={result['total_trades']:>3} "
                  f"均持={result['avg_hold_days']:4.1f}天 ({elapsed:.1f}s)")

    print(f"\n第二轮耗时: {time.time()-t_start:.1f}s ({len(round2_results)}组)")

    # ==========================================
    # 第三轮: 止损测试
    # 用前两轮最优参数
    # ==========================================
    valid_r2 = [r for r in round2_results if r["total_return"] > 0]
    if valid_r2:
        best_r2 = sorted(valid_r2, key=lambda x: x["sharpe_ratio"], reverse=True)[0]
    else:
        best_r2 = round2_results[0]

    print("\n" + "=" * 70)
    print("📊 第三轮: 止损测试")
    print(f"   固定: top_n={best_r2['top_n']} max_pos={best_r2['max_positions']} "
          f"hold={best_r2['max_hold_days']}天 scan={best_r2['scan_interval']}天")
    print("=" * 70)

    stop_loss_list = [-0.05, -0.06, -0.08, -0.10, -0.12, -0.15]
    round3_results = []

    t_start = time.time()
    for sl in stop_loss_list:
        t1 = time.time()
        result = runner.run_single(
            top_n=best_r2["top_n"],
            max_positions=best_r2["max_positions"],
            max_hold_days=best_r2["max_hold_days"],
            scan_interval=best_r2["scan_interval"],
            stop_loss=sl,
        )
        elapsed = time.time() - t1
        round3_results.append(result)
        print(f"  止损={sl*100:+.0f}% | "
              f"收益={result['total_return']:+7.2f}% 年化={result['annual_return']:+6.2f}% "
              f"回撤={result['max_drawdown']:5.2f}% 夏普={result['sharpe_ratio']:.3f} "
              f"胜率={result['win_rate']:5.1f}% ({elapsed:.1f}s)")

    print(f"\n第三轮耗时: {time.time()-t_start:.1f}s ({len(round3_results)}组)")

    # ==========================================
    # 汇总
    # ==========================================
    all_results = round1_results + round2_results + round3_results

    # 最终排名（夏普>0 且收益>0）
    valid_all = [r for r in all_results if r["total_return"] > 0]
    if valid_all:
        by_sharpe = sorted(valid_all, key=lambda x: x["sharpe_ratio"], reverse=True)[:10]
        by_return = sorted(valid_all, key=lambda x: x["total_return"], reverse=True)[:10]
    else:
        by_sharpe = sorted(all_results, key=lambda x: x["total_return"], reverse=True)[:10]
        by_return = by_sharpe

    print("\n" + "=" * 70)
    print("🏆 最终排名 — 按夏普比率 Top 10")
    print("=" * 70)
    for i, r in enumerate(by_sharpe):
        print(f"  #{i+1}: top_n={r['top_n']} max_pos={r['max_positions']} "
              f"hold={r['max_hold_days']}天 scan={r['scan_interval']}天 止损={r['stop_loss']*100:+.0f}% | "
              f"收益={r['total_return']:+.2f}% 年化={r['annual_return']:+.2f}% "
              f"回撤={r['max_drawdown']:.2f}% 夏普={r['sharpe_ratio']:.3f} "
              f"胜率={r['win_rate']:.1f}%")

    print("\n💰 最终排名 — 按总收益 Top 10")
    print("=" * 70)
    for i, r in enumerate(by_return):
        print(f"  #{i+1}: top_n={r['top_n']} max_pos={r['max_positions']} "
              f"hold={r['max_hold_days']}天 scan={r['scan_interval']}天 止损={r['stop_loss']*100:+.0f}% | "
              f"收益={r['total_return']:+.2f}% 年化={r['annual_return']:+.2f}% "
              f"回撤={r['max_drawdown']:.2f}% 夏普={r['sharpe_ratio']:.3f}")

    # 保存结果
    output = {
        "scan_time": datetime.now().isoformat(),
        "period": f"{START_DATE}~{END_DATE}",
        "baseline": {
            "top_n": 5, "max_positions": 10, "max_hold_days": 30,
            "scan_interval": 1, "stop_loss": -0.08,
            "total_return": 15.29, "annual_return": 7.42,
            "max_drawdown": 14.98, "sharpe_ratio": 0.441,
        },
        "round1_topn_maxpos": round1_results,
        "round2_hold_scan": round2_results,
        "round3_stoploss": round3_results,
        "best_by_sharpe": by_sharpe,
        "best_by_return": by_return,
    }

    output_path = backend_dir / "param_sweep_results.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n💾 扫描结果已保存: {output_path}")


if __name__ == "__main__":
    main()
