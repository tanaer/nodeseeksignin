# NodeSeek 自动签到 + Telegram Bot 监控

基于 **Camoufox** 反检测浏览器引擎的 NodeSeek 论坛自动化工具，支持 GitHub Actions 定时签到 和 Telegram Bot 常驻监控两种运行模式。

## ✨ 功能

### 📅 每日签到（GitHub Actions）
- ✅ 自动签到领奖（"试试手气" / "鸡腿 x 5" 可选）
- 💬 随机评论帖子（3-5 篇，间隔 1-2 分钟）
- 👥 多账号支持（Cookie 用 `|` 分隔）
- ⏰ 随机延迟执行（防固定时间触发）
- 📱 Telegram 通知汇报

### 🤖 Telegram Bot 常驻服务（需自行部署）
- 🆙 **自动顶贴** — 指定帖子 ID，最后回复超过 N 分钟自动顶贴
- 🔍 **关键词监控** — 搜索论坛，N 分钟内有新帖即推送通知
- 📢 **双通道通知** — 支持 Telegram 和 PushPlus
- 📝 **任务管理** — 通过 Bot 命令增删改查所有任务
- 💾 **Upstash Redis 持久化** — 任务配置和冷却时间云端存储

### 🛡️ 反检测与验证码
- 🦊 **Camoufox** — 基于 Firefox 的反指纹浏览器，远超传统 Selenium
- 🔓 **2Captcha 兜底** — 遇到 CF Turnstile 验证码自动求解

---

## 🚀 快速开始

### 方式一：GitHub Actions 自动签到（Fork 即用）

1. **Fork** 本仓库
2. 在 `Settings → Secrets and variables → Actions` 中添加配置（见下方表格）
3. Actions 将每天自动执行两次：
   - 北京时间 **00:10** 和 **12:20**

### 方式二：Telegram Bot 常驻部署

```bash
# 1. 克隆仓库
git clone https://github.com/tanaer/nodeseek-AutoDaily-signin.git
cd nodeseek-AutoDaily-signin

# 2. 安装依赖
pip install -r requirements.txt
python -m camoufox fetch   # 下载 Camoufox 浏览器内核

# 3. 配置环境变量（见下方表格）
export NS_COOKIE="your_cookie_here"
export TG_BOT_TOKEN="your_bot_token"
export TG_CHAT_ID="your_chat_id"
export REDIS_URL="rediss://your_upstash_url"

# 4. 启动 Bot
python bot.py
```

---

## 🤖 Bot 命令

| 命令 | 说明 | 示例 |
|------|------|------|
| `/start` | 显示帮助 | `/start` |
| `/add_bump <帖子ID> <冷却分钟>` | 添加自动顶贴任务 | `/add_bump 12345 60` |
| `/add_notify <关键字> <tg\|pushplus> <冷却分钟>` | 添加关键词监控 | `/add_notify 服务器 tg 10` |
| `/list` | 查看所有任务 | `/list` |
| `/delete <任务ID>` | 删除任务 | `/delete f47ac10b` |

### 功能说明

**自动顶贴** `/add_bump`
- 系统每 5 分钟巡检一次
- 检查指定帖子最后一条回复的时间
- 如果距今超过设定的冷却分钟数 → 自动发一条评论顶贴
- 顶贴成功后进入冷却期，冷却结束后继续巡检

**关键词监控** `/add_notify`
- 系统每 3 分钟巡检一次
- 访问 `nodeseek.com/search?q=关键字` 获取搜索结果
- 如果搜索到的最新帖子发布时间在冷却分钟数内 → 推送通知
- 通知后进入冷却期，避免重复提醒

---

## ⚙️ 环境变量

### Secrets（敏感信息）

| 变量名 | 必填 | 说明 |
|--------|------|------|
| `NS_COOKIE` | ✅ | NodeSeek Cookie，多账号用 `\|` 分隔 |
| `TG_BOT_TOKEN` | ✅ | Telegram Bot Token |
| `TG_CHAT_ID` | ✅ | Telegram Chat ID |
| `REDIS_URL` | Bot 模式必填 | Upstash Redis 连接 URL（`rediss://...`） |
| `PUSHPLUS_TOKEN` | ❌ | PushPlus 推送 Token（使用 pushplus 通道时需要） |
| `TWOCAPTCHA_API_KEY` | ❌ | 2Captcha API Key（已内置默认值） |
| `NS_RANDOM` | ❌ | `true`(默认): 试试手气 / `false`: 鸡腿 x 5 |
| `NS_COMMENT_URL` | ❌ | 评论区域 URL（默认交易区） |
| `NS_COMMENT` | ❌ | `true`(默认)，设为 `false` 关闭评论 |

### Variables（非敏感配置）

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `NS_DELAY_MIN` | `0` | 随机延迟最小分钟 |
| `NS_DELAY_MAX` | `10` | 随机延迟最大分钟 |
| `HEADLESS` | `true` | 是否使用无头模式 |

---

## 🍪 如何获取 NodeSeek Cookie

1. 打开浏览器，访问 [NodeSeek](https://www.nodeseek.com) 并登录
2. 按 `F12` 打开开发者工具 → **Network（网络）** 标签
3. 刷新页面，点击任意请求
4. 在 **Headers（标头）** 中找到 `Cookie` 字段，复制全部内容

```
session=abc123xyz; token=def456uvw; user_id=12345
```

> ⚠️ Cookie 包含登录凭证，请勿泄露！

## 📝 多账号配置

Cookie 之间用 `|` 分隔：

```
session=abc123; token=xyz|session=def456; token=uvw
```

---

## 📁 项目结构

```
├── bot.py              # Telegram Bot 主程序（常驻服务）
├── nodeseek_daily.py   # 每日签到脚本（GitHub Actions 用）
├── ns_config.py        # 统一配置管理
├── ns_crawler.py       # Camoufox 爬虫引擎 + 2Captcha 兜底
├── db_manager.py       # Upstash Redis 数据持久化
├── notifier.py         # 双通道通知 (Telegram + PushPlus)
├── requirements.txt    # Python 依赖
└── .github/workflows/
    └── daily.yml       # GitHub Actions 工作流
```

---

## ❓ 常见问题

**Q: Cookie 多久过期？**
A: 一般 7-30 天，过期后会收到 Telegram 告警。

**Q: 如何手动触发签到？**
A: 进入 Actions 页面 → 选择 workflow → 点击 "Run workflow"。

**Q: Bot 部署需要什么配置？**
A: 最低 1 核 1G 内存的 VPS 即可，需要能联网访问 Telegram API 和 NodeSeek。

**Q: Camoufox 支持 ARM 架构吗？**
A: 目前 Camoufox 主要支持 x86_64，ARM 支持请关注 [Camoufox 官方仓库](https://github.com/daijro/camoufox)。

## License

MIT
