#!/usr/bin/env python3
"""QuantWeave 策略参数网格搜索 - 找最优参数组合"""
import json, os, datetime, itertools
import numpy as np, pandas as pd, tushare as ts
from enum import Enum

# ===== Config =====
TS_TOKEN = os.environ.get("TUSHARE_TOKEN", "REDACTED_TUSHARE_TOKEN")
ts.set_token(TS_TOKEN)
pro = ts.pro_api()

STOCKS = {
    "600519.SH": "贵州茅台", "000858.SZ": "五粮液", "601318.SH": "中国平安",
    "600036.SH": "招商银行", "000001.SZ": "平安银行", "000333.SZ": "美的集团",
    "000651.SZ": "格力电器", "601398.SH": "工商银行",
}
START, END = "20230101", "20250410"
INIT_CASH = 1000000
COMM = 0.001
RESULTS_DIR = "grid_results"

class ST(str, Enum):
    BUY="buy"; SELL="sell"

class Sig:
    def __init__(self, t, code, price, reason="", date=""):
        self.signal_type=t; self.ts_code=code; self.price=price
        self.reason=reason; self.date=date

# ===== Strategy Base =====
class Base:
    name=""; params={}
    def __init__(self, p=None):
        if p: self.params={**self.params,**p}

# ===== Strategies =====
class DualMA(Base):
    name="双均线交叉"
    def generate_signals(self, df, tc=""):
        sp=self.params.get("sp",5); lp=self.params.get("lp",20)
        df=df.sort_values("trade_date").copy()
        df["ms"]=df["close"].rolling(sp).mean(); df["ml"]=df["close"].rolling(lp).mean()
        sigs=[]
        for i in range(1,len(df)):
            p,c=df.iloc[i-1],df.iloc[i]
            if pd.isna(c["ms"]) or pd.isna(c["ml"]): continue
            if p["ms"]<=p["ml"] and c["ms"]>c["ml"]:
                sigs.append(Sig(ST.BUY,tc,float(c["close"]),f"MA{sp}上穿MA{lp}",str(c["trade_date"])))
            elif p["ms"]>=p["ml"] and c["ms"]<c["ml"]:
                sigs.append(Sig(ST.SELL,tc,float(c["close"]),f"MA{sp}下穿MA{lp}",str(c["trade_date"])))
        return sigs

class Bollinger(Base):
    name="布林带突破"
    def generate_signals(self, df, tc=""):
        p=self.params.get("p",20); sd=self.params.get("sd",2.0)
        df=df.sort_values("trade_date").copy()
        df["mid"]=df["close"].rolling(p).mean(); df["std"]=df["close"].rolling(p).std()
        df["up"]=df["mid"]+sd*df["std"]; df["lo"]=df["mid"]-sd*df["std"]
        sigs=[]
        for i in range(1,len(df)):
            pv,c=df.iloc[i-1],df.iloc[i]
            if pd.isna(c["lo"]): continue
            if pv["close"]>pv["lo"] and c["close"]<=c["lo"]:
                sigs.append(Sig(ST.BUY,tc,float(c["close"]),"下轨买入",str(c["trade_date"])))
            elif pv["close"]<pv["up"] and c["close"]>=c["up"]:
                sigs.append(Sig(ST.SELL,tc,float(c["close"]),"上轨卖出",str(c["trade_date"])))
        return sigs

class RSI(Base):
    name="RSI超买超卖"
    def generate_signals(self, df, tc=""):
        p=self.params.get("p",14); ob=self.params.get("ob",70); os_=self.params.get("os",30)
        df=df.sort_values("trade_date").copy()
        delta=df["close"].diff()
        gain=delta.clip(lower=0); loss=(-delta).clip(lower=0)
        avg_g=gain.ewm(alpha=1/p,adjust=False).mean()
        avg_l=loss.ewm(alpha=1/p,adjust=False).mean()
        rs=avg_g/avg_l; df["rsi"]=100-(100/(1+rs))
        sigs=[]
        for i in range(1,len(df)):
            pv,c=df.iloc[i-1],df.iloc[i]
            if pd.isna(c["rsi"]): continue
            if pv["rsi"]<=os_ and c["rsi"]>os_:
                sigs.append(Sig(ST.BUY,tc,float(c["close"]),f"RSI上穿{os_}",str(c["trade_date"])))
            elif pv["rsi"]>=ob and c["rsi"]<ob:
                sigs.append(Sig(ST.SELL,tc,float(c["close"]),f"RSI下穿{ob}",str(c["trade_date"])))
        return sigs

class MACD(Base):
    name="MACD金叉死叉"
    def generate_signals(self, df, tc=""):
        f=self.params.get("fast",12); s=self.params.get("slow",26); sig=self.params.get("signal",9)
        df=df.sort_values("trade_date").copy()
        ema_f=df["close"].ewm(span=f,adjust=False).mean()
        ema_s=df["close"].ewm(span=s,adjust=False).mean()
        dif=ema_f-ema_s; dea=dif.ewm(span=sig,adjust=False).mean(); hist=2*(dif-dea)
        sigs=[]
        for i in range(1,len(df)):
            pv,c=df.iloc[i-1],df.iloc[i]
            if pd.isna(hist.iloc[i]): continue
            if dif.iloc[i-1]<=dea.iloc[i-1] and dif.iloc[i]>dea.iloc[i]:
                sigs.append(Sig(ST.BUY,tc,float(c["close"]),"MACD金叉",str(c["trade_date"])))
            elif dif.iloc[i-1]>=dea.iloc[i-1] and dif.iloc[i]<dea.iloc[i]:
                sigs.append(Sig(ST.SELL,tc,float(c["close"]),"MACD死叉",str(c["trade_date"])))
        return sigs

# ===== Backtest Engine =====
def run_backtest(strategy, df, tc, cash=INIT_CASH, commission=COMM):
    # Sort data ascending by date first!
    df = df.sort_values("trade_date").copy().reset_index(drop=True)
    signals = strategy.generate_signals(df, tc)
    if not signals: return None
    position=0; cash_left=cash; trades=[]; peak_val=cash
    max_dd=0; equity_curve=[]
    for sig in signals:
        price=sig.price*(1+commission) if sig.signal_type==ST.BUY else sig.price*(1-commission)
        if sig.signal_type==ST.BUY and position==0:
            shares=int(cash_left/price/100)*100
            if shares<=0: continue
            cost=shares*price; cash_left-=cost; position=shares
            trades.append({"date":sig.date,"action":"buy","price":sig.price,"shares":shares,"reason":sig.reason})
        elif sig.signal_type==ST.SELL and position>0:
            revenue=position*price; cash_left+=revenue
            trades.append({"date":sig.date,"action":"sell","price":sig.price,"shares":position,"reason":sig.reason})
            position=0
        val=cash_left+position*sig.price
        if val>peak_val: peak_val=val
        dd=(peak_val-val)/peak_val
        if dd>max_dd: max_dd=dd
        equity_curve.append({"date":sig.date,"value":val})
    final_val=cash_left+(position*df.iloc[-1]["close"]*(1-commission) if position>0 else 0)
    total_ret=(final_val-cash)/cash
    days=(pd.Timestamp(df.iloc[-1]["trade_date"])-pd.Timestamp(df.iloc[0]["trade_date"])).days
    ann_ret=(1+total_ret)**(365/max(days,1))-1 if total_ret>-1 else -1
    wins=[t for i,t in enumerate(trades) if t["action"]=="sell" and i>0]
    win_trades=sum(1 for i,t in enumerate(wins) if trades[trades.index(t)-1]["price"]<t["price"]) if wins else 0
    win_rate=win_trades/len(wins) if wins else 0
    # Simplified risk-adjusted metric: return / max(drawdown, 5%)
    sharpe = ann_ret / max(max_dd, 0.05)
    return {
        "total_return":round(total_ret*100,2),"annual_return":round(ann_ret*100,2),
        "max_drawdown":round(max_dd*100,2),"sharpe_ratio":round(sharpe,3),
        "win_rate":round(win_rate*100,2),"trades":len([t for t in trades if t["action"]=="sell"]),
        "final_value":round(final_val,0),"params":str(strategy.params),
    }

# ===== Grid Search =====
PARAM_GRIDS = {
    "双均线交叉": {"class": DualMA, "grid": {
        "sp": [3,5,8,10,15], "lp": [15,20,30,40,60]
    }},
    "布林带突破": {"class": Bollinger, "grid": {
        "p": [10,15,20,25,30], "sd": [1.5,2.0,2.5,3.0]
    }},
    "RSI超买超卖": {"class": RSI, "grid": {
        "p": [6,9,12,14,21], "ob": [65,70,75,80], "os": [20,25,30,35]
    }},
    "MACD金叉死叉": {"class": MACD, "grid": {
        "fast": [8,10,12,15], "slow": [20,26,30,35], "signal": [7,9,11,13]
    }},
}

def grid_search():
    os.makedirs(RESULTS_DIR, exist_ok=True)
    # Load data
    all_data = {}
    for code, name in STOCKS.items():
        try:
            df = pro.daily(ts_code=code, start_date=START, end_date=END)
            if df is not None and len(df) > 60:
                all_data[code] = df
                print(f"  数据: {name} {len(df)}天")
        except Exception as e:
            print(f"  跳过: {name} {e}")
    
    all_results = {}
    for strat_name, config in PARAM_GRIDS.items():
        print(f"\n{'='*50}")
        print(f"网格搜索: {strat_name}")
        print(f"{'='*50}")
        
        grid = config["grid"]
        keys = list(grid.keys())
        values = list(grid.values())
        combos = list(itertools.product(*values))
        
        best_score = -999
        best_params = None
        best_detail = None
        all_combos = []
        
        for combo in combos:
            params = dict(zip(keys, combo))
            # Skip invalid combos
            if "sp" in params and "lp" in params and params["sp"] >= params["lp"]: continue
            if "fast" in params and "slow" in params and params["fast"] >= params["slow"]: continue
            
            strategy = config["class"](params)
            stock_results = []
            for code, df in all_data.items():
                r = run_backtest(strategy, df, code)
                if r: stock_results.append({"code": code, "name": STOCKS[code], **r})
            
            if not stock_results: continue
            
            avg_ret = np.mean([s["total_return"] for s in stock_results])
            avg_sharpe = np.mean([s["sharpe_ratio"] for s in stock_results])
            avg_dd = np.mean([s["max_drawdown"] for s in stock_results])
            avg_wr = np.mean([s["win_rate"] for s in stock_results])
            positive_rate = sum(1 for s in stock_results if s["total_return"] > 0) / len(stock_results)
            
            # Composite score: 收益 + 夏普*5 + 胜率 + 正比例*20 - 回撤
            score = avg_ret + avg_sharpe * 5 + avg_wr * 0.2 + positive_rate * 20 - avg_dd * 0.5
            
            combo_result = {
                "params": params, "avg_return": round(avg_ret, 2),
                "avg_sharpe": round(avg_sharpe, 3), "avg_drawdown": round(avg_dd, 2),
                "avg_win_rate": round(avg_wr, 2), "positive_rate": round(positive_rate*100, 1),
                "score": round(score, 2), "stocks": stock_results
            }
            all_combos.append(combo_result)
            
            if score > best_score:
                best_score = score
                best_params = params
                best_detail = combo_result
        
        # Sort by score
        all_combos.sort(key=lambda x: x["score"], reverse=True)
        all_results[strat_name] = {
            "best_params": best_params,
            "best_score": best_score,
            "best_detail": best_detail,
            "top10": all_combos[:10],
            "total_combos": len(all_combos)
        }
        
        print(f"\n最优参数: {best_params}")
        print(f"综合得分: {best_score:.2f}")
        print(f"平均收益: {best_detail['avg_return']:.2f}%")
        print(f"平均夏普: {best_detail['avg_sharpe']:.3f}")
        print(f"胜率: {best_detail['avg_win_rate']:.1f}%")
        print(f"正收益比例: {best_detail['positive_rate']:.0f}%")
        print(f"\nTop 5 参数组合:")
        for i, c in enumerate(all_combos[:5]):
            print(f"  #{i+1} {c['params']} → 收益:{c['avg_return']:+.2f}% 夏普:{c['avg_sharpe']:.3f} 得分:{c['score']:.2f}")
    
    # Save
    with open(os.path.join(RESULTS_DIR, "grid_search_results.json"), "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2, default=str)
    
    # Summary
    print(f"\n\n{'='*60}")
    print(f"网格搜索总结")
    print(f"{'='*60}")
    for name, res in all_results.items():
        bp = res["best_params"]
        bd = res["best_detail"]
        print(f"\n{name}:")
        print(f"  最优参数: {bp}")
        print(f"  平均收益: {bd['avg_return']:+.2f}% | 夏普: {bd['avg_sharpe']:.3f} | 回撤: {bd['avg_drawdown']:.2f}%")
        print(f"  正收益比例: {bd['positive_rate']:.0f}% | 搜索组合数: {res['total_combos']}")
    
    return all_results

if __name__ == "__main__":
    results = grid_search()
    print(f"\n结果已保存到 {RESULTS_DIR}/grid_search_results.json")
