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
import json
import re
import requests

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
        else:
            print("[+] 发现年龄验证弹窗")
        checkbox = page.locator("#form1 input[type='checkbox']")
        if checkbox.count() > 0:
            checkbox.first.click()
        else:
            print("[-] 未发现年龄验证弹窗的 checkbox")
        submit = page.locator("#submit")
        if submit.count() > 0:
            submit.click()
        # 等待弹窗消失/内容刷新
        modal.wait_for(state="hidden", timeout=8000)
        return True
    except Exception:
        return False


def _handle_age_verify_interstitial(page):
    """处理 javbus 的"你是否已經成年?"年龄确认页(driver-verify 前置页)

    与旧式 #ageVerify 弹窗不同,该页是一个居中模态,含"我已經成年"按钮,
    点击后设置 cookie 并跳转到真实内容。返回 True 表示已处理(至少点击过)。
    """
    try:
        # 判断是否命中年龄确认页文案
        body_text = page.locator("body").inner_text(timeout=3000)
        if "你是否已經成年" not in body_text and "是否已经成年" not in body_text:
            return False
        # 依次尝试点击"我已經成年"类按钮/链接
        for selector in [
            "button:has-text(\"我已經成年\")",
            "a:has-text(\"我已經成年\")",
            "button:has-text(\"我已经成年\")",
            "a:has-text(\"我已经成年\")",
            "button:has-text(\"滿18歲\")",
            "#submit",
            "button[type='submit']",
        ]:
            loc = page.locator(selector)
            if loc.count() > 0:
                try:
                    loc.first.click(timeout=3000)
                    return True
                except Exception:
                    continue
        # 兜底:直接勾选所有 checkbox 并提交第一个表单
        try:
            page.eval_on_selector_all(
                "input[type='checkbox']", "els => els.forEach(e => { if (!e.checked) e.checked = true; e.dispatchEvent(new Event('change')); })"
            )
            for s in ["button[type='submit']", "input[type='submit']", "#submit"]:
                if page.locator(s).count() > 0:
                    page.locator(s).first.click(timeout=3000)
                    return True
        except Exception:
            pass
    except Exception:
        return False


def _ask_llm(question_text):
    """调用大模型回答验证题目,返回 {题目名: 选项值} 字典

    使用 OpenAI 兼容的 Chat Completions 接口(config.ini 的 [llm])。
    失败返回 None。
    """
    conf = config.getInstance()
    api_url = conf.llm_api_url()
    api_key = conf.llm_api_key()
    if not api_url or not api_key:
        if conf.debug():
            print("[-]LLM 未配置 api_url/api_key,无法解决站内问题验证")
        return None
    model = conf.llm_model() or "glm-4-flash"
    prompt = (
        "你是一名道路交通安全专家。以下是 javbus 站点的驾驶证考试验证题目,"
        "每一道题的选项名形如 userAnswers[数字]。请为每道题选择唯一正确的一项,"
        '只返回如下的 JSON,不要任何解释:\n'
        '{"userAnswers[数字]": "正确选项", ...}\n\n'
        "题目:\n" + question_text
    )
    try:
        resp = requests.post(
            api_url,
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + api_key,
            },
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
                "top_p": 0.8,
            },
            timeout=30,
        )
    except Exception as e:
        if config.getInstance().debug():
            print("[-]调用大模型 API 失败:", e)
        return None
    if resp.status_code != 200:
        if config.getInstance().debug():
            print("[-]大模型 API 返回异常:", resp.status_code, resp.text[:200])
        return None
    try:
        content = resp.json()["choices"][0]["message"]["content"]
        # 抽取 JSON 对象
        m = re.search(r"\{[^{}]*\}", content, re.S)
        answers = json.loads(m.group(0)) if m else {}
        return answers if isinstance(answers, dict) else None
    except Exception as e:
        if config.getInstance().debug():
            print("[-]解析大模型答案失败:", e, resp.text[:200])
        return None


def _handle_driver_verify(page):
    """处理 javbus 的"问题验证"(driver-verify: 驾驶证考试题)

    页面包含表单,每题一个 <li>:
        <label> 题目文字 </label>
        <input type="radio" name="userAnswers[N]" value="A|B|C|D"> 选项文字
    按钮: <button type="submit" name="submit" value="question">
    用大模型计算答案并勾选提交。成功返回 True。
    """
    try:
        if page.locator("input[name^='userAnswers[']").count() == 0:
            return False
        if not config.getInstance().use_llm():
            if config.getInstance().debug():
                print("[-]检测到站内问题验证,但 [llm] 未开启")
            return False

        # 提取题目文本供大模型阅读
        parts = []
        for li in page.locator("form li").all():
            label = li.locator("label")
            if label.count() == 0:
                continue
            parts.append("题目: " + label.first.inner_text().strip())
            for radio in li.locator("input[type='radio']").all():
                name = radio.get_attribute("name") or ""
                value = radio.get_attribute("value") or ""
                # 取 radio 之后的文本作为选项文字
                t = radio.evaluate("el => (el.nextSibling && el.nextSibling.nodeType===3) ? el.nextSibling.nodeValue : ''")
                parts.append("  [{}= {}] {}".format(name, value, (t or "").strip()))
        if not parts:
            return False
        question_text = "\n".join(parts)

        answers = _ask_llm(question_text)
        if not answers:
            return False

        selected = 0
        for name, value in answers.items():
            try:
                radio = page.locator("input[name='{}'][value='{}']".format(name, value))
                if radio.count() > 0:
                    radio.first.check(timeout=3000)
                    selected += 1
            except Exception:
                continue
        if selected == 0:
            return False

        # 提交答案
        for s in [
            "button[type='submit'][name='submit'][value='question']",
            "button[type='submit']",
            "input[type='submit']",
        ]:
            loc = page.locator(s)
            if loc.count() > 0:
                try:
                    loc.first.click(timeout=3000)
                    break
                except Exception:
                    continue
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

        # 1) 处理旧式 #ageVerify 年龄验证弹窗
        _handle_age_verify(page)

        # 2) 处理 javbus 的"你是否已經成年?"前置页:点击确认后需重新访问原 URL
        if _handle_age_verify_interstitial(page):
            page.wait_for_timeout(1500)
            # 确认年龄后 cookie 已种下,重新访问原始 URL 以获取真实页面
            try:
                page.goto(url, timeout=timeout * 1000, wait_until="domcontentloaded")
                page.wait_for_timeout(1500)
            except Exception:
                pass

        # 3) 处理"问题验证"(driver-verify):用大模型作答并提交,随后等待跳回内容页
        if _handle_driver_verify(page):
            page.wait_for_timeout(4000)
            page.wait_for_load_state("domcontentloaded", timeout=10000)

        content = page.content()
        context.close()
        return content
    except Exception as e:
        if config.getInstance().debug():
            print(f"[-]browser.get() Failed! {e}")
        return None