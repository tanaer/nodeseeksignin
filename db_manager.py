import redis
import json
import time
from typing import Dict, Any, Optional

class DBManager:
    """封装对 Upstash Redis (或其他 Redis) 的数据操作，前缀统一用 ns: 配合 Worker"""
    def __init__(self, redis_url: str):
        if not redis_url:
            self.redis = None
            print("⚠️ 未配置 REDIS_URL, 部分功能无法正常工作")
        else:
            # Upstash strict SSL requirement fix
            if "upstash.io" in redis_url and redis_url.startswith("redis://"):
                redis_url = redis_url.replace("redis://", "rediss://", 1)
                
            try:
                self.redis = redis.Redis.from_url(redis_url, decode_responses=True)
            except Exception as e:
                self.redis = None
                print(f"⚠️ Redis 连接初始化失败: {e}")

    def set_config(self, key: str, value: str):
        if self.redis: self.redis.set(f"ns:{key}", value)

    def get_config(self, key: str) -> Optional[str]:
        if self.redis: return self.redis.get(f"ns:{key}")
        return None

    def delete_config(self, key: str):
        if self.redis: self.redis.delete(f"ns:{key}")

    # ==================== 任务 CRUD ====================

    def get_all_tasks(self) -> Dict[str, dict]:
        """获取所有任务列表"""
        if not self.redis: return {}
        tasks_raw = self.redis.hgetall("ns:tasks")
        tasks = {}
        for k, v in tasks_raw.items():
            try:
                tasks[k] = json.loads(v)
            except Exception:
                pass
        return tasks

    def increment_bump_count(self, task_id: str) -> int:
        """增加任务的执行次数"""
        if not self.redis: return 0
        raw = self.redis.hget("ns:tasks", task_id)
        if not raw: return 0
        task = json.loads(raw)
        task['bump_count'] = task.get('bump_count', 0) + 1
        self.redis.hset("ns:tasks", task_id, json.dumps(task))
        return task['bump_count']

    # ==================== 冷却管理 ====================

    def is_in_cooldown(self, task_id: str) -> bool:
        if not self.redis: return False
        return self.redis.exists(f"ns:cooldown:{task_id}") > 0

    def set_cooldown(self, task_id: str, minutes: int):
        if not self.redis or minutes <= 0: return
        self.redis.setex(f"ns:cooldown:{task_id}", int(minutes * 60), "1")

    # ==================== 状态追踪 ====================

    def has_notified(self, task_id: str, link: str) -> bool:
        if not self.redis: return False
        return self.redis.exists(f"ns:notified:{task_id}:{link}") > 0

    def mark_notified(self, task_id: str, link: str, ttl_seconds: int):
        if not self.redis: return
        self.redis.setex(f"ns:notified:{task_id}:{link}", ttl_seconds, "1")

    # ==================== 自动回帖管理 ====================

    def has_replied(self, post_id: str) -> bool:
        if not self.redis: return False
        return self.redis.sismember("ns:replied", post_id)

    def add_replied_post(self, post_id: str):
        if not self.redis: return
        self.redis.sadd("ns:replied", post_id)
        self.redis.expire("ns:replied", 3 * 24 * 3600)  # 保留3天记录即可

    def get_daily_reply_count(self, date_str: str) -> int:
        if not self.redis: return 0
        val = self.redis.get(f"ns:reply_count:{date_str}")
        return int(val) if val else 0

    def incr_daily_reply_count(self, date_str: str) -> int:
        if not self.redis: return 0
        val = self.redis.incr(f"ns:reply_count:{date_str}")
        self.redis.expire(f"ns:reply_count:{date_str}", 48 * 3600) # 过期自动清理
        return val
