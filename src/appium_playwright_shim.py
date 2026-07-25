#!/usr/bin/env python3
"""Playwright-like async API over Appium WebDriver (cloud real devices).

complete_apply.py is written against Playwright Page/Locator. Cloud phones
expose Appium (Selenium) instead of CDP. This shim implements the subset of
the Playwright async API that complete_apply uses, so the same form-fill
logic can run on a rented Galaxy S26 Chrome session.

Not a full Playwright replacement — multi-tab, complex frames, and some
locator engines are best-effort.
"""
from __future__ import annotations

import asyncio
import base64
import re
import time
from pathlib import Path
from typing import Any, Callable, Optional

from selenium.common.exceptions import (
    NoSuchElementException,
    StaleElementReferenceException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait


def _run(fn: Callable, *args, **kwargs):
    return asyncio.to_thread(fn, *args, **kwargs)


def _css_from_playwright(sel: str) -> str:
    """Best-effort Playwright → CSS (drops :visible pseudo)."""
    s = (sel or "").strip()
    s = re.sub(r":visible\b", "", s)
    s = re.sub(r":has-text\([^)]*\)", "", s)
    return s.strip() or "body"


class AppiumLocator:
    def __init__(
        self,
        page: "AppiumPage",
        *,
        css: str | None = None,
        xpath: str | None = None,
        by: str = By.CSS_SELECTOR,
        value: str | None = None,
        index: int | None = None,
    ):
        self._page = page
        self._css = css
        self._xpath = xpath
        self._by = by
        self._value = value if value is not None else (xpath or css or "")
        self._index = index

    def _find_all_sync(self) -> list[WebElement]:
        d = self._page.driver
        try:
            els = d.find_elements(self._by, self._value)
        except WebDriverException:
            return []
        return [e for e in els if e]

    def _pick_sync(self) -> WebElement | None:
        els = self._find_all_sync()
        if not els:
            return None
        if self._index is not None:
            if self._index < 0 or self._index >= len(els):
                return None
            return els[self._index]
        # Prefer displayed elements
        for e in els:
            try:
                if e.is_displayed():
                    return e
            except StaleElementReferenceException:
                continue
        return els[0]

    def nth(self, i: int) -> "AppiumLocator":
        return AppiumLocator(
            self._page,
            by=self._by,
            value=self._value,
            css=self._css,
            xpath=self._xpath,
            index=i,
        )

    def first(self) -> "AppiumLocator":
        return self.nth(0)

    async def count(self) -> int:
        return await _run(lambda: len(self._find_all_sync()))

    async def all(self) -> list["AppiumLocator"]:
        n = await self.count()
        return [self.nth(i) for i in range(n)]

    async def is_visible(self, timeout: float = 0) -> bool:
        def _vis() -> bool:
            el = self._pick_sync()
            if not el:
                return False
            try:
                return bool(el.is_displayed())
            except Exception:
                return False

        if timeout and timeout > 0:
            end = time.time() + timeout / 1000.0
            while time.time() < end:
                if await _run(_vis):
                    return True
                await asyncio.sleep(0.15)
            return False
        return await _run(_vis)

    async def click(self, timeout: float = 10000, force: bool = False, **kwargs):
        def _click():
            el = self._pick_sync()
            if not el:
                raise TimeoutException(f"No element for {self._by}={self._value}")
            try:
                el.click()
            except WebDriverException:
                self._page.driver.execute_script("arguments[0].click();", el)

        await _run(_click)

    async def fill(self, value: str, timeout: float = 10000, **kwargs):
        def _fill():
            el = self._pick_sync()
            if not el:
                raise TimeoutException(f"No element to fill: {self._value}")
            try:
                el.clear()
            except Exception:
                pass
            el.send_keys(str(value))

        await _run(_fill)

    async def type(self, text: str, delay: float = 0, **kwargs):
        await self.fill(text)

    async def press(self, key: str, **kwargs):
        mapping = {
            "Enter": Keys.ENTER,
            "Tab": Keys.TAB,
            "Escape": Keys.ESCAPE,
            "Backspace": Keys.BACKSPACE,
        }
        k = mapping.get(key, key)

        def _press():
            el = self._pick_sync()
            if el:
                el.send_keys(k)

        await _run(_press)

    async def check(self, **kwargs):
        def _check():
            el = self._pick_sync()
            if not el:
                return
            if not el.is_selected():
                el.click()

        await _run(_check)

    async def uncheck(self, **kwargs):
        def _uncheck():
            el = self._pick_sync()
            if not el:
                return
            if el.is_selected():
                el.click()

        await _run(_uncheck)

    async def select_option(
        self,
        value: str | None = None,
        label: str | None = None,
        index: int | None = None,
        **kwargs,
    ):
        def _sel():
            el = self._pick_sync()
            if not el:
                raise TimeoutException("select not found")
            s = Select(el)
            if value is not None:
                try:
                    s.select_by_value(value)
                    return
                except Exception:
                    pass
            if label is not None:
                try:
                    s.select_by_visible_text(label)
                    return
                except Exception:
                    for opt in s.options:
                        if label.lower() in (opt.text or "").lower():
                            opt.click()
                            return
            if index is not None:
                s.select_by_index(index)

        await _run(_sel)

    async def get_attribute(self, name: str) -> str | None:
        def _ga():
            el = self._pick_sync()
            if not el:
                return None
            return el.get_attribute(name)

        return await _run(_ga)

    async def inner_text(self, timeout: float = 5000) -> str:
        def _it():
            el = self._pick_sync()
            if not el:
                return ""
            return (el.text or el.get_attribute("textContent") or "").strip()

        return await _run(_it)

    async def text_content(self) -> str | None:
        return await self.inner_text()

    async def input_value(self) -> str:
        return (await self.get_attribute("value")) or ""

    async def set_input_files(self, files, **kwargs):
        """Upload local file(s) to a mobile Chrome file input via Appium push_file."""
        paths: list[str]
        if isinstance(files, (list, tuple)):
            paths = [str(p) for p in files]
        else:
            paths = [str(files)]
        local = Path(paths[0])
        if not local.is_file():
            raise FileNotFoundError(local)

        def _upload():
            d = self._page.driver
            remote = f"/data/local/tmp/{local.name}"
            data = base64.b64encode(local.read_bytes()).decode("ascii")
            # Appium push_file
            try:
                d.push_file(remote, data)
                remote_path = remote
            except Exception:
                # Some farms accept local path via send_keys without push
                remote_path = str(local.resolve())
            el = self._pick_sync()
            if not el:
                # try any file input
                inputs = d.find_elements(By.CSS_SELECTOR, "input[type=file]")
                el = inputs[0] if inputs else None
            if not el:
                raise TimeoutException("file input not found")
            el.send_keys(remote_path)

        await _run(_upload)

    async def wait_for(self, state: str = "visible", timeout: float = 10000):
        end = time.time() + timeout / 1000.0
        while time.time() < end:
            if state in ("visible", "attached"):
                if await self.is_visible():
                    return self
            elif state == "hidden":
                if not await self.is_visible():
                    return self
            await asyncio.sleep(0.15)
        raise TimeoutException(f"wait_for({state}) timeout: {self._value}")

    def locator(self, sel: str) -> "AppiumLocator":
        # Nested: scope under first match via CSS descendant (best effort)
        parent_css = self._css or self._value
        child = _css_from_playwright(sel)
        combined = f"{parent_css} {child}".strip()
        return AppiumLocator(self._page, css=combined, by=By.CSS_SELECTOR, value=combined)

    async def evaluate(self, expression: str, arg: Any = None):
        def _ev():
            el = self._pick_sync()
            if not el:
                return None
            # Playwright-style element evaluate often is "(el) => ..."
            expr = expression.strip()
            if expr.startswith("el =>") or expr.startswith("(el)"):
                return self._page.driver.execute_script(
                    f"return ({expression})(arguments[0]);", el
                )
            return self._page.driver.execute_script(
                f"return ({expression})(arguments[0]);", el
            )

        return await _run(_ev)


class _FrameProxy:
    """Minimal frame stand-in so `page.frames` loops don't crash."""

    def __init__(self, page: "AppiumPage", is_main: bool = True):
        self._page = page
        self._is_main = is_main

    @property
    def url(self) -> str:
        return self._page.url if self._is_main else ""

    def locator(self, sel: str) -> AppiumLocator:
        return self._page.locator(sel)

    def get_by_role(self, role: str, **kwargs) -> AppiumLocator:
        return self._page.get_by_role(role, **kwargs)

    def get_by_label(self, text, **kwargs) -> AppiumLocator:
        return self._page.get_by_label(text, **kwargs)


class AppiumPage:
    def __init__(self, driver: WebDriver, context: "AppiumContext"):
        self.driver = driver
        self._context = context
        self._closed = False
        self._listeners: dict[str, list] = {}
        self.main_frame = _FrameProxy(self, True)
        self._default_timeout = 15000
        self._default_nav_timeout = 40000

    def set_default_timeout(self, timeout: float) -> None:
        self._default_timeout = float(timeout)

    def set_default_navigation_timeout(self, timeout: float) -> None:
        self._default_nav_timeout = float(timeout)

    @property
    def url(self) -> str:
        try:
            return self.driver.current_url or ""
        except Exception:
            return ""

    @property
    def frames(self) -> list:
        # Full iframe walk is expensive/fragile on farms; expose main only.
        return [self.main_frame]

    def is_closed(self) -> bool:
        return self._closed

    def on(self, event: str, handler):
        self._listeners.setdefault(event, []).append(handler)

    def locator(self, sel: str) -> AppiumLocator:
        css = _css_from_playwright(sel)
        # Playwright text= / role= not handled here
        if sel.strip().startswith("text="):
            text = sel.split("=", 1)[1].strip("'\"")
            xp = f"//*[contains(normalize-space(.), {_xpath_literal(text)})]"
            return AppiumLocator(self, xpath=xp, by=By.XPATH, value=xp)
        return AppiumLocator(self, css=css, by=By.CSS_SELECTOR, value=css)

    def get_by_role(self, role: str, name=None, **kwargs) -> AppiumLocator:
        role = (role or "").lower()
        tag_map = {
            "button": "button",
            "link": "a",
            "textbox": "input",
            "checkbox": "input[@type='checkbox']",
            "radio": "input[@type='radio']",
            "option": "option",
            "heading": "h1|h2|h3|h4|h5|h6",
            "combobox": "select",
        }
        tag = tag_map.get(role, "*")
        if name is None:
            if "|" in tag:
                xp = f"//*[{' or '.join('self::' + t for t in tag.split('|'))}]"
            elif tag.startswith("input"):
                xp = f"//{tag}"
            else:
                xp = f"//{tag}"
            return AppiumLocator(self, xpath=xp, by=By.XPATH, value=xp)

        pat = name.pattern if isinstance(name, re.Pattern) else str(name)
        # XPath 1.0: case-sensitive contains; good enough for apply buttons
        if "|" in tag:
            parts = []
            for t in tag.split("|"):
                parts.append(
                    f"(self::{t} and contains(translate(normalize-space(.),"
                    f"'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),"
                    f"{_xpath_literal(pat.lower())}))"
                )
            xp = f"//*[{' or '.join(parts)}]"
        else:
            xp = (
                f"//{tag}[contains(translate(normalize-space(.),"
                f"'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),"
                f"{_xpath_literal(pat.lower())})]"
            )
        return AppiumLocator(self, xpath=xp, by=By.XPATH, value=xp)

    def get_by_label(self, text, **kwargs) -> AppiumLocator:
        pat = text.pattern if isinstance(text, re.Pattern) else str(text)
        lit = _xpath_literal(pat.lower() if not isinstance(text, re.Pattern) else pat[:40].lower())
        # label text → control; also aria-label / placeholder
        xp = (
            f"//input[contains(translate(@aria-label,"
            f"'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),{lit})]|"
            f"//textarea[contains(translate(@aria-label,"
            f"'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),{lit})]|"
            f"//input[contains(translate(@placeholder,"
            f"'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),{lit})]|"
            f"//textarea[contains(translate(@placeholder,"
            f"'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),{lit})]|"
            f"//label[contains(translate(normalize-space(.),"
            f"'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),{lit})]"
            f"/following::input[1]|"
            f"//label[contains(translate(normalize-space(.),"
            f"'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),{lit})]"
            f"/following::textarea[1]"
        )
        return AppiumLocator(self, xpath=xp, by=By.XPATH, value=xp)

    def get_by_text(self, text, **kwargs) -> AppiumLocator:
        pat = text.pattern if isinstance(text, re.Pattern) else str(text)
        lit = _xpath_literal(pat if not isinstance(text, re.Pattern) else pat[:60])
        xp = f"//*[contains(normalize-space(.), {lit})]"
        return AppiumLocator(self, xpath=xp, by=By.XPATH, value=xp)

    def get_by_placeholder(self, text, **kwargs) -> AppiumLocator:
        pat = text.pattern if isinstance(text, re.Pattern) else str(text)
        lit = _xpath_literal(pat.lower())
        xp = (
            f"//*[@placeholder and contains(translate(@placeholder,"
            f"'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),{lit})]"
        )
        return AppiumLocator(self, xpath=xp, by=By.XPATH, value=xp)

    async def goto(
        self,
        url: str,
        wait_until: str = "domcontentloaded",
        timeout: float = 60000,
        **kwargs,
    ):
        def _go():
            self.driver.set_page_load_timeout(max(5, int(timeout / 1000)))
            self.driver.get(url)

        await _run(_go)
        if wait_until:
            await self.wait_for_load_state(wait_until, timeout=timeout)

    async def wait_for_timeout(self, ms: float):
        await asyncio.sleep(max(0, ms) / 1000.0)

    async def wait_for_load_state(self, state: str = "load", timeout: float = 30000):
        # Appium has no full load-state API; brief settle is enough for forms.
        await asyncio.sleep(0.4 if state != "networkidle" else 1.0)

    async def title(self) -> str:
        return await _run(lambda: self.driver.title or "")

    async def content(self) -> str:
        return await _run(lambda: self.driver.page_source or "")

    async def inner_text(self, selector: str = "body", timeout: float = 5000) -> str:
        loc = self.locator(selector)
        try:
            return await loc.inner_text(timeout=timeout)
        except Exception:
            return await _run(
                lambda: self.driver.execute_script(
                    "return document.body ? document.body.innerText : '';"
                )
                or ""
            )

    async def evaluate(self, expression: str, arg: Any = None):
        def _ev():
            expr = (expression or "").strip()
            # Common complete_apply: window.scrollBy(0, 400)
            if expr.startswith("window.") or expr.startswith("document."):
                return self.driver.execute_script(f"return ({expr});" if not expr.endswith(";") else expr)
            if "=>" in expr or expr.startswith("function") or expr.startswith("("):
                if arg is not None:
                    return self.driver.execute_script(
                        f"return ({expression})(arguments[0]);", arg
                    )
                return self.driver.execute_script(f"return ({expression})();")
            return self.driver.execute_script(f"return {expression}")

        return await _run(_ev)

    async def eval_on_selector_all(self, selector: str, expression: str):
        css = _css_from_playwright(selector)

        def _ev():
            return self.driver.execute_script(
                """
                const sel = arguments[0];
                const els = Array.from(document.querySelectorAll(sel));
                const fn = new Function('elements', 'return (' + arguments[1] + ')(elements)');
                try { return fn(els); } catch (e) {
                  // Playwright style: (els) => els.map(...)
                  try {
                    return eval('(' + arguments[1] + ')')(els);
                  } catch (e2) { return []; }
                }
                """,
                css,
                expression,
            )

        try:
            return await _run(_ev)
        except Exception:
            return []

    async def screenshot(self, path: str | None = None, **kwargs) -> bytes:
        def _shot():
            raw = self.driver.get_screenshot_as_png()
            if path:
                Path(path).write_bytes(raw)
            return raw

        return await _run(_shot)

    async def close(self):
        self._closed = True
        # Session quit is owned by context; do not quit driver per page.

    async def bring_to_front(self):
        return None

    async def reload(self, **kwargs):
        await _run(self.driver.refresh)

    async def go_back(self, **kwargs):
        await _run(self.driver.back)

    async def keyboard_press(self, key: str):
        # Best-effort active element
        def _k():
            el = self.driver.switch_to.active_element
            mapping = {"Enter": Keys.ENTER, "Tab": Keys.TAB, "Escape": Keys.ESCAPE}
            el.send_keys(mapping.get(key, key))

        await _run(_k)


class _ExpectPage:
    def __init__(self, ctx: "AppiumContext", timeout: float):
        self._ctx = ctx
        self._timeout = timeout
        self._page = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def __await__(self):
        async def _wait():
            # Mobile Chrome rarely opens real new "pages"; return same page.
            await asyncio.sleep(0.5)
            return self._ctx.pages[0] if self._ctx.pages else None

        return _wait().__await__()


class AppiumContext:
    def __init__(self, driver: WebDriver):
        self.driver = driver
        self._page = AppiumPage(driver, self)
        self.pages: list[AppiumPage] = [self._page]
        self._closed = False
        self._handlers: dict[str, list] = {}

    def on(self, event: str, handler):
        self._handlers.setdefault(event, []).append(handler)

    def expect_page(self, timeout: float = 10000):
        return _ExpectPage(self, timeout)

    async def new_page(self) -> AppiumPage:
        # Same mobile browser tab — open about:blank then navigate
        p = self._page
        try:
            await p.goto("about:blank", timeout=15000)
        except Exception:
            pass
        return p

    async def close(self):
        if self._closed:
            return
        self._closed = True
        self._page._closed = True

        def _quit():
            try:
                self.driver.quit()
            except Exception:
                pass

        await _run(_quit)


class AppiumBrowser:
    """Stand-in for Playwright Browser (connect_over_cdp return value)."""

    def __init__(self, driver: WebDriver, context: AppiumContext):
        self.driver = driver
        self.contexts = [context]

    async def close(self):
        if self.contexts:
            await self.contexts[0].close()


def _xpath_literal(s: str) -> str:
    s = s or ""
    if "'" not in s:
        return f"'{s}'"
    if '"' not in s:
        return f'"{s}"'
    parts = s.split("'")
    return "concat(" + ", \"'\", ".join(f"'{p}'" for p in parts) + ")"


def create_appium_session(hub_url: str, capabilities: dict) -> tuple[AppiumBrowser, AppiumContext, AppiumPage]:
    """Synchronous Appium session start → browser, context, page."""
    from appium import webdriver as appium_webdriver
    from appium.options.common import AppiumOptions

    options = AppiumOptions()
    options.load_capabilities(capabilities)
    driver = appium_webdriver.Remote(command_executor=hub_url, options=options)
    try:
        driver.set_page_load_timeout(60)
        driver.implicitly_wait(0)
    except Exception:
        pass
    ctx = AppiumContext(driver)
    browser = AppiumBrowser(driver, ctx)
    return browser, ctx, ctx.pages[0]
