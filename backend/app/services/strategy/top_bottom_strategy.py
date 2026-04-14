"""
QuantWeave - 顶底图策略（通达信顶底图指标转换）
根据好大哥提供的顶底图指标公式实现。

指标公式：
VAR1:=1;
VAR2:=1/WINNER(CLOSE);
VAR3:=MA(CLOSE,13);
VAR4:=100-ABS((CLOSE-VAR3)/VAR3*100);
VAR5:=LLV(LOW,75);
VAR6:=HHV(HIGH,75);
VAR7:=(VAR6-VAR5)/100;
VAR8:=SMA((CLOSE-VAR5)/VAR7,20,1);
VAR9:=SMA((OPEN-VAR5)/VAR7,20,1);
VARA:=3*VAR8-2*SMA(VAR8,15,1);
VARB:=3*VAR9-2*SMA(VAR9,15,1);
VARC:=100-VARB;
髑战: (100-VARA)*VAR1,COLOR0099FF;
三胖: MA(WINNER(CLOSE*0.95)*100,3)*VAR1,COLORYELLOW;
切手: (100-IF(VAR2>5,IF(VAR2<100,VAR2,VAR4-10),0))*VAR1,COLORGREEN,LINETHICK1,POINTDOT ;
VARD:=三胖>VAR4;
VARE:=REF(LOW,1)*0.9;
VARF:=LOW*0.9;
VAR10:=(VARF*VOL+VARE*(CAPITAL-VOL))/CAPITAL;
VAR11:=EMA(VAR10,30);
VAR12:=CLOSE-REF(CLOSE,1);
VAR13:=MAX(VAR12,0);
VAR14:=ABS(VAR12);
VAR15:=SMA(VAR13,7,1)/SMA(VAR14,7,1)*100;
VAR16:=SMA(VAR13,13,1)/SMA(VAR14,13,1)*100;
VAR17:=BARSCOUNT(CLOSE);
VAR18:=SMA(MAX(VAR12,0),6,1)/SMA(ABS(VAR12),6,1)*100;
VAR19:=(-200)*(HHV(HIGH,60)-CLOSE)/(HHV(HIGH,60)-LLV(LOW,60))+100;
VAR1A:=(CLOSE-LLV(LOW,15))/(HHV(HIGH,15)-LLV(LOW,15))*100;
VAR1B:=SMA((SMA(VAR1A,4,1)-50)*2,3,1);
VAR1C:=(INDEXC-LLV(INDEXL,14))/(HHV(INDEXH,14)-LLV(INDEXL,14))*100;
VAR1D:=SMA(VAR1C,4,1);
VAR1E:=SMA(VAR1D,3,1);
VAR1F:=(HHV(HIGH,30)-CLOSE)/CLOSE*100;
VAR20:=VAR18<=25 AND VAR19<-95 AND VAR1F>20 AND VAR1B<-30 AND VAR1E<30 AND VAR11-CLOSE>=-0.25 AND VAR15<22 AND VAR16<28 AND VAR17>50;
STICKLINE(VARD,VAR4,三胖,5,0),COLORWHITE;
STICKLINE(1,切手,100,1,0),COLORGREEN;
STICKLINE(VAR20,0,80,5,0),COLORRED,LINETHICK3 ;
100,COLORGREEN ,LINETHICK2 ;
0,COLORYELLOW ,LINETHICK2 ;
波段: 15,COLORRED ,LINETHICK4 ;

主要输出线：
- 髑战（战斗线）
- 三胖（胖手指线）
- 切手（切手线）
- 波段线（15水平线）

信号条件：
- 白色柱：当三胖 > VAR4
- 绿色柱：切手到100
- 红色柱：满足VAR20条件时，底部信号强烈
"""
import numpy as np
import pandas as pd
from loguru import logger
from typing import List, Optional, Set
from .strategy_service import StrategyBase, Signal, SignalType


class TopBottomStrategy(StrategyBase):
    """顶底图策略
    
    基于顶底图指标识别超买超卖区域，捕捉底部反转机会。
    买入信号：VAR20红色柱状线 + 切手线低位向上
    卖出信号：髑战线高位回落 + 三胖线拐头向下
    """
    name = "顶底图策略"
    description = "通达信顶底图指标，识别顶部和底部区域"
    params = {
        "var1": 1.0,  # 缩放因子
        "winner_lookback": 250,  # WINNER计算的历史窗口
        "stop_loss_pct": -0.08,
        "take_profit_pct": 0.15,
        "buy_confirmation_days": 2,  # 买入确认所需连续天数
    }

    def __init__(self, params: dict = None):
        super().__init__(params)
        self.position = None
        self.entry_price = None
        self.var1 = self.params.get("var1", 1.0)
        self.winner_lookback = self.params.get("winner_lookback", 250)

    @staticmethod
    def _tdx_sma(x, n, m):
        """通达信 SMA(X, N, M): Y = (M*X + (N-M)*Y_prev) / N"""
        y = np.empty(len(x))
        y[0] = x[0]
        for i in range(1, len(x)):
            y[i] = (m * x[i] + (n - m) * y[i - 1]) / n
        return y

    def _winner(self, price: pd.Series, lookback: int = None) -> pd.Series:
        """计算获利盘比例近似值（简化版）
        
        WINNER(CLOSE) 近似为收盘价在历史价格分布中的百分位
        使用滚动窗口计算价格在历史区间中的位置比例
        """
        if lookback is None:
            lookback = self.winner_lookback
        # 最小需要lookback个数据
        if len(price) < lookback:
            lookback = len(price)
        winner_values = np.ones(len(price))
        for i in range(len(price)):
            start = max(0, i - lookback + 1)
            window = price.iloc[start:i+1]
            if len(window) < 2:
                winner_values[i] = 0.5
            else:
                # 计算收盘价在该窗口中的分位数
                rank = (window <= price.iloc[i]).sum()
                winner_values[i] = rank / len(window)
        return pd.Series(winner_values, index=price.index)

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算顶底图所有指标"""
        df = df.sort_values("trade_date").copy()
        close = df["close"]
        open_ = df["open"]
        high = df["high"]
        low = df["low"]
        # 如果缺少成交量或市值，用默认值
        volume = df["vol"] if "vol" in df.columns else pd.Series(1000000, index=df.index)
        # 假设市值为流通市值，用近似值
        capital = df["vol"] * df["close"] * 10 if "vol" in df.columns else pd.Series(1e9, index=df.index)
        
        # VAR1: 缩放因子，默认为1
        var1 = self.var1
        
        # VAR2 = 1/WINNER(CLOSE)
        winner_close = self._winner(close)
        var2 = 1.0 / np.where(winner_close > 1e-10, winner_close, 1e-10)
        
        # VAR3 = MA(CLOSE,13)
        var3 = close.rolling(13, min_periods=1).mean()
        
        # VAR4 = 100 - ABS((CLOSE-VAR3)/VAR3*100)
        var4 = 100 - np.abs((close - var3) / np.where(var3 > 1e-10, var3, 1e-10) * 100)
        
        # VAR5 = LLV(LOW,75)
        var5 = low.rolling(75, min_periods=1).min()
        
        # VAR6 = HHV(HIGH,75)
        var6 = high.rolling(75, min_periods=1).max()
        
        # VAR7 = (VAR6 - VAR5) / 100
        var7 = (var6 - var5) / 100.0
        
        # VAR8 = SMA((CLOSE-VAR5)/VAR7,20,1)
        raw_var8 = np.where(var7 > 1e-10, (close - var5) / var7, 0.0)
        var8 = self._tdx_sma(raw_var8, 20, 1)
        
        # VAR9 = SMA((OPEN-VAR5)/VAR7,20,1)
        raw_var9 = np.where(var7 > 1e-10, (open_ - var5) / var7, 0.0)
        var9 = self._tdx_sma(raw_var9, 20, 1)
        
        # VARA = 3*VAR8 - 2*SMA(VAR8,15,1)
        var8_sma = self._tdx_sma(var8, 15, 1)
        vara = 3.0 * var8 - 2.0 * var8_sma
        
        # VARB = 3*VAR9 - 2*SMA(VAR9,15,1)
        var9_sma = self._tdx_sma(var9, 15, 1)
        varb = 3.0 * var9 - 2.0 * var9_sma
        
        # VARC = 100 - VARB (未使用)
        varc = 100 - varb
        
        # 髑战 = (100 - VARA) * VAR1
        fight = (100 - vara) * var1
        
        # 三胖 = MA(WINNER(CLOSE*0.95)*100, 3) * VAR1
        winner_close_95 = self._winner(close * 0.95)
        sanpang_raw = winner_close_95 * 100
        sanpang = sanpang_raw.rolling(3, min_periods=1).mean() * var1
        
        # 切手 = (100 - IF(VAR2>5, IF(VAR2<100, VAR2, VAR4-10), 0)) * VAR1
        # 通达信 IF条件转换
        cond1 = var2 > 5
        cond2 = var2 < 100
        val_if = np.where(cond1, 
                         np.where(cond2, var2, var4 - 10),
                         0)
        qieshou = (100 - val_if) * var1
        
        # VARD = 三胖 > VAR4
        vard = sanpang > var4
        
        # VARE = REF(LOW,1)*0.9
        vare = low.shift(1) * 0.9
        
        # VARF = LOW*0.9
        varf = low * 0.9
        
        # VAR10 = (VARF*VOL + VARE*(CAPITAL-VOL)) / CAPITAL
        var10 = (varf * volume + vare * (capital - volume)) / np.where(capital > 0, capital, 1)
        
        # VAR11 = EMA(VAR10,30)
        var11 = var10.ewm(span=30, adjust=False).mean()
        
        # VAR12 = CLOSE - REF(CLOSE,1)
        var12 = close - close.shift(1)
        
        # VAR13 = MAX(VAR12,0)
        var13 = np.maximum(var12, 0)
        
        # VAR14 = ABS(VAR12)
        var14 = np.abs(var12)
        
        # VAR15 = SMA(VAR13,7,1) / SMA(VAR14,7,1) * 100
        var13_sma = self._tdx_sma(var13.values, 7, 1)
        var14_sma = self._tdx_sma(var14.values, 7, 1)
        var15 = np.where(var14_sma > 1e-10, var13_sma / var14_sma * 100, 50)
        
        # VAR16 = SMA(VAR13,13,1) / SMA(VAR14,13,1) * 100
        var13_sma13 = self._tdx_sma(var13.values, 13, 1)
        var14_sma13 = self._tdx_sma(var14.values, 13, 1)
        var16 = np.where(var14_sma13 > 1e-10, var13_sma13 / var14_sma13 * 100, 50)
        
        # VAR17 = BARSCOUNT(CLOSE) 数据长度
        var17 = pd.Series(range(1, len(close)+1), index=close.index)
        
        # VAR18 = SMA(MAX(VAR12,0),6,1) / SMA(ABS(VAR12),6,1) * 100
        var18_numer = self._tdx_sma(np.maximum(var12, 0).values, 6, 1)
        var18_denom = self._tdx_sma(np.abs(var12).values, 6, 1)
        var18 = np.where(var18_denom > 1e-10, var18_numer / var18_denom * 100, 50)
        
        # VAR19 = (-200)*(HHV(HIGH,60)-CLOSE)/(HHV(HIGH,60)-LLV(LOW,60)) + 100
        hhv_60 = high.rolling(60, min_periods=1).max()
        llv_60 = low.rolling(60, min_periods=1).min()
        var19 = (-200) * (hhv_60 - close) / np.where((hhv_60 - llv_60) > 1e-10, hhv_60 - llv_60, 1e-10) + 100
        
        # VAR1A = (CLOSE-LLV(LOW,15))/(HHV(HIGH,15)-LLV(LOW,15))*100
        llv_15 = low.rolling(15, min_periods=1).min()
        hhv_15 = high.rolling(15, min_periods=1).max()
        var1a = (close - llv_15) / np.where((hhv_15 - llv_15) > 1e-10, hhv_15 - llv_15, 1e-10) * 100
        
        # VAR1B = SMA((SMA(VAR1A,4,1)-50)*2,3,1)
        var1a_sma4 = self._tdx_sma(var1a.values, 4, 1)
        var1b_raw = (var1a_sma4 - 50) * 2
        var1b = self._tdx_sma(var1b_raw, 3, 1)
        
        # VAR1C = (INDEXC-LLV(INDEXL,14))/(HHV(INDEXH,14)-LLV(INDEXL,14))*100
        # 使用大盘指数数据（这里用沪深300近似），如果没有则用股票自身数据
        # 暂时用股票自身数据替代
        var1c = var1a  # 简化
        
        # VAR1D = SMA(VAR1C,4,1)
        var1d = self._tdx_sma(var1c.values, 4, 1)
        
        # VAR1E = SMA(VAR1D,3,1)
        var1e = self._tdx_sma(var1d, 3, 1)
        
        # VAR1F = (HHV(HIGH,30)-CLOSE)/CLOSE*100
        hhv_30 = high.rolling(30, min_periods=1).max()
        var1f = (hhv_30 - close) / np.where(close > 1e-10, close, 1e-10) * 100
        
        # VAR20 复杂条件
        var20 = (
            (var18 <= 25) &
            (var19 < -95) &
            (var1f > 20) &
            (var1b < -30) &
            (var1e < 30) &
            (var11 - close >= -0.25) &
            (var15 < 22) &
            (var16 < 28) &
            (var17 > 50)
        )
        
        # 保存所有指标到 DataFrame
        df["fight"] = fight  # 髑战
        df["sanpang"] = sanpang  # 三胖
        df["qieshou"] = qieshou  # 切手
        df["var4"] = var4
        df["vard"] = vard.astype(bool)  # 白色柱条件
        df["var20"] = var20.astype(bool)  # 红色柱条件
        df["vara"] = vara
        df["varb"] = varb
        df["var11"] = var11
        df["var15"] = var15
        df["var16"] = var16
        df["var18"] = var18
        df["var19"] = var19
        df["var1a"] = var1a
        df["var1b"] = var1b
        df["var1e"] = var1e
        df["var1f"] = var1f
        
        return df

    def generate_signals(self, df: pd.DataFrame, ts_code: str = "") -> List[Signal]:
        """生成交易信号"""
        if df.empty or len(df) < 100:
            return []
        
        df = self.calculate_indicators(df)
        close = df["close"]
        fight = df["fight"]  # 髑战线
        sanpang = df["sanpang"]  # 三胖线
        qieshou = df["qieshou"]  # 切手线
        var20 = df["var20"]  # 红色柱条件
        
        self.position = None
        self.entry_price = None
        signals = []
        
        # 趋势判断：切手线低位回升 + 红色柱出现，作为底部信号
        for i in range(100, len(df)):
            row = df.iloc[i]
            p = close.iloc[i]
            qs = qieshou.iloc[i]
            ft = fight.iloc[i]
            sp = sanpang.iloc[i]
            is_red_bar = var20.iloc[i]
            dt = str(row["trade_date"])
            
            if self.position is None:
                # 买入条件：红色柱出现 + 切手线小于30（低位）+ 髑战线开始拐头向上
                # 简化：红色柱出现且切手线小于30
                buy_cond = (
                    is_red_bar and 
                    qs < 30 and 
                    sp > 50  # 三胖线在中位以上
                )
                if buy_cond:
                    signals.append(Signal(
                        signal_type=SignalType.BUY,
                        ts_code=ts_code,
                        price=float(p),
                        reason=f"顶底图红色柱+切手低位 qieshou={qs:.1f} fight={ft:.1f}",
                        confidence=0.75,
                        date=dt,
                    ))
                    self.position = "buy"
                    self.entry_price = p
            else:
                pnl = (p - self.entry_price) / self.entry_price
                sell = False
                reason = ""
                
                # 止损
                if pnl <= self.params["stop_loss_pct"]:
                    sell = True
                    reason = f"止损 {pnl*100:+.1f}%"
                # 止盈
                elif pnl >= self.params["take_profit_pct"]:
                    sell = True
                    reason = f"止盈 {pnl*100:+.1f}%"
                # 技术卖出：髑战线高位拐头向下
                elif ft > 70 and fight.iloc[i] < fight.iloc[i-1] and fight.iloc[i-1] > fight.iloc[i-2]:
                    sell = True
                    reason = f"髑战线高位拐头 fight={ft:.1f}"
                # 三胖线死叉VAR4
                elif sanpang.iloc[i] < df["var4"].iloc[i] and sanpang.iloc[i-1] >= df["var4"].iloc[i-1]:
                    sell = True
                    reason = f"三胖线下穿VAR4 sanpang={sp:.1f}"
                
                if sell:
                    signals.append(Signal(
                        signal_type=SignalType.SELL,
                        ts_code=ts_code,
                        price=float(p),
                        reason=reason,
                        confidence=0.75,
                        date=dt,
                    ))
                    self.position = None
                    self.entry_price = None
        
        return signals