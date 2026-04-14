"""
QuantWeave - 板块分析服务
分析板块热点、资金流向和市场结构
"""
import tushare as ts
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from loguru import logger
from typing import List, Dict, Optional, Tuple
from sqlalchemy.orm import Session


class SectorService:
    """板块分析服务 - 分析板块热点和资金流向"""

    def __init__(self, db: Session, tushare_token: str = None):
        self.db = db
        self.tushare_token = tushare_token
        self.pro = ts.pro_api(token=tushare_token) if tushare_token else ts.pro_api()
        
        # 板块分类系统
        self.SECTOR_SOURCES = {
            "thsw": "同花顺",  # 同花顺行业概念板块
            "tdx": "通达信",   # 通达信板块
            "sw": "申万",      # 申万行业
            "dfcf": "东方财富"  # 东方财富概念
        }

    def get_sector_list(self, source: str = "thsw") -> pd.DataFrame:
        """
        获取板块列表
        
        Args:
            source: 数据源 (thsw/tdx/sw/dfcf)
            
        Returns:
            板块列表数据
        """
        try:
            if source == "thsw":
                # 同花顺行业概念板块
                df = self.pro.ths_index(symbol="", exchange="")
                logger.info(f"获取到同花顺{len(df)}个板块")
                return df
            elif source == "tdx":
                # 通达信板块
                df = self.pro.tdx_class()
                logger.info(f"获取到通达信{len(df)}个板块")
                return df
            elif source == "sw":
                # 申万行业
                df = self.pro.sw_index()
                logger.info(f"获取到申万{len(df)}个行业")
                return df
            elif source == "dfcf":
                # 东方财富概念
                df = self.pro.dfcf_concept()
                logger.info(f"获取到东方财富{len(df)}个概念板块")
                return df
            else:
                logger.error(f"不支持的板块数据源: {source}")
                return pd.DataFrame()
        except Exception as e:
            logger.error(f"获取板块列表失败: {e}")
            return pd.DataFrame()

    def get_sector_components(self, sector_code: str, source: str = "thsw") -> pd.DataFrame:
        """
        获取板块成分股
        
        Args:
            sector_code: 板块代码
            source: 数据源
            
        Returns:
            成分股列表
        """
        try:
            if source == "thsw":
                df = self.pro.ths_member(code=sector_code)
            elif source == "tdx":
                df = self.pro.tdx_member(code=sector_code)
            elif source == "sw":
                df = self.pro.sw_member(code=sector_code)
            elif source == "dfcf":
                df = self.pro.dfcf_member(code=sector_code)
            else:
                logger.error(f"不支持的板块数据源: {source}")
                return pd.DataFrame()
            
            logger.info(f"获取到板块{sector_code}的{len(df)}只成分股")
            return df
        except Exception as e:
            logger.error(f"获取板块成分股失败: {e}")
            return pd.DataFrame()

    def analyze_sector_performance(self, days: int = 5) -> Dict:
        """
        分析板块表现
        
        Args:
            days: 分析最近多少天的表现
            
        Returns:
            板块表现分析
        """
        try:
            # 获取近期的板块行情
            end_date = datetime.now().strftime("%Y%m%d")
            start_date = (datetime.now() - timedelta(days=days*2)).strftime("%Y%m%d")  # 多取几天数据
            
            # 获取同花顺板块行情
            df = self.pro.ths_daily(
                ts_code="",
                start_date=start_date,
                end_date=end_date
            )
            
            if df.empty:
                return {"error": "无板块行情数据"}
            
            # 按板块分组分析
            sector_performance = {}
            
            for sector_code in df["ts_code"].unique():
                sector_df = df[df["ts_code"] == sector_code].sort_values("trade_date")
                
                if len(sector_df) < 2:
                    continue
                
                # 计算涨跌幅
                latest = sector_df.iloc[-1]
                prev = sector_df.iloc[-min(len(sector_df), days)]
                
                # 确保有足够数据
                if pd.isna(latest["close"]) or pd.isna(prev["close"]) or prev["close"] == 0:
                    continue
                
                change_pct = (latest["close"] - prev["close"]) / prev["close"] * 100
                volume_ratio = latest["vol"] / sector_df["vol"].mean() if sector_df["vol"].mean() > 0 else 1
                turnover_ratio = latest["amount"] / sector_df["amount"].mean() if sector_df["amount"].mean() > 0 else 1
                
                # 技术指标
                sector_df["ma5"] = sector_df["close"].rolling(5).mean()
                sector_df["ma10"] = sector_df["close"].rolling(10).mean()
                
                latest_ma5 = sector_df.iloc[-1]["ma5"] if not pd.isna(sector_df.iloc[-1]["ma5"]) else latest["close"]
                latest_ma10 = sector_df.iloc[-1]["ma10"] if not pd.isna(sector_df.iloc[-1]["ma10"]) else latest["close"]
                
                # 判断趋势
                if latest["close"] > latest_ma5 > latest_ma10:
                    trend = "强势上升"
                elif latest["close"] < latest_ma5 < latest_ma10:
                    trend = "弱势下降"
                elif latest["close"] > latest_ma5:
                    trend = "短期反弹"
                elif latest["close"] < latest_ma5:
                    trend = "短期调整"
                else:
                    trend = "震荡"
                
                sector_performance[sector_code] = {
                    "name": sector_code,  # 实际应用中应该获取板块名称
                    "latest_close": round(latest["close"], 2),
                    "change_pct": round(change_pct, 2),
                    "volume_ratio": round(volume_ratio, 2),
                    "turnover_ratio": round(turnover_ratio, 2),
                    "volume": int(latest["vol"]),
                    "amount": int(latest["amount"]),
                    "trend": trend,
                    "ma_status": "金叉" if latest_ma5 > latest_ma10 else "死叉" if latest_ma5 < latest_ma10 else "粘合"
                }
            
            # 按涨跌幅排序
            sorted_sectors = sorted(
                sector_performance.items(), 
                key=lambda x: x[1]["change_pct"], 
                reverse=True
            )
            
            # 获取涨跌停板块信息
            limit_up_sectors = []
            limit_down_sectors = []
            
            for sector_code, perf in sector_performance.items():
                if perf["change_pct"] > 9.5:  # 近似涨停
                    limit_up_sectors.append((sector_code, perf["change_pct"]))
                elif perf["change_pct"] < -9.5:  # 近似跌停
                    limit_down_sectors.append((sector_code, perf["change_pct"]))
            
            return {
                "total_sectors": len(sector_performance),
                "top_gainers": sorted_sectors[:10],  # 涨幅前十
                "top_losers": sorted_sectors[-10:],  # 跌幅前十
                "limit_up_count": len(limit_up_sectors),
                "limit_down_count": len(limit_down_sectors),
                "hot_sectors": sorted_sectors[:5],  # 最热板块
                "cold_sectors": sorted_sectors[-5:],  # 最冷板块
                "volume_leaders": sorted(
                    sector_performance.items(), 
                    key=lambda x: x[1]["volume_ratio"], 
                    reverse=True
                )[:5],  # 量比前五
                "amount_leaders": sorted(
                    sector_performance.items(), 
                    key=lambda x: x[1]["amount"], 
                    reverse=True
                )[:5],  # 成交额前五
            }
            
        except Exception as e:
            logger.error(f"分析板块表现失败: {e}")
            return {"error": str(e)}

    def analyze_sector_rotation(self, days: int = 20) -> Dict:
        """
        分析板块轮动
        
        Args:
            days: 分析天数
            
        Returns:
            板块轮动分析
        """
        try:
            end_date = datetime.now().strftime("%Y%m%d")
            start_date = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
            
            # 获取板块日线数据
            df = self.pro.ths_daily(
                ts_code="",
                start_date=start_date,
                end_date=end_date
            )
            
            if df.empty:
                return {"error": "无板块轮动数据"}
            
            # 按板块和时间分组
            pivot_df = pd.pivot_table(
                df, 
                values="close", 
                index="trade_date", 
                columns="ts_code",
                aggfunc="first"
            )
            
            # 计算相关性矩阵（简化版）
            # 在实际应用中应该更复杂的轮动分析
            if len(pivot_df.columns) < 2:
                return {"error": "板块数量不足"}
            
            # 计算每日涨跌排名
            daily_returns = pivot_df.pct_change().dropna()
            if daily_returns.empty:
                return {"error": "收益率数据不足"}
            
            # 分析领涨板块切换
            leading_sectors = []
            last_leading = None
            rotation_signals = []
            
            for date in daily_returns.index[-10:]:  # 分析最近10天
                day_returns = daily_returns.loc[date]
                if day_returns.isna().all():
                    continue
                
                top_sector = day_returns.idxmax()  # 当日涨幅最大板块
                top_return = day_returns.max()
                
                leading_sectors.append({
                    "date": date,
                    "sector": top_sector,
                    "return": round(top_return * 100, 2)
                })
                
                if last_leading and last_leading != top_sector:
                    rotation_signals.append({
                        "date": date,
                        "from": last_leading,
                        "to": top_sector,
                        "days_leading": len([s for s in leading_sectors[-5:] if s["sector"] == last_leading])
                    })
                
                last_leading = top_sector
            
            # 计算板块稳定性
            sector_stability = {}
            for sector in daily_returns.columns:
                sector_returns = daily_returns[sector].dropna()
                if len(sector_returns) > 5:
                    volatility = sector_returns.std() * np.sqrt(252)  # 年化波动率
                    avg_return = sector_returns.mean() * 252  # 年化收益率
                    sharpe = avg_return / volatility if volatility > 0 else 0
                    
                    sector_stability[sector] = {
                        "volatility": round(volatility, 4),
                        "avg_return": round(avg_return, 4),
                        "sharpe": round(sharpe, 2),
                        "trend_strength": len([r for r in sector_returns if r > 0]) / len(sector_returns)
                    }
            
            # 识别当前轮动阶段
            if rotation_signals:
                latest_rotation = rotation_signals[-1]
                rotation_stage = f"从{latest_rotation['from']}轮动到{latest_rotation['to']}"
            else:
                rotation_stage = "板块轮动不明显"
            
            return {
                "analysis_period": f"{start_date} 至 {end_date}",
                "total_trading_days": len(daily_returns),
                "leading_sectors_recent": leading_sectors[-5:],
                "rotation_signals": rotation_signals,
                "rotation_stage": rotation_stage,
                "sector_stability": dict(sorted(
                    sector_stability.items(), 
                    key=lambda x: x[1]["sharpe"], 
                    reverse=True
                )[:10]),
                "high_volatility_sectors": dict(sorted(
                    sector_stability.items(), 
                    key=lambda x: x[1]["volatility"], 
                    reverse=True
                )[:5]),
                "stable_sectors": dict(sorted(
                    sector_stability.items(), 
                    key=lambda x: x[1]["sharpe"], 
                    reverse=True
                )[:5]),
            }
            
        except Exception as e:
            logger.error(f"分析板块轮动失败: {e}")
            return {"error": str(e)}

    def analyze_sector_correlation(self, top_n: int = 10) -> Dict:
        """
        分析板块相关性
        
        Args:
            top_n: 分析前多少个板块
            
        Returns:
            板块相关性分析
        """
        try:
            end_date = datetime.now().strftime("%Y%m%d")
            start_date = (datetime.now() - timedelta(days=60)).strftime("%Y%m%d")  # 60天数据
            
            df = self.pro.ths_daily(
                ts_code="",
                start_date=start_date,
                end_date=end_date
            )
            
            if df.empty:
                return {"error": "无板块相关性数据"}
            
            # 获取成交额最大的前N个板块
            recent_df = df[df["trade_date"] >= (datetime.now() - timedelta(days=5)).strftime("%Y%m%d")]
            sector_volume = recent_df.groupby("ts_code")["amount"].sum().nlargest(top_n)
            top_sectors = sector_volume.index.tolist()
            
            # 创建收益率面板数据
            pivot_df = pd.pivot_table(
                df[df["ts_code"].isin(top_sectors)], 
                values="close", 
                index="trade_date", 
                columns="ts_code",
                aggfunc="first"
            )
            
            returns_df = pivot_df.pct_change().dropna()
            
            if returns_df.empty or len(returns_df.columns) < 2:
                return {"error": "收益率数据不足"}
            
            # 计算相关性矩阵
            corr_matrix = returns_df.corr()
            
            # 分析板块聚类
            sector_clusters = {}
            threshold = 0.7  # 高相关性阈值
            
            for sector in corr_matrix.columns:
                high_corr = corr_matrix[sector][corr_matrix[sector] > threshold].index.tolist()
                high_corr = [s for s in high_corr if s != sector]  # 排除自身
                
                if high_corr:
                    sector_clusters[sector] = {
                        "high_correlation_with": high_corr,
                        "avg_correlation": round(corr_matrix[sector][high_corr].mean(), 3),
                        "cluster_size": len(high_corr) + 1
                    }
            
            # 识别独立板块（低相关性）
            independent_sectors = []
            for sector in corr_matrix.columns:
                other_corrs = [corr_matrix.loc[sector, other] for other in corr_matrix.columns if other != sector]
                if other_corrs:
                    avg_corr = np.mean(other_corrs)
                    if abs(avg_corr) < 0.3:  # 平均相关性低于0.3
                        independent_sectors.append({
                            "sector": sector,
                            "avg_correlation": round(avg_corr, 3)
                        })
            
            return {
                "analyzed_sectors": top_sectors,
                "correlation_matrix_summary": {
                    "avg_correlation": round(corr_matrix.values.mean(), 3),
                    "max_correlation": round(corr_matrix.values.max(), 3),
                    "min_correlation": round(corr_matrix.values.min(), 3)
                },
                "sector_clusters": dict(sorted(
                    sector_clusters.items(),
                    key=lambda x: x[1]["cluster_size"],
                    reverse=True
                )[:5]),
                "independent_sectors": sorted(
                    independent_sectors,
                    key=lambda x: abs(x["avg_correlation"])
                )[:5],
                "highest_correlation_pairs": self._find_top_correlation_pairs(corr_matrix, top_n=5),
                "lowest_correlation_pairs": self._find_bottom_correlation_pairs(corr_matrix, top_n=5)
            }
            
        except Exception as e:
            logger.error(f"分析板块相关性失败: {e}")
            return {"error": str(e)}

    def _find_top_correlation_pairs(self, corr_matrix: pd.DataFrame, top_n: int = 5) -> List[Dict]:
        """找出相关性最高的板块对"""
        pairs = []
        n = len(corr_matrix.columns)
        
        for i in range(n):
            for j in range(i+1, n):
                sector_i = corr_matrix.columns[i]
                sector_j = corr_matrix.columns[j]
                corr = corr_matrix.iloc[i, j]
                
                if not pd.isna(corr):
                    pairs.append({
                        "sector1": sector_i,
                        "sector2": sector_j,
                        "correlation": round(corr, 3)
                    })
        
        return sorted(pairs, key=lambda x: abs(x["correlation"]), reverse=True)[:top_n]

    def _find_bottom_correlation_pairs(self, corr_matrix: pd.DataFrame, top_n: int = 5) -> List[Dict]:
        """找出相关性最低的板块对"""
        pairs = []
        n = len(corr_matrix.columns)
        
        for i in range(n):
            for j in range(i+1, n):
                sector_i = corr_matrix.columns[i]
                sector_j = corr_matrix.columns[j]
                corr = corr_matrix.iloc[i, j]
                
                if not pd.isna(corr):
                    pairs.append({
                        "sector1": sector_i,
                        "sector2": sector_j,
                        "correlation": round(corr, 3)
                    })
        
        return sorted(pairs, key=lambda x: abs(x["correlation"]))[:top_n]

    def generate_sector_report(self, days: int = 5) -> Dict:
        """
        生成板块分析报告
        
        Args:
            days: 分析天数
            
        Returns:
            综合板块报告
        """
        performance = self.analyze_sector_performance(days)
        rotation = self.analyze_sector_rotation(days * 4)  # 轮动分析需要更长时间
        correlation = self.analyze_sector_correlation()
        
        # 生成报告摘要
        summary_lines = []
        summary_lines.append(f"📊 {days}天板块分析报告")
        summary_lines.append(f"分析板块数: {performance.get('total_sectors', 0)}")
        
        if "hot_sectors" in performance and performance["hot_sectors"]:
            summary_lines.append("🔥 热点板块:")
            for sector_code, perf in performance["hot_sectors"][:3]:
                summary_lines.append(f"  • {sector_code}: {perf['change_pct']}% ({perf['trend']})")
        
        if "limit_up_count" in performance:
            summary_lines.append(f"📈 近似涨停板块: {performance['limit_up_count']}个")
            summary_lines.append(f"📉 近似跌停板块: {performance['limit_down_count']}个")
        
        if "rotation_stage" in rotation:
            summary_lines.append(f"🔄 板块轮动阶段: {rotation['rotation_stage']}")
        
        if "sector_clusters" in correlation and correlation["sector_clusters"]:
            cluster_info = list(correlation["sector_clusters"].items())[0]
            summary_lines.append(f"🤝 最强板块集群: {cluster_info[0]} (关联{cluster_info[1]['cluster_size']}个板块)")
        
        # 投资建议
        recommendations = []
        
        if "hot_sectors" in performance and performance["hot_sectors"]:
            hot_sector = performance["hot_sectors"][0][1]
            recommendations.append(f"关注热点板块{performance['hot_sectors'][0][0]}，近期表现强势")
        
        if "limit_up_count" in performance and performance["limit_up_count"] > 3:
            recommendations.append("多个板块涨停，市场情绪高涨，可积极布局")
        elif "limit_down_count" in performance and performance["limit_down_count"] > 3:
            recommendations.append("多个板块跌停，市场情绪低迷，建议谨慎")
        
        if "rotation_signals" in rotation and rotation["rotation_signals"]:
            latest_signal = rotation["rotation_signals"][-1]
            recommendations.append(f"板块轮动进行中，从{latest_signal['from']}转向{latest_signal['to']}")
        
        return {
            "summary": "\n".join(summary_lines),
            "performance": performance,
            "rotation": rotation,
            "correlation": correlation,
            "recommendations": recommendations,
            "report_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }