"""
NeoData 金融数据服务
集成 NeoData Financial Search 技能，提供自然语言金融数据查询
"""
import os
import json
import requests
from typing import Dict, Any, Optional, List
from loguru import logger

class NeoDataService:
    """NeoData 金融数据服务"""
    
    # 默认端点
    DEFAULT_ENDPOINT = "https://copilot.tencent.com/agenttool/v1/neodata"
    
    def __init__(self, token: str = None, endpoint: str = None):
        """
        初始化 NeoData 服务
        
        Args:
            token: JWT token，如果为 None 则从环境变量 NEODATA_TOKEN 读取
            endpoint: API 端点，如果为 None 则从环境变量 NEODATA_ENDPOINT 读取或使用默认值
        """
        self.token = token or os.getenv("NEODATA_TOKEN")
        self.endpoint = endpoint or os.getenv("NEODATA_ENDPOINT", self.DEFAULT_ENDPOINT)
        
        if not self.token:
            logger.warning("NeoData token 未提供，部分功能可能受限")
    
    def query(self, query_text: str, data_type: str = "all") -> Dict[str, Any]:
        """
        查询金融数据
        
        Args:
            query_text: 自然语言查询，如"贵州茅台股价"
            data_type: 数据类型，可选 "all"（默认）、"api"（仅结构化数据）、"doc"（仅文档）
            
        Returns:
            查询结果字典
        """
        if not self.token:
            return {"error": "NeoData token 未配置", "success": False}
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.token}",
        }
        
        payload = {
            "query": query_text,
            "data_type": data_type,
            "channel": "neodata",
            "sub_channel": "workbuddy",
        }
        
        try:
            response = requests.post(self.endpoint, headers=headers, json=payload, timeout=30)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"NeoData 查询失败: {e}")
            return {"error": str(e), "success": False}
    
    def get_stock_quote(self, symbol: str, market: str = "A股") -> Dict[str, Any]:
        """
        获取股票行情
        
        Args:
            symbol: 股票代码或名称，如"600519"、"贵州茅台"
            market: 市场类型，如"A股"、"港股"、"美股"
            
        Returns:
            股票行情数据
        """
        query_text = f"{symbol} {market} 最新股价"
        result = self.query(query_text, data_type="api")
        
        if result.get("suc") and result.get("code") == "200":
            return self._parse_stock_quote(result)
        else:
            logger.warning(f"获取股票行情失败: {result.get('msg', '未知错误')}")
            return {}
    
    def _parse_stock_quote(self, response: Dict[str, Any]) -> Dict[str, Any]:
        """解析股票行情响应"""
        try:
            api_data = response.get("data", {}).get("apiData", {})
            api_recall = api_data.get("apiRecall", [])
            
            if not api_recall:
                return {}
            
            # 提取第一个召回结果
            recall = api_recall[0]
            content = recall.get("content", "")
            
            # 简单解析内容文本（实际应用中应使用更复杂的解析）
            parsed = {
                "type": recall.get("type", ""),
                "desc": recall.get("desc", ""),
                "content": content,
                "raw": response
            }
            
            # 尝试提取关键数值
            lines = content.split("\n")
            for line in lines:
                if "最新价格:" in line:
                    parsed["latest_price"] = line.split("最新价格:")[1].split(";")[0].strip()
                elif "昨日收盘价格:" in line:
                    parsed["prev_close"] = line.split("昨日收盘价格:")[1].split(";")[0].strip()
                elif "当日涨跌幅:" in line:
                    parsed["change_pct"] = line.split("当日涨跌幅:")[1].split(";")[0].strip()
            
            return parsed
        except Exception as e:
            logger.error(f"解析股票行情失败: {e}")
            return {}
    
    def get_major_indices(self) -> List[Dict[str, Any]]:
        """
        获取主要指数行情
        
        Returns:
            指数数据列表
        """
        indices = [
            {"name": "上证指数", "query": "上证指数最新点位"},
            {"name": "深证成指", "query": "深证成指最新点位"},
            {"name": "创业板指", "query": "创业板指最新点位"},
            {"name": "沪深300", "query": "沪深300指数最新点位"},
            {"name": "上证50", "query": "上证50指数最新点位"},
            {"name": "中证500", "query": "中证500指数最新点位"},
        ]
        
        results = []
        for idx in indices:
            try:
                result = self.query(idx["query"], data_type="api")
                if result.get("suc") and result.get("code") == "200":
                    content = result.get("data", {}).get("apiData", {}).get("apiRecall", [{}])[0].get("content", "")
                    # 简单解析
                    parsed = self._parse_index_content(content)
                    parsed["name"] = idx["name"]
                    results.append(parsed)
            except Exception as e:
                logger.warning(f"获取指数 {idx['name']} 失败: {e}")
                continue
        
        return results
    
    def _parse_index_content(self, content: str) -> Dict[str, Any]:
        """解析指数内容"""
        parsed = {"content": content}
        
        try:
            lines = content.split("\n")
            for line in lines:
                if "最新价格:" in line:
                    parts = line.split("最新价格:")
                    if len(parts) > 1:
                        parsed["latest"] = parts[1].split(";")[0].strip()
                elif "昨日收盘价格:" in line:
                    parts = line.split("昨日收盘价格:")
                    if len(parts) > 1:
                        parsed["prev_close"] = parts[1].split(";")[0].strip()
                elif "当日涨跌幅:" in line:
                    parts = line.split("当日涨跌幅:")
                    if len(parts) > 1:
                        parsed["change_pct"] = parts[1].split(";")[0].strip()
        except Exception as e:
            logger.warning(f"解析指数内容失败: {e}")
        
        return parsed
    
    def get_news_summary(self, days: int = 1) -> Dict[str, Any]:
        """
        获取财经新闻摘要
        
        Args:
            days: 最近多少天的新闻
            
        Returns:
            新闻摘要
        """
        query_text = f"{days}天财经新闻"
        result = self.query(query_text, data_type="all")
        
        if result.get("suc") and result.get("code") == "200":
            return self._parse_news_summary(result)
        else:
            return {"error": result.get("msg", "获取新闻失败"), "success": False}
    
    def _parse_news_summary(self, response: Dict[str, Any]) -> Dict[str, Any]:
        """解析新闻摘要"""
        try:
            # 实际解析逻辑需要根据 NeoData 返回的具体结构实现
            # 这里返回一个简化版本
            return {
                "success": True,
                "total_news": 0,  # 需要根据实际响应解析
                "sentiment": "中性",
                "hot_topics": [],
                "stock_mentions": {},
                "source": "neodata"
            }
        except Exception as e:
            logger.error(f"解析新闻摘要失败: {e}")
            return {"success": False, "error": str(e)}
    
    def get_sector_performance(self) -> Dict[str, Any]:
        """
        获取板块表现
        
        Returns:
            板块表现数据
        """
        query_text = "今日板块涨跌情况"
        result = self.query(query_text, data_type="api")
        
        if result.get("suc") and result.get("code") == "200":
            return self._parse_sector_performance(result)
        else:
            return {"error": result.get("msg", "获取板块数据失败"), "success": False}
    
    def _parse_sector_performance(self, response: Dict[str, Any]) -> Dict[str, Any]:
        """解析板块表现"""
        # 实际解析逻辑需要根据 NeoData 返回的具体结构实现
        return {
            "success": True,
            "hot_sectors": [],
            "volume_leaders": [],
            "source": "neodata"
        }


# 全局实例
neodata_service = NeoDataService()