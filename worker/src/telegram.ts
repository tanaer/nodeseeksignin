/**
 * Telegram Bot 命令处理（含管理员鉴权）
 *
 * 命令体系:
 *   /bump <帖子ID> <冷却分钟> [最大次数]
 *   /unbump <任务ID>
 *   /watch <关键字> <tg|pushplus> <冷却分钟>
 *   /unwatch <任务ID>
 *   /list
 *   /pause <任务ID>
 *   /resume <任务ID>
 *   /clear
 *   /setchat [chat_id]
 *   /help
 */
import { DB } from './db';
import { Env } from './types';

function genId(): string {
  return Math.random().toString(36).substring(2, 10);
}

interface TgUpdate {
  message?: {
    chat: { id: number };
    from?: { id: number; username?: string };
    text?: string;
  };
}

export class TelegramBot {
  private botToken: string;
  private db: DB;
  private env: Env;

  constructor(botToken: string, db: DB, env: Env) {
    this.botToken = botToken;
    this.db = db;
    this.env = env;
  }

  async handleUpdate(update: TgUpdate): Promise<void> {
    const msg = update.message;
    if (!msg?.text) return;

    const chatId = msg.chat.id;
    const userId = msg.from?.id ?? 0;
    const text = msg.text.trim();
    const parts = text.split(/\s+/);
    const cmd = parts[0].toLowerCase().replace(/@\w+$/, '');

    // ─── 管理员鉴权 ───
    const isAdmin = await this.checkAdmin(userId);

    // /start 和 /help 任何人可用
    if (cmd === '/start' || cmd === '/help') {
      return this.reply(chatId, this.helpText(isAdmin));
    }

    // 其他命令需管理员权限
    if (!isAdmin) {
      // 如果还没有管理员，第一个使用的人成为管理员
      const hasAdmin = await this.db.getConfig('admin_id');
      if (!hasAdmin) {
        await this.db.setConfig('admin_id', String(userId));
        await this.db.setConfig('notify_chat_id', String(chatId));
        return this.reply(chatId,
          `🔐 你已成为管理员\n\n` +
          `👤 用户 ID: <code>${userId}</code>\n` +
          `💬 通知 Chat ID 已设为: <code>${chatId}</code>\n\n` +
          `发送 /help 查看完整命令`
        );
      }
      return this.reply(chatId, '⛔ 仅管理员可操作此机器人');
    }

    switch (cmd) {
      case '/bump':    return this.handleBump(chatId, parts.slice(1));
      case '/unbump':
      case '/unwatch':
      case '/delete':  return this.handleDelete(chatId, parts.slice(1));
      case '/watch':   return this.handleWatch(chatId, parts.slice(1));
      case '/list':    return this.handleList(chatId);
      case '/pause':   return this.handlePause(chatId, parts.slice(1));
      case '/resume':  return this.handleResume(chatId, parts.slice(1));
      case '/clear':   return this.handleClear(chatId);
      case '/setchat': return this.handleSetChat(chatId, parts.slice(1));
    }
  }

  // ─── Auth ───

  private async checkAdmin(userId: number): Promise<boolean> {
    // 环境变量中设置的 ADMIN_ID 优先
    if (this.env.ADMIN_ID) {
      return String(userId) === String(this.env.ADMIN_ID);
    }
    // 否则从 Redis 读取（首位注册者）
    const adminId = await this.db.getConfig('admin_id');
    if (!adminId) return false;
    return String(userId) === adminId;
  }

  /** 获取通知 Chat ID（管理员可通过 /setchat 动态修改） */
  async getNotifyChatId(): Promise<string> {
    const stored = await this.db.getConfig('notify_chat_id');
    return stored || this.env.TG_CHAT_ID || '';
  }

  // ─── Help ───

  private helpText(isAdmin: boolean): string {
    const lines = [
      '🤖 <b>NodeSeek Bot 控制台</b>',
      '',
    ];

    if (!isAdmin) {
      lines.push('发送任意命令成为管理员（仅首位生效）');
      return lines.join('\n');
    }

    lines.push(
      '🆙 <b>顶贴管理</b>',
      '<code>/bump 帖子ID 冷却分钟 [最大次数]</code>',
      '  最后回复超时自动顶帖',
      '  末位是自己 → 间隔自动 x2',
      '  最大次数可选，0或不填=无限',
      '<code>/unbump 任务ID</code>',
      '',
      '🔍 <b>关键词监控</b>',
      '<code>/watch 关键字 tg|pushplus 冷却分钟</code>',
      '  有新帖时推送通知',
      '<code>/unwatch 任务ID</code>',
      '',
      '⚙️ <b>管理</b>',
      '<code>/list</code> — 任务列表',
      '<code>/pause 任务ID</code> — 暂停',
      '<code>/resume 任务ID</code> — 恢复',
      '<code>/clear</code> — 清空所有任务',
      '<code>/setchat [chat_id]</code> — 设置通知目标',
      '',
      '💡 <b>示例</b>',
      '<code>/bump 12345 60 10</code>',
      '<code>/watch 服务器 tg 10</code>',
    );
    return lines.join('\n');
  }

  // ─── Bump ───

  private async handleBump(chatId: number, args: string[]): Promise<void> {
    if (args.length < 2) {
      return this.reply(chatId, '⛔ /bump <帖子ID> <冷却分钟> [最大次数]\n示例: /bump 12345 60 10');
    }
    const threadId = args[0];
    const cooldown = parseInt(args[1]);
    if (isNaN(cooldown) || cooldown <= 0) {
      return this.reply(chatId, '⛔ 冷却时间须为正整数');
    }
    const maxCount = args[2] ? parseInt(args[2]) : 0;

    const id = genId();
    await this.db.addBumpTask(id, threadId, cooldown, isNaN(maxCount) ? 0 : maxCount);
    return this.reply(chatId,
      `✅ <b>顶贴任务已添加</b>\n\n` +
      `📋 编号: <code>${id}</code>\n` +
      `🎯 帖子: ${threadId}\n` +
      `⏱ 冷却: ${cooldown} 分钟\n` +
      `🔢 上限: ${maxCount > 0 ? maxCount + ' 次' : '无限'}\n` +
      `💡 末位是自己时间隔 x2`
    );
  }

  // ─── Watch ───

  private async handleWatch(chatId: number, args: string[]): Promise<void> {
    if (args.length < 3) {
      return this.reply(chatId, '⛔ /watch <关键字> <tg|pushplus> <冷却分钟>\n示例: /watch 服务器 tg 10');
    }
    const cooldown = parseInt(args[args.length - 1]);
    const channel = args[args.length - 2].toLowerCase();
    const keyword = args.slice(0, -2).join(' ');

    if (isNaN(cooldown) || cooldown <= 0) return this.reply(chatId, '⛔ 冷却时间须为正整数');
    if (!['tg', 'telegram', 'pushplus'].includes(channel)) return this.reply(chatId, '⛔ 渠道: tg / pushplus');

    const id = genId();
    await this.db.addMonitorTask(id, keyword, channel, cooldown);
    return this.reply(chatId,
      `✅ <b>监控任务已添加</b>\n\n` +
      `📋 编号: <code>${id}</code>\n` +
      `🔍 关键字: ${keyword}\n` +
      `📢 渠道: ${channel}\n` +
      `⏱ 冷却: ${cooldown} 分钟`
    );
  }

  // ─── List ───

  private async handleList(chatId: number): Promise<void> {
    const tasks = await this.db.getAllTasks();
    const keys = Object.keys(tasks);
    if (keys.length === 0) return this.reply(chatId, '📭 当前没有任务');

    const lines: string[] = ['📝 <b>任务列表</b>\n'];
    for (const id of keys) {
      const t = tasks[id];
      const cd = await this.db.isInCooldown(id);
      let status = t.paused ? '⏸暂停' : (cd ? '⏳冷却' : '🟢活跃');

      if (t.type === 'bump') {
        const max = t.max_count > 0 ? `${t.bump_count}/${t.max_count}` : `${t.bump_count}/∞`;
        if (t.max_count > 0 && t.bump_count >= t.max_count) status = '✅完成';
        lines.push(`<code>${id}</code> 🆙 帖:${t.thread_id} | ${t.cooldown}分 | ${max} | ${status}`);
      } else if (t.type === 'monitor') {
        lines.push(`<code>${id}</code> 🔍 词:${t.keyword} | ${t.channel} | ${t.cooldown}分 | ${status}`);
      }
    }
    return this.reply(chatId, lines.join('\n'));
  }

  // ─── Delete / Pause / Resume / Clear ───

  private async handleDelete(chatId: number, args: string[]): Promise<void> {
    if (args.length !== 1) return this.reply(chatId, '⛔ /unbump <任务ID>  或  /unwatch <任务ID>');
    const ok = await this.db.deleteTask(args[0]);
    return this.reply(chatId, ok ? `✅ 任务 <code>${args[0]}</code> 已删除` : `❌ 未找到 ${args[0]}`);
  }

  private async handlePause(chatId: number, args: string[]): Promise<void> {
    if (args.length !== 1) return this.reply(chatId, '⛔ /pause <任务ID>');
    const ok = await this.db.pauseTask(args[0]);
    return this.reply(chatId, ok ? `⏸ <code>${args[0]}</code> 已暂停` : `❌ 未找到 ${args[0]}`);
  }

  private async handleResume(chatId: number, args: string[]): Promise<void> {
    if (args.length !== 1) return this.reply(chatId, '⛔ /resume <任务ID>');
    const ok = await this.db.resumeTask(args[0]);
    return this.reply(chatId, ok ? `▶️ <code>${args[0]}</code> 已恢复` : `❌ 未找到 ${args[0]}`);
  }

  private async handleClear(chatId: number): Promise<void> {
    const count = await this.db.clearAllTasks();
    return this.reply(chatId, `🗑 已清空 <b>${count}</b> 个任务`);
  }

  // ─── SetChat ───

  private async handleSetChat(chatId: number, args: string[]): Promise<void> {
    const targetChatId = args[0] || String(chatId);
    await this.db.setConfig('notify_chat_id', targetChatId);
    return this.reply(chatId, `✅ 通知目标已设为: <code>${targetChatId}</code>`);
  }

  // ─── Reply ───

  private async reply(chatId: number, text: string): Promise<void> {
    await fetch(`https://api.telegram.org/bot${this.botToken}/sendMessage`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ chat_id: chatId, text, parse_mode: 'HTML' }),
    });
  }
}
