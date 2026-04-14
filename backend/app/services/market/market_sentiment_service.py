"""
QuantWeave - 市场情绪分析服务
分析市场整体情绪、投资者情绪指数和风险偏好
"""
import tushare as ts
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from loguru import logger
from typing import List, Dict, Optional, Tuple
from sqlalchemy.orm import Session


class MarketSentimentService:
    """市场情绪分析服务 - 分析市场情绪和投资者行为"""

    def __init__(self, db: Session, tushare_token: str = None):
        self.db = db
        self.tushare_token = tushare_token
        self.pro = ts.pro_api(token=tushare_token) if tushare_token else ts.pro_api()
        
        # 情绪指标权重
        self.SENTIMENT_WEIGHTS = {
            "market_breadth": 0.25,      # 市场广度
            "volume_momentum": 0.20,     # 量能动向
            "volatility_index": 0.15,    # 波动率指数
            "limit_up_down": 0.15,       # 涨跌停比
            "northbound_flow": 0.15,     # 北向资金
            "fear_greed": 0.10           # 贪婪恐惧指数
        }
        
        # VIX-like 波动率指数计算参数
        self.VOLATILITY_WINDOW = 20  # 计算波动率的窗口

    def calculate_market_breadth(self, date: str = None) -> Dict:
        """
        计算市场广度指标
        
        Args:
            date: 分析日期，默认最新
            
        Returns:
            市场广度指标
        """
        try:
            if date is None:
                date = datetime.now().strftime("%Y%m%d")
            
            # 获取市场涨跌数据
            df = self.pro.daily(trade_date=date)
            
            if df.empty:
                # 如果当天无数据，获取前一天
                prev_date = (datetime.strptime(date, "%Y%m%d") - timedelta(days=1)).strftime("%Y%m%d")
                df = self.pro.daily(trade_date=prev_date)
            
            if df.empty:
                return {"error": "无市场数据"}
            
            # 计算涨跌家数
            total_stocks = len(df)
            up_count = len(df[df["pct_chg"] > 0])
            down_count = len(df[df["pct_chg"] < 0])
            flat_count = total_stocks - up_count - down_count
            
            # 计算涨跌比
            advance_decline_ratio = up_count / max(down_count, 1)
            
            # 计算涨跌家数差
            advance_decline_diff = up_count - down_count
            
            # 计算涨跌家数比例
            up_ratio = up_count / total_stocks
            down_ratio = down_count / total_stocks
            
            # 计算市场广度得分 (0-100)
            breadth_score = min(100, max(0, 50 + (advance_decline_diff / total_stocks * 100)))
            
            # 分析市场宽度强度
            if up_ratio > 0.7:
                breadth_strength = "非常强势"
            elif up_ratio > 0.6:
                breadth_strength = "强势"
            elif up_ratio > 0.5:
                breadth_strength = "偏强"
            elif down_ratio > 0.7:
                breadth_strength = "非常弱势"
            elif down_ratio > 0.6:
                breadth_strength = "弱势"
            elif down_ratio > 0.5:
                breadth_strength = "偏弱"
            else:
                breadth_strength = "均衡"
            
            return {
                "date": date,
                "total_stocks": total_stocks,
                "up_count": up_count,
                "down_count": down_count,
                "flat_count": flat_count,
                "up_ratio": round(up_ratio, 3),
                "down_ratio": round(down_ratio, 3),
                "advance_decline_ratio": round(advance_decline_ratio, 2),
                "advance_decline_diff": advance_decline_diff,
                "breadth_score": round(breadth_score, 1),
                "breadth_strength": breadth_strength,
                "market_breadth": "扩张" if up_count > down_count else "收缩"
            }
            
        except Exception as e:
            logger.error(f"计算市场广度失败: {e}")
            return {"error": str(e)}

    def calculate_volume_momentum(self, days: int = 5) -> Dict:
        """
        计算量能动向指标
        
        Args:
            days: 分析天数
            
        Returns:
            量能动向指标
        """
        try:
            end_date = datetime.now().strftime("%Y%m%d")
            start_date = (datetime.now() - timedelta(days=days*2)).strftime("%Y%m%d")
            
            # 获取主要指数成交量数据
            indices = ["000001.SH", "399001.SZ", "399006.SZ"]  # 上证、深证、创业板
            volume_data = {}
            
            for index_code in indices:
                df = self.pro.index_daily(
                    ts_code=index_code,
                    start_date=start_date,
                    end_date=end_date
                )
                
                if not df.empty:
                    df = df.sort_values("trade_date")
                    latest = df.iloc[-1]
                    avg_volume = df["vol"].tail(days).mean()
                    
                    volume_ratio = latest["vol"] / avg_volume if avg_volume > 0 else 1
                    amount_ratio = latest["amount"] / df["amount"].tail(days).mean() if df["amount"].tail(days).mean() > 0 else 1
                    
                    volume_data[index_code] = {
                        "latest_volume": int(latest["vol"]),
                        "avg_volume": int(avg_volume),
                        "volume_ratio": round(volume_ratio, 2),
                        "amount_ratio": round(amount_ratio, 2),
                        "volume_trend": "放量" if volume_ratio > 1.2 else "缩量" if volume_ratio < 0.8 else "平量"
                    }
            
            # 计算整体量能得分
            if volume_data:
                avg_volume_ratio = np.mean([data["volume_ratio"] for data in volume_data.values()])
                volume_score = min(100, max(0, 50 + (avg_volume_ratio - 1) * 50))
                
                # 判断量能趋势
                if avg_volume_ratio > 1.3:
                    volume_trend = "大幅放量"
                elif avg_volume_ratio > 1.1:
                    volume_trend = "温和放量"
                elif avg_volume_ratio < 0.7:
                    volume_trend = "大幅缩量"
                elif avg_volume_ratio < 0.9:
                    volume_trend = "温和缩量"
                else:
                    volume_trend = "量能平稳"
            else:
                avg_volume_ratio = 1.0
                volume_score = 50
                volume_trend = "数据不足"
            
            return {
                "analysis_period": f"{days}天",
                "volume_data": volume_data,
                "avg_volume_ratio": round(avg_volume_ratio, 2),
                "volume_score": round(volume_score, 1),
                "volume_trend": volume_trend,
                "market_liquidity": "充足" if avg_volume_ratio > 1.1 else "不足" if avg_volume_ratio < 0.9 else "适中"
            }
            
        except Exception as e:
            logger.error(f"计算量能动向失败: {e}")
            return {"error": str(e)}

    def calculate_volatility_index(self, days: int = 20) -> Dict:
        """
        计算波动率指数（类似VIX）
        
        Args:
            days: 计算窗口
            
        Returns:
            波动率指数
        """
        try:
            end_date = datetime.now().strftime("%Y%m%d")
            start_date = (datetime.now() - timedelta(days=days*2)).strftime("%Y%m%d")
            
            # 获取上证指数数据
            df = self.pro.index_daily(
                ts_code="000001.SH",  # 上证指数
                start_date=start_date,
                end_date=end_date
            )
            
            if df.empty or len(df) < days:
                return {"error": "指数数据不足"}
            
            df = df.sort_values("trade_date")
            
            # 计算收益率
            df["returns"] = df["close"].pct_change()
            
            # 计算历史波动率（年化）
            recent_returns = df["returns"].tail(days).dropna()
            if len(recent_returns) < 10:
                return {"error": "收益率数据不足"}
            
            historical_volatility = recent_returns.std() * np.sqrt(252)  # 年化波动率
            
            # 计算ATR（平均真实波幅）
            df["high_low"] = df["high"] - df["low"]
            df["high_close"] = (df["high"] - df["close"].shift(1)).abs()
            df["low_close"] = (df["low"] - df["close"].shift(1)).abs()
            df["tr"] = df[["high_low", "high_close", "low_close"]].max(axis=1)
            atr = df["tr"].tail(days).mean()
            atr_pct = atr / df["close"].iloc[-1] * 100 if df["close"].iloc[-1] > 0 else 0
            
            # 计算布林带宽度
            df["ma20"] = df["close"].rolling(20).mean()
            df["std20"] = df["close"].rolling(20).std()
            df["bb_upper"] = df["ma20"] + 2 * df["std20"]
            df["bb_lower"] = df["ma20"] - 2 * df["std20"]
            df["bb_width"] = (df["bb_upper"] - df["bb_lower"]) / df["ma20"] * 100
            
            latest_bb_width = df["bb_width"].iloc[-1] if not pd.isna(df["bb_width"].iloc[-1]) else 0
            
            # 计算波动率得分 (0-100，越高波动越大)
            volatility_score = min(100, max(0, historical_volatility * 100))
            
            # 判断市场波动状态
            if historical_volatility > 0.25:
                volatility_state = "高波动"
            elif historical_volatility > 0.15:
                volatility_state = "中高波动"
            elif historical_volatility > 0.08:
                volatility_state = "中等波动"
            else:
                volatility_state = "低波动"
            
            # 计算恐慌指数（简化版）
            fear_index = min(100, max(0, 
                (historical_volatility * 200) + 
                (atr_pct * 10) + 
                (latest_bb_width * 3)
            ))
            
            return {
                "historical_volatility": round(historical_volatility, 4),
                "volatility_score": round(volatility_score, 1),
                "volatility_state": volatility_state,
                "atr": round(atr, 2),
                "atr_pct": round(atr_pct, 2),
                "bollinger_width": round(latest_bb_width, 2),
                "fear_index": round(fear_index, 1),
                "market_stability": "不稳定" if historical_volatility > 0.2 else "较稳定" if historical_volatility > 0.1 else "稳定"
            }
            
        except Exception as e:
            logger.error(f"计算波动率指数失败: {e}")
            return {"error": str(e)}

    def calculate_limit_up_down_ratio(self, date: str = None) -> Dict:
        """
        计算涨跌停比率
        
        Args:
            date: 分析日期
            
        Returns:
            涨跌停分析
        """
        try:
            if date is None:
                date = datetime.now().strftime("%Y%m%d")
            
            # 获取涨跌停数据
            df = self.pro.limit_list(trade_date=date)
            
            if df.empty:
                # 尝试前一天
                prev_date = (datetime.strptime(date, "%Y%m%d") - timedelta(days=1)).strftime("%Y%m%d")
                df = self.pro.limit_list(trade_date=prev_date)
            
            if df.empty:
                return {"error": "无涨跌停数据"}
            
            # 计算涨跌停数量
            limit_up = len(df[df["limit"] == "U"])  # 涨停
            limit_down = len(df[df["limit"] == "D"])  # 跌停
            
            # 计算比率
            total_limit = limit_up + limit_down
            limit_ratio = limit_up / max(limit_down, 1)
            
            # 计算涨跌停强度得分
            if total_limit > 0:
                limit_score = min(100, max(0, 50 + (limit_up - limit_down) / total_limit * 50))
            else:
                limit_score = 50
            
            # 分析市场情绪
            if limit_ratio > 5:
                limit_sentiment = "极度乐观"
            elif limit_ratio > 3:
                limit_sentiment = "乐观"
            elif limit_ratio > 1.5:
                limit_sentiment = "偏乐观"
            elif limit_ratio > 0.67:
                limit_sentiment = "中性"
            elif limit_ratio > 0.33:
                limit_sentiment = "偏悲观"
            elif limit_ratio > 0.2:
                limit_sentiment = "悲观"
            else:
                limit_sentiment = "极度悲观"
            
            # 分析连板情况（如果有相关数据）
            consecutive_limit = {}
            if "limit_count" in df.columns:
                consecutive_up = df[df["limit"] == "U"]["limit_count"].max()
                consecutive_down = df[df["limit"] == "D"]["limit_count"].max()
                consecutive_limit = {
                    "max_consecutive_up": int(consecutive_up) if not pd.isna(consecutive_up) else 0,
                    "max_consecutive_down": int(consecutive_down) if not pd.isna(consecutive_down) else 0
                }
            
            return {
                "date": date,
                "limit_up": limit_up,
                "limit_down": limit_down,
                "limit_ratio": round(limit_ratio, 2),
                "limit_score": round(limit_score, 1),
                "limit_sentiment": limit_sentiment,
                "consecutive_limit": consecutive_limit,
                "market_sentiment": "狂热" if limit_ratio > 5 and limit_up > 50 else 
                                   "恐慌" if limit_ratio < 0.2 and limit_down > 50 else 
                                   "正常"
            }
            
        except Exception as e:
            logger.error(f"计算涨跌停比率失败: {e}")
            return {"error": str(e)}

    def analyze_northbound_flow(self, days: int = 5) -> Dict:
        """
        分析北向资金流向
        
        Args:
            days: 分析天数
            
        Returns:
            北向资金分析
        """
        try:
            end_date = datetime.now().strftime("%Y%m%d")
            start_date = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
            
            # 获取北向资金数据
            df = self.pro.moneyflow_hsgt(start_date=start_date, end_date=end_date)
            
            if df.empty:
                return {"error": "无北向资金数据"}
            
            df = df.sort_values("trade_date")
            
            # 计算累计净流入
            df["cum_net_inflow"] = df["north_money"].cumsum()
            
            # 计算近期趋势
            recent_inflows = df["north_money"].tail(days).tolist()
            avg_daily_inflow = np.mean(recent_inflows)
            
            # 计算流入流出比率
            inflow_days = sum(1 for x in recent_inflows if x > 0)
            outflow_days = sum(1 for x in recent_inflows if x < 0)
            inflow_ratio = inflow_days / max(len(recent_inflows), 1)
            
            # 计算北向资金得分
            if avg_daily_inflow > 5:  # 亿
                northbound_score = min(100, 60 + min(avg_daily_inflow / 10 * 40, 40))
            elif avg_daily_inflow > 0:
                northbound_score = 50 + avg_daily_inflow
            elif avg_daily_inflow > -5:
                northbound_score = 40 + avg_daily_inflow
            else:
                northbound_score = max(0, 30 + avg_daily_inflow / 5 * 10)
            
            # 判断资金趋势
            if avg_daily_inflow > 10:
                flow_trend = "大幅流入"
            elif avg_daily_inflow > 3:
                flow_trend = "持续流入"
            elif avg_daily_inflow > 0:
                flow_trend = "小幅流入"
            elif avg_daily_inflow > -3:
                flow_trend = "小幅流出"
            elif avg_daily_inflow > -10:
                flow_trend = "持续流出"
            else:
                flow_trend = "大幅流出"
            
            # 分析板块偏好（如果有相关数据）
            sector_preference = {}
            
            return {
                "analysis_period": f"{start_date} 至 {end_date}",
                "total_days": len(df),
                "total_net_inflow": round(df["north_money"].sum(), 2),
                "cum_net_inflow": round(df["cum_net_inflow"].iloc[-1], 2),
                "avg_daily_inflow": round(avg_daily_inflow, 2),
                "inflow_days": inflow_days,
                "outflow_days": outflow_days,
                "inflow_ratio": round(inflow_ratio, 2),
                "northbound_score": round(northbound_score, 1),
                "flow_trend": flow_trend,
                "recent_inflows": recent_inflows,
                "sentiment": "乐观" if avg_daily_inflow > 5 else "谨慎" if avg_daily_inflow < -5 else "中性",
                "smart_money": "积极" if inflow_ratio > 0.7 and avg_daily_inflow > 0 else 
                              "撤退" if inflow_ratio < 0.3 and avg_daily_inflow < 0 else 
                              "观望"
            }
            
        except Exception as e:
            logger.error(f"分析北向资金失败: {e}")
            return {"error": str(e)}

    def calculate_fear_greed_index(self) -> Dict:
        """
        计算贪婪恐惧指数（简化版）
        结合多个市场指标
        
        Returns:
            贪婪恐惧指数
        """
        try:
            # 获取各项指标
            market_breadth = self.calculate_market_breadth()
            volume_momentum = self.calculate_volume_momentum(5)
            volatility_index = self.calculate_volatility_index(20)
            limit_ratio = self.calculate_limit_up_down_ratio()
            northbound_flow = self.analyze_northbound_flow(5)
            
            # 提取各项得分
            scores = {}
            
            if "breadth_score" in market_breadth:
                scores["market_breadth"] = market_breadth["breadth_score"]
            
            if "volume_score" in volume_momentum:
                scores["volume_momentum"] = volume_momentum["volume_score"]
            
            if "fear_index" in volatility_index:
                # 恐惧指数转换为贪婪指数（100 - 恐惧指数）
                scores["volatility_index"] = 100 - volatility_index["fear_index"]
            
            if "limit_score" in limit_ratio:
                scores["limit_up_down"] = limit_ratio["limit_score"]
            
            if "northbound_score" in northbound_flow:
                scores["northbound_flow"] = northbound_flow["northbound_score"]
            
            # 计算加权综合指数
            total_score = 0
            total_weight = 0
            
            for indicator, weight in self.SENTIMENT_WEIGHTS.items():
                if indicator in scores:
                    total_score += scores[indicator] * weight
                    total_weight += weight
            
            if total_weight > 0:
                fear_greed_index = total_score / total_weight
            else:
                fear_greed_index = 50
            
            # 确定情绪状态
            if fear_greed_index > 80:
                sentiment_state = "极度贪婪"
                color = "🟢"
            elif fear_greed_index > 60:
                sentiment_state = "贪婪"
                color = "🟡"
            elif fear_greed_index > 40:
                sentiment_state = "中性"
                color = "🟠"
            elif fear_greed_index > 20:
                sentiment_state = "恐惧"
                color = "🔴"
            else:
                sentiment_state = "极度恐惧"
                color = "💀"
            
            # 生成投资建议
            recommendations = []
            if fear_greed_index > 70:
                recommendations.append("市场情绪过热，建议控制仓位，防范风险")
                recommendations.append("避免追高，等待回调机会")
            elif fear_greed_index > 50:
                recommendations.append("市场情绪积极，可适当参与")
                recommendations.append("关注强势板块，把握结构性机会")
            elif fear_greed_index > 30:
                recommendations.append("市场情绪谨慎，建议控制风险")
                recommendations.append("保持谨慎，等待情绪修复")
            else:
                recommendations.append("市场情绪极度悲观，可能是机会")
                recommendations.append("逐步布局超跌优质标的")
            
            return {
                "fear_greed_index": round(fear_greed_index, 1),
                "sentiment_state": sentiment_state,
                "color": color,
                "component_scores": scores,
                "recommendations": recommendations,
                "market_sentiment": "牛市情绪" if fear_greed_index > 70 else 
                                   "平衡市情绪" if fear_greed_index > 40 else 
                                   "熊市情绪",
                "risk_appetite": "高风险偏好" if fear_greed_index > 70 else 
                                "中等风险偏好" if fear_greed_index > 50 else 
                                "低风险偏好"
            }
            
        except Exception as e:
            logger.error(f"计算贪婪恐惧指数失败: {e}")
            return {"error": str(e)}

    def generate_market_sentiment_report(self, comprehensive: bool = True) -> Dict:
        """
        生成市场情绪综合报告
        
        Args:
            comprehensive: 是否生成完整报告
            
        Returns:
            市场情绪报告
        """
        if comprehensive:
            # 完整报告
            market_breadth = self.calculate_market_breadth()
            volume_momentum = self.calculate_volume_momentum(5)
            volatility_index = self.calculate_volatility_index(20)
            limit_ratio = self.calculate_limit_up_down_ratio()
            northbound_flow = self.analyze_northbound_flow(5)
            fear_greed = self.calculate_fear_greed_index()
        else:
            # 简化报告
            market_breadth = self.calculate_market_breadth()
            limit_ratio = self.calculate_limit_up_down_ratio()
            fear_greed = self.calculate_fear_greed_index()
            volume_momentum = {}
            volatility_index = {}
            northbound_flow = {}
        
        # 生成报告摘要
        summary_lines = []
        summary_lines.append("📈 市场情绪分析报告")
        summary_lines.append(f"⏰ 报告时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        if "sentiment_state" in fear_greed:
            summary_lines.append(f"{fear_greed['color']} 市场情绪: {fear_greed['sentiment_state']} ({fear_greed['fear_greed_index']}/100)")
        
        if "breadth_strength" in market_breadth:
            summary_lines.append(f"📊 市场广度: {market_breadth['breadth_strength']} (上涨{market_breadth.get('up_ratio', 0)*100:.1f}%)")
        
        if "limit_sentiment" in limit_ratio:
            summary_lines.append(f"🎯 涨跌停情绪: {limit_ratio['limit_sentiment']} (涨停{limit_ratio.get('limit_up', 0)} : 跌停{limit_ratio.get('limit_down', 0)})")
        
        if "flow_trend" in northbound_flow:
            summary_lines.append(f"💸 北向资金: {northbound_flow['flow_trend']} ({northbound_flow.get('avg_daily_inflow', 0):.1f}亿/日)")
        
        if "volatility_state" in volatility_index:
            summary_lines.append(f"📉 市场波动: {volatility_index['volatility_state']}")
        
        if "volume_trend" in volume_momentum:
            summary_lines.append(f"📈 量能趋势: {volume_momentum['volume_trend']}")
        
        # 市场状态判断
        market_state = "未知"
        if comprehensive:
            positive_signals = 0
            total_signals = 5
            
            if market_breadth.get("breadth_strength", "") in ["强势", "非常强势"]:
                positive_signals += 1
            
            if limit_ratio.get("limit_ratio", 0) > 1.5:
                positive_signals += 1
            
            if northbound_flow.get("avg_daily_inflow", 0) > 0:
                positive_signals += 1
            
            if volatility_index.get("volatility_state", "") in ["低波动", "中等波动"]:
                positive_signals += 1
            
            if volume_momentum.get("volume_trend", "") in ["温和放量", "大幅放量"]:
                positive_signals += 1
            
            positive_ratio = positive_signals / total_signals
            
            if positive_ratio > 0.7:
                market_state = "强市"
            elif positive_ratio > 0.5:
                market_state = "偏强市"
            elif positive_ratio > 0.3:
                market_state = "偏弱市"
            else:
                market_state = "弱市"
        
        summary_lines.append(f"🏆 市场状态: {market_state}")
        
        # 生成建议
        recommendations = []
        
        if "recommendations" in fear_greed:
            recommendations.extend(fear_greed["recommendations"])
        
        if market_breadth.get("up_ratio", 0) > 0.6:
            recommendations.append("市场普涨，可积极布局强势股")
        elif market_breadth.get("down_ratio", 0) > 0.6:
            recommendations.append("市场普跌，建议控制仓位，等待企稳")
        
        if limit_ratio.get("limit_ratio", 0) > 3:
            recommendations.append("涨停个股大幅多于跌停，市场赚钱效应明显")
        elif limit_ratio.get("limit_ratio", 0) < 0.33:
            recommendations.append("跌停个股大幅多于涨停，市场风险较高")
        
        if northbound_flow.get("smart_money", "") == "积极":
            recommendations.append("聪明资金积极流入，可跟随布局")
        elif northbound_flow.get("smart_money", "") == "撤退":
            recommendations.append("聪明资金流出，建议保持谨慎")
        
        return {
            "summary": "\n".join(summary_lines),
            "market_state": market_state,
            "detailed_analysis": {
                "market_breadth": market_breadth,
                "volume_momentum": volume_momentum,
                "volatility_index": volatility_index,
                "limit_up_down": limit_ratio,
                "northbound_flow": northbound_flow,
                "fear_greed_index": fear_greed
            },
            "recommendations": list(set(recommendations))[:5],  # 去重并限制数量
            "report_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "report_type": "comprehensive" if comprehensive else "simplified"
        }