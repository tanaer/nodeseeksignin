/**
 * 全局类型定义
 */
export interface Env {
  TG_BOT_TOKEN: string;
  TG_CHAT_ID: string;
  NS_COOKIE: string;
  REDIS_URL: string;   // redis://default:TOKEN@host:port
  WORKER_URL: string;
  ADMIN_ID?: string;    // 管理员 TG User ID（可选，不设则首位注册者为管理员）
  PUSHPLUS_TOKEN?: string;
  WEBHOOK_SECRET?: string;
}
