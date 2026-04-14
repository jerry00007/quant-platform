"""
QuantWeave - 增强版晨报服务
整合新闻、板块、市场情绪、持仓分析，生成AI操盘手级别晨报
"""
import tushare as ts
import pandas as pd
from datetime import datetime, timedelta
from loguru import logger
from typing import List, Dict, Optional, Tuple, Any
from sqlalchemy.orm import Session

from ..news.news_service import NewsService
from ..sector.sector_service import SectorService
from ..market.market_sentiment_service import MarketSentimentService
from ..portfolio.portfolio_service import PortfolioService
from ..signal.signal_service import SignalService
from ..data.data_service import DataService
from ..data.neodata_service import NeoDataService


class EnhancedMorningBriefService:
    """增强版晨报服务 - AI操盘手级别晨报生成"""

    def __init__(self, db: Session, tushare_token: str = None):
        self.db = db
        self.tushare_token = tushare_token
        
        # 初始化Tushare Pro API
        if tushare_token:
            ts.set_token(tushare_token)
            self.pro = ts.pro_api()
        else:
            self.pro = None
        
        # 初始化所有服务
        self.news_service = NewsService(db, tushare_token)
        self.sector_service = SectorService(db, tushare_token)
        self.market_service = MarketSentimentService(db, tushare_token)
        self.portfolio_service = PortfolioService()
        self.signal_service = SignalService(db, DataService(db, tushare_token))
        self.neodata_service = NeoDataService()
        
        # 晨报模板配置
        self.TEMPLATE_SECTIONS = [
            "market_overview",      # 市场概览
            "urgent_news",          # 紧急要闻
            "sector_analysis",      # 板块分析
            "sentiment_index",      # 情绪指数
            "portfolio_status",     # 持仓状态
            "trading_signals",      # 交易信号
            "risk_alerts",          # 风险提示
            "today_strategy"        # 今日策略
        ]

    def generate_comprehensive_brief(self, account_name: str = "main") -> Dict:
        """
        生成全面晨报
        
        Args:
            account_name: 账户名称
            
        Returns:
            全面晨报内容
        """
        logger.info(f"🚀 开始生成AI操盘手级别晨报，账户: {account_name}")
        
        try:
            # 并行收集所有数据（在实际应用中应使用异步）
            data = self._collect_all_data(account_name)
            
            # 生成各章节内容
            sections = {}
            for section_key in self.TEMPLATE_SECTIONS:
                section_content = self._generate_section(section_key, data)
                if section_content:
                    sections[section_key] = section_content
            
            # 生成最终晨报
            brief = self._assemble_brief(sections, data)
            
            logger.info(f"✅ 晨报生成完成，总长度: {len(brief)}字符")
            return {
                "success": True,
                "brief": brief,
                "sections": sections,
                "data_summary": self._create_data_summary(data),
                "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            
        except Exception as e:
            logger.error(f"生成晨报失败: {e}")
            return {
                "success": False,
                "error": str(e),
                "fallback_brief": self._generate_fallback_brief()
            }

    def _collect_all_data(self, account_name: str) -> Dict[str, Any]:
        """收集所有需要的数据"""
        logger.info("📊 开始收集晨报数据...")
        
        data = {
            "timestamp": datetime.now(),
            "account_name": account_name
        }
        
        try:
            # 1. 新闻数据（仅过去1天）
            logger.info("  获取新闻数据...")
            data["news_summary"] = self.news_service.generate_news_summary(days=1)
            data["urgent_news"] = self.news_service.get_urgent_news(hours=24)
            
            # 2. 板块数据
            logger.info("  获取板块数据...")
            data["sector_report"] = self.sector_service.generate_sector_report(days=3)
            
            # 3. 市场情绪数据
            logger.info("  获取市场情绪数据...")
            data["market_sentiment"] = self.market_service.generate_market_sentiment_report(comprehensive=True)
            
            # 4. 持仓数据
            logger.info("  获取持仓数据...")
            data["portfolio_status"] = self.portfolio_service.get_account_summary(self.db, account_name)
            data["positions"] = self.portfolio_service.get_positions_summary(self.db, account_name)
            data["recent_transactions"] = self.portfolio_service.get_recent_transactions(self.db, account_name, limit=5)
            
            # 5. 交易信号
            logger.info("  获取交易信号...")
            # 使用持仓中的股票作为关注列表
            if data["positions"] and "positions" in data["positions"]:
                position_codes = [pos["ts_code"] for pos in data["positions"]["positions"]]
                data["trading_signals"] = self.signal_service.generate_daily_signals(stock_codes=position_codes)
            else:
                data["trading_signals"] = self.signal_service.generate_daily_signals()
            
            # 6. 指数数据
            logger.info("  获取指数数据...")
            data["indices"] = self._get_major_indices()
            
            logger.info("✅ 数据收集完成")
            
        except Exception as e:
            logger.error(f"数据收集失败: {e}")
            # 继续使用已收集的数据
            
        return data

    def _generate_section(self, section_key: str, data: Dict) -> str:
        """生成单个章节内容"""
        try:
            if section_key == "market_overview":
                return self._generate_market_overview(data)
            elif section_key == "urgent_news":
                return self._generate_urgent_news(data)
            elif section_key == "sector_analysis":
                return self._generate_sector_analysis(data)
            elif section_key == "sentiment_index":
                return self._generate_sentiment_index(data)
            elif section_key == "portfolio_status":
                return self._generate_portfolio_status(data)
            elif section_key == "trading_signals":
                return self._generate_trading_signals(data)
            elif section_key == "risk_alerts":
                return self._generate_risk_alerts(data)
            elif section_key == "today_strategy":
                return self._generate_today_strategy(data)
            else:
                return ""
        except Exception as e:
            logger.error(f"生成章节 {section_key} 失败: {e}")
            return ""

    def _generate_market_overview(self, data: Dict) -> str:
        """生成市场概览"""
        lines = ["📊 市场概览", ""]
        
        # 指数表现
        if "indices" in data and data["indices"]:
            lines.append("📈 主要指数:")
            for idx in data["indices"][:3]:  # 显示前3个
                lines.append(f"  • {idx['name']}: {idx['close']:.2f} ({idx['change_pct']:+.2f}%) [{idx['status']}]")
            lines.append("")
        
        # 市场广度
        market_breadth = data.get("market_sentiment", {}).get("detailed_analysis", {}).get("market_breadth", {})
        if market_breadth and "breadth_strength" in market_breadth:
            lines.append(f"🌐 市场广度: {market_breadth['breadth_strength']}")
            lines.append(f"   上涨: {market_breadth.get('up_ratio', 0)*100:.1f}% | 下跌: {market_breadth.get('down_ratio', 0)*100:.1f}%")
            lines.append("")
        
        # 成交量
        volume_data = data.get("market_sentiment", {}).get("detailed_analysis", {}).get("volume_momentum", {})
        if volume_data and "volume_trend" in volume_data:
            lines.append(f"📉 量能趋势: {volume_data['volume_trend']}")
            if "avg_volume_ratio" in volume_data:
                lines.append(f"   量比均值: {volume_data['avg_volume_ratio']:.2f}")
            lines.append("")
        
        # 市场状态
        if "market_sentiment" in data and "market_state" in data["market_sentiment"]:
            lines.append(f"🏆 市场状态: {data['market_sentiment']['market_state']}")
        
        return "\n".join(lines)

    def _generate_urgent_news(self, data: Dict) -> str:
        """生成紧急要闻"""
        urgent_news = data.get("urgent_news", [])
        news_summary = data.get("news_summary", {})
        
        if not urgent_news and not news_summary.get("total_news", 0):
            return ""
        
        lines = ["🚨 紧急要闻", ""]
        
        if urgent_news:
            lines.append(f"过去24小时紧急新闻 ({len(urgent_news)}条):")
            for i, news in enumerate(urgent_news[:3], 1):  # 最多3条
                time_str = news.get("datetime", "")[:16] if news.get("datetime") else "时间未知"
                lines.append(f"{i}. [{time_str}] {news.get('title', '')}")
            lines.append("")
        
        if news_summary.get("total_news", 0) > 0:
            lines.append(f"📰 过去24小时财经新闻: {news_summary['total_news']}条")
            lines.append(f"市场情绪: {news_summary.get('sentiment', '中性')}")
            
            if news_summary.get("hot_topics"):
                lines.append("🔥 热门话题:")
                for topic, count in news_summary["hot_topics"][:3]:
                    lines.append(f"  • {topic}: {count}条")
            
            if news_summary.get("stock_mentions"):
                lines.append("📈 高频提及股票:")
                for ts_code, count in list(news_summary["stock_mentions"].items())[:3]:
                    lines.append(f"  • {ts_code}: {count}次")
        
        return "\n".join(lines)

    def _generate_sector_analysis(self, data: Dict) -> str:
        """生成板块分析"""
        sector_report = data.get("sector_report", {})
        if not sector_report or "summary" not in sector_report:
            return ""
        
        lines = ["🔥 板块分析", ""]
        
        # 热点板块
        performance = sector_report.get("performance", {})
        if performance and "hot_sectors" in performance:
            lines.append("📈 热点板块:")
            for sector_code, perf in performance["hot_sectors"][:3]:
                lines.append(f"  • {sector_code}: {perf['change_pct']}% ({perf['trend']})")
            lines.append("")
        
        # 资金流向
        if performance and "volume_leaders" in performance:
            lines.append("💰 资金流入板块:")
            for sector_code, perf in performance["volume_leaders"][:3]:
                lines.append(f"  • {sector_code}: 量比{perf['volume_ratio']}倍")
            lines.append("")
        
        # 板块轮动
        rotation = sector_report.get("rotation", {})
        if rotation and "rotation_stage" in rotation:
            lines.append(f"🔄 板块轮动: {rotation['rotation_stage']}")
        
        # 投资建议
        if sector_report.get("recommendations"):
            lines.append("💡 板块建议:")
            for rec in sector_report["recommendations"][:2]:
                lines.append(f"  • {rec}")
        
        return "\n".join(lines)

    def _generate_sentiment_index(self, data: Dict) -> str:
        """生成情绪指数"""
        market_sentiment = data.get("market_sentiment", {})
        if not market_sentiment or "summary" not in market_sentiment:
            return ""
        
        lines = ["🎭 市场情绪指数", ""]
        
        # 贪婪恐惧指数
        fear_greed = market_sentiment.get("detailed_analysis", {}).get("fear_greed_index", {})
        if fear_greed and "fear_greed_index" in fear_greed:
            lines.append(f"{fear_greed.get('color', '⚪')} 贪婪恐惧指数: {fear_greed['fear_greed_index']}/100")
            lines.append(f"情绪状态: {fear_greed.get('sentiment_state', '未知')}")
            lines.append(f"风险偏好: {fear_greed.get('risk_appetite', '未知')}")
            lines.append("")
        
        # 涨跌停情绪
        limit_data = market_sentiment.get("detailed_analysis", {}).get("limit_up_down", {})
        if limit_data and "limit_sentiment" in limit_data:
            lines.append(f"🎯 涨跌停情绪: {limit_data['limit_sentiment']}")
            lines.append(f"涨停: {limit_data.get('limit_up', 0)} | 跌停: {limit_data.get('limit_down', 0)}")
            lines.append(f"涨跌停比: {limit_data.get('limit_ratio', 0):.2f}")
            lines.append("")
        
        # 北向资金
        northbound = market_sentiment.get("detailed_analysis", {}).get("northbound_flow", {})
        if northbound and "flow_trend" in northbound:
            lines.append(f"💸 北向资金: {northbound['flow_trend']}")
            lines.append(f"日均净流入: {northbound.get('avg_daily_inflow', 0):.1f}亿")
            lines.append(f"聪明资金态度: {northbound.get('smart_money', '未知')}")
        
        return "\n".join(lines)

    def _generate_portfolio_status(self, data: Dict) -> str:
        """生成持仓状态"""
        portfolio_status = data.get("portfolio_status", {})
        positions = data.get("positions", {})
        
        if not portfolio_status or "total_assets" not in portfolio_status:
            return ""
        
        lines = ["💰 持仓状态", ""]
        
        # 账户概览
        lines.append(f"账户: {data.get('account_name', 'main')}")
        lines.append(f"总资产: ¥{portfolio_status.get('total_assets', 0):,.2f}")
        lines.append(f"现金余额: ¥{portfolio_status.get('cash_balance', 0):,.2f}")
        lines.append(f"持仓市值: ¥{portfolio_status.get('market_value', 0):,.2f}")
        lines.append(f"浮动盈亏: ¥{portfolio_status.get('profit', 0):,.2f} ({portfolio_status.get('profit_pct', 0):+.2f}%)")
        lines.append("")
        
        # 持仓详情
        if positions and "positions" in positions and positions["positions"]:
            lines.append("📋 持仓明细:")
            for pos in positions["positions"][:5]:  # 最多显示5个
                profit_pct = (pos.get("current_value", 0) / max(pos.get("cost", 1), 1) - 1) * 100
                lines.append(f"  • {pos.get('name', '')}({pos.get('ts_code', '')})")
                lines.append(f"    持仓: {pos.get('volume', 0)}股 | 成本: {pos.get('avg_cost', 0):.2f}")
                lines.append(f"    现价: {pos.get('current_price', 0):.2f} | 盈亏: {profit_pct:+.2f}%")
            lines.append("")
        
        # 交易流水
        recent_transactions = data.get("recent_transactions", [])
        if recent_transactions:
            lines.append("📝 最近交易:")
            for txn in recent_transactions[:3]:  # 最近3笔
                txn_type = "买入" if txn.get("action") == "buy" else "卖出"
                lines.append(f"  • {txn.get('transaction_date', '')}: {txn_type} {txn.get('ts_code', '')} {txn.get('volume', 0)}股")
        
        return "\n".join(lines)

    def _generate_trading_signals(self, data: Dict) -> str:
        """生成交易信号"""
        trading_signals = data.get("trading_signals", {})
        
        if not trading_signals or not trading_signals.get("signals"):
            return ""
        
        lines = ["📡 今日交易信号", ""]
        
        signals = trading_signals["signals"]
        buy_signals = [s for s in signals if s.get("action") == "buy"]
        sell_signals = [s for s in signals if s.get("action") == "sell"]
        
        if buy_signals:
            lines.append("🟢 买入建议:")
            for signal in buy_signals[:3]:  # 最多3个
                lines.append(f"  • {signal.get('name', '')}({signal.get('ts_code', '')})")
                lines.append(f"    现价: {signal.get('price', 0):.2f} | 止损: {signal.get('stop_loss', 0):.2f}")
                lines.append(f"    止盈: {signal.get('take_profit', 0):.2f} | 策略: {','.join(signal.get('strategies', ['']))}")
            lines.append("")
        
        if sell_signals:
            lines.append("🔴 卖出建议:")
            for signal in sell_signals[:3]:  # 最多3个
                lines.append(f"  • {signal.get('name', '')}({signal.get('ts_code', '')})")
                lines.append(f"    现价: {signal.get('price', 0):.2f} | 策略: {','.join(signal.get('strategies', ['']))}")
            lines.append("")
        
        # 信号统计
        summary = trading_signals.get("summary", {})
        if summary:
            lines.append(f"📊 信号统计: 买入{summary.get('buy', 0)} | 卖出{summary.get('sell', 0)} | 观望{summary.get('hold', 0)}")
        
        return "\n".join(lines)

    def _generate_risk_alerts(self, data: Dict) -> str:
        """生成风险提示"""
        lines = ["⚠️ 风险提示", ""]
        
        # 市场风险
        market_sentiment = data.get("market_sentiment", {})
        if market_sentiment:
            fear_greed = market_sentiment.get("detailed_analysis", {}).get("fear_greed_index", {})
            if fear_greed and fear_greed.get("fear_greed_index", 50) > 80:
                lines.append("• 市场情绪过热，存在回调风险")
            elif fear_greed and fear_greed.get("fear_greed_index", 50) < 20:
                lines.append("• 市场情绪极度悲观，可能存在超跌反弹机会")
            
            volatility = market_sentiment.get("detailed_analysis", {}).get("volatility_index", {})
            if volatility and volatility.get("volatility_state") in ["高波动", "中高波动"]:
                lines.append("• 市场波动率较高，注意控制仓位风险")
        
        # 板块风险
        sector_report = data.get("sector_report", {})
        if sector_report:
            performance = sector_report.get("performance", {})
            if performance and performance.get("limit_down_count", 0) > 5:
                lines.append("• 多个板块跌停，市场风险较高")
        
        # 新闻风险
        news_summary = data.get("news_summary", {})
        if news_summary and news_summary.get("sentiment_score", 0) < -0.2:
            lines.append("• 新闻情绪偏负面，需关注政策风险")
        
        # 持仓风险
        portfolio_status = data.get("portfolio_status", {})
        if portfolio_status:
            max_drawdown = portfolio_status.get("max_drawdown", 0)
            if max_drawdown > 10:  # 最大回撤超过10%
                lines.append(f"• 账户最大回撤达{max_drawdown:.1f}%，需注意风险控制")
        
        if len(lines) == 2:  # 只有标题和空行
            lines.append("• 当前市场风险相对可控")
        
        return "\n".join(lines)

    def _generate_today_strategy(self, data: Dict) -> str:
        """生成今日策略"""
        lines = ["🎯 今日操作策略", ""]
        
        # 综合市场判断
        market_state = data.get("market_sentiment", {}).get("market_state", "未知")
        
        if market_state == "强市":
            lines.append("📈 市场强势，建议积极操作:")
            lines.append("  • 关注热点板块，把握强势股机会")
            lines.append("  • 可适当提高仓位至7-8成")
            lines.append("  • 重点布局有资金流入的品种")
        elif market_state == "偏强市":
            lines.append("📊 市场偏强，建议稳健操作:")
            lines.append("  • 关注结构性机会，精选个股")
            lines.append("  • 仓位控制在5-7成")
            lines.append("  • 注意高低切换，避免追高")
        elif market_state == "偏弱市":
            lines.append("📉 市场偏弱，建议谨慎操作:")
            lines.append("  • 控制仓位，以防守为主")
            lines.append("  • 仓位控制在3-5成")
            lines.append("  • 关注超跌反弹机会")
        elif market_state == "弱市":
            lines.append("⚠️ 市场弱势，建议观望为主:")
            lines.append("  • 严格控制仓位，不超过3成")
            lines.append("  • 多看少动，等待右侧机会")
            lines.append("  • 避免盲目抄底")
        else:
            lines.append("⚪ 市场状态不明，建议观望:")
            lines.append("  • 等待市场方向明确")
            lines.append("  • 仓位控制在5成以下")
            lines.append("  • 关注重大消息面变化")
        
        lines.append("")
        
        # 具体建议
        recommendations = []
        
        # 从各服务收集建议
        if data.get("news_summary", {}).get("recommendations"):
            recommendations.extend(data["news_summary"]["recommendations"][:2])
        
        if data.get("sector_report", {}).get("recommendations"):
            recommendations.extend(data["sector_report"]["recommendations"][:2])
        
        if data.get("market_sentiment", {}).get("recommendations"):
            recommendations.extend(data["market_sentiment"]["recommendations"][:2])
        
        if recommendations:
            lines.append("💡 具体建议:")
            for rec in recommendations[:3]:
                lines.append(f"  • {rec}")
        
        return "\n".join(lines)

    def _get_major_indices(self) -> List[Dict]:
        """获取主要指数数据（优先使用NeoData，失败后回退到Tushare）"""
        try:
            # 首先尝试使用NeoData（更实时）
            logger.info("📊 尝试通过NeoData获取指数数据...")
            neodata_results = self.neodata_service.get_major_indices()
            
            if neodata_results:
                logger.info(f"✅ NeoData返回{len(neodata_results)}个指数数据")
                results = []
                for idx in neodata_results:
                    # 解析NeoData返回的数据
                    content = idx.get("content", "")
                    latest = idx.get("latest", "0")
                    change_pct = idx.get("change_pct", "0%")
                    
                    try:
                        # 提取数值
                        close_val = float(latest.replace(",", "")) if latest != "0" else 0
                        change_pct_val = float(change_pct.strip("%")) if "%" in change_pct else 0
                        
                        # 判断状态
                        if change_pct_val > 1.5:
                            status = "强势"
                        elif change_pct_val > 0:
                            status = "上涨"
                        elif change_pct_val > -1.5:
                            status = "调整"
                        else:
                            status = "弱势"
                        
                        results.append({
                            "code": "",  # NeoData可能不返回代码
                            "name": idx.get("name", "未知指数"),
                            "close": round(close_val, 2),
                            "change": round(close_val * change_pct_val / 100, 2),
                            "change_pct": round(change_pct_val, 2),
                            "status": status,
                            "source": "neodata"
                        })
                    except Exception as e:
                        logger.warning(f"解析NeoData指数数据失败: {e}")
                        continue
                
                if results:
                    return results
            
            # NeoData失败或无数据，回退到Tushare
            logger.info("📊 NeoData不可用，回退到Tushare...")
            if self.pro is None:
                logger.warning("Tushare Pro API未初始化")
                return []
            
            # 主要指数代码
            indices = [
                {"code": "000001.SH", "name": "上证指数"},
                {"code": "399001.SZ", "name": "深证成指"},
                {"code": "399006.SZ", "name": "创业板指"},
                {"code": "000016.SH", "name": "上证50"},
                {"code": "000300.SH", "name": "沪深300"},
                {"code": "000905.SH", "name": "中证500"}
            ]
            
            today = datetime.now().strftime("%Y%m%d")
            yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
            
            results = []
            for idx in indices:
                try:
                    df = self.pro.index_daily(
                        ts_code=idx["code"],
                        trade_date=today
                    )
                    
                    if df.empty:
                        df = self.pro.index_daily(
                            ts_code=idx["code"],
                            trade_date=yesterday
                        )
                    
                    if not df.empty:
                        latest = df.iloc[0]
                        prev_close = latest["pre_close"]
                        current_close = latest["close"]
                        change = current_close - prev_close
                        change_pct = change / prev_close * 100 if prev_close > 0 else 0
                        
                        # 判断状态
                        if change_pct > 1.5:
                            status = "强势"
                        elif change_pct > 0:
                            status = "上涨"
                        elif change_pct > -1.5:
                            status = "调整"
                        else:
                            status = "弱势"
                        
                        results.append({
                            "code": idx["code"],
                            "name": idx["name"],
                            "close": round(current_close, 2),
                            "change": round(change, 2),
                            "change_pct": round(change_pct, 2),
                            "status": status,
                            "source": "tushare"
                        })
                except Exception as e:
                    logger.warning(f"获取指数{idx['name']}数据失败: {e}")
                    continue
            
            return results
            
        except Exception as e:
            logger.error(f"获取主要指数失败: {e}")
            return []

    def _assemble_brief(self, sections: Dict[str, str], data: Dict) -> str:
        """组装完整晨报"""
        lines = []
        
        # 标题和时间
        lines.append("=" * 50)
        lines.append("🚀 QuantWeave AI操盘手晨报")
        lines.append(f"📅 {datetime.now().strftime('%Y年%m月%d日 %A')}")
        lines.append(f"⏰ {datetime.now().strftime('%H:%M:%S')}")
        lines.append("=" * 50)
        lines.append("")
        
        # 按顺序添加各个章节
        for section_key in self.TEMPLATE_SECTIONS:
            if section_key in sections and sections[section_key]:
                lines.append(sections[section_key])
                lines.append("")  # 章节间空行
        
        # 结尾
        lines.append("=" * 50)
        lines.append("📊 数据来源: Tushare Pro API")
        lines.append("🤖 AI分析: QuantWeave 量化交易平台")
        lines.append("⚠️ 风险提示: 股市有风险，投资需谨慎")
        lines.append("=" * 50)
        
        return "\n".join(lines)

    def _create_data_summary(self, data: Dict) -> Dict:
        """创建数据汇总"""
        summary = {
            "data_sources": [],
            "data_points": 0,
            "collection_time": data.get("timestamp", datetime.now()).strftime("%Y-%m-%d %H:%M:%S")
        }
        
        # 统计数据源
        if data.get("news_summary"):
            summary["data_sources"].append("财经新闻")
            summary["data_points"] += data["news_summary"].get("total_news", 0)
        
        if data.get("sector_report"):
            summary["data_sources"].append("板块数据")
        
        if data.get("market_sentiment"):
            summary["data_sources"].append("市场情绪")
        
        if data.get("portfolio_status"):
            summary["data_sources"].append("持仓数据")
        
        if data.get("trading_signals"):
            summary["data_sources"].append("交易信号")
            summary["data_points"] += len(data["trading_signals"].get("signals", []))
        
        return summary

    def _generate_fallback_brief(self) -> str:
        """生成降级晨报（当主服务失败时）"""
        current_time = datetime.now().strftime("%H:%M")
        
        return f"""🚀 QuantWeave 晨报（降级模式）
📅 {datetime.now().strftime('%Y年%m月%d日')}
⏰ {current_time}

⚠️ 晨报服务暂时降级
因数据服务暂时不可用，今日生成简化版晨报。

📊 建议操作：
• 关注持仓股票的最新公告
• 查看市场重要新闻
• 控制仓位，防范风险
• 等待系统恢复后获取详细分析

📞 技术支持：
数据服务正在恢复中，请稍后重试。

⚠️ 投资有风险，决策需谨慎
"""

    def generate_quick_brief(self, account_name: str = "main") -> str:
        """
        生成快速晨报（简化版）
        
        Args:
            account_name: 账户名称
            
        Returns:
            简化版晨报
        """
        try:
            # 获取最基本的数据
            portfolio_status = self.portfolio_service.get_account_summary(self.db, account_name)
            trading_signals = self.signal_service.generate_daily_signals()
            news_summary = self.news_service.generate_news_summary(days=1)
            
            lines = []
            lines.append("🚀 QuantWeave 快速晨报")
            lines.append(f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M')}")
            lines.append("")
            
            # 账户状态
            if portfolio_status:
                lines.append(f"💰 账户: {account_name}")
                lines.append(f"总资产: ¥{portfolio_status.get('total_assets', 0):,.2f}")
                lines.append(f"盈亏: {portfolio_status.get('profit_pct', 0):+.2f}%")
                lines.append("")
            
            # 交易信号
            if trading_signals and trading_signals.get("signals"):
                buy_count = len([s for s in trading_signals["signals"] if s.get("action") == "buy"])
                sell_count = len([s for s in trading_signals["signals"] if s.get("action") == "sell"])
                
                lines.append(f"📡 今日信号: 买入{buy_count} | 卖出{sell_count}")
                if buy_count > 0:
                    lines.append("建议关注买入信号个股")
                lines.append("")
            
            # 新闻摘要
            if news_summary and news_summary.get("total_news", 0) > 0:
                lines.append(f"📰 财经新闻: {news_summary['total_news']}条")
                lines.append(f"市场情绪: {news_summary.get('sentiment', '中性')}")
                lines.append("")
            
            lines.append("💡 今日策略:")
            lines.append("• 关注持仓股票表现")
            lines.append("• 控制仓位，做好风险控制")
            lines.append("• 等待详细晨报生成")
            lines.append("")
            lines.append("⚠️ 此为快速晨报，详细分析请稍后")
            
            return "\n".join(lines)
            
        except Exception as e:
            logger.error(f"生成快速晨报失败: {e}")
            return self._generate_fallback_brief()