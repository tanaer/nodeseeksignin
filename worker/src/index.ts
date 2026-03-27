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
    ctx.waitUntil((async () => {
      // 首次 Cron 自动注册 Webhook
      await autoRegisterWebhook(env);
      // 执行巡检
      await runScheduledTasks(env);
    })());
  },
};

// ==================== 自动注册 Webhook ====================

async function autoRegisterWebhook(env: Env): Promise<void> {
  if (!env.WORKER_URL || !env.TG_BOT_TOKEN) return;

  const db = new DB(env.REDIS_URL);
  const registered = await db.getConfig('webhook_registered');
  if (registered === 'true') return;

  try {
    const webhookUrl = `${env.WORKER_URL}/webhook`;
    const res = await fetch(
      `https://api.telegram.org/bot${env.TG_BOT_TOKEN}/setWebhook?url=${encodeURIComponent(webhookUrl)}`
    );
    const data: any = await res.json();
    if (data.ok) {
      await db.setConfig('webhook_registered', 'true');
      console.log(`✅ Webhook 自动注册成功: ${webhookUrl}`);
    }
  } catch (e) {
    console.error('Webhook 自动注册失败:', e);
  }
}

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
        await handleBump(tid, task as BumpTask, db, ns, env, myUsername, notifyChatId);
      } else if (task.type === 'monitor') {
        await handleMonitor(tid, task as any, db, ns, env, notifyChatId);
      }
    } catch (e) {
      console.error(`Task ${tid} error:`, e);
    }
  }

  // ==================== 全局自动回帖 ====================
  try {
    const autoreplyEnabled = await db.getConfig('autoreply_enabled');
    if (autoreplyEnabled === 'true') {
      await handleGlobalAutoReply(db, ns, env, notifyChatId);
    }
  } catch (e) {
    console.error(`AutoReply error:`, e);
  }
}

async function handleGlobalAutoReply(db: DB, ns: NodeSeek, env: Env, notifyChatId: string): Promise<void> {
  const limit = parseInt(await db.getConfig('autoreply_limit') || '20');
  const keywordsStr = await db.getConfig('autoreply_keywords') || '';
  const keywords = keywordsStr.split(/[,，\|]/).map((k: string) => k.trim()).filter((k: string) => k);

  const posts = await ns.getLatestPosts();
  if (!posts || posts.length === 0) return;

  // 使用东八区当前日期作为 Key
  const dateStr = new Date(Date.now() + 8 * 3600 * 1000).toISOString().split('T')[0];
  let currentCount = await db.getDailyReplyCount(dateStr);

  // 每次 Cron 最多只回复 1~2 帖，防止被拉黑
  let repliedThisCron = 0;

  for (const post of posts) {
    if (repliedThisCron >= 2) break; // max 2 per run

    if (await db.hasReplied(post.threadId)) continue;
    
    const isKeywordMatch = keywords.some((k: string) => post.title.toLowerCase().includes(k.toLowerCase()));
    
    // 如果没有命中关键词，且当日随机次数已满，则跳过
    if (!isKeywordMatch && currentCount >= limit) {
      continue;
    }

    console.log(`自动回复尝试: ${post.title} (命中关键词: ${isKeywordMatch})`);
    
    // 执行回复 (内容可以带点随机，这里先走内置的 randomComments)
    const ok = await ns.bumpThread(post.threadId);
    if (!ok) {
      console.log(`自动回复失败: ${post.threadId}`);
      continue;
    }

    await db.addRepliedPost(post.threadId);
    repliedThisCron++;

    let msg = ``;
    if (isKeywordMatch) {
      msg = `🤖 <b>关键词捡漏成功</b>\n\n🎯 命中词: ${keywords.join(',')}\n`;
    } else {
      currentCount = await db.incrDailyReplyCount(dateStr);
      msg = `🤖 <b>随机水贴完成</b>\n\n📊 今日进度: ${currentCount} / ${limit}\n`;
    }

    console.log(`✅ 自动回复成功: ${post.threadId}`);

    if (notifyChatId) {
       await Notifier.sendTg(
          env.TG_BOT_TOKEN,
          notifyChatId,
          `${msg}📝 标题: ${post.title}\n🔗 链接: https://www.nodeseek.com/post-${post.threadId}-1`
        );
    }
    
    // 稍微延时防止频率过快
    await new Promise(r => setTimeout(r, 2000));
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
