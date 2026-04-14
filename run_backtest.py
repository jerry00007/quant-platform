#!/usr/bin/env python3
"""QuantWeave 全策略回测 - 6策略×8股票"""
import json, os, datetime
import numpy as np, pandas as pd, tushare as ts
from enum import Enum

class ST(str, Enum):
    BUY="buy"; SELL="sell"

class Sig:
    def __init__(self, t, code, price, reason="", date=""):
        self.signal_type=t; self.ts_code=code; self.price=price
        self.reason=reason; self.date=date

class Base:
    name=""; params={}
    def __init__(self, p=None):
        if p: self.params={**self.params,**p}

class DualMA(Base):
    name="双均线交叉"; params={"sp":5,"lp":40}  # 网格搜索最优
    def generate_signals(self, df, tc=""):
        df=df.sort_values("trade_date").copy()
        s,l=self.params["sp"],self.params["lp"]
        df["ms"]=df["close"].rolling(s).mean(); df["ml"]=df["close"].rolling(l).mean()
        sigs=[]
        for i in range(1,len(df)):
            p,c=df.iloc[i-1],df.iloc[i]
            if pd.isna(c["ms"]) or pd.isna(c["ml"]): continue
            if p["ms"]<=p["ml"] and c["ms"]>c["ml"]:
                sigs.append(Sig(ST.BUY,tc,float(c["close"]),f"MA{s}上穿MA{l}",str(c["trade_date"])))
            elif p["ms"]>=p["ml"] and c["ms"]<c["ml"]:
                sigs.append(Sig(ST.SELL,tc,float(c["close"]),f"MA{s}下穿MA{l}",str(c["trade_date"])))
        return sigs

class Bollinger(Base):
    name="布林带突破"; params={"p":25,"sd":2.5}  # 网格搜索最优
    def generate_signals(self, df, tc=""):
        df=df.sort_values("trade_date").copy()
        p,sd=self.params["p"],self.params["sd"]
        df["mid"]=df["close"].rolling(p).mean(); df["std"]=df["close"].rolling(p).std()
        df["up"]=df["mid"]+sd*df["std"]; df["lo"]=df["mid"]-sd*df["std"]
        sigs=[]
        for i in range(1,len(df)):
            pv,c=df.iloc[i-1],df.iloc[i]
            if pd.isna(c["lo"]): continue
            if pv["close"]>pv["lo"] and c["close"]<=c["lo"]:
                sigs.append(Sig(ST.BUY,tc,float(c["close"]),"突破布林带下轨",str(c["trade_date"])))
            elif pv["close"]<pv["up"] and c["close"]>=c["up"]:
                sigs.append(Sig(ST.SELL,tc,float(c["close"]),"突破布林带上轨",str(c["trade_date"])))
        return sigs

class RSI(Base):
    name="RSI超买超卖"; params={"p":12,"os":25,"ob":80}  # 网格搜索最优
    def generate_signals(self, df, tc=""):
        df=df.sort_values("trade_date").copy()
        d=df["close"].diff(); g=d.where(d>0,0); lo=-d.where(d<0,0)
        ag=g.ewm(alpha=1.0/self.params["p"],adjust=False).mean()  # Wilder's EMA
        al=lo.ewm(alpha=1.0/self.params["p"],adjust=False).mean()
        df["rsi"]=100-(100/(1+ag/al))
        sigs=[]
        for i in range(1,len(df)):
            c=df.iloc[i]
            if pd.isna(c["rsi"]): continue
            if c["rsi"]<self.params["os"]:
                sigs.append(Sig(ST.BUY,tc,float(c["close"]),f"RSI={c['rsi']:.1f}",str(c["trade_date"])))
            elif c["rsi"]>self.params["ob"]:
                sigs.append(Sig(ST.SELL,tc,float(c["close"]),f"RSI={c['rsi']:.1f}",str(c["trade_date"])))
        return sigs

class MACD(Base):
    name="MACD金叉死叉"; params={"f":15,"s":26,"sp":13}  # 网格搜索最优
    def generate_signals(self, df, tc=""):
        df=df.sort_values("trade_date").copy()
        ef=df["close"].ewm(span=self.params["f"],adjust=False).mean()
        es=df["close"].ewm(span=self.params["s"],adjust=False).mean()
        df["dif"]=ef-es; df["dea"]=df["dif"].ewm(span=self.params["sp"],adjust=False).mean()
        sigs=[]
        for i in range(1,len(df)):
            pv,c=df.iloc[i-1],df.iloc[i]
            if pd.isna(c["dif"]) or pd.isna(c["dea"]): continue
            if pv["dif"]<=pv["dea"] and c["dif"]>c["dea"]:
                sigs.append(Sig(ST.BUY,tc,float(c["close"]),"MACD金叉",str(c["trade_date"])))
            elif pv["dif"]>=pv["dea"] and c["dif"]<c["dea"]:
                sigs.append(Sig(ST.SELL,tc,float(c["close"]),"MACD死叉",str(c["trade_date"])))
        return sigs

def _tdx_sma(x,n,m):
    y=np.empty(len(x));y[0]=x[0]
    for i in range(1,len(x)):y[i]=(m*x[i]+(n-m)*y[i-1])/n
    return y

def _barslast_high(z,n):
    r=np.full(len(z),np.nan)
    for i in range(len(z)):
        s=max(0,i-n+1);w=z[s:i+1]
        if len(w)==0 or np.any(np.isnan(w)):continue
        mv=np.max(w)
        for j in range(len(w)-1,-1,-1):
            if not np.isnan(w[j]) and w[j]==mv:r[i]=len(w)-1-j;break
    return r

def _calc_zlcmq(close,high,low):
    c,h,lo=close.values.astype(float),high.values.astype(float),low.values.astype(float)
    v5=pd.Series(lo).rolling(75,min_periods=1).min().values
    v6=pd.Series(h).rolling(75,min_periods=1).max().values
    v7=(v6-v5)/100.0
    raw=np.where(v7>1e-10,(c-v5)/v7,0.0); raw=np.nan_to_num(raw,nan=0.0)
    v8=_tdx_sma(raw,20,1); v8s=_tdx_sma(v8,15,1)
    return pd.Series(100.0-(3.0*v8-2.0*v8s),index=close.index)

class Chip(Base):
    name="主力筹码"; params={"nd":5,"mh":98,"mf":5,"sl":-0.08,"tp":0.15,"ce":15}
    def __init__(self,p=None):
        super().__init__(p); self.pos=None; self.ep=None
    def generate_signals(self,df,tc=""):
        if df.empty or len(df)<80:return[]
        df=df.sort_values("trade_date").copy()
        cl,op=df["close"],df["open"]; zq=_calc_zlcmq(cl,df["high"],df["low"])
        nd,mh,mf,sl,tp,ce=self.params["nd"],self.params["mh"],self.params["mf"],self.params["sl"],self.params["tp"],self.params["ce"]
        zh=zq.rolling(nd,min_periods=1).max(); wh=zh>=mh
        c95=(zq.shift(1)>=95)&(zq<95)
        hb=_barslast_high(zq.values,nd); fv=zh-zq
        ff=(hb>=2)&(hb<=nd-1)&(fv>=mf)
        st=(cl>op)|(cl>cl.shift(1)); bc=wh&c95&ff&st
        self.pos=None;self.ep=None;sigs=[]
        for i in range(75,len(df)):
            r=df.iloc[i];p=cl.iloc[i];z=zq.iloc[i]
            if self.pos is None:
                if bc.iloc[i]:
                    sigs.append(Sig(ST.BUY,tc,float(p),f"筹码高位回落企稳ZLCMQ={z:.1f}",str(r["trade_date"])))
                    self.pos="buy";self.ep=p
            else:
                pnl=(p-self.ep)/self.ep;sell=False;rsn=""
                if pnl<=sl:sell,rsn=True,f"止损{pnl*100:+.1f}%"
                elif pnl>=tp:sell,rsn=True,f"止盈{pnl*100:+.1f}%"
                elif not np.isnan(z) and z<ce:sell,rsn=True,f"筹码极度分散ZLCMQ={z:.1f}"
                if sell:
                    sigs.append(Sig(ST.SELL,tc,float(p),rsn,str(r["trade_date"])))
                    self.pos=None;self.ep=None
        return sigs

class EChip(Base):
    name="增强筹码"; params={"nd":5,"mh":98,"mf":5,"atrm":2.5,"tp":0.20,"ce":15,
        "vsm":1.5,"tmap":60,"tps":0.10,"tam":1.5}
    def __init__(self,p=None):
        super().__init__(p);self.pos=None;self.ep=None;self.ts_=None
    def generate_signals(self,df,tc=""):
        if df.empty or len(df)<80:return[]
        df=df.sort_values("trade_date").copy()
        cl,op=df["close"],df["open"]
        vol=df["vol"] if "vol" in df.columns else pd.Series(0,index=df.index)
        zq=_calc_zlcmq(cl,df["high"],df["low"])
        va=vol.rolling(20,min_periods=1).mean(); vs=vol>va*self.params["vsm"]
        mt=cl.rolling(self.params["tmap"],min_periods=1).mean(); tok=cl>mt*0.98
        nd=self.params["nd"]
        zh=zq.rolling(nd,min_periods=1).max(); wh=zh>=self.params["mh"]
        c95=(zq.shift(1)>=95)&(zq<95)
        hb=_barslast_high(zq.values,nd); fv=zh-zq
        ff=(hb>=2)&(hb<=nd-1)&(fv>=self.params["mf"])
        st=(cl>op)|(cl>cl.shift(1)); bc=wh&c95&ff&st&vs&tok
        tr1=df["high"]-df["low"]; tr2=np.abs(df["high"]-cl.shift(1))
        tr3=np.abs(df["low"]-cl.shift(1))
        tr=pd.concat([tr1,tr2,tr3],axis=1).max(axis=1); atr=tr.rolling(14).mean()
        astop=atr*self.params["atrm"]; atrail=atr*self.params["tam"]
        self.pos=None;self.ep=None;self.ts_=None;sigs=[]
        for i in range(75,len(df)):
            r=df.iloc[i];p=cl.iloc[i];z=zq.iloc[i]
            zp=zq.iloc[i-1] if i>0 else np.nan
            if self.pos is None:
                if bc.iloc[i]:
                    self.ts_=p-atrail.iloc[i]
                    sigs.append(Sig(ST.BUY,tc,float(p),f"筹码+放量+趋势ZLCMQ={z:.1f}",str(r["trade_date"])))
                    self.pos="buy";self.ep=p
            else:
                pnl=(p-self.ep)/self.ep;sell=False;rsn=""
                if p<=(self.ep-astop.iloc[i]):sell,rsn=True,f"ATR止损{pnl*100:+.1f}%"
                elif pnl>self.params["tps"]:
                    self.ts_=max(self.ts_,p-atrail.iloc[i])
                    if p<=self.ts_:sell,rsn=True,f"移动止盈{pnl*100:+.1f}%"
                elif pnl>=self.params["tp"]:sell,rsn=True,f"止盈{pnl*100:+.1f}%"
                elif (not np.isnan(z) and not np.isnan(zp) and z<self.params["ce"] and zp<self.params["ce"]):
                    sell,rsn=True,f"筹码极度分散ZLCMQ={z:.1f}"
                if sell:
                    sigs.append(Sig(ST.SELL,tc,float(p),rsn,str(r["trade_date"])))
                    self.pos=None;self.ep=None;self.ts_=None
        return sigs

class PullbackStable(Base):
    """强势股首次回调企稳 - 改良版（通达信公式迁移）
    核心：强势股从高位快速回落后，出现缩量企稳信号
    买入: ZLCMQ高位回落 + 5选3企稳条件 + 大盘20日线上方
    卖出: 止损-8% / 止盈+15% / 盈利>10%后5%移动止盈
    """
    name="强势股回调企稳"
    params={"n_days":8,"high_level":92,"fall_min":3,"vol_shrink":0.7,
            "sl":-0.08,"tp":0.15,"trail_start":0.10,"trail_pct":0.05}
    def __init__(self,p=None):
        super().__init__(p);self.pos=None;self.ep=None;self.tstop=None
        self.market_ok_dates=None
    def set_market_ok(self,dates_set):
        self.market_ok_dates=dates_set
    def generate_signals(self,df,tc=""):
        if df.empty or len(df)<80:return[]
        df=df.sort_values("trade_date").copy()
        cl,op,lo,hi=df["close"],df["open"],df["low"],df["high"]
        vol=df["vol"] if "vol" in df.columns else pd.Series(0,index=df.index)
        zq=_calc_zlcmq(cl,hi,lo)
        nd=self.params["n_days"];hl=self.params["high_level"]
        fm=self.params["fall_min"];vs=self.params["vol_shrink"]
        # 高位判断: N天内ZLCMQ最高值 >= HIGH_LEVEL
        zq_max=zq.rolling(nd,min_periods=1).max()
        was_high=zq_max>=hl
        # 回落幅度
        fall_value=zq_max-zq
        has_fall=fall_value>=fm
        # 企稳条件（5选3）
        s1=(cl>op).astype(int)                          # 真阳线
        s2=(cl>cl.shift(1)).astype(int)                  # 收盘高于昨日
        s3=(lo>lo.shift(1)).astype(int)                  # 低点抬高
        s4=(vol<vol.shift(1)*vs).astype(int)             # 缩量
        s5=(cl>cl.rolling(5,min_periods=1).mean()).astype(int)  # 站上5日线
        stable_count=s1+s2+s3+s4+s5
        is_stable=stable_count>=3
        # 买入条件
        buy_cond=was_high&has_fall&is_stable
        self.pos=None;self.ep=None;self.tstop=None;sigs=[]
        for i in range(75,len(df)):
            r=df.iloc[i];p=cl.iloc[i];z=zq.iloc[i]
            dt=str(r["trade_date"])
            # 大盘过滤: 非市场OK日不开新仓
            if self.market_ok_dates is not None and dt not in self.market_ok_dates:
                continue
            if self.pos is None:
                if buy_cond.iloc[i]:
                    sigs.append(Sig(ST.BUY,tc,float(p),
                        f"强势回调企稳 ZLCMQ={z:.1f} 企稳={int(stable_count.iloc[i])}项",dt))
                    self.pos="buy";self.ep=p;self.tstop=None
            else:
                pnl=(p-self.ep)/self.ep;sell=False;rsn=""
                if pnl<=self.params["sl"]:
                    sell=True;rsn=f"止损{pnl*100:+.1f}%"
                elif pnl>=self.params["tp"]:
                    sell=True;rsn=f"止盈{pnl*100:+.1f}%"
                elif pnl>self.params["trail_start"]:
                    trail_price=p*(1-self.params["trail_pct"])
                    if self.tstop is None or trail_price>self.tstop:
                        self.tstop=trail_price
                    if p<=self.tstop:
                        sell=True;rsn=f"移动止盈{pnl*100:+.1f}%"
                if sell:
                    sigs.append(Sig(ST.SELL,tc,float(p),rsn,dt))
                    self.pos=None;self.ep=None;self.tstop=None
        return sigs

TOKEN="f7ab0774ef145a98c1d7e6e31d78b13759fb547fc9b0d38c8824f821"
IC=1_000_000; COMM=0.0003; SLIP=0.001
SD="2024-01-01"; ED="2025-04-10"
STOCKS={"600519.SH":"贵州茅台","000858.SZ":"五粮液","601318.SH":"中国平安",
    "600036.SH":"招商银行","000001.SZ":"平安银行","000333.SZ":"美的集团",
    "601398.SH":"工商银行","000651.SZ":"格力电器"}

# ===== 锋芒新策略 =====

class VolumeBreakout(Base):
    """爆量突破 — 锋芒爆点盈利系统
    低位横盘后爆量突破20日高点，换手率放大
    买入: 横盘20日 + 量>2倍均量 + 突破20日高点
    卖出: 止损-8% / 止盈+20% / 移动止盈(盈利>10%后回撤5%)
    """
    name="爆量突破(锋芒)"
    params={"box_days":20,"vol_mult":2.0,"sl":-0.08,"tp":0.20,"trail_start":0.10,"trail_pct":0.05}
    def __init__(self,p=None):
        super().__init__(p);self.pos=None;self.ep=None;self.tstop=None
    def generate_signals(self,df,tc=""):
        if df.empty or len(df)<30:return[]
        df=df.sort_values("trade_date").copy()
        cl=df["close"]; hi=df["high"]; vol=df["vol"] if "vol" in df.columns else pd.Series(0,index=df.index)
        bd=self.params["box_days"]; vm=self.params["vol_mult"]
        # 20日均线和均量
        ma20=cl.rolling(bd).mean(); avg_vol=vol.rolling(bd).mean()
        # 横盘判定: 20日波动率 < 15%
        ret20=cl.pct_change().rolling(bd).std()*np.sqrt(bd)
        is_box=ret20<0.15
        # 爆量: 今日量 > 2倍均量
        is_vol=vol>avg_vol*vm
        # 突破: 收盘突破20日最高价
        high20=hi.rolling(bd).max().shift(1)
        is_break=cl>high20
        # 买入条件
        buy_cond=is_box&is_vol&is_break
        # 价格也在20日均线上方
        buy_cond=buy_cond&(cl>ma20)
        self.pos=None;self.ep=None;self.tstop=None;sigs=[]
        for i in range(bd,len(df)):
            r=df.iloc[i];p=cl.iloc[i];dt=str(r["trade_date"])
            if self.pos is None:
                if buy_cond.iloc[i]:
                    sigs.append(Sig(ST.BUY,tc,float(p),
                        f"爆量突破 量比{vol.iloc[i]/max(avg_vol.iloc[i],1):.1f}",dt))
                    self.pos="buy";self.ep=p;self.tstop=None
            else:
                pnl=(p-self.ep)/self.ep;sell=False;rsn=""
                if pnl<=self.params["sl"]:
                    sell=True;rsn=f"止损{pnl*100:+.1f}%"
                elif pnl>=self.params["tp"]:
                    sell=True;rsn=f"止盈{pnl*100:+.1f}%"
                elif pnl>self.params["trail_start"]:
                    tp_=p*(1-self.params["trail_pct"])
                    if self.tstop is None or tp_>self.tstop:self.tstop=tp_
                    if p<=self.tstop:sell=True;rsn=f"移动止盈{pnl*100:+.1f}%"
                if sell:
                    sigs.append(Sig(ST.SELL,tc,float(p),rsn,dt))
                    self.pos=None;self.ep=None;self.tstop=None
        return sigs

class DragonFirstYin(Base):
    """龙头首阴反抽 — 锋芒爆点盈利系统
    连续涨停后首次收大阴线，次日低吸博弈反抽
    买入: 连续涨停≥2天后首阴(跌幅>3%)
    卖出: 止损-5% / 止盈+10% / 3日内保利
    """
    name="龙头首阴反抽(锋芒)"
    params={"limit_pct":0.095,"min_limits":2,"yin_pct":-0.03,"sl":-0.05,"tp":0.10,"max_hold":3}
    def __init__(self,p=None):
        super().__init__(p)
    def generate_signals(self,df,tc=""):
        if df.empty or len(df)<30:return[]
        df=df.sort_values("trade_date").copy()
        cl=df["close"]; op=df["open"]
        pct=df["pct_chg"] if "pct_chg" in df.columns else cl.pct_change()*100
        lp=self.params["limit_pct"]; ml=self.params["min_limits"]
        yp=self.params["yin_pct"]; mh=self.params["max_hold"]
        # 检测涨停: 涨幅 > 9.5%
        is_limit=pct>lp*100
        # 统计连续涨停天数
        limit_streak=pd.Series(0,index=df.index)
        streak=0
        for i in range(len(df)):
            if is_limit.iloc[i]:streak+=1;limit_streak.iloc[i]=streak
            else:streak=0
        # 首阴: 连续涨停≥N天后，当日收阴且跌幅>3%
        first_yin=(limit_streak.shift(1)>=ml)&(pct<yp*100)&(cl<op)
        # 次日买入信号
        buy_signal=first_yin.shift(1).fillna(False)
        sigs=[]
        pending_buy=None
        hold_days=0
        in_pos=False;ep=0
        for i in range(30,len(df)):
            r=df.iloc[i];p=cl.iloc[i];dt=str(r["trade_date"])
            if not in_pos and buy_signal.iloc[i]:
                sigs.append(Sig(ST.BUY,tc,float(p),"首阴次日低吸",dt))
                in_pos=True;ep=p;hold_days=0
            elif in_pos:
                hold_days+=1;pnl=(p-ep)/ep;sell=False;rsn=""
                if pnl<=self.params["sl"]:sell=True;rsn=f"止损{pnl*100:+.1f}%"
                elif pnl>=self.params["tp"]:sell=True;rsn=f"止盈{pnl*100:+.1f}%"
                elif hold_days>=mh:sell=True;rsn=f"持仓{mh}日保利{pnl*100:+.1f}%"
                if sell:
                    sigs.append(Sig(ST.SELL,tc,float(p),rsn,dt))
                    in_pos=False
        return sigs

class TrendMA(Base):
    """均线趋势跟踪 — 锋芒波段实战
    三阶段(酝势→起势→趋势)均线系统
    买入: MA5>MA10>MA20>MA30 多头排列首次形成(起势)
    卖出: 趋势保利(5均不破) + 浮动保利(盈利>5%后回撤3%)
    """
    name="均线趋势跟踪(锋芒)"
    params={"mas":[5,10,20,30],"sl":-0.05,"trail_start":0.05,"trail_pct":0.03}
    def __init__(self,p=None):
        super().__init__(p);self.pos=None;self.ep=None;self.tstop=None;self.prev_bull=False
    def generate_signals(self,df,tc=""):
        if df.empty or len(df)<40:return[]
        df=df.sort_values("trade_date").copy()
        cl=df["close"]; ms=self.params["mas"]
        # 计算均线
        for m in ms:df[f"ma{m}"]=cl.rolling(m).mean()
        # 多头排列: MA5>MA10>MA20>MA30
        bull=True
        for j in range(len(ms)-1):
            bull=bull&(df[f"ma{ms[j]}"]>df[f"ma{ms[j+1]}"])
        # 首次多头: 之前非多头，今天多头
        first_bull=bull&~bull.shift(1).fillna(False)
        self.pos=None;self.ep=None;self.tstop=None;self.prev_bull=False;sigs=[]
        for i in range(max(ms),len(df)):
            r=df.iloc[i];p=cl.iloc[i];dt=str(r["trade_date"])
            if self.pos is None:
                if first_bull.iloc[i]:
                    sigs.append(Sig(ST.BUY,tc,float(p),"均线起势(多头排列)",dt))
                    self.pos="buy";self.ep=p;self.tstop=None
            else:
                pnl=(p-self.ep)/self.ep;sell=False;rsn=""
                # 固定止损
                if pnl<=self.params["sl"]:sell=True;rsn=f"止损{pnl*100:+.1f}%"
                # 浮动保利: 盈利>5%后，回撤3%出局
                elif pnl>self.params["trail_start"]:
                    tp_=p*(1-self.params["trail_pct"])
                    if self.tstop is None or tp_>self.tstop:self.tstop=tp_
                    if p<=self.tstop:sell=True;rsn=f"浮动保利{pnl*100:+.1f}%"
                # 趋势保利: 5均线不破不卖(收盘破5均则出)
                elif not bull.iloc[i] and self.prev_bull:
                    sell=True;rsn=f"趋势破位{pnl*100:+.1f}%"
                self.prev_bull=bull.iloc[i]
                if sell:
                    sigs.append(Sig(ST.SELL,tc,float(p),rsn,dt))
                    self.pos=None;self.ep=None;self.tstop=None
        return sigs
STRATS={"dual_ma":("双均线交叉",DualMA),"bollinger":("布林带突破(优化)",Bollinger),
    "rsi":("RSI超买超卖(优化)",RSI),"macd":("MACD金叉死叉(优化)",MACD),
    "chip":("主力筹码",Chip),"enhanced_chip":("增强筹码",EChip),
    "pullback_stable":("强势股回调企稳",PullbackStable),
    "vol_breakout":("爆量突破(锋芒)",VolumeBreakout),
    "first_yin":("龙头首阴反抽(锋芒)",DragonFirstYin),
    "trend_ma":("均线趋势跟踪(锋芒)",TrendMA)}

def fetch(tc,s,e):
    pro=ts.pro_api(TOKEN)
    df=pro.daily(ts_code=tc,start_date=s.replace("-",""),end_date=e.replace("-",""),
        fields="ts_code,trade_date,open,high,low,close,vol,amount,pct_chg")
    if df is None or df.empty: return pd.DataFrame()
    df=df.sort_values("trade_date").reset_index(drop=True)
    df["trade_date"]=df["trade_date"].astype(str); df["vol"]=df["vol"].astype(float)*100
    return df

def backtest(df,cls,name,tc,extra_ctx=None):
    if df.empty or len(df)<30: return {"error":"数据不足"}
    strat=cls()
    if extra_ctx and hasattr(strat,'set_market_ok'): strat.set_market_ok(extra_ctx)
    sigs=strat.generate_signals(df,tc)
    cash, pos=IC, 0; trades=[]; ec=[]
    for i,row in df.iterrows():
        dt,pr=str(row["trade_date"]),float(row["close"])
        for sig in [s for s in sigs if s.date==dt]:
            if sig.signal_type==ST.BUY and pos==0:
                bp=pr*(1+SLIP); sh=int(cash/bp/100)*100
                if sh<=0:continue
                cost=sh*bp; cm=cost*COMM; cash-=(cost+cm); pos=sh
                trades.append({"date":dt,"dir":"buy","price":round(bp,2),"vol":sh,"amt":round(cost,2),"sig":sig.reason})
            elif sig.signal_type==ST.SELL and pos>0:
                sp=pr*(1-SLIP); amt=pos*sp; cm=amt*COMM
                pf=amt-trades[-1]["amt"] if trades else 0; cash+=(amt-cm)
                trades.append({"date":dt,"dir":"sell","price":round(sp,2),"vol":pos,"amt":round(amt,2),"pf":round(pf,2),"sig":sig.reason})
                pos=0
        tv=cash+pos*pr; ec.append({"date":dt,"v":round(tv,2)})
    fv=ec[-1]["v"] if ec else IC
    tr_=(fv-IC)/IC*100; d=len(df)
    ar=((1+tr_/100)**(244/max(d,1))-1)*100 if d>0 else 0
    vals=[e["v"] for e in ec]; pk=vals[0] if vals else IC; md=0
    for v in vals:
        if v>pk:pk=v
        dd=(pk-v)/pk*100
        if dd>md:md=dd
    rets=[(ec[i]["v"]-ec[i-1]["v"])/ec[i-1]["v"] for i in range(1,len(ec)) if ec[i-1]["v"]>0]
    sh=float(np.mean(rets)/np.std(rets)*np.sqrt(244)) if len(rets)>1 and np.std(rets)>0 else 0
    sells=[t for t in trades if t["dir"]=="sell" and "pf" in t]
    wins=[t for t in sells if t["pf"]>0]
    wr=len(wins)/len(sells)*100 if sells else 0
    aw=float(np.mean([t["pf"] for t in wins])) if wins else 0
    al=abs(float(np.mean([t["pf"] for t in sells if t["pf"]<=0]))) if sells else 1
    return {"strategy":name,"total_return":round(tr_,2),"annual_return":round(ar,2),
        "max_drawdown":round(md,2),"sharpe_ratio":round(sh,3),"win_rate":round(wr,2),
        "profit_loss_ratio":round(aw/al,2) if al>0 else 0,"total_trades":len(trades),
        "final_value":round(fv,2),"trades":trades,"equity_curve":ec}

def main():
    ts.set_token(TOKEN); ar={}
    # 获取上证指数数据，用于强势股回调企稳策略的大盘过滤
    market_ok=None
    try:
        idx_df=fetch("000001.SH",SD,ED)
        if not idx_df.empty:
            idx_ma20=idx_df["close"].rolling(20).mean()
            market_ok=set(idx_df[idx_df["close"]>idx_ma20]["trade_date"].astype(str).tolist())
            print(f"📊 大盘过滤: {len(market_ok)}/{len(idx_df)}天符合条件")
    except Exception as e:
        print(f"⚠️ 大盘数据获取失败(不影响其他策略): {e}")
    for sc,sn in STOCKS.items():
        print(f"\n📡 {sn}({sc})")
        df=fetch(sc,SD,ED)
        if df.empty: print("  ⚠️ 空数据"); continue
        print(f"  ✅ {len(df)}条 ({df['trade_date'].iloc[0]}~{df['trade_date'].iloc[-1]})")
        sr={}
        for sk,(sn2,cls) in STRATS.items():
            print(f"  🔄 {sn2}...",end=" ",flush=True)
            try:
                r=backtest(df,cls,sn2,sc,market_ok)
                if "error" in r: print(f"❌ {r['error']}")
                else:
                    e="🟢" if r["total_return"]>0 else "🔴"
                    print(f"{e} {r['total_return']:+.2f}% 夏普{r['sharpe_ratio']:.3f} 回撤{r['max_drawdown']:.1f}% {r['total_trades']}笔")
                sr[sk]=r
            except Exception as e:
                print(f"❌ {e}"); sr[sk]={"error":str(e)}
        ar[sc]=sr
    jp=os.path.join(os.path.dirname(__file__) or ".","backtest_results.json")
    with open(jp,"w",encoding="utf-8") as f: json.dump(ar,f,ensure_ascii=False,indent=2)
    print(f"\n📄 JSON → {jp}")
    for sc,sn in STOCKS.items():
        sr=ar.get(sc,{})
        br,bn=-999,""
        for sk,r in sr.items():
            if "error" not in r and r["total_return"]>br: br=r["total_return"];bn=STRATS[sk][0]
        print(f"  {'🟢' if br>0 else '🔴'} {sn}: {bn} {br:+.2f}%")

if __name__=="__main__": main()
