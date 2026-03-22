import redis
import json
import time

class DBManager:
    """封装对 Upstash Redis (或其他 Redis) 的数据持久化和冷却处理"""
    def __init__(self, redis_url):
        if not redis_url:
            self.redis = None
            print("未配置 REDIS_URL, 部分功能(持久化/任务大盘/冷却)将无法使用")
        else:
            self.redis = redis.Redis.from_url(redis_url, decode_responses=True)

    def add_bump_task(self, task_id, thread_id, cooldown_minutes):
        """新增主帖保活/顶贴任务"""
        if not self.redis: return False
        task = {
            "type": "bump",
            "thread_id": thread_id,
            "cooldown": cooldown_minutes,
            "created_at": time.time()
        }
        self.redis.hset("ns_tasks", task_id, json.dumps(task))
        return True

    def add_monitor_task(self, task_id, keyword, channel, cooldown_minutes):
        """新增关键词监控任务"""
        if not self.redis: return False
        task = {
            "type": "monitor",
            "keyword": keyword,
            "channel": channel,  # tg or pushplus
            "cooldown": cooldown_minutes,
            "created_at": time.time()
        }
        self.redis.hset("ns_tasks", task_id, json.dumps(task))
        return True

    def delete_task(self, task_id):
        """删除某个任务"""
        if not self.redis: return False
        res = self.redis.hdel("ns_tasks", task_id)
        return res > 0

    def get_all_tasks(self):
        """获取并解析所有的任务列表"""
        if not self.redis: return {}
        tasks = self.redis.hgetall("ns_tasks")
        for k, v in tasks.items():
            tasks[k] = json.loads(v)
        return tasks

    def is_in_cooldown(self, task_id):
        """检查任务是否在冷却中"""
        if not self.redis: return False
        return self.redis.exists(f"cooldown:{task_id}") > 0

    def set_cooldown(self, task_id, minutes):
        """设置冷却时间并自动过期 (TTL)"""
        if not self.redis or minutes <= 0: return
        self.redis.setex(f"cooldown:{task_id}", int(minutes * 60), "1")
        
    def get_last_post_time(self, keyword):
        """获取监控关键字最后一次检测到的最新帖子时间，防止重复通知"""
        if not self.redis: return None
        return self.redis.get(f"last_post_time:{keyword}")
        
    def set_last_post_time(self, keyword, post_time_str):
        """保存最新检测到的帖子发布时间"""
        if not self.redis: return
        # 保留7天，免得长期不匹配导致脏数据堆积
        self.redis.setex(f"last_post_time:{keyword}", 7 * 24 * 3600, post_time_str)
