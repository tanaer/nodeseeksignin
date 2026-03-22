import os

class Config:
    """统一配置管理类"""
    def __init__(self):
        # NodeSeek Cookie 配置（支持多账号，用 | 分隔）
        raw_cookie = os.environ.get("NS_COOKIE") or os.environ.get("COOKIE") or ""
        self.cookies = [c.strip() for c in raw_cookie.split("|") if c.strip()]
        
        # 基础配置
        ns_random_env = os.environ.get("NS_RANDOM", "")
        self.ns_random = (ns_random_env.lower() == "true") if ns_random_env else True
        self.headless = os.environ.get("HEADLESS", "true").lower() == "true"
        
        # 通知配置 (TG 和 PushPlus)
        self.tg_bot_token = os.environ.get("TG_BOT_TOKEN")
        self.tg_chat_id = os.environ.get("TG_CHAT_ID")
        self.pushplus_token = os.environ.get("PUSHPLUS_TOKEN")
        
        # Upstash Redis 配置 (标准 rediss:// URL)
        self.redis_url = os.environ.get("REDIS_URL")
        
        # 2Captcha API Key (CF Turnstile 兜底方案)
        self.twocaptcha_api_key = os.environ.get("TWOCAPTCHA_API_KEY", "2da4800aedce6c5f4063c336f2289e41")
        
    @property
    def account_count(self):
        return len(self.cookies)

# 全局配置实例
config = Config()
