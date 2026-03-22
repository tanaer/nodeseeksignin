import requests
from ns_config import config

class Notifier:
    """双通道消息推送工具"""
    
    @staticmethod
    def send_tg(message):
        if not config.tg_bot_token or not config.tg_chat_id:
            return False
        url = f"https://api.telegram.org/bot{config.tg_bot_token}/sendMessage"
        payload = {
            "chat_id": config.tg_chat_id,
            "text": message,
            "parse_mode": "HTML"
        }
        try:
            response = requests.post(url, json=payload, timeout=10)
            return response.status_code == 200
        except Exception as e:
            print(f"Telegram 通知发送出错: {e}")
            return False

    @staticmethod
    def send_pushplus(title, content):
        if not config.pushplus_token:
            print("未配置 PushPlus Token")
            return False
        url = "http://www.pushplus.plus/send"
        payload = {
            "token": config.pushplus_token,
            "title": title,
            "content": content,
            "template": "html"
        }
        try:
            response = requests.post(url, json=payload, timeout=10)
            return response.status_code == 200
        except Exception as e:
            print(f"PushPlus 通知发送出错: {e}")
            return False

    @classmethod
    def notify(cls, channel, title, message):
        """统一发送入口"""
        if channel == "tg" or channel == "telegram":
            full_msg = f"<b>{title}</b>\n\n{message}"
            return cls.send_tg(full_msg)
        elif channel == "pushplus":
            # Pushplus 不需要手动拼接 HTML title，因为有独立 title 字段，但内容可以含HTML
            return cls.send_pushplus(title, message)
        else:
            print(f"未知通知管道: {channel}")
            return False
