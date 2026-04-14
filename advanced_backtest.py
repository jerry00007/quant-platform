#!/usr/bin/env python3
"""
QuantWeave 专业级回测引擎 v3.0
  - Walk-Forward 滚动窗口验证
  - Monte Carlo 模拟（5000次）
  - 组合级回测
  - 增强风险指标（Sortino/Calmar/VaR/CVaR/Ulcer）
"""
import json, os, warnings
import numpy as np, pandas as pd, tushare as ts
from scipy import stats
from collections import defaultdict
warnings.filterwarnings('ignore')

TOKEN = "f7ab0774ef145a98c1d7e6e31d78b13759fb547fc9b0d38c8824f821"
IC = 1_000_000; COMM = 0.0003; SLIP = 0.001
STOCKS = {"600519.SH":"贵州茅台","000858.SZ":"五粮液","601318.SH":"中国平安",
    "600036.SH":"招商银行","000001.SZ":"平安银行","000333.SZ":"美的集团",
    "601398.SH":"工商银行","000651.SZ":"格力电器"}
CACHE_DIR = os.path.join(os.path.dirname(__file__) or ".", "data_cache")

def fetch(tc, s, e):
    os.makedirs(CACHE_DIR, exist_ok=True)
    cf = os.path.join(CACHE_DIR, f"{tc}_{s.replace('-','')}_{e.replace('-','')}.parquet")
    if os.path.exists(cf): return pd.read_parquet(cf)
    pro = ts.pro_api(TOKEN)
    df = pro.daily(ts_code=tc, start_date=s.replace("-",""), end_date=e.replace("-",""),
        fields="ts_code,trade_date,open,high,low,close,vol,amount,pct_chg")
    if df is None or df.empty: return pd.DataFrame()
    df = df.sort_values("trade_date").reset_index(drop=True)
    df["trade_date"] = df["trade_date"].astype(str); df["vol"] = df["vol"].astype(float)*100
    df.to_parquet(cf, index=False)
    return df

# ═══ 增强风险指标 ═══
def calc_risk_metrics(equity_curve, rf=0.02):
    vals = [e["v"] for e in equity_curve]
    if len(vals) < 10: return {}
    rets = pd.Series([(vals[i]-vals[i-1])/vals[i-1] for i in range(1, len(vals))])
    tr = (vals[-1]-vals[0])/vals[0]*100; days = len(vals)
    ar = ((1+tr/100)**(244/max(days,1))-1)*100
    # 最大回撤 + 回撤持续
    pk = vals[0]; mdd = 0; dd_start = 0; max_dd_dur = 0
    for i, v in enumerate(vals):
        if v > pk: pk = v; dd_start = i
        dd = (pk-v)/pk*100
        if dd > mdd: mdd = dd
        if v < pk: max_dd_dur = max(max_dd_dur, i - dd_start)
    # Sharpe
    rf_d = rf/244; exc = rets - rf_d
    sharpe = float(np.mean(exc)/np.std(rets)*np.sqrt(244)) if np.std(rets)>0 else 0
    # Sortino
    ds = rets[rets<0]; ds_std = np.std(ds) if len(ds)>0 else 1e-10
    sortino = float(np.mean(exc)/ds_std*np.sqrt(244))
    # Calmar
    calmar = ar/mdd if mdd>0 else 0
    # VaR / CVaR
    var95 = float(np.percentile(rets,5))*100; var99 = float(np.percentile(rets,1))*100
    cvar95 = float(rets[rets<=np.percentile(rets,5)].mean())*100
    cvar99 = float(rets[rets<=np.percentile(rets,1)].mean())*100 if len(rets[rets<=np.percentile(rets,1)])>0 else cvar95
    # Ulcer Index
    dds = []; pk = vals[0]
    for v in vals:
        if v>pk: pk=v
        dds.append((pk-v)/pk*100)
    ulcer = float(np.sqrt(np.mean(np.array(dds)**2)))
    # 胜率盈亏比
    wr = sum(1 for r in rets if r>0)/len(rets)*100
    aw = float(rets[rets>0].mean())*100 if sum(rets>0)>0 else 0
    al = abs(float(rets[rets<0].mean()))*100 if sum(rets<0)>0 else 1
    plr = aw/al if al>0 else 0
    return {"total_return":round(tr,2),"annual_return":round(ar,2),
        "max_drawdown":round(mdd,2),"max_dd_duration":max_dd_dur,
        "sharpe":round(sharpe,3),"sortino":round(sortino,3),
        "calmar":round(calmar,3),"var95":round(var95,3),"var99":round(var99,3),
        "cvar95":round(cvar95,3),"cvar99":round(cvar99,3),
        "ulcer":round(ulcer,3),"win_rate":round(wr,2),
        "profit_loss_ratio":round(plr,2),"final_value":round(vals[-1],2)}

# ═══ 基础回测 ═══
def run_backtest(df, strat_cls, tc, market_ok=None):
    """运行单策略回测，返回增强指标 + 交易列表 + 权益曲线"""
    from run_backtest import STRATS, Sig, ST
    if df.empty or len(df)<30: return None
    strat = strat_cls()
    if market_ok and hasattr(strat,'set_market_ok'): strat.set_market_ok(market_ok)
    sigs = strat.generate_signals(df, tc)
    cash, pos = IC, 0; trades = []; ec = []
    for _, row in df.iterrows():
        dt, pr = str(row["trade_date"]), float(row["close"])
        for sig in [s for s in sigs if s.date==dt]:
            if sig.signal_type=="buy" and pos==0:
                bp = pr*(1+SLIP); sh = int(cash/bp/100)*100
                if sh<=0: continue
                cost = sh*bp; cm = cost*COMM; cash -= (cost+cm); pos = sh
                trades.append({"date":dt,"dir":"buy","price":round(bp,2),"vol":sh,
                    "ret":0,"reason":sig.reason})
            elif sig.signal_type=="sell" and pos>0:
                sp = pr*(1-SLIP); amt = pos*sp; cm = amt*COMM
                prev_cost = trades[-1]["price"]*pos if trades else cost
                tr_ = (amt-prev_cost)/prev_cost
                cash += (amt-cm)
                trades.append({"date":dt,"dir":"sell","price":round(sp,2),"vol":pos,
                    "ret":round(tr_*100,2),"reason":sig.reason})
                pos = 0
        ec.append({"date":dt,"v":round(cash+pos*pr,2)})
    metrics = calc_risk_metrics(ec)
    if metrics:
        metrics["trades"] = trades; metrics["equity_curve"] = ec
        metrics["strategy"] = strat.name; metrics["ts_code"] = tc
    return metrics

# ═══ Walk-Forward 验证 ═══
def walk_forward(df, strat_cls, tc, train_days=244, test_days=60, market_ok=None):
    """滚动窗口 Walk-Forward 验证
    返回: {"is_metrics":..., "oos_metrics":..., "wf_ratio":...}
    """
    if df.empty or len(df) < train_days + test_days: return None
    df = df.sort_values("trade_date").reset_index(drop=True)
    all_oos_ec = []; all_is_ec = []
    start = 0
    while start + train_days + test_days <= len(df):
        train_df = df.iloc[start:start+train_days]
        test_df = df.iloc[start+train_days:start+train_days+test_days]
        # 样本内
        is_r = run_backtest(train_df, strat_cls, tc, market_ok)
        # 样本外
        oos_r = run_backtest(test_df, strat_cls, tc, market_ok)
        if is_r and oos_r:
            all_is_ec.append(is_r)
            all_oos_ec.append(oos_r)
        start += test_days
    if not all_is_ec or not all_oos_ec: return None
    # 汇总
    avg_is_sharpe = np.mean([r["sharpe"] for r in all_is_ec])
    avg_oos_sharpe = np.mean([r["sharpe"] for r in all_oos_ec])
    avg_is_ret = np.mean([r["total_return"] for r in all_is_ec])
    avg_oos_ret = np.mean([r["total_return"] for r in all_oos_ec])
    wf_ratio = avg_oos_sharpe / avg_is_sharpe if avg_is_sharpe != 0 else 0
    is_overfit = wf_ratio < 0.7  # 样本外Sharpe比样本内低30%以上
    return {
        "n_windows": len(all_is_ec),
        "avg_is_return": round(avg_is_ret, 2),
        "avg_oos_return": round(avg_oos_ret, 2),
        "avg_is_sharpe": round(avg_is_sharpe, 3),
        "avg_oos_sharpe": round(avg_oos_sharpe, 3),
        "wf_ratio": round(wf_ratio, 3),
        "is_overfit": is_overfit,
        "is_details": all_is_ec,
        "oos_details": all_oos_ec,
    }

# ═══ Monte Carlo 模拟 ═══
def monte_carlo(trades_list, n_sim=5000, initial_capital=IC):
    """Monte Carlo 模拟：打乱交易顺序，生成权益曲线分布
    trades_list: [{"ret": 5.2, ...}, ...]  每笔交易收益率(%)
    """
    if len(trades_list) < 5: return None
    trade_rets = np.array([t["ret"]/100 for t in trades_list if t["dir"]=="sell" and "ret" in t])
    if len(trade_rets) < 3: return None
    final_vals = []; max_dds = []; sharpes = []
    for _ in range(n_sim):
        shuffled = np.random.permutation(trade_rets)
        equity = initial_capital
        peak = equity; mdd = 0; eq_curve = [equity]
        for r in shuffled:
            equity *= (1 + r)
            eq_curve.append(equity)
            if equity > peak: peak = equity
            dd = (peak - equity) / peak * 100
            if dd > mdd: mdd = dd
        final_vals.append(equity)
        max_dds.append(mdd)
        # Sharpe from equity curve
        if len(eq_curve) > 2:
            rts = [(eq_curve[i]-eq_curve[i-1])/eq_curve[i-1] for i in range(1,len(eq_curve)) if eq_curve[i-1]>0]
            if len(rts)>1 and np.std(rts)>0:
                sharpes.append(np.mean(rts)/np.std(rts)*np.sqrt(244))
            else:
                sharpes.append(0)
        else:
            sharpes.append(0)
    fv = np.array(final_vals); md = np.array(max_dds); sh = np.array(sharpes)
    orig_ret = (np.prod(1+trade_rets)-1)*100
    mc_ret = (np.mean(fv)-initial_capital)/initial_capital*100
    return {
        "n_simulations": n_sim,
        "original_return": round(orig_ret, 2),
        "mc_median_return": round(np.median(fv)/initial_capital*100-100, 2),
        "mc_mean_return": round(mc_ret, 2),
        "mc_return_ci90": [round(np.percentile(fv/initial_capital*100-100, 5), 2),
                           round(np.percentile(fv/initial_capital*100-100, 95), 2)],
        "mc_median_mdd": round(np.median(md), 2),
        "mc_p95_mdd": round(np.percentile(md, 95), 2),
        "mc_p99_mdd": round(np.percentile(md, 99), 2),
        "mc_median_sharpe": round(float(np.median(sh)), 3),
        "mc_p95_sharpe": round(float(np.percentile(sh, 95)), 3),
        "ruin_prob": round(float(np.mean(fv < initial_capital*0.5))*100, 2),
        "positive_prob": round(float(np.mean(fv > initial_capital))*100, 2),
        "original_vs_median": round(orig_ret - (np.median(fv)/initial_capital*100-100), 2),
    }

# ═══ 组合级回测 ═══
def portfolio_backtest(all_results, n_stocks=8, equal_weight=True):
    """组合级分析：等权分配资金到N只股票
    all_results: {stock_code: {strategy_key: result_dict}}
    """
    # 每只股票选最优策略
    best = {}
    for sc, sdict in all_results.items():
        br, bk = -999, ""
        for sk, r in sdict.items():
            if isinstance(r, dict) and "total_return" in r and r["total_return"] > br:
                br = r["total_return"]; bk = sk
        if bk: best[sc] = (bk, sdict[bk])

    if not best: return None
    per_stock_cap = IC / len(best)
    port_ec = defaultdict(float)
    port_trades = []
    for sc, (sk, r) in best.items():
        if "equity_curve" not in r: continue
        for e in r["equity_curve"]:
            port_ec[e["date"]] += e["v"] / IC * per_stock_cap
        if "trades" in r:
            for t in r["trades"]:
                t2 = t.copy(); t2["stock"] = sc; t2["strategy"] = sk
                port_trades.append(t2)

    dates = sorted(port_ec.keys())
    vals = [port_ec[d] for d in dates]
    ec = [{"date": d, "v": round(port_ec[d], 2)} for d in dates]
    metrics = calc_risk_metrics(ec) if len(ec) > 10 else {}
    if metrics: metrics["portfolio_trades"] = port_trades

    # 相关性矩阵
    corr_data = {}
    for sc, (sk, r) in best.items():
        if "equity_curve" not in r: continue
        vals_s = {e["date"]: e["v"] for e in r["equity_curve"]}
        corr_data[STOCKS.get(sc, sc)] = vals_s

    corr_matrix = None
    if len(corr_data) >= 2:
        cdf = pd.DataFrame(corr_data)
        ret_df = cdf.pct_change().dropna()
        corr_matrix = ret_df.corr().round(3).to_dict()

    return {
        "n_stocks": len(best),
        "per_stock_capital": round(per_stock_cap, 0),
        "best_per_stock": {STOCKS.get(sc, sc): sk for sc, (sk, _) in best.items()},
        "portfolio_metrics": metrics,
        "correlation_matrix": corr_matrix,
    }

# ═══ 主流程 ═══
def main():
    from run_backtest import STRATS
    ts.set_token(TOKEN)
    print("═"*60)
    print("  QuantWeave 专业级回测引擎 v3.0")
    print("  Walk-Forward + Monte Carlo + 组合分析 + 增强指标")
    print("═"*60)

    # 1. 获取数据
    print("\n📡 获取数据（2023-01-01 ~ 2025-04-10）...")
    all_data = {}
    market_ok = None
    for sc, sn in STOCKS.items():
        df = fetch(sc, "2023-01-01", "2025-04-10")
        if not df.empty:
            all_data[sc] = df
            print(f"  ✅ {sn}: {len(df)}条")
    # 大盘过滤
    idx_df = fetch("000001.SH", "2023-01-01", "2025-04-10")
    if not idx_df.empty:
        idx_ma20 = idx_df["close"].rolling(20).mean()
        market_ok = set(idx_df[idx_df["close"]>idx_ma20]["trade_date"].astype(str).tolist())

    # 2. 全量回测（使用增强指标）
    print("\n📊 阶段一：全量增强回测（9策略×8股票）...")
    all_results = {}
    for sc, sn in STOCKS.items():
        df = all_data.get(sc)
        if df is None or df.empty: continue
        print(f"\n  📈 {sn}({sc})")
        sr = {}
        for sk, (sn2, cls) in STRATS.items():
            try:
                r = run_backtest(df, cls, sc, market_ok)
                if r:
                    tag = "🟢" if r["total_return"]>0 else "🔴"
                    print(f"    {tag} {sn2}: {r['total_return']:+.2f}% "
                          f"Sharpe={r['sharpe']:.3f} Sortino={r['sortino']:.3f} "
                          f"Calmar={r['calmar']:.3f} VaR95={r['var95']:.3f}%")
                    sr[sk] = r
            except Exception as e:
                print(f"    ❌ {sn2}: {e}")
        all_results[sc] = sr

    # 3. Walk-Forward 验证
    print("\n📊 阶段二：Walk-Forward 滚动验证...")
    wf_results = {}
    for sk, (sn, cls) in STRATS.items():
        print(f"\n  🔄 {sn} Walk-Forward...")
        stock_wf = []
        for sc in list(STOCKS.keys())[:4]:  # 前4只股票做WF（节省时间）
            df = all_data.get(sc)
            if df is None: continue
            wf = walk_forward(df, cls, sc, train_days=244, test_days=60, market_ok=market_ok)
            if wf:
                stock_wf.append(wf)
                tag = "⚠️过拟合" if wf["is_overfit"] else "✅稳健"
                print(f"    {STOCKS[sc]}: IS={wf['avg_is_return']:+.1f}% OOS={wf['avg_oos_return']:+.1f}% "
                      f"IS_Sharpe={wf['avg_is_sharpe']:.2f} OOS_Sharpe={wf['avg_oos_sharpe']:.2f} "
                      f"WF比={wf['wf_ratio']:.2f} {tag}")
        if stock_wf:
            avg_wf_ratio = np.mean([w["wf_ratio"] for w in stock_wf])
            wf_results[sk] = {
                "strategy": sn,
                "avg_wf_ratio": round(avg_wf_ratio, 3),
                "is_overfit": avg_wf_ratio < 0.7,
                "details": stock_wf,
            }

    # 4. Monte Carlo 模拟
    print("\n📊 阶段三：Monte Carlo 稳健性检验（5000次模拟）...")
    mc_results = {}
    for sc, sr in all_results.items():
        for sk, r in sr.items():
            if "trades" not in r: continue
            sells = [t for t in r["trades"] if t["dir"]=="sell"]
            if len(sells) < 5: continue
            mc = monte_carlo(sells, n_sim=5000)
            if mc:
                key = f"{sc}_{sk}"
                mc_results[key] = mc
                sn = STOCKS.get(sc, sc)
                sn2 = STRATS[sk][0] if sk in STRATS else sk
                print(f"  {sn}|{sn2}: MC中位收益={mc['mc_median_return']:+.1f}% "
                      f"P95回撤={mc['mc_p95_mdd']:.1f}% 正收益概率={mc['positive_prob']:.0f}% "
                      f"破产概率={mc['ruin_prob']:.1f}%")

    # 5. 组合级分析
    print("\n📊 阶段四：组合级分析...")
    from run_backtest import STRATS as _S
    port = portfolio_backtest(all_results)
    if port:
        pm = port.get("portfolio_metrics", {})
        print(f"  组合收益: {pm.get('total_return','N/A')}%")
        print(f"  组合Sharpe: {pm.get('sharpe','N/A')}")
        print(f"  组合Sortino: {pm.get('sortino','N/A')}")
        print(f"  组合最大回撤: {pm.get('max_drawdown','N/A')}%")
        if port.get("correlation_matrix"):
            print("  相关系数矩阵:")
            for k1, row in port["correlation_matrix"].items():
                vals_str = " ".join([f"{v:.2f}" for k2, v in row.items()])
                print(f"    {k1}: {vals_str}")

    # 6. 汇总输出
    print("\n📊 阶段五：汇总评分...")
    final_scores = {}
    for sk, (sn, _) in STRATS.items():
        stock_rets = [all_results[sc][sk]["total_return"] for sc in all_results
                      if sk in all_results[sc] and "total_return" in all_results[sc][sk]]
        wf = wf_results.get(sk, {})
        mc_keys = [k for k in mc_results if k.endswith(f"_{sk}")]
        avg_mc_pos = np.mean([mc_results[k]["positive_prob"] for k in mc_keys]) if mc_keys else 0
        avg_mc_mdd = np.mean([mc_results[k]["mc_p95_mdd"] for k in mc_keys]) if mc_keys else 0

        if not stock_rets: continue
        score = {
            "strategy": sn,
            "avg_return": round(np.mean(stock_rets), 2),
            "positive_rate": round(sum(1 for r in stock_rets if r>0)/len(stock_rets)*100, 1),
            "wf_ratio": wf.get("avg_wf_ratio", "N/A"),
            "is_overfit": wf.get("is_overfit", "N/A"),
            "mc_positive_prob": round(avg_mc_pos, 1),
            "mc_p95_mdd": round(avg_mc_mdd, 1),
        }
        # 综合评分: 收益40% + 稳健(WF)30% + MC正概率20% + 正收益比例10%
        robust = score["wf_ratio"] if isinstance(score["wf_ratio"], (int, float)) else 0.5
        composite = (np.mean(stock_rets)/50*40 +
                    max(0, min(1, robust))*30 +
                    avg_mc_pos/100*20 +
                    score["positive_rate"]/100*10)
        score["composite_score"] = round(composite, 1)
        final_scores[sk] = score
        print(f"  {sn}: 综合={composite:.1f} 均收益={score['avg_return']:+.1f}% "
              f"WF比={score['wf_ratio']} MC正概率={score['mc_positive_prob']:.0f}%")

    # 排序
    ranked = sorted(final_scores.items(), key=lambda x: x[1]["composite_score"], reverse=True)
    print("\n  🏆 策略排名:")
    for i, (sk, s) in enumerate(ranked, 1):
        print(f"    {i}. {s['strategy']}: {s['composite_score']}分 "
              f"(均收益{s['avg_return']:+.1f}% WF={s['wf_ratio']})")

    # 7. 保存结果
    output = {
        "generated_at": datetime.datetime.now().isoformat(),
        "period": "2023-01-01 ~ 2025-04-10",
        "initial_capital": IC,
        "stocks": STOCKS,
        "backtest_results": {sc: {sk: {k:v for k,v in r.items() if k not in ["trades","equity_curve"]}
                                   for sk, r in sr.items() if isinstance(r, dict)}
                            for sc, sr in all_results.items()},
        "walk_forward": {sk: {k:v for k,v in r.items() if k!="details"} for sk, r in wf_results.items()},
        "monte_carlo": mc_results,
        "portfolio": {k:v for k,v in port.items() if k!="portfolio_trades"} if port else None,
        "strategy_ranking": [{"rank":i+1, **s} for i,(sk,s) in enumerate(ranked)],
    }
    jp = os.path.join(os.path.dirname(__file__) or ".", "advanced_results.json")
    with open(jp, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n📄 结果已保存 → {jp}")

    # 同时保存完整数据（含权益曲线）给报告用
    full_output = {"all_results": {}, "wf_results": wf_results,
                   "mc_results": mc_results, "portfolio": port, "ranking": ranked}
    for sc, sr in all_results.items():
        full_output["all_results"][sc] = {}
        for sk, r in sr.items():
            r2 = {k:v for k,v in r.items()}
            if "equity_curve" in r2:
                # 降采样权益曲线（每5天一个点，节省体积）
                ec = r2["equity_curve"]
                r2["equity_curve"] = ec[::5] + [ec[-1]] if len(ec)>10 else ec
            full_output["all_results"][sc][sk] = r2
    fp = os.path.join(os.path.dirname(__file__) or ".", "advanced_full_data.json")
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(full_output, f, ensure_ascii=False, indent=2, default=str)
    print(f"📄 完整数据 → {fp}")
    return output

if __name__ == "__main__":
    import datetime
    main()
