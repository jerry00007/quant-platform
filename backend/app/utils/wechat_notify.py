"""
微信通知工具 — 通过 Server酱 推送消息到微信
API文档: https://sct.ftqq.com/
"""
import os
import json
import logging
import requests
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# 加载环境变量
load_dotenv()


def send_wechat(title: str, content: str, short: str = "") -> bool:
    """
    通过 Server酱 发送微信消息

    Args:
        title: 消息标题（必填，最长256字符）
        content: 消息正文（支持Markdown）
        short: 消息短摘要（可选，最长64字符，用于微信通知预览）

    Returns:
        bool: 是否发送成功
    """
    sendkey = os.getenv("SERVERCHAN_KEY", "").strip()
    if not sendkey:
        logger.warning("SERVERCHAN_KEY 未配置，跳过微信推送")
        return False

    url = f"https://sctapi.ftqq.com/{sendkey}.send"
    payload = {
        "title": title[:256],
        "desp": content,
    }
    if short:
        payload["short"] = short[:64]

    try:
        resp = requests.post(url, data=payload, timeout=10)
        result = resp.json()
        if result.get("code") == 0:
            logger.info(f"✅ 微信推送成功: {title}")
            return True
        else:
            logger.warning(f"⚠️ 微信推送失败: {result.get('message', '未知错误')}")
            return False
    except requests.RequestException as e:
        logger.warning(f"⚠️ 微信推送网络错误: {e}")
        return False


def send_trading_report(report_type: str, report_text: str) -> bool:
    """
    发送交易报告到微信

    Args:
        report_type: 报告类型（盘前速递/做T建议/卖出扫描/每日选股/盘后复盘）
        report_text: 报告全文
    """
    # 提取前3行作为短摘要
    lines = [l for l in report_text.strip().split("\n") if l.strip()][:3]
    short_summary = " | ".join(lines)[:64]

    # 报告文本转 Markdown（替换emoji箭头等）
    md_content = report_text

    return send_wechat(
        title=f"📊 {report_type}",
        content=md_content,
        short=short_summary,
    )
