/**
 * Cloudflare Worker 入口
 * - fetch: Telegram Webhook + 管理路由
 * - scheduled: Cron 巡检 (顶贴 + 监控)
 */

import { DB, BumpTask } from './db';
import { NodeSeek } from './nodeseek';
import { TelegramBot } from './telegram';
import { Notifier } from './notifier';
import { Env } from './types';

export { Env };

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);

    // ─── 注册 Webhook ───
    if (url.pathname === '/register') {
      const workerUrl = env.WORKER_URL || url.origin;
      const webhookUrl = `${workerUrl}/webhook`;
      const setUrl = `https://api.telegram.org/bot${env.TG_BOT_TOKEN}/setWebhook?url=${encodeURIComponent(webhookUrl)}`;
      const res = await fetch(setUrl);
      const data: any = await res.json();

      if (data.ok) {
        return new Response(
          `✅ Webhook 注册成功!\n\nURL: ${webhookUrl}\n\n去 Telegram 给 Bot 发消息吧`,
          { status: 200 }
        );
      }
      return new Response(`❌ 注册失败: ${JSON.stringify(data)}`, { status: 500 });
    }

    // ─── Telegram Webhook ───
    if (url.pathname === '/webhook' && request.method === 'POST') {
      if (env.WEBHOOK_SECRET) {
        const secret = request.headers.get('X-Telegram-Bot-Api-Secret-Token');
        if (secret !== env.WEBHOOK_SECRET) {
          return new Response('Unauthorized', { status: 403 });
        }
      }

      try {
        const update = await request.json();
        const db = new DB(env.REDIS_URL);
        const bot = new TelegramBot(env.TG_BOT_TOKEN, db, env);
        await bot.handleUpdate(update as any);
      } catch (e) {
        console.error('Webhook error:', e);
      }
      return new Response('OK');
    }

    // ─── 手动触发巡检 ───
    if (url.pathname === '/check') {
      await runScheduledTasks(env);
      return new Response('✅ 巡检完成');
    }

    // ─── 健康检查 ───
    return new Response(
      JSON.stringify({
        status: 'ok',
        service: 'NodeSeek Bot Worker',
        routes: ['/register', '/webhook', '/check'],
      }),
      { headers: { 'Content-Type': 'application/json' } }
    );
  },

  async scheduled(event: ScheduledEvent, env: Env, ctx: ExecutionContext): Promise<void> {
    ctx.waitUntil(runScheduledTasks(env));
  },
};

// ==================== 巡检逻辑 ====================

async function runScheduledTasks(env: Env): Promise<void> {
  const db = new DB(env.REDIS_URL);
  const ns = new NodeSeek(env.NS_COOKIE);

  // 获取通知 Chat ID（管理员可通过 /setchat 设置）
  const bot = new TelegramBot(env.TG_BOT_TOKEN, db, env);
  const notifyChatId = await bot.getNotifyChatId();

  // 获取当前用户名（用于判断末位回帖人是否是自己）
  let myUsername = '';
  try {
    myUsername = await ns.getMyUsername();
  } catch { /* ignore */ }

  const tasks = await db.getAllTasks();

  for (const [tid, task] of Object.entries(tasks)) {
    try {
      // 已暂停 → 跳过
      if (task.paused) continue;
      // 冷却中 → 跳过
      if (await db.isInCooldown(tid)) continue;

      if (task.type === 'bump') {
        await handleBump(tid, task, db, ns, env, myUsername, notifyChatId);
      } else if (task.type === 'monitor') {
        await handleMonitor(tid, task, db, ns, env, notifyChatId);
      }
    } catch (e) {
      console.error(`Task ${tid} error:`, e);
    }
  }
}

async function handleBump(
  tid: string,
  task: BumpTask,
  db: DB,
  ns: NodeSeek,
  env: Env,
  myUsername: string,
  notifyChatId: string
): Promise<void> {
  // 已达上限 → 跳过
  if (task.max_count > 0 && (task.bump_count || 0) >= task.max_count) {
    console.log(`任务 ${tid} 已达上限 ${task.max_count} 次，跳过`);
    return;
  }

  const info = await ns.getLastReplyInfo(task.thread_id);
  if (!info) {
    console.log(`⚠️ 无法获取帖子 ${task.thread_id} 信息`);
    return;
  }

  // 计算实际冷却: 末位是自己 → x2
  let effectiveCooldown = task.cooldown;
  const isSelf = myUsername && info.lastPoster && info.lastPoster === myUsername;
  if (isSelf) {
    effectiveCooldown = task.cooldown * 2;
    console.log(`帖子 ${task.thread_id} 末位是自己(${myUsername})，冷却 x2 = ${effectiveCooldown}分`);
  }

  console.log(
    `顶贴检查: ${task.thread_id} | ` +
    `最后回复 ${info.minutes.toFixed(1)}分前(${info.lastPoster}) | ` +
    `阈值 ${effectiveCooldown}分`
  );

  if (info.minutes >= effectiveCooldown) {
    const ok = await ns.bumpThread(task.thread_id);
    if (ok) {
      const newCount = await db.incrementBumpCount(tid);
      await db.setCooldown(tid, task.cooldown);

      const countText = task.max_count > 0 ? `${newCount}/${task.max_count}` : `${newCount}`;
      console.log(`✅ 帖子 ${task.thread_id} 顶贴成功 (${countText})`);

      if (notifyChatId) {
        await Notifier.sendTg(
          env.TG_BOT_TOKEN,
          notifyChatId,
          `🆙 <b>自动顶贴完成</b>\n\n` +
          `📋 任务: <code>${tid}</code>\n` +
          `🎯 帖子: ${task.thread_id}\n` +
          `🕒 距上次: ${info.minutes.toFixed(0)}分\n` +
          `🔢 次数: ${countText}` +
          (isSelf ? '\n💡 末位是自己，下次间隔 x2' : '')
        );
      }
    } else {
      console.log(`❌ 帖子 ${task.thread_id} 顶贴失败`);
    }
  }
}

async function handleMonitor(
  tid: string,
  task: { keyword: string; channel: string; cooldown: number },
  db: DB,
  ns: NodeSeek,
  env: Env,
  notifyChatId: string
): Promise<void> {
  const result = await ns.searchLatest(task.keyword);
  if (!result) return;

  // 防重复
  const lastRecorded = await db.getLastPostTime(task.keyword);
  if (lastRecorded === result.timeStr) return;

  if (result.diffMinutes <= task.cooldown) {
    const msg = [
      `🔍 <b>关键字:</b> ${task.keyword}`,
      `🏷 <b>标题:</b> ${result.title}`,
      `🔗 <a href="${result.link}">点击直达</a>`,
      `🕒 <b>距今:</b> ${result.diffMinutes.toFixed(1)} 分钟`,
    ].join('\n');

    console.log(`监控命中: [${task.keyword}] → ${result.title}`);

    // 使用任务指定的渠道发通知
    if (task.channel === 'tg' || task.channel === 'telegram') {
      const chatId = notifyChatId || env.TG_CHAT_ID;
      await Notifier.sendTg(env.TG_BOT_TOKEN, chatId, `💡 <b>新帖通知</b>\n\n${msg}`);
    } else if (task.channel === 'pushplus') {
      await Notifier.sendPushPlus(env.PUSHPLUS_TOKEN || '', `新帖: ${task.keyword}`, msg);
    }

    await db.setLastPostTime(task.keyword, result.timeStr);
    await db.setCooldown(tid, task.cooldown);
  }
}
