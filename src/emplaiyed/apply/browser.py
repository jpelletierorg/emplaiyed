"""Playwright browser wrapper for apply runs.

Provides a thin async context manager around a Playwright browser session
with cookie persistence, screenshot capture, and page lifecycle management.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import AsyncIterator

from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)


class BrowserSession:
    """Wraps a Playwright browser context with persistence and evidence capture."""

    def __init__(
        self,
        page,  # playwright.async_api.Page
        context,  # playwright.async_api.BrowserContext
        artifact_dir: Path,
    ):
        self._page = page
        self._context = context
        self._artifact_dir = artifact_dir
        self._screenshot_count = 0

    @property
    def page(self):
        return self._page

    @property
    def url(self) -> str:
        return self._page.url

    async def goto(self, url: str, *, wait_until: str = "domcontentloaded") -> None:
        await self._page.goto(url, wait_until=wait_until)

    async def screenshot(self, name: str | None = None) -> Path:
        """Take a screenshot and save it to the artifact directory."""
        self._screenshot_count += 1
        filename = name or f"step_{self._screenshot_count:03d}.png"
        path = self._artifact_dir / filename
        await self._page.screenshot(path=str(path), full_page=True)
        logger.debug("Screenshot saved: %s", path)
        return path

    async def save_html(self, name: str = "page.html") -> Path:
        """Save the current page HTML to the artifact directory."""
        path = self._artifact_dir / name
        content = await self._page.content()
        path.write_text(content, encoding="utf-8")
        return path

    async def click(self, selector: str, **kwargs) -> None:
        await self._page.click(selector, **kwargs)

    async def fill(self, selector: str, value: str) -> None:
        await self._page.fill(selector, value)

    async def upload_file(self, selector: str, path: str | Path) -> None:
        await self._page.set_input_files(selector, str(path))

    async def wait_for_selector(self, selector: str, **kwargs):
        return await self._page.wait_for_selector(selector, **kwargs)

    async def query_selector(self, selector: str):
        return await self._page.query_selector(selector)

    async def query_selector_all(self, selector: str):
        return await self._page.query_selector_all(selector)

    async def inner_text(self, selector: str) -> str:
        return await self._page.inner_text(selector)

    async def evaluate(self, expression: str, *args):
        return await self._page.evaluate(expression, *args)

    async def wait_for_navigation(self, **kwargs):
        return await self._page.wait_for_url(
            kwargs.get("url", "**"), timeout=kwargs.get("timeout", 30000)
        )

    async def content(self) -> str:
        return await self._page.content()


@asynccontextmanager
async def open_browser(
    artifact_dir: Path,
    *,
    headless: bool = False,
    storage_dir: Path | None = None,
) -> AsyncIterator[BrowserSession]:
    """Open a Playwright browser session.

    Args:
        artifact_dir: Directory to save screenshots and HTML snapshots.
        headless: Run browser in headless mode. Default is visible (headed).
        storage_dir: Directory for persistent cookie/session storage.
            If provided, cookies are saved/restored across runs.
    """
    from playwright.async_api import async_playwright

    artifact_dir.mkdir(parents=True, exist_ok=True)

    storage_path = (storage_dir / "storage_state.json") if storage_dir else None

    pw = await async_playwright().start()
    try:
        browser = await pw.chromium.launch(headless=headless)
        context_kwargs: dict = {}
        if storage_path and storage_path.exists():
            context_kwargs["storage_state"] = str(storage_path)

        context = await browser.new_context(**context_kwargs)
        page = await context.new_page()

        session = BrowserSession(page, context, artifact_dir)
        try:
            yield session
        finally:
            # Persist storage state if configured
            if storage_path:
                storage_path.parent.mkdir(parents=True, exist_ok=True)
                await context.storage_state(path=str(storage_path))
            await context.close()
            await browser.close()
    finally:
        await pw.stop()
