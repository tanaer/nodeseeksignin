import os
import time
import schedule
from datetime import datetime, timezone
import traceback

from db_manager import DBManager
from ns_crawler import NodeSeekCrawler
from notifier import Notifier
from ns_config import config

db = DBManager(os.environ.get("REDIS_URL"))
crawler = NodeSeekCrawler()

def _get_datetime_str():
    # 东八区时间
    return datetime.fromtimestamp(time.time() + 8 * 3600, timezone.utc).strftime('%Y-%m-%d')

def handle_bump(tid, task, my_username):
    """处理单个顶贴任务"""
    max_count = task.get('max_count', 0)
    bump_count = task.get('bump_count', 0)
    
    if max_count > 0 and bump_count >= max_count:
        print(f"任务 {tid} 已达上限 {max_count} 次，跳过")
        return

    thread_id = task.get('thread_id')
    cooldown = task.get('cooldown', 60)
    
    minutes, last_user = crawler.get_thread_last_reply_time(thread_id)
    if minutes == -1:
        print(f"⚠️ 无法获取帖子 {thread_id} 信息")
        return

    effective_cooldown = cooldown
    is_self = bool(my_username and last_user and last_user == my_username)
    if is_self:
        effective_cooldown *= 2
        print(f"帖子 {thread_id} 末位是自己({my_username})，冷却 x2 = {effective_cooldown}分")

    print(f"顶贴检查: {thread_id} | 最后回复 {minutes:.1f}分前({last_user}) | 阈值 {effective_cooldown}分")

    if minutes >= effective_cooldown:
        ok = crawler.bump_thread(thread_id)
        if ok:
            new_count = db.increment_bump_count(tid)
            db.set_cooldown(tid, cooldown)

            count_text = f"{new_count}/{max_count}" if max_count > 0 else f"{new_count}"
            print(f"✅ 帖子 {thread_id} 顶贴成功 ({count_text})")

            notify_chat_id = db.get_config("notify_chat_id") or config.tg_chat_id
            if notify_chat_id:
                msg = (f"🆙 <b>自动顶贴完成</b>\n\n"
                       f"📋 任务: <code>{tid}</code>\n"
                       f"🎯 帖子: {thread_id}\n"
                       f"🕒 距上次: {int(minutes)}分\n"
                       f"🔢 次数: {count_text}")
                if is_self: msg += "\n💡 末位是自己，下次间隔 x2"
                
                # notifier 需要直接用 requests 调用或配置好
                Notifier.send_tg(msg)
        else:
            print(f"❌ 帖子 {thread_id} 顶贴失败")

def handle_monitor(tid, task):
    """处理关键字监控"""
    keyword = task.get('keyword', '')
    channel = task.get('channel', 'tg')
    cooldown = task.get('cooldown', 60)

    res = crawler.search_keyword_latest(keyword)
    if not res: return

    print(f"监控检查: {keyword} | 最新帖子 {res['diff_minutes']:.1f}分前")

    if res['diff_minutes'] < 30:
        if not db.has_notified(tid, res['link']):
            print(f"📢 新帖提示: {res['title']}")
            db.mark_notified(tid, res['link'], 86400)
            db.set_cooldown(tid, cooldown)

            msg = (f"🔔 <b>关键词监控触发</b>\n\n"
                   f"🔍 词: {keyword}\n"
                   f"📝 标题: {res['title']}\n"
                   f"🔗 链接: <a href='{res['link']}'>点击直达</a>\n"
                   f"🕒 时间: {res['time_str']}")
            
            if channel == 'tg':
                notify_chat_id = db.get_config("notify_chat_id") or config.tg_chat_id
                if notify_chat_id:
                    Notifier.send_tg(msg)
            elif channel == 'pushplus':
                Notifier.send_pushplus(f"NodeSeek 监控 - {keyword}", msg.replace('<b>', '').replace('</b>', ''))

def handle_autoreply():
    """处理全局自动水贴"""
    try:
        enabled = db.get_config('autoreply_enabled')
        if enabled != 'true': return

        limit = int(db.get_config('autoreply_limit') or '20')
        k_str = db.get_config('autoreply_keywords') or ''
        keywords = [k.strip() for k in k_str.replace('，', ',').replace('|', ',').split(',') if k.strip()]

        posts = crawler.get_latest_posts()
        if not posts: return

        date_str = _get_datetime_str()
        current_count = db.get_daily_reply_count(date_str)

        replied_this_cron = 0

        for post in posts:
            if replied_this_cron >= 2: break
            if db.has_replied(post['thread_id']): continue

            title = post['title']
            is_match = any(k.lower() in title.lower() for k in keywords)

            if not is_match and current_count >= limit:
                continue

            print(f"自动回复尝试: {title} (命中关键词: {is_match})")
            
            ok = crawler.bump_thread(post['thread_id'])
            if not ok:
                print(f"自动回复失败: {post['thread_id']}")
                continue

            db.add_replied_post(post['thread_id'])
            replied_this_cron += 1

            if is_match:
                msg = f"🤖 <b>关键词捡漏成功</b>\n\n🎯 命中词: {','.join(keywords)}\n"
            else:
                current_count = db.incr_daily_reply_count(date_str)
                msg = f"🤖 <b>随机水贴完成</b>\n\n📊 今日进度: {current_count} / {limit}\n"

            print(f"✅ 自动回复成功: {post['thread_id']}")

            notify_chat_id = db.get_config("notify_chat_id") or config.tg_chat_id
            if notify_chat_id:
                Notifier.send_tg(f"{msg}📝 标题: {title}\n🔗 https://www.nodeseek.com/post-{post['thread_id']}-1")
            
            time.sleep(2)
    except Exception as e:
        print(f"AutoReply error: {e}")
        traceback.print_exc()

def process_tasks():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 🚀 开始执行定时巡检队列...")
    # 判断是否有最新的 Cookie 更新
    new_cookie = db.get_config("ns_cookie")
    if new_cookie and len(config.cookies) > 0 and config.cookies[0] != new_cookie:
        config.cookies[0] = new_cookie
        print("已热更新 Cookie")

    my_username = crawler.get_my_username()

    tasks = db.get_all_tasks()
    for tid, task in tasks.items():
        try:
            if task.get('paused'): continue
            if db.is_in_cooldown(tid): continue

            t_type = task.get('type')
            if t_type == 'bump':
                handle_bump(tid, task, my_username)
            elif t_type == 'monitor':
                handle_monitor(tid, task)
        except Exception as e:
            print(f"Task {tid} error: {e}")
            traceback.print_exc()

    handle_autoreply()
    print("✅ 巡检队列执行完毕")

def check_manual_signals():
    """检查来自 Telegram 机器人的单次强制放行信号"""
    if db.get_config("force_run") == "true":
        db.delete_config("force_run")
        print("🔔 接收到立即巡检信号！")
        process_tasks()
    
    test_bump = db.get_config("test_bump")
    if test_bump:
        db.delete_config("test_bump")
        print(f"🔔 接收到单次顶贴测试信号: {test_bump}")
        ok = crawler.bump_thread(test_bump)
        msg = f"✅ 帖子 <code>{test_bump}</code> 顶贴测试成功！(Worker分离端回调)" if ok else f"❌ 帖子 <code>{test_bump}</code> 顶贴测试失败"
        Notifier.send_tg(msg)

    test_watch = db.get_config("test_watch")
    if test_watch:
        db.delete_config("test_watch")
        print(f"🔔 接收到单次监控测试信号: {test_watch}")
        res = crawler.search_keyword_latest(test_watch)
        if res:
            msg = f"✅ <b>搜索测试成功</b> (Worker分离端回调)\n\n📝 标题: {res['title']}\n🔗 <a href='{res['link']}'>直达链接</a>\n🕒 距今: {res['diff_minutes']:.1f} 分"
            Notifier.send_tg(msg)
        else:
            Notifier.send_tg(f"❌ 未能搜到关于 <code>{test_watch}</code> 的最新帖子")

if __name__ == "__main__":
    print("======== NodeSeek 守护进程启动 ========")
    print(f"代理配置: HTTP_PROXY={os.environ.get('HTTP_PROXY')} SOCKS_PROXY={os.environ.get('SOCKS_PROXY')}")
    
    # 将旧版 Cookie 初始化
    cfg_cookie = db.get_config("ns_cookie")
    if cfg_cookie:
        config.cookies = [cfg_cookie]

    # 每 5 分钟巡检一次任务
    schedule.every(5).minutes.do(process_tasks)
    
    # 每天强制调用一次原来的打卡签到程序 (也可根据需要拆出)
    # schedule.every().day.at("09:00").do(lambda: os.system("python nodeseek_daily.py"))

    print("✅ 守护进程进入轮询状态...")
    # 立刻执行一次大盘巡检
    process_tasks()

    while True:
        schedule.run_pending()
        check_manual_signals()
        time.sleep(30)
