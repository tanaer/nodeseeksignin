import time
import threading
from datetime import datetime, timezone
import urllib.parse
import traceback
import random

from camoufox.sync_api import Camoufox
from twocaptcha import TwoCaptcha
from ns_config import config

# 随机顶贴评论内容
BUMP_COMMENTS = [
    "bd", "绑定", "帮顶", "好价", "过来看一下", "前排",
    "公道公道", "还可以", "挺不错的 bdbd", "好价 好价",
    "祝早出", "观望一下 早出", "bd一下", "bd", "帮顶一下",
    "顶一下", "支持支持", "棒棒哒"
]


class NodeSeekCrawler:
    """
    使用 Camoufox 引擎 (基于 Playwright) 进行高强度反检测爬取。
    Camoufox 必须通过 `with` 上下文管理器使用，因此本类在需要时打开浏览器，
    使用完毕后自动关闭，避免长期持有进程引起异常。
    对外暴露的每个公共方法都是完整的 "打开→操作→关闭" 原子操作。
    使用互斥锁防止并发冲突。
    """
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(NodeSeekCrawler, cls).__new__(cls)
            cls._instance.solver = TwoCaptcha(config.twocaptcha_api_key)
        return cls._instance

    def _setup_cookies(self, page):
        """向浏览器注入 NodeSeek Cookie"""
        if not config.cookies:
            return False
        cookie_str = config.cookies[0]
        cookies_to_add = []
        for cookie_item in cookie_str.split(';'):
            try:
                name, value = cookie_item.strip().split('=', 1)
                cookies_to_add.append({
                    'name': name.strip(),
                    'value': value.strip(),
                    'domain': '.nodeseek.com',
                    'path': '/'
                })
            except Exception:
                continue
        if cookies_to_add:
            page.context.add_cookies(cookies_to_add)
        return True

    def _wait_for_cloudflare(self, page, max_wait=30):
        """等待 Cloudflare 验证通过，超时后尝试 2Captcha 兜底"""
        try:
            time.sleep(3)
            title = page.title()

            if "Just a moment" not in title and "Attention Required" not in title:
                return True

            print("🛡️ 检测到 Cloudflare 防火墙，等待自动通过...")

            # 靠 Camoufox 指纹能力自动通过
            for i in range(max_wait // 3):
                time.sleep(3)
                title = page.title()
                if "Just a moment" not in title and "Attention Required" not in title:
                    print(f"✅ CF 自动验证通过 (等待了约 {(i+1)*3} 秒)")
                    return True

            # 超时 → 2Captcha 兜底
            print("⚠️ 自动验证超时，启动 2Captcha Turnstile 兜底...")
            return self._solve_turnstile_with_2captcha(page)

        except Exception as e:
            print(f"CF 判定异常: {e}")
            return False

    def _solve_turnstile_with_2captcha(self, page):
        """调用 2Captcha API 解决 CF Turnstile"""
        try:
            sitekey = page.evaluate('''() => {
                const el = document.querySelector('.cf-turnstile, [data-sitekey]');
                if (el) return el.getAttribute('data-sitekey');
                if (window._cf_chl_opt && window._cf_chl_opt.cRay) {
                    // CF challenge page often has sitekey in _cf_chl_opt
                    return window._cf_chl_opt.chlApiSitekey || null;
                }
                return null;
            }''')

            if not sitekey:
                print("❌ 无法提取 CF Turnstile Sitekey")
                return False

            print(f"🔑 Sitekey: {sitekey}，请求 2Captcha 求解中...")

            result = self.solver.turnstile(
                sitekey=sitekey,
                url=page.url
            )

            cf_token = result['code']
            print("✅ 2Captcha 返回 Token，正在注入页面...")

            page.evaluate('''(token) => {
                // 方案A: 直接写入隐藏 input 并提交表单
                var input = document.querySelector('[name="cf-turnstile-response"]');
                if (input) {
                    input.value = token;
                    if (input.form) { input.form.submit(); return; }
                }
                // 方案B: 调用 turnstile 回调
                if (typeof window.turnstileCallback === 'function') {
                    window.turnstileCallback(token);
                }
            }''', cf_token)

            time.sleep(5)
            title = page.title()
            if "Just a moment" not in title and "Attention Required" not in title:
                print("🎉 2Captcha 兜底成功！")
                return True
            else:
                print("❌ Token 注入后页面仍未放行")
                return False

        except Exception as e:
            print(f"❌ 2Captcha 兜底异常: {e}")
            return False

    def _open_and_login(self, browser):
        """打开首页、注入 Cookie、刷新并验证 CF"""
        page = browser.new_page()
        page.set_viewport_size({"width": 1920, "height": 1080})
        page.goto('https://www.nodeseek.com', wait_until="domcontentloaded")
        time.sleep(2)
        self._setup_cookies(page)
        page.reload(wait_until="domcontentloaded")
        time.sleep(2)
        self._wait_for_cloudflare(page)
        return page

    # ==================== 公共业务方法 ====================

    def get_thread_last_reply_time(self, thread_id):
        """
        获取某主题帖最后一条回复距今的分钟数。
        返回 -1 表示获取失败。
        """
        with self._lock:
            try:
                with Camoufox(headless=config.headless) as browser:
                    page = self._open_and_login(browser)
                    page.goto(f"https://www.nodeseek.com/post-{thread_id}-1",
                              wait_until="domcontentloaded")
                    self._wait_for_cloudflare(page)
                    time.sleep(2)

                    # 如果有分页，找最后一页
                    page_links = page.locator('.pager-pos').all()
                    max_page = 1
                    for link in page_links:
                        text = link.inner_text().strip()
                        if text.isdigit():
                            max_page = max(max_page, int(text))
                    
                    if max_page > 1:
                        page.goto(f"https://www.nodeseek.com/post-{thread_id}-{max_page}",
                                  wait_until="domcontentloaded")
                        self._wait_for_cloudflare(page)
                        time.sleep(2)
                        
                    # 等待帖子加载
                    page.wait_for_selector('.post-list-item', timeout=15000)
                    posts = page.locator('.post-list-item').all()
                    if not posts:
                        return -1

                    last_post = posts[-1]
                    time_els = last_post.locator('time').all()
                    if not time_els:
                        return -1

                    date_str = time_els[-1].get_attribute('datetime')
                    if not date_str:
                        return -1

                    post_time = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                    now = datetime.now(timezone.utc)
                    return (now - post_time).total_seconds() / 60.0

            except Exception as e:
                print(f"获取帖子 {thread_id} 最后回复时间失败: {e}")
                traceback.print_exc()
                return -1

    def bump_thread(self, thread_id, content=None):
        """在指定主题下发送评论以实现顶贴"""
        if content is None:
            content = random.choice(BUMP_COMMENTS)

        with self._lock:
            try:
                with Camoufox(headless=config.headless) as browser:
                    page = self._open_and_login(browser)

                    # 导航到最后一页（帖子末尾）
                    page.goto(f"https://www.nodeseek.com/post-{thread_id}-1",
                              wait_until="domcontentloaded")
                    self._wait_for_cloudflare(page)
                    time.sleep(2)

                    # 定位 CodeMirror 编辑器
                    editor = page.locator('.CodeMirror')
                    editor.wait_for(state='visible', timeout=15000)
                    editor.click()
                    time.sleep(0.5)

                    # JS 注入内容到 CodeMirror
                    try:
                        page.evaluate('''(text) => {
                            var cm = document.querySelector('.CodeMirror').CodeMirror;
                            if (cm) { cm.setValue(text); }
                        }''', content)
                    except Exception:
                        editor.type(content, delay=80)

                    time.sleep(1)

                    # 点击发布按钮
                    submit = page.locator(
                        "button.submit.btn:has-text('发布评论')"
                    )
                    if submit.count() == 0:
                        # XPath 备用
                        submit = page.locator(
                            "xpath=//button[contains(@class,'submit') and contains(text(),'发布评论')]"
                        )
                    submit.scroll_into_view_if_needed()
                    time.sleep(0.3)
                    submit.click()
                    time.sleep(3)
                    print(f"✅ 帖子 {thread_id} 顶帖成功 (内容: {content})")
                    return True

            except Exception as e:
                print(f"顶贴(ID:{thread_id})失败: {e}")
                traceback.print_exc()
                return False

    def search_keyword_latest(self, keyword):
        """
        执行站内搜索，返回第一条结果的元数据。
        返回 dict or None。
        """
        with self._lock:
            try:
                with Camoufox(headless=config.headless) as browser:
                    page = self._open_and_login(browser)

                    q = urllib.parse.quote(keyword)
                    page.goto(f"https://www.nodeseek.com/search?q={q}",
                              wait_until="domcontentloaded")
                    self._wait_for_cloudflare(page)
                    time.sleep(2)

                    # 等待搜索结果渲染
                    try:
                        page.wait_for_selector('.post-list-item', timeout=10000)
                    except Exception:
                        print(f"搜索 '{keyword}' 无结果或页面加载超时")
                        return None

                    posts = page.locator('.post-list-item').all()
                    if not posts:
                        return None

                    first_post = posts[0]

                    # 标题与链接
                    title_loc = first_post.locator('.post-title a')
                    if title_loc.count() == 0:
                        title_loc = first_post.locator('a').first
                    else:
                        title_loc = title_loc.first

                    title = title_loc.inner_text()
                    link = title_loc.get_attribute('href')

                    # 时间
                    time_els = first_post.locator('time').all()
                    if not time_els:
                        return None
                    time_str = time_els[0].get_attribute('datetime')
                    if not time_str:
                        return None

                    post_time = datetime.fromisoformat(time_str.replace('Z', '+00:00'))
                    now = datetime.now(timezone.utc)
                    diff_minutes = (now - post_time).total_seconds() / 60.0

                    return {
                        "title": title,
                        "link": link,
                        "time_str": time_str,
                        "diff_minutes": diff_minutes
                    }

            except Exception as e:
                print(f"搜索关键字 '{keyword}' 异常: {e}")
                traceback.print_exc()
                return None
