"""
QuantWeave - 通知服务
支持钉钉、企业微信、邮件、Server酱(个人微信) 四种通知渠道
"""
import requests
import smtplib
from email.mime.text import MIMEText
from loguru import logger
from typing import Optional
from datetime import datetime


class NotifyService:
    """通知服务"""

    def __init__(self, dingtalk_webhook: str = "", wechat_webhook: str = "",
                 email_smtp: str = "", email_sender: str = "",
                 email_password: str = "", email_receiver: str = "",
                 serverchan_key: str = ""):
        self.dingtalk_webhook = dingtalk_webhook
        self.wechat_webhook = wechat_webhook
        self.email_smtp = email_smtp
        self.email_sender = email_sender
        self.email_password = email_password
        self.email_receiver = email_receiver
        self.serverchan_key = serverchan_key

    def send(self, title: str, content: str, level: str = "info"):
        """统一发送通知（所有已配置的渠道）"""
        if level == "critical":
            emoji = "🚨"
        elif level == "warning":
            emoji = "⚠️"
        else:
            emoji = "ℹ️"

        message = f"{emoji} [{level.upper()}] {title}\n\n{content}"

        if self.dingtalk_webhook:
            self._send_dingtalk(message)
        if self.wechat_webhook:
            self._send_wechat(message)
        if self.email_smtp and self.email_sender:
            self._send_email(title, message)
        if self.serverchan_key:
            self._send_serverchan(title, content)

    def _send_dingtalk(self, message: str):
        """发送钉钉通知"""
        try:
            payload = {
                "msgtype": "text",
                "text": {"content": message}
            }
            resp = requests.post(self.dingtalk_webhook, json=payload, timeout=10)
            if resp.status_code == 200:
                logger.info("钉钉通知发送成功")
            else:
                logger.warning(f"钉钉通知失败: {resp.text}")
        except Exception as e:
            logger.error(f"钉钉通知异常: {e}")

    def _send_wechat(self, message: str):
        """发送企业微信通知"""
        try:
            payload = {
                "msgtype": "text",
                "text": {"content": message}
            }
            resp = requests.post(self.wechat_webhook, json=payload, timeout=10)
            if resp.status_code == 200:
                logger.info("企业微信通知发送成功")
            else:
                logger.warning(f"企业微信通知失败: {resp.text}")
        except Exception as e:
            logger.error(f"企业微信通知异常: {e}")

    def _send_email(self, subject: str, body: str):
        """发送邮件通知"""
        try:
            msg = MIMEText(body, "plain", "utf-8")
            msg["Subject"] = f"[QuantWeave] {subject}"
            msg["From"] = self.email_sender
            msg["To"] = self.email_receiver

            with smtplib.SMTP(self.email_smtp, 587) as server:
                server.starttls()
                server.login(self.email_sender, self.email_password)
                server.sendmail(self.email_sender, self.email_receiver, msg.as_string())
            logger.info("邮件通知发送成功")
        except Exception as e:
            logger.error(f"邮件通知异常: {e}")

    def _send_serverchan(self, title: str, content: str):
        """通过 Server酱 发送微信通知（推送到个人微信）"""
        try:
            url = f"https://sctapi.ftqq.com/{self.serverchan_key}.send"
            payload = {
                "title": f"[QuantWeave] {title}",
                "desp": content,
            }
            resp = requests.post(url, data=payload, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("code") == 0:
                    logger.info("Server酱微信通知发送成功")
                else:
                    logger.warning(f"Server酱发送失败: {data.get('message', '')}")
            else:
                logger.warning(f"Server酱请求失败: HTTP {resp.status_code}")
        except Exception as e:
            logger.error(f"Server酱通知异常: {e}")

    def notify_signal(self, signal: dict):
        """发送交易信号通知"""
        title = f"交易信号: {signal.get('signal', '').upper()} {signal.get('ts_code', '')}"
        content = (
            f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"股票: {signal.get('ts_code', '')}\n"
            f"信号: {signal.get('signal', '')}\n"
            f"价格: {signal.get('price', '')}\n"
            f"原因: {signal.get('reason', '')}\n"
            f"置信度: {signal.get('confidence', '')}"
        )
        self.send(title, content, level="info")

    def notify_risk_alert(self, alert: dict):
        """发送风控告警"""
        level = alert.get("level", "warning")
        title = f"风控告警: {alert.get('title', '')}"
        content = (
            f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"类型: {alert.get('alert_type', '')}\n"
            f"级别: {level}\n"
            f"详情: {alert.get('detail', '')}"
        )
        self.send(title, content, level=level)
