/**
 * Cloudflare Worker 入口
 * - fetch: Telegram Webhook + 管理路由
 */

import { DB } from './db';
import { TelegramBot } from './telegram';
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
      const db = new DB(env.REDIS_URL);
      await db.setConfig('force_run', 'true');
      return new Response('✅ 已写入立即巡检标志');
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
};
