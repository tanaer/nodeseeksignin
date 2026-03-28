/**
 * NodeSeek HTTP 客户端
 * 纯 fetch 实现，无需浏览器
 */

const BUMP_COMMENTS = [
  'bd', '绑定', '帮顶', '好价', '前排', '公道公道',
  '还可以', '挺不错的 bdbd', '好价 好价', '祝早出',
  '观望一下 早出', 'bd一下', '顶一下', '支持支持',
];

const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36';

export interface LastReplyInfo {
  minutes: number;      // 距今分钟数
  lastPoster: string;   // 最后回帖人用户名
}

export class NodeSeek {
  private cookie: string;

  constructor(cookie: string) {
    this.cookie = cookie;
  }

  private headers(extra: Record<string, string> = {}): Record<string, string> {
    return {
      'User-Agent': UA,
      Cookie: this.cookie,
      Accept: 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
      'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
      ...extra,
    };
  }

  /**
   * 获取帖子最后回复信息（距今分钟数 + 最后回帖人）
   */
  async getLastReplyInfo(threadId: string): Promise<LastReplyInfo | null> {
    try {
      let res = await fetch(`https://www.nodeseek.com/post-${threadId}-1`, {
        headers: this.headers(),
        redirect: 'follow',
      });
      if (!res.ok) return null;

      let html = await res.text();

      // 获取最大页数
      const pageRegex = /<a[^>]+href="\/post-\d+-(\d+)"[^>]*class="[^"]*page-link[^"]*"[^>]*>/g;
      let maxPage = 1;
      let pm: RegExpExecArray | null;
      while ((pm = pageRegex.exec(html)) !== null) {
        const pNum = parseInt(pm[1]);
        if (!isNaN(pNum) && pNum > maxPage) {
          maxPage = pNum;
        }
      }

      // 如果有分页，获取最后一页内容
      if (maxPage > 1) {
        res = await fetch(`https://www.nodeseek.com/post-${threadId}-${maxPage}`, {
          headers: this.headers(),
          redirect: 'follow',
        });
        if (res.ok) html = await res.text();
      }

      // 提取所有 <time datetime="..."> 和对应的用户名
      // 帖子结构: .post-list-item 包含用户名和时间
      const timeRegex = /<time[^>]+datetime="([^"]+)"/g;
      let lastTimeStr: string | null = null;
      let m: RegExpExecArray | null;
      while ((m = timeRegex.exec(html)) !== null) {
        lastTimeStr = m[1];
      }
      if (!lastTimeStr) return null;

      // 提取最后一个回帖用户名
      // NodeSeek 帖子中用户名通常在 .post-user-name 或 a[href^="/space/"] 中
      const userRegex = /class="[^"]*post-user-name[^"]*"[^>]*>([^<]+)</g;
      let lastPoster = '';
      let um: RegExpExecArray | null;
      while ((um = userRegex.exec(html)) !== null) {
        lastPoster = um[1].trim();
      }

      // 备选: 从 /space/ 链接提取
      if (!lastPoster) {
        const spaceRegex = /<a[^>]+href="\/space\/(\d+)"[^>]*>([^<]+)<\/a>/g;
        let sm: RegExpExecArray | null;
        while ((sm = spaceRegex.exec(html)) !== null) {
          lastPoster = sm[2].trim();
        }
      }

      const postTime = new Date(lastTimeStr).getTime();
      const minutes = (Date.now() - postTime) / 60000;

      return { minutes, lastPoster };
    } catch (e) {
      console.error(`getLastReplyInfo error for ${threadId}:`, e);
      return null;
    }
  }

  /**
   * 获取当前登录用户名
   */
  async getMyUsername(): Promise<string> {
    try {
      const res = await fetch('https://www.nodeseek.com', {
        headers: this.headers(),
      });
      const html = await res.text();
      // 尝试从页面提取当前用户名
      const match = html.match(/class="[^"]*username[^"]*"[^>]*>([^<]+)</);
      if (match) return match[1].trim();
      // 备选
      const match2 = html.match(/"username"\s*:\s*"([^"]+)"/);
      if (match2) return match2[1].trim();
      return '';
    } catch {
      return '';
    }
  }

  /**
   * 提取 CSRF Token
   */
  private extractCsrfToken(html: string): string | null {
    const meta = html.match(/<meta[^>]+name="csrf-token"[^>]+content="([^"]+)"/i);
    if (meta) return meta[1];
    const win = html.match(/csrfToken["']?\s*[:=]\s*["']([^"']+)["']/);
    if (win) return win[1];
    const ck = this.cookie.match(/(?:csrf|token)=([^;]+)/i);
    if (ck) return ck[1];
    return null;
  }

  /**
   * 获取最新帖子列表 (用于自动回帖)
   */
  async getLatestPosts(): Promise<{ threadId: string; title: string }[]> {
    try {
      const res = await fetch('https://www.nodeseek.com/', { headers: this.headers() });
      if (!res.ok) return [];
      const html = await res.text();
      
      const posts: { threadId: string; title: string }[] = [];
      const regex = /<a[^>]+href="\/post-(\d+)-\d+"[^>]*class="[^"]*post-title[^"]*"[^>]*>([^<]+)<\/a>/g;
      let m: RegExpExecArray | null;
      while ((m = regex.exec(html)) !== null) {
        posts.push({ threadId: m[1], title: m[2].trim() });
      }
      return posts;
    } catch {
      return [];
    }
  }

  /**
   * 顶贴：发送评论
   */
  async bumpThread(threadId: string, content?: string): Promise<boolean> {
    try {
      const pageRes = await fetch(`https://www.nodeseek.com/post-${threadId}-1`, {
        headers: this.headers(),
      });
      const pageHtml = await pageRes.text();
      const csrfToken = this.extractCsrfToken(pageHtml);
      const postIdMatch = pageHtml.match(/data-post-id="(\d+)"/);

      const commentText = content || BUMP_COMMENTS[Math.floor(Math.random() * BUMP_COMMENTS.length)];

      const apiHeaders: Record<string, string> = {
        'Content-Type': 'application/json',
        Origin: 'https://www.nodeseek.com',
        Referer: `https://www.nodeseek.com/post-${threadId}-1`,
      };
      if (csrfToken) apiHeaders['Csrf-Token'] = csrfToken;

      const body: any = { content: commentText };
      if (postIdMatch) body.post_id = parseInt(postIdMatch[1]);

      const res = await fetch('https://www.nodeseek.com/api/content/new-comment', {
        method: 'POST',
        headers: this.headers(apiHeaders),
        body: JSON.stringify(body),
      });

      if (res.ok) {
        const data: any = await res.json();
        return data.success !== false;
      }
      return false;
    } catch (e) {
      console.error(`bumpThread error for ${threadId}:`, e);
      return false;
    }
  }

  /**
   * 搜索关键词，返回最新结果
   */
  async searchLatest(keyword: string): Promise<{
    title: string;
    link: string;
    timeStr: string;
    diffMinutes: number;
  } | null> {
    try {
      const q = encodeURIComponent(keyword);
      const res = await fetch(`https://www.nodeseek.com/search?q=${q}`, {
        headers: this.headers(),
        redirect: 'follow',
      });
      if (!res.ok) return null;
      const html = await res.text();

      // 找第一个帖子链接
      const titleMatch = html.match(/<a[^>]+href="(\/post-\d+-\d+)"[^>]*class="[^"]*post-title[^"]*"[^>]*>([^<]+)<\/a>/)
        || html.match(/<a[^>]+href="(\/post-\d+-\d+)"[^>]*>([^<]{2,})<\/a>/);
      if (!titleMatch) return null;

      const link = titleMatch[1];
      const title = titleMatch[2].trim();

      // 找附近的时间
      const pos = html.indexOf(link);
      const nearby = html.substring(Math.max(0, pos - 300), pos + 600);
      const tm = nearby.match(/<time[^>]+datetime="([^"]+)"/);
      if (!tm) return null;

      const timeStr = tm[1];
      const diffMinutes = (Date.now() - new Date(timeStr).getTime()) / 60000;

      return { title, link: `https://www.nodeseek.com${link}`, timeStr, diffMinutes };
    } catch (e) {
      console.error(`searchLatest error for '${keyword}':`, e);
      return null;
    }
  }
}
