# -*- coding: utf-8 -*-

"""真实浏览器抓取(Playwright)

用于绕过站点对纯 HTTP 客户端的反爬拦截(如 javbus 的空正文/年龄验证弹窗)。
该模块对 Playwright 采用懒加载:未安装 playwright 时不会影响程序其它功能,
只有 config.ini 里 `[scraper] use_browser = 1` 且安装了 playwright 才会启用。

首次使用需安装:
    pip install playwright
    playwright install chromium
"""

import time
import config

# 单例复用已启动的浏览器,避免每次请求都重新拉起
_shared_browser = None


def _get_browser(headless=True):
    """获取(或启动)浏览器实例"""
    global _shared_browser
    if _shared_browser is not None and _shared_browser.is_connected():
        return _shared_browser
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None
    try:
        pw = sync_playwright().start()
        _shared_browser = pw.chromium.launch(headless=headless, args=["--no-sandbox"])
        # 浏览器实例上挂载 playwright 对象,便于后续关闭
        setattr(_shared_browser, "_pw", pw)
        return _shared_browser
    except Exception as e:
        if config.getInstance().debug():
            print(f"[-]启动浏览器失败: {e} (确认已执行 playwright install chromium)")
        return None


def _close_browser():
    """关闭浏览器(供外部在程序退出时调用,节省资源)"""
    global _shared_browser
    if _shared_browser is not None:
        try:
            _shared_browser.close()
        except Exception:
            pass
        try:
            getattr(_shared_browser, "_pw", None) and getattr(_shared_browser, "_pw").stop()
        except Exception:
            pass
        _shared_browser = None


def _handle_age_verify(page):
    """处理 javbus 的年龄验证弹窗(#ageVerify): 勾选 checkbox 并点击确认

    返回 True 表示已处理;False 表示页面不存在年龄验证弹窗。
    """
    try:
        modal = page.locator("#ageVerify")
        if modal.count() == 0:
            return False
        checkbox = page.locator("#form1 input[type='checkbox']")
        if checkbox.count() > 0:
            checkbox.first.click()
        submit = page.locator("#submit")
        if submit.count() > 0:
            submit.click()
        # 等待弹窗消失/内容刷新
        modal.wait_for(state="hidden", timeout=8000)
        return True
    except Exception:
        return False


def get(url, cookies: dict = None, ua: str = None, timeout: int = 15,
        encoding: str = None, headless: bool = True):
    """通过真实浏览器抓取 url 页面 HTML

    若站点返回年龄验证弹窗,会自动确认年龄后重新获取真实内容。
    返回页面 HTML 字符串;失败返回 None。
    """
    browser = _get_browser(headless=headless)
    if browser is None:
        if config.getInstance().debug():
            print("[-]playwright 未安装,浏览器抓取不可用(需: pip install playwright && playwright install chromium)")
        return None
    try:
        context = browser.new_context(user_agent=ua or None)
        if isinstance(cookies, dict) and cookies:
            context.add_cookies([{"name": k, "url": url, "value": str(v)} for k, v in cookies.items()])
        page = context.new_page()
        page.goto(url, timeout=timeout * 1000, wait_until="domcontentloaded")
        # 处理年龄验证弹窗并等待真实内容
        _handle_age_verify(page)
        page.wait_for_timeout(1500)
        content = page.content()
        context.close()
        return content
    except Exception as e:
        if config.getInstance().debug():
            print(f"[-]browser.get() Failed! {e}")
        return None