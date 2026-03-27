/**
 * Upstash Redis 数据管理层（REST API）
 * 负责任务 CRUD、冷却管理、暂停/恢复
 */

export interface BumpTask {
  type: 'bump';
  thread_id: string;
  cooldown: number;      // 分钟 — 基础冷却阈值
  max_count: number;     // 最大顶贴次数 (0=无限)
  bump_count: number;    // 已顶贴次数
  paused: boolean;
  created_at: number;
}

export interface MonitorTask {
  type: 'monitor';
  keyword: string;
  channel: string;       // tg | pushplus
  cooldown: number;      // 分钟
  paused: boolean;
  created_at: number;
}

export type Task = BumpTask | MonitorTask;

export class DB {
  private url: string;
  private token: string;

  /**
   * 接受标准 Redis 连接串: redis://default:TOKEN@host:port
   */
  constructor(redisUrl: string) {
    const parsed = new URL(redisUrl);
    this.token = parsed.password;
    this.url = `https://${parsed.hostname}`;
  }

  private async cmd(...args: string[]): Promise<any> {
    const res = await fetch(this.url, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${this.token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(args),
    });
    const data: any = await res.json();
    if (data.error) throw new Error(data.error);
    return data.result;
  }

  // ==================== 任务 CRUD ====================

  async addBumpTask(id: string, threadId: string, cooldown: number, maxCount: number): Promise<void> {
    const task: BumpTask = {
      type: 'bump',
      thread_id: threadId,
      cooldown,
      max_count: maxCount,
      bump_count: 0,
      paused: false,
      created_at: Date.now(),
    };
    await this.cmd('HSET', 'ns:tasks', id, JSON.stringify(task));
  }

  async addMonitorTask(id: string, keyword: string, channel: string, cooldown: number): Promise<void> {
    const task: MonitorTask = {
      type: 'monitor',
      keyword,
      channel,
      cooldown,
      paused: false,
      created_at: Date.now(),
    };
    await this.cmd('HSET', 'ns:tasks', id, JSON.stringify(task));
  }

  async deleteTask(id: string): Promise<boolean> {
    const res = await this.cmd('HDEL', 'ns:tasks', id);
    return res > 0;
  }

  async getAllTasks(): Promise<Record<string, Task>> {
    const raw = await this.cmd('HGETALL', 'ns:tasks');
    const tasks: Record<string, Task> = {};
    if (!raw) return tasks;
    for (let i = 0; i < raw.length; i += 2) {
      try { tasks[raw[i]] = JSON.parse(raw[i + 1]); } catch { /* skip */ }
    }
    return tasks;
  }

  async getTask(id: string): Promise<Task | null> {
    const raw = await this.cmd('HGET', 'ns:tasks', id);
    if (!raw) return null;
    return JSON.parse(raw);
  }

  async updateTask(id: string, task: Task): Promise<void> {
    await this.cmd('HSET', 'ns:tasks', id, JSON.stringify(task));
  }

  async clearAllTasks(): Promise<number> {
    const tasks = await this.getAllTasks();
    const count = Object.keys(tasks).length;
    if (count > 0) {
      await this.cmd('DEL', 'ns:tasks');
    }
    return count;
  }

  // ==================== 暂停/恢复 ====================

  async pauseTask(id: string): Promise<boolean> {
    const task = await this.getTask(id);
    if (!task) return false;
    task.paused = true;
    await this.updateTask(id, task);
    return true;
  }

  async resumeTask(id: string): Promise<boolean> {
    const task = await this.getTask(id);
    if (!task) return false;
    task.paused = false;
    await this.updateTask(id, task);
    return true;
  }

  // ==================== 顶贴计数 ====================

  async incrementBumpCount(id: string): Promise<number> {
    const task = await this.getTask(id) as BumpTask | null;
    if (!task || task.type !== 'bump') return -1;
    task.bump_count = (task.bump_count || 0) + 1;
    await this.updateTask(id, task);
    return task.bump_count;
  }

  // ==================== 冷却管理 ====================

  async isInCooldown(id: string): Promise<boolean> {
    return (await this.cmd('EXISTS', `ns:cd:${id}`)) > 0;
  }

  async setCooldown(id: string, minutes: number): Promise<void> {
    if (minutes <= 0) return;
    await this.cmd('SETEX', `ns:cd:${id}`, String(Math.floor(minutes * 60)), '1');
  }

  async getLastPostTime(keyword: string): Promise<string | null> {
    return await this.cmd('GET', `ns:lpt:${keyword}`);
  }

  async setLastPostTime(keyword: string, timeStr: string): Promise<void> {
    await this.cmd('SETEX', `ns:lpt:${keyword}`, String(7 * 24 * 3600), timeStr);
  }

  // ==================== 配置管理 ====================

  async getConfig(key: string): Promise<string | null> {
    return await this.cmd('GET', `ns:config:${key}`);
  }

  async setConfig(key: string, value: string): Promise<void> {
    await this.cmd('SET', `ns:config:${key}`, value);
  }
}
