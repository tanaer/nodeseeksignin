import logging
import uuid
import asyncio
import threading
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from ns_config import config
from db_manager import DBManager
from ns_crawler import NodeSeekCrawler
from notifier import Notifier

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

db = DBManager(config.redis_url)
crawler = NodeSeekCrawler()

# ==================== 后台定时任务 ====================

async def job_check_bumps():
    """遍历所有顶贴任务，根据冷却状态调用爬虫"""
    if not db.redis:
        return
    try:
        tasks = db.get_all_tasks()
        for tid, t in tasks.items():
            if t.get('type') != 'bump':
                continue
            if db.is_in_cooldown(tid):
                continue

            thread_id = t['thread_id']
            cooldown = int(t['cooldown'])

            # 在线程池中运行同步爬虫方法，避免阻塞事件循环
            diff_mins = await asyncio.to_thread(
                crawler.get_thread_last_reply_time, thread_id
            )
            if diff_mins < 0:
                logger.warning(f"无法获取帖子 {thread_id} 的回复信息")
                continue

            logger.info(
                f"顶贴检查: 帖子 {thread_id} "
                f"最后回复 {diff_mins:.1f} 分钟前 (阈值 {cooldown})"
            )

            if diff_mins >= cooldown:
                res = await asyncio.to_thread(
                    crawler.bump_thread, thread_id
                )
                if res:
                    logger.info(f"✅ 任务 {tid}: 帖子 {thread_id} 顶贴成功")
                    db.set_cooldown(tid, cooldown)
                    Notifier.notify(
                        "tg",
                        "NodeSeek 自动顶贴完成",
                        f"任务ID: {tid}\n帖子ID: {thread_id}\n距上次回复: {diff_mins:.0f}分钟"
                    )
                else:
                    logger.warning(f"❌ 任务 {tid}: 帖子 {thread_id} 顶贴失败")
    except Exception as e:
        logger.error(f"顶贴任务异常: {e}", exc_info=True)


async def job_check_monitors():
    """遍历所有监控任务，查询是否有新帖"""
    if not db.redis:
        return
    try:
        tasks = db.get_all_tasks()
        for tid, t in tasks.items():
            if t.get('type') != 'monitor':
                continue
            if db.is_in_cooldown(tid):
                continue

            keyword = t['keyword']
            channel = t['channel']
            cooldown = int(t['cooldown'])

            result = await asyncio.to_thread(
                crawler.search_keyword_latest, keyword
            )
            if not result:
                continue

            post_title = result['title']
            post_link = result['link']
            post_time_str = result['time_str']
            diff_mins = result['diff_minutes']

            # 防止对同一帖子重复通知
            last_recorded = db.get_last_post_time(keyword)
            if last_recorded == post_time_str:
                continue

            # 仅通知"新帖" — 发帖时间在冷却窗口内
            if diff_mins <= cooldown:
                msg = (
                    f"🔍 <b>匹配关键字:</b> {keyword}\n\n"
                    f"🏷 <b>标题:</b> {post_title}\n"
                    f"🔗 <a href='{post_link}'>点击直达</a>\n"
                    f"🕒 <b>发帖距今:</b> {diff_mins:.1f} 分钟"
                )
                logger.info(f"监控命中: [{keyword}] → {post_title}")
                Notifier.notify(channel, f"💡 论坛新帖通知 ({keyword})", msg)

                db.set_last_post_time(keyword, post_time_str)
                db.set_cooldown(tid, cooldown)
    except Exception as e:
        logger.error(f"监控任务异常: {e}", exc_info=True)


# ==================== Telegram Bot 命令处理 ====================

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示帮助信息"""
    help_text = (
        "🤖 <b>NodeSeek Bot 控制台</b>\n\n"
        "<b>可用命令:</b>\n"
        "/add_bump <code>&lt;主题ID&gt;</code> <code>&lt;冷却/分钟&gt;</code>\n"
        "  └ 检测帖子最后回复超过N分钟后自动顶贴\n\n"
        "/add_notify <code>&lt;关键字&gt;</code> <code>&lt;tg|pushplus&gt;</code> <code>&lt;冷却/分钟&gt;</code>\n"
        "  └ 搜索关键字，有N分钟内新帖时推送通知\n\n"
        "/list\n"
        "  └ 查看当前所有任务\n\n"
        "/delete <code>&lt;task_id&gt;</code>\n"
        "  └ 删除指定任务\n\n"
        "💡 <b>示例:</b>\n"
        "<code>/add_bump 12345 60</code>\n"
        "<code>/add_notify 服务器 tg 10</code>"
    )
    await update.message.reply_html(help_text)


async def cmd_add_bump(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """添加自动顶贴任务"""
    args = context.args
    if not args or len(args) != 2:
        await update.message.reply_text(
            "⛔️ 格式错误\n用法: /add_bump <主题ID> <冷却分钟>\n示例: /add_bump 12345 60"
        )
        return

    thread_id = args[0]
    try:
        cooldown = int(args[1])
    except ValueError:
        await update.message.reply_text("⛔️ 冷却时间必须是整数")
        return

    if cooldown <= 0:
        await update.message.reply_text("⛔️ 冷却时间必须大于 0")
        return

    tid = str(uuid.uuid4())[:8]
    if db.add_bump_task(tid, thread_id, cooldown):
        await update.message.reply_html(
            f"✅ <b>顶贴任务添加成功</b>\n\n"
            f"📋 任务编号: <code>{tid}</code>\n"
            f"🎯 目标帖子: {thread_id}\n"
            f"⏱ 冷却时间: {cooldown} 分钟\n\n"
            f"系统将每 5 分钟巡检一次"
        )
    else:
        await update.message.reply_text("❌ 添加失败，请检查 REDIS_URL 配置")


async def cmd_add_notify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """添加关键词监控任务"""
    args = context.args
    if not args or len(args) < 3:
        await update.message.reply_text(
            "⛔️ 格式错误\n用法: /add_notify <关键字> <tg|pushplus> <冷却分钟>\n"
            "示例: /add_notify 服务器 tg 10"
        )
        return

    # 最后一个参数是冷却，倒数第二是渠道，其余拼接为关键字
    keyword = " ".join(args[:-2])
    channel = args[-2].lower()
    try:
        cooldown = int(args[-1])
    except ValueError:
        await update.message.reply_text("⛔️ 冷却时间必须是整数")
        return

    if channel not in ("tg", "telegram", "pushplus"):
        await update.message.reply_text(
            "⛔️ 通知渠道不合法，支持: tg / pushplus"
        )
        return

    if cooldown <= 0:
        await update.message.reply_text("⛔️ 冷却时间必须大于 0")
        return

    tid = str(uuid.uuid4())[:8]
    if db.add_monitor_task(tid, keyword, channel, cooldown):
        await update.message.reply_html(
            f"✅ <b>监控任务添加成功</b>\n\n"
            f"📋 任务编号: <code>{tid}</code>\n"
            f"🔍 关键字: {keyword}\n"
            f"📢 通知渠道: {channel}\n"
            f"⏱ 冷却时间: {cooldown} 分钟\n\n"
            f"系统将每 3 分钟巡检一次"
        )
    else:
        await update.message.reply_text("❌ 添加失败，请检查 REDIS_URL 配置")


async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """列出所有活跃任务"""
    tasks = db.get_all_tasks()
    if not tasks:
        await update.message.reply_text("📭 当前没有任何任务")
        return

    lines = ["📝 <b>当前任务列表</b>\n"]
    for tid, t in tasks.items():
        cd_status = "⏳冷却中" if db.is_in_cooldown(tid) else "🟢活跃"
        if t['type'] == 'bump':
            lines.append(
                f"<code>{tid}</code> 🆙顶贴 | "
                f"帖号:{t['thread_id']} | "
                f"冷却:{t['cooldown']}分 | {cd_status}"
            )
        elif t['type'] == 'monitor':
            lines.append(
                f"<code>{tid}</code> 🔍监控 | "
                f"词:{t['keyword']} | "
                f"渠道:{t['channel']} | "
                f"冷却:{t['cooldown']}分 | {cd_status}"
            )

    await update.message.reply_html("\n".join(lines))


async def cmd_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """删除指定任务"""
    args = context.args
    if not args or len(args) != 1:
        await update.message.reply_text(
            "⛔️ 格式错误\n用法: /delete <任务编号>\n示例: /delete f47ac10b"
        )
        return

    tid = args[0]
    if db.delete_task(tid):
        await update.message.reply_html(
            f"✅ 任务 <code>{tid}</code> 已删除"
        )
    else:
        await update.message.reply_text(f"❌ 未找到任务 {tid}")


# ==================== 主入口 ====================

def main():
    if not config.tg_bot_token:
        logger.error("❌ TG_BOT_TOKEN 未配置，无法启动 Bot 服务")
        return
    if not config.redis_url:
        logger.warning("⚠️ REDIS_URL 未配置，任务持久化功能将不可用")

    app = ApplicationBuilder().token(config.tg_bot_token).build()

    # 注册命令
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_start))
    app.add_handler(CommandHandler("add_bump", cmd_add_bump))
    app.add_handler(CommandHandler("add_notify", cmd_add_notify))
    app.add_handler(CommandHandler("list", cmd_list))
    app.add_handler(CommandHandler("delete", cmd_delete))

    # 后台调度
    scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
    scheduler.add_job(job_check_bumps, 'interval', minutes=5, id='bumps')
    scheduler.add_job(job_check_monitors, 'interval', minutes=3, id='monitors')
    scheduler.start()

    logger.info("=" * 40)
    logger.info("  NodeSeek Bot 服务启动成功")
    logger.info("  顶贴巡检: 每 5 分钟")
    logger.info("  监控巡检: 每 3 分钟")
    logger.info("=" * 40)

    app.run_polling(drop_pending_updates=True)


if __name__ == '__main__':
    main()
