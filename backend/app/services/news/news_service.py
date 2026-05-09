"""
QuantWeave - 新闻资讯服务
集成Tushare新闻API，提供财经新闻获取和分析功能
"""
import tushare as ts
import pandas as pd
from datetime import datetime, timedelta
from loguru import logger
from typing import List, Dict, Optional, Tuple
from sqlalchemy.orm import Session


class NewsService:
    """新闻资讯服务 - 获取和分析财经新闻"""

    def __init__(self, db: Session, tushare_token: str = None):
        self.db = db
        self.tushare_token = tushare_token
        self.pro = ts.pro_api(token=tushare_token) if tushare_token else ts.pro_api()
        
        # 新闻源配置
        self.NEWS_SOURCES = {
            "sina": "新浪财经",
            "wallstreetcn": "华尔街见闻", 
            "10jqka": "同花顺",
            "eastmoney": "东方财富",
            "cls": "财联社",
            "yicai": "第一财经"
        }
        
        # 新闻分类关键词
        self.CATEGORY_KEYWORDS = {
            "政策": ["政策", "监管", "法规", "指导意见", "会议", "讲话", "国务院", "发改委", "证监会"],
            "宏观": ["GDP", "CPI", "PMI", "通胀", "通缩", "利率", "汇率", "货币", "财政", "经济数据"],
            "行业": ["行业", "板块", "产业链", "供应链", "产能", "产量", "需求", "供应", "库存"],
            "公司": ["财报", "业绩", "净利润", "营收", "公告", "增持", "减持", "回购", "分红"],
            "市场": ["大盘", "指数", "涨停", "跌停", "涨跌", "成交", "资金", "北向", "南下", "外资"],
            "科技": ["AI", "人工智能", "芯片", "半导体", "5G", "新能源", "光伏", "锂电池", "自动驾驶"],
            "商品": ["原油", "黄金", "铜", "铝", "钢铁", "煤炭", "农产品", "大宗商品", "期货"],
            "国际": ["美联储", "欧央行", "加息", "降息", "关税", "贸易", "地缘", "冲突", "战争"]
        }

    def fetch_news(self, days: int = 1, sources: List[str] = None) -> pd.DataFrame:
        """
        获取指定天数的新闻
        
        Args:
            days: 获取最近多少天的新闻
            sources: 新闻源列表，默认使用所有配置的新闻源
            
        Returns:
            DataFrame包含新闻数据
        """
        if sources is None:
            sources = list(self.NEWS_SOURCES.keys())
        
        end_time = datetime.now()
        start_time = end_time - timedelta(days=days)
        
        all_news = []
        
        for source in sources:
            if source not in self.NEWS_SOURCES:
                logger.warning(f"未知新闻源: {source}")
                continue
                
            try:
                df = self.pro.news(
                    src=source,
                    start_date=start_time.strftime("%Y-%m-%d %H:%M:%S"),
                    end_date=end_time.strftime("%Y-%m-%d %H:%M:%S")
                )
                
                if not df.empty:
                    df["source"] = source
                    df["source_name"] = self.NEWS_SOURCES[source]
                    all_news.append(df)
                    logger.info(f"从{self.NEWS_SOURCES[source]}获取{len(df)}条新闻")
                else:
                    logger.info(f"从{self.NEWS_SOURCES[source]}未获取到新闻")
                    
            except Exception as e:
                logger.error(f"获取{self.NEWS_SOURCES[source]}新闻失败: {e}")
                continue
        
        if all_news:
            return pd.concat(all_news, ignore_index=True)
        else:
            return pd.DataFrame()

    def categorize_news(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        对新闻进行分类
        
        Args:
            df: 新闻数据
            
        Returns:
            添加分类列的数据
        """
        if df.empty:
            return df
        
        # 先创建分类列
        df["categories"] = ""
        
        for idx, row in df.iterrows():
            content = str(row.get("content", "")) + " " + str(row.get("title", ""))
            content_lower = content.lower()
            
            detected_categories = []
            for category, keywords in self.CATEGORY_KEYWORDS.items():
                for keyword in keywords:
                    if keyword.lower() in content_lower:
                        detected_categories.append(category)
                        break
            
            # 去重
            detected_categories = list(set(detected_categories))
            df.at[idx, "categories"] = ",".join(detected_categories) if detected_categories else "其他"
        
        return df

    def analyze_news_sentiment(self, df: pd.DataFrame) -> Dict:
        """
        分析新闻情感
        
        Args:
            df: 新闻数据
            
        Returns:
            情感分析结果
        """
        if df.empty:
            return {
                "total_news": 0,
                "positive_count": 0,
                "negative_count": 0,
                "neutral_count": 0,
                "sentiment_score": 0.0,
                "hot_topics": [],
                "sources_distribution": {}
            }
        
        # 简单情感关键词分析（实际应用中可使用NLP模型）
        positive_keywords = ["增长", "利好", "上涨", "提升", "改善", "复苏", "创新高", "突破", "超预期"]
        negative_keywords = ["下跌", "下滑", "利空", "风险", "警告", "亏损", "下降", "放缓", "危机", "冲突"]
        
        positive_count = 0
        negative_count = 0
        neutral_count = 0
        
        for _, row in df.iterrows():
            content = str(row.get("content", ""))
            content_lower = content.lower()
            
            positive_score = sum(1 for kw in positive_keywords if kw in content_lower)
            negative_score = sum(1 for kw in negative_keywords if kw in content_lower)
            
            if positive_score > negative_score:
                positive_count += 1
            elif negative_score > positive_score:
                negative_count += 1
            else:
                neutral_count += 1
        
        total = len(df)
        sentiment_score = (positive_count - negative_count) / max(total, 1)
        
        # 热门话题分析（按分类）
        if "categories" in df.columns:
            category_counts = {}
            for categories in df["categories"]:
                if pd.isna(categories) or not categories:
                    continue
                for cat in categories.split(","):
                    if cat != "其他":
                        category_counts[cat] = category_counts.get(cat, 0) + 1
            
            hot_topics = sorted(category_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        else:
            hot_topics = []
        
        # 新闻源分布
        sources_distribution = {}
        if "source_name" in df.columns:
            for source in df["source_name"]:
                sources_distribution[source] = sources_distribution.get(source, 0) + 1
        
        return {
            "total_news": total,
            "positive_count": positive_count,
            "negative_count": negative_count,
            "neutral_count": neutral_count,
            "sentiment_score": round(sentiment_score, 3),
            "hot_topics": hot_topics,
            "sources_distribution": sources_distribution
        }

    def extract_stock_mentions(self, df: pd.DataFrame) -> Dict[str, int]:
        """
        提取新闻中提到的股票
        
        Args:
            df: 新闻数据
            
        Returns:
            股票提及次数统计
        """
        # 此处简化实现，实际应用中可以更复杂
        # 可以从数据库获取股票列表进行匹配
        from ..data.data_service import DataService
        
        stock_mentions = {}
        
        try:
            data_service = DataService(self.db, self.tushare_token)
            stocks = data_service.get_stock_list()
            stock_names = {stock["name"]: stock["ts_code"] for stock in stocks}
            
            for _, row in df.iterrows():
                content = str(row.get("content", ""))
                title = str(row.get("title", ""))
                text = title + " " + content
                
                for stock_name, ts_code in stock_names.items():
                    if stock_name in text:
                        stock_mentions[ts_code] = stock_mentions.get(ts_code, 0) + 1
                        # 同时检查是否包含公司简称（去除"股份"等字样）
                        short_name = stock_name.replace("股份", "").replace("有限", "").replace("公司", "").strip()
                        if short_name and short_name in text and short_name != stock_name:
                            stock_mentions[ts_code] = stock_mentions.get(ts_code, 0) + 1
        except Exception as e:
            logger.error(f"提取股票提及失败: {e}")
        
        # 按提及次数排序
        return dict(sorted(stock_mentions.items(), key=lambda x: x[1], reverse=True)[:10])

    def generate_news_summary(self, days: int = 1) -> Dict:
        """
        生成新闻摘要报告
        
        Args:
            days: 分析最近多少天的新闻
            
        Returns:
            新闻摘要报告
        """
        # 获取新闻
        news_df = self.fetch_news(days=days)
        
        if news_df.empty:
            return {
                "summary": "无近期新闻数据",
                "total_news": 0,
                "sentiment": "中性",
                "hot_topics": [],
                "stock_mentions": {},
                "recommendations": []
            }
        
        # 分类和情感分析
        news_df = self.categorize_news(news_df)
        sentiment_result = self.analyze_news_sentiment(news_df)
        stock_mentions = self.extract_stock_mentions(news_df)
        
        # 生成摘要文本
        summary_lines = []
        summary_lines.append(f"📰 过去{days}天财经新闻摘要")
        summary_lines.append(f"总计新闻: {sentiment_result['total_news']}条")
        
        if sentiment_result['sentiment_score'] > 0.1:
            sentiment = "乐观"
        elif sentiment_result['sentiment_score'] < -0.1:
            sentiment = "谨慎"
        else:
            sentiment = "中性"
        
        summary_lines.append(f"市场情绪: {sentiment} (得分: {sentiment_result['sentiment_score']})")
        summary_lines.append(f"正面新闻: {sentiment_result['positive_count']}条, 负面新闻: {sentiment_result['negative_count']}条")
        
        if sentiment_result['hot_topics']:
            summary_lines.append("🔥 热门话题:")
            for topic, count in sentiment_result['hot_topics']:
                summary_lines.append(f"  • {topic}: {count}条")
        
        if stock_mentions:
            summary_lines.append("📈 热门提及股票:")
            for ts_code, count in list(stock_mentions.items())[:5]:
                summary_lines.append(f"  • {ts_code}: {count}次")
        
        # 基于分析生成建议
        recommendations = []
        if sentiment_result['hot_topics']:
            hot_topic = sentiment_result['hot_topics'][0][0]
            recommendations.append(f"关注{hot_topic}相关板块和个股")
        
        if sentiment_result['sentiment_score'] > 0.2:
            recommendations.append("市场情绪积极，可适当增加仓位")
        elif sentiment_result['sentiment_score'] < -0.2:
            recommendations.append("市场情绪谨慎，建议控制风险")
        
        if stock_mentions:
            top_stock = list(stock_mentions.keys())[0]
            recommendations.append(f"{top_stock}被频繁提及，值得关注")
        
        return {
            "summary": "\n".join(summary_lines),
            "total_news": sentiment_result['total_news'],
            "sentiment": sentiment,
            "sentiment_score": sentiment_result['sentiment_score'],
            "hot_topics": sentiment_result['hot_topics'],
            "stock_mentions": stock_mentions,
            "recommendations": recommendations
        }

    def get_urgent_news(self, hours: int = 24) -> List[Dict]:
        """
        获取紧急重要新闻（高相关性）
        
        Args:
            hours: 最近多少小时
            
        Returns:
            紧急新闻列表
        """
        urgent_keywords = [
            "紧急", "突发", "重大", "重要", "警告", "风险", "危机", "冲突",
            "暴涨", "暴跌", "业绩", "大跌", "涨停", "跌停",
            "Trump", "特朗普", "关税", "谈判", "制裁",
            "降息", "加息", "美股", "美联储", "护盘", "救市",
            "减持", "回购", "增持", "ST", "退市", "爆雷"
        ]
        
        end_time = datetime.now()
        start_time = end_time - timedelta(hours=hours)
        
        try:
            df = self.pro.news(
                src="cls",  # 财联社以快讯著称
                start_date=start_time.strftime("%Y-%m-%d %H:%M:%S"),
                end_date=end_time.strftime("%Y-%m-%d %H:%M:%S")
            )
            
            if df.empty:
                return []
            
            urgent_news = []
            for _, row in df.iterrows():
                title = str(row.get("title", ""))
                content = str(row.get("content", ""))
                text = title + " " + content
                
                # 检查是否包含紧急关键词
                for keyword in urgent_keywords:
                    if keyword in text:
                        urgent_news.append({
                            "datetime": row.get("datetime"),
                            "title": title[:100] + "..." if len(title) > 100 else title,
                            "content": content[:200] + "..." if len(content) > 200 else content,
                            "urgency_keyword": keyword
                        })
                        break
            
            return urgent_news[:10]  # 返回最多10条
            
        except Exception as e:
            logger.error(f"获取紧急新闻失败: {e}")
            return []