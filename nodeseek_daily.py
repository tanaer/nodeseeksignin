# -- coding: utf-8 --
"""
Copyright (c) 2024 [Hosea]
Licensed under the MIT License.
See LICENSE file in the project root for full license information.

重构版: 使用 Camoufox (Playwright) 替代 Selenium + undetected-chromedriver
"""
import os
import requests
import random
import time
import re
import traceback
from datetime import datetime, timezone, timedelta

from camoufox.sync_api import Camoufox
from ns_config import config
from notifier import Notifier

# 随机评论内容
randomInputStr = [
    "bd", "绑定", "帮顶", "吃瓜吃瓜", "好价", "过来看一下",
    "喝杯奶茶压压惊", "咕噜咕噜", "前排", "悄悄地我来了悄悄地又走了",
    "恭喜发财", "好基", "公道公道", "楼主不错 绑定", "还可以",
    "再看看吧", "楼下要了", "挺不错的 bdbd", "好价 好价",
    "给楼下点个", "祝早出", "观望一下 早出", "让给楼下",
    "bd 可惜用不上 楼下来秒了", "还要啥自行车", "卷起来",
    "就是这个feel", "这是什么东西", "吗喽~~~",
    "收了吧楼下", "bd一下", "bd"
]

# 评论区域配置
COMMENT_URL = (os.environ.get("NS_COMMENT_URL", "") or "").strip() or "https://www.nodeseek.com/categories/trade"
ENABLE_COMMENT = os.environ.get("NS_COMMENT", "").lower() != "false"

# 随机延迟配置
DELAY_MIN = int(os.environ.get("NS_DELAY_MIN", "") or "0")
DELAY_MAX = int(os.environ.get("NS_DELAY_MAX", "") or "10")


def _wait_for_cloudflare(page, max_wait=30):
    """等待 Cloudflare 验证通过"""
    time.sleep(3)
    for i in range(max_wait // 3):
        try:
            title = page.title()
            if "Just a moment" not in title and "Attention Required" not in title:
                return True
            print(f"等待 Cloudflare 验证... (已等待 {(i+1)*3} 秒)")
            time.sleep(3)
        except:
            time.sleep(3)
    print("Cloudflare 验证超时")
    return False


def check_login_status(page):
    """检测 Cookie 是否有效"""
    try:
        print("正在检测登录状态...")
        title = page.title()
        print(f"当前页面标题: {title}")

        if "Just a moment" in title or "Attention" in title:
            if not _wait_for_cloudflare(page):
                return False

        content = page.content()

        # 存在头像相关元素 → 已登录
        avatar_count = page.locator('.avatar, .nsk-user-avatar, [class*="avatar"]').count()
        login_btn_count = page.locator("text=登录").count()

        print(f"检测结果: 头像={avatar_count}, 登录按钮={login_btn_count}")

        if avatar_count > 0 and login_btn_count == 0:
            print("✅ 登录状态有效")
            return True
        else:
            print("❌ Cookie 已过期或未登录")
            return False
    except Exception as e:
        print(f"检测登录状态出错: {e}")
        return False


def _parse_reward_from_text(text):
    """从文本中解析鸡腿数量"""
    match = re.search(
        r"获得\s*(\d+)\s*鸡腿|鸡腿\s*(\d+)\s*个|踩到鸡腿\s*(\d+)\s*个|得鸡腿(\d+)个",
        text
    )
    if match:
        return match.group(1) or match.group(2) or match.group(3) or match.group(4)
    match2 = re.search(r"(\d+)\s*(?:个?\s*鸡腿|鸡腿)", text)
    if match2:
        return match2.group(1)
    return "未知"


def click_sign_icon(page):
    """
    执行签到操作
    返回: (status, message)
    """
    try:
        print("直接访问签到页面...")
        page.goto("https://www.nodeseek.com/board", wait_until="domcontentloaded")
        _wait_for_cloudflare(page)
        time.sleep(3)

        current_url = page.url
        print(f"当前页面URL: {current_url}")

        # 查找签到面板
        try:
            page.wait_for_selector('.board-intro', timeout=10000)
            intro_text = page.locator('.board-intro').inner_text()
            print(f"面板文本: {intro_text}")

            if "获得" in intro_text or "排名" in intro_text or "已签到" in intro_text:
                print("✅ 已签到")
                count = _parse_reward_from_text(intro_text)
                return "already", count

            # 检查按钮
            buttons = page.locator('.board-intro button').all()
            if buttons:
                target = None
                for btn in buttons:
                    text = btn.inner_text()
                    if config.ns_random and "手气" in text:
                        target = btn
                        print("选择 '试试手气' 按钮")
                        break
                    elif not config.ns_random and ("鸡腿" in text or "x 5" in text):
                        target = btn
                        print("选择 '鸡腿 x 5' 按钮")
                        break

                if not target:
                    target = buttons[0]

                target.scroll_into_view_if_needed()
                time.sleep(0.3)
                target.click()
                print("签到按钮点击成功")
                time.sleep(3)

                new_text = page.locator('.board-intro').inner_text()
                count = _parse_reward_from_text(new_text)
                return "success", count

            return "failed", "未找到按钮"

        except Exception:
            # 兜底: 全局搜索
            print("未找到签到面板，尝试全局查找...")
            body_text = page.locator('body').inner_text()

            if "今日已签到" in body_text or "签到成功" in body_text:
                count = _parse_reward_from_text(body_text)
                return "already", count

            btns = page.locator("button:has-text('鸡腿'), button:has-text('手气')").all()
            if btns:
                btns[0].click()
                time.sleep(3)
                body_text = page.locator('body').inner_text()
                count = _parse_reward_from_text(body_text)
                return "success", count

            return "failed", "状态未知"

    except Exception as e:
        print(f"签到出错: {e}")
        traceback.print_exc()
        return "failed", f"异常: {e}"


def nodeseek_comment(page):
    """执行随机评论任务"""
    comment_count = 0
    try:
        print(f"正在访问评论区域: {COMMENT_URL}")
        page.goto(COMMENT_URL, wait_until="domcontentloaded")
        _wait_for_cloudflare(page)

        page.wait_for_selector('.post-list-item', timeout=30000)
        posts = page.locator('.post-list-item').all()
        print(f"获取到 {len(posts)} 个帖子")

        # 过滤置顶
        valid_posts = []
        for p in posts:
            if p.locator('.pined').count() == 0:
                valid_posts.append(p)

        post_count = random.randint(3, 5)
        selected = random.sample(valid_posts, min(post_count, len(valid_posts)))

        # 收集 URL
        urls = []
        for post in selected:
            try:
                link = post.locator('.post-title a').first.get_attribute('href')
                if link:
                    urls.append(link)
            except:
                continue

        consecutive_fails = 0
        for i, url in enumerate(urls):
            if consecutive_fails >= 2:
                print(f"⚠️ 连续失败 {consecutive_fails} 次，停止评论")
                break

            try:
                print(f"处理第 {i+1} 个帖子: {url}")
                page.goto(url, wait_until="domcontentloaded")
                _wait_for_cloudflare(page)
                time.sleep(2)

                editor = page.locator('.CodeMirror')
                editor.wait_for(state='visible', timeout=15000)
                editor.click()
                time.sleep(0.5)

                input_text = random.choice(randomInputStr)
                try:
                    page.evaluate('''(text) => {
                        var cm = document.querySelector('.CodeMirror').CodeMirror;
                        if (cm) { cm.setValue(text); }
                    }''', input_text)
                except:
                    editor.type(input_text, delay=100)

                time.sleep(1)

                submit = page.locator("button.submit.btn:has-text('发布评论')")
                if submit.count() == 0:
                    submit = page.locator(
                        "xpath=//button[contains(@class,'submit') and contains(text(),'发布评论')]"
                    )
                submit.scroll_into_view_if_needed()
                time.sleep(0.3)
                submit.click()

                print(f"已完成评论: {url}")
                comment_count += 1
                consecutive_fails = 0

                wait_min = random.uniform(1, 2)
                print(f"等待 {wait_min:.1f} 分钟后继续...")
                time.sleep(wait_min * 60)

            except Exception as e:
                print(f"处理帖子出错: {e}")
                consecutive_fails += 1
                try:
                    page.goto("https://www.nodeseek.com", wait_until="domcontentloaded")
                    time.sleep(2)
                except:
                    break

        return comment_count

    except Exception as e:
        print(f"评论出错: {e}")
        traceback.print_exc()
        return comment_count


def run_for_account(cookie_str, account_index):
    """为单个账号执行签到+评论任务"""
    result = {
        "sign_in": "failed",
        "reward": "0",
        "comments": 0,
        "error": None
    }

    print(f"\n{'='*50}")
    print(f"开始处理账号 {account_index + 1}")
    print(f"{'='*50}")

    if not cookie_str:
        result["error"] = "Cookie 为空"
        return result

    try:
        with Camoufox(headless=config.headless) as browser:
            page = browser.new_page()
            page.set_viewport_size({"width": 1920, "height": 1080})

            # 访问首页并注入 Cookie
            page.goto('https://www.nodeseek.com', wait_until="domcontentloaded")
            time.sleep(3)

            cookies_to_add = []
            for item in cookie_str.split(';'):
                try:
                    name, value = item.strip().split('=', 1)
                    cookies_to_add.append({
                        'name': name.strip(),
                        'value': value.strip(),
                        'domain': '.nodeseek.com',
                        'path': '/'
                    })
                except:
                    continue

            page.context.add_cookies(cookies_to_add)
            page.reload(wait_until="domcontentloaded")
            time.sleep(3)
            _wait_for_cloudflare(page)

            # 检测登录
            if not check_login_status(page):
                result["error"] = "Cookie 已过期"
                return result

            # 签到
            status, reward = click_sign_icon(page)
            result["sign_in"] = status
            result["reward"] = reward

            # 评论
            if ENABLE_COMMENT:
                result["comments"] = nodeseek_comment(page)
            else:
                print("评论功能已关闭")

    except Exception as e:
        result["error"] = f"浏览器异常: {e}"
        traceback.print_exc()

    return result


if __name__ == "__main__":
    print("开始执行 NodeSeek 自动任务...")
    print(f"当前配置: NS_RANDOM={config.ns_random}, HEADLESS={config.headless}")

    if config.account_count == 0:
        print("未配置 Cookie，退出")
        Notifier.send_tg("❌ <b>NodeSeek 自动任务失败</b>\n\n未配置 NS_COOKIE 环境变量")
        exit(1)

    print(f"检测到 {config.account_count} 个账号")

    # 随机延迟
    if DELAY_MAX > 0:
        actual_min = min(DELAY_MIN, DELAY_MAX)
        actual_max = max(DELAY_MIN, DELAY_MAX)
        delay_min = random.randint(actual_min, actual_max)
        if delay_min > 0:
            print(f"随机延迟: 等待 {delay_min} 分钟...")
            time.sleep(delay_min * 60)

    # 执行
    all_results = []
    for i, cookie in enumerate(config.cookies):
        result = run_for_account(cookie, i)
        all_results.append(result)

    print(f"\n{'='*50}")
    print("所有账号任务执行完成")
    print(f"{'='*50}")

    # 汇报 (北京时间)
    beijing_tz = timezone(timedelta(hours=8))
    beijing_time = datetime.now(beijing_tz).strftime("%Y-%m-%d %H:%M:%S")

    if config.account_count == 1:
        r = all_results[0]
        if r["error"]:
            report = (
                f"<b>NodeSeek 每日简报</b>\n"
                f"━━━━━━━━━━━━━━━\n"
                f"❌ <b>任务失败</b>\n"
                f"⚠️ <b>错误</b>: {r['error']}\n"
                f"🕒 {beijing_time}"
            )
        else:
            sign_icon = "✅" if r["sign_in"] in ("success", "already") else "❌"
            sign_text = "已签到" if r["sign_in"] == "already" else ("签到成功" if r["sign_in"] == "success" else "签到失败")
            report = (
                f"<b>NodeSeek 每日简报</b>\n"
                f"━━━━━━━━━━━━━━━\n"
                f"🏆 <b>奖励</b>: <b>{r['reward']}</b> 🍗\n"
                f"💬 <b>评论</b>: {r['comments']} 条\n"
                f"{sign_icon} <b>状态</b>: {sign_text}\n"
                f"🕒 {beijing_time}"
            )
    else:
        lines = []
        for i, r in enumerate(all_results):
            if r["error"]:
                lines.append(f"❌ 账号{i+1}: {r['error']}")
            else:
                sign = f"✅ +{r['reward']}🍗" if r["sign_in"] in ("success", "already") else "❌"
                lines.append(f"👤 账号{i+1}: {sign} | 💬 {r['comments']}条")
        report = (
            f"<b>NodeSeek 每日简报</b>\n"
            f"━━━━━━━━━━━━━━━\n"
            + "\n".join(lines)
            + f"\n━━━━━━━━━━━━━━━\n🕒 {beijing_time}"
        )

    Notifier.send_tg(report)
