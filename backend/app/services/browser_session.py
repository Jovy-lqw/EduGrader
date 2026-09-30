from __future__ import annotations

import asyncio
import json
from typing import Any, Optional
from urllib.parse import unquote

from playwright.async_api import (
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)

from ..config import settings
from ..file_utils import set_file_mode


TEACHER_HOME_URL = (
    "https://onlineweb.zhihuishu.com/onlineMuster/teacherIndex"
)
SESSION_STATE_PATH = settings.data_dir / "browser-session.json"


class BrowserSessionError(RuntimeError):
    pass


class BrowserSession:
    def __init__(self) -> None:
        self._playwright: Optional[Playwright] = None
        self._context: Optional[BrowserContext] = None
        self._lock = asyncio.Lock()

    @property
    def started(self) -> bool:
        return self._context is not None

    async def start(self) -> BrowserContext:
        async with self._lock:
            if self._context:
                return self._context
            settings.ensure_directories()
            self._playwright = await async_playwright().start()
            try:
                self._context = await self._playwright.chromium.launch_persistent_context(
                    user_data_dir=str(settings.browser_profile_dir),
                    headless=False,
                    accept_downloads=True,
                    viewport={"width": 1440, "height": 960},
                    locale="zh-CN",
                )
                await self._restore_state(self._context)
            except Exception as exc:
                await self._playwright.stop()
                self._playwright = None
                raise BrowserSessionError(
                    "无法启动 Chromium。请先执行 "
                    "`python -m playwright install chromium`。"
                ) from exc
            return self._context

    async def open_login(self) -> None:
        context = await self.start()
        page = await self._preferred_page(context)
        await page.goto(TEACHER_HOME_URL, wait_until="domcontentloaded")
        await page.bring_to_front()

    async def page(self) -> Page:
        return await self._preferred_page(await self.start())

    async def persist_state(self) -> None:
        context = self._context or await self.start()
        state = await context.storage_state()
        temporary_path = SESSION_STATE_PATH.with_suffix(".tmp")
        temporary_path.write_text(
            json.dumps(state, ensure_ascii=False),
            encoding="utf-8",
        )
        set_file_mode(temporary_path, 0o600)
        temporary_path.replace(SESSION_STATE_PATH)

    async def request(
        self,
        method: str,
        url: str,
        *,
        params: Optional[dict[str, Any]] = None,
        form: Optional[dict[str, Any]] = None,
        timeout_ms: int = 30_000,
    ) -> tuple[int, dict[str, str], bytes]:
        context = await self.start()
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://onlineweb.zhihuishu.com/",
        }
        authorization = await self._authorization_value(context)
        if authorization:
            headers["Authorization"] = authorization
        response = await context.request.fetch(
            url,
            method=method,
            params=params,
            form=form,
            headers=headers,
            timeout=timeout_ms,
            fail_on_status_code=False,
        )
        return response.status, response.headers, await response.body()

    async def close(self) -> None:
        async with self._lock:
            if self._context:
                await self.persist_state()
                await self._context.close()
                self._context = None
            if self._playwright:
                await self._playwright.stop()
                self._playwright = None

    @staticmethod
    async def _restore_state(context: BrowserContext) -> None:
        if not SESSION_STATE_PATH.exists():
            return
        try:
            state = json.loads(SESSION_STATE_PATH.read_text(encoding="utf-8"))
            cookies = state.get("cookies") or []
            if cookies:
                await context.add_cookies(cookies)
            local_storage = {
                origin["origin"]: origin.get("localStorage") or []
                for origin in state.get("origins") or []
                if origin.get("origin")
            }
            if local_storage:
                await context.add_init_script(
                    f"""(() => {{
                        const storage = {json.dumps(local_storage)};
                        for (const item of storage[location.origin] || []) {{
                            localStorage.setItem(item.name, item.value);
                        }}
                    }})()"""
                )
        except (OSError, ValueError, TypeError):
            SESSION_STATE_PATH.unlink(missing_ok=True)

    @staticmethod
    async def _preferred_page(context: BrowserContext) -> Page:
        for page in context.pages:
            if "zhihuishu.com" in page.url:
                return page
        return context.pages[0] if context.pages else await context.new_page()

    @classmethod
    async def _authorization_value(
        cls, context: BrowserContext
    ) -> Optional[str]:
        cookies = await context.cookies()
        by_name = {cookie["name"]: cookie["value"] for cookie in cookies}
        direct = by_name.get("jt-cas")
        if direct:
            return unquote(direct)
        caslogc = by_name.get("CASLOGC")
        if not caslogc:
            return None
        value = caslogc
        for _ in range(3):
            decoded = unquote(value)
            if decoded == value:
                break
            value = decoded
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return value if len(value) > 20 else None
        return cls._find_token(parsed)

    @classmethod
    def _find_token(cls, value: Any) -> Optional[str]:
        if isinstance(value, dict):
            preferred = (
                "authorization",
                "accessToken",
                "access_token",
                "token",
                "jwt",
            )
            for key in preferred:
                token = value.get(key)
                if isinstance(token, str) and token:
                    return token
            for nested in value.values():
                token = cls._find_token(nested)
                if token:
                    return token
        elif isinstance(value, list):
            for nested in value:
                token = cls._find_token(nested)
                if token:
                    return token
        return None

browser_session = BrowserSession()
