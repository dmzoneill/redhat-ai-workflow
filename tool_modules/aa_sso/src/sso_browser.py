"""Persistent Playwright browser session shared by the browser_* tools."""

import asyncio
import atexit
import logging
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from tool_modules.aa_sso.src.sso_models import _AUTOMATION_ERRORS

logger = logging.getLogger(__name__)

# ==================== Persistent Browser Session ====================

# Module-level browser session for browser_* tools.
# These persist across tool calls within a session, enabling multi-step
# browser automation (navigate, click, wait, screenshot).


@dataclass
class _BrowserSession:
    """The live Playwright objects behind the browser_* tools."""

    playwright: Any = None  # Playwright instance
    browser: Browser | None = None
    context: BrowserContext | None = None
    page: Page | None = None

    def clear(self) -> None:
        """Forget all browser objects."""
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None


_SESSION = _BrowserSession()

# Screenshot output directory - use tempfile.gettempdir() for portability
BROWSER_SNAPSHOT_DIR = Path(tempfile.gettempdir()) / "browser_snapshots"


async def _get_or_create_browser(headless: bool = True) -> Page:
    """Get the existing browser page or create a new browser session.

    Lazily initializes a Playwright browser instance that persists across
    tool calls. This allows multi-step browser automation workflows.

    Args:
        headless: Run browser in headless mode

    Returns:
        Active Playwright Page object

    Raises:
        RuntimeError: If Playwright is not installed or browser fails to launch
    """
    # Return existing page if browser is still connected
    if _SESSION.page is not None and _SESSION.browser is not None:
        try:
            # Verify the browser is still alive by checking the page URL
            _ = _SESSION.page.url
            return _SESSION.page
        # Intentional: log the failure and continue at this boundary.
        except _AUTOMATION_ERRORS:
            logger.warning("Browser session expired, creating new one")
            await _close_browser()

    logger.info("Launching browser (headless=%s)", headless)
    _SESSION.playwright = await async_playwright().start()
    _SESSION.browser = await _SESSION.playwright.chromium.launch(headless=headless)
    _SESSION.context = await _SESSION.browser.new_context(
        viewport={"width": 1280, "height": 720},
    )
    page = await _SESSION.context.new_page()
    _SESSION.page = page

    logger.info("Browser session created")
    return page


async def _close_browser() -> None:
    """Close the persistent browser session and clean up resources."""
    if _SESSION.browser is not None:
        try:
            await _SESSION.browser.close()
        # Intentional: log the failure and continue at this boundary.
        except _AUTOMATION_ERRORS as e:
            logger.warning("Error closing browser: %s", e)

    if _SESSION.playwright is not None:
        try:
            await _SESSION.playwright.stop()
        # Intentional: log the failure and continue at this boundary.
        except _AUTOMATION_ERRORS as e:
            logger.warning("Error stopping playwright: %s", e)

    _SESSION.clear()
    logger.info("Browser session closed")


def _cleanup_browser_sync() -> None:
    """Synchronous atexit handler to clean up browser on process exit."""
    if _SESSION.browser is not None:
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(_close_browser())
            else:
                loop.run_until_complete(_close_browser())
        # Intentional: log the failure and continue at this boundary.
        except _AUTOMATION_ERRORS as exc:
            logger.debug("Suppressed error: %s", exc)


atexit.register(_cleanup_browser_sync)


# ==================== browser_* tool implementations ====================

_WAIT_CONDITIONS = ("load", "domcontentloaded", "networkidle")
_ELEMENT_STATES = ("visible", "hidden", "attached", "detached")


def _effective_selector(selector: str, text: str) -> str:
    """Text (Playwright text selector) takes precedence over a CSS selector."""
    return f"text={text}" if text else selector


def _target_label(selector: str, text: str) -> str:
    return f"text={text!r}" if text else f"selector={selector!r}"


async def browser_navigate_impl(url: str, wait_for: str, timeout: int) -> str:
    """Navigate the persistent browser to ``url``."""
    if wait_for not in _WAIT_CONDITIONS:
        return f"Invalid wait_for value: {wait_for!r}. Must be one of: {', '.join(_WAIT_CONDITIONS)}"

    try:
        page = await _get_or_create_browser()
        await page.goto(url, wait_until=wait_for, timeout=timeout * 1000)
        title = await page.title()
        final_url = page.url

        output = "Browser navigation successful\n\n"
        output += f"**URL:** {final_url}\n"
        output += f"**Title:** {title}\n"
        output += f"**Wait condition:** {wait_for}\n"
        return output

    # Intentional: convert the failure into an error result for the caller.
    except _AUTOMATION_ERRORS as e:
        return f"Browser navigation failed\n\n**URL:** {url}\n**Error:** {e}"


async def browser_click_impl(selector: str, text: str, timeout: int) -> str:
    """Click an element by CSS selector or text."""
    if not selector and not text:
        return "At least one of 'selector' or 'text' must be provided."

    try:
        page = await _get_or_create_browser()
        effective_selector = _effective_selector(selector, text)
        await page.wait_for_selector(effective_selector, timeout=timeout * 1000, state="visible")
        await page.click(effective_selector, timeout=timeout * 1000)

        output = "Click action successful\n\n"
        if text:
            output += f"**Clicked text:** {text!r}\n"
        else:
            output += f"**Clicked selector:** {selector!r}\n"
        output += f"**Current URL:** {page.url}\n"
        return output

    # Intentional: convert the failure into an error result for the caller.
    except _AUTOMATION_ERRORS as e:
        return f"Click action failed\n\n**Target:** {_target_label(selector, text)}\n**Error:** {e}"


async def browser_fill_impl(selector: str, value: str, timeout: int) -> str:
    """Fill an input element."""
    if not selector:
        return "The 'selector' parameter is required."

    try:
        page = await _get_or_create_browser()
        await page.wait_for_selector(selector, timeout=timeout * 1000, state="visible")
        await page.fill(selector, value, timeout=timeout * 1000)

        # Truncate displayed value for security (passwords, etc.)
        display_value = value[:30] + "..." if len(value) > 30 else value
        output = "Fill action successful\n\n"
        output += f"**Selector:** {selector!r}\n"
        output += f"**Value:** {display_value!r}\n"
        output += f"**Current URL:** {page.url}\n"
        return output

    # Intentional: convert the failure into an error result for the caller.
    except _AUTOMATION_ERRORS as e:
        return f"Fill action failed\n\n**Selector:** {selector!r}\n**Error:** {e}"


def _snapshot_path(name: str) -> Path:
    """Filesystem-safe, timestamped screenshot path under BROWSER_SNAPSHOT_DIR."""
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
    return BROWSER_SNAPSHOT_DIR / f"{safe_name}_{timestamp}.png"


async def browser_snapshot_impl(name: str, full_page: bool) -> str:
    """Screenshot the current page."""
    try:
        page = await _get_or_create_browser()
        BROWSER_SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        filepath = _snapshot_path(name)
        await page.screenshot(path=str(filepath), full_page=full_page)
        title = await page.title()

        output = "Screenshot captured\n\n"
        output += f"**Path:** {filepath}\n"
        output += f"**Page:** {title}\n"
        output += f"**URL:** {page.url}\n"
        output += f"**Full page:** {full_page}\n"
        return output

    # Intentional: convert the failure into an error result for the caller.
    except _AUTOMATION_ERRORS as e:
        return f"Screenshot failed\n\n**Name:** {name}\n**Error:** {e}"


async def browser_wait_for_impl(selector: str, text: str, timeout: int, state: str) -> str:
    """Wait for an element to reach ``state``."""
    if not selector and not text:
        return "At least one of 'selector' or 'text' must be provided."
    if state not in _ELEMENT_STATES:
        return f"Invalid state value: {state!r}. Must be one of: {', '.join(_ELEMENT_STATES)}"

    try:
        page = await _get_or_create_browser()
        await page.wait_for_selector(_effective_selector(selector, text), timeout=timeout * 1000, state=state)

        output = "Wait condition met\n\n"
        if text:
            output += f"**Waited for text:** {text!r}\n"
        else:
            output += f"**Waited for selector:** {selector!r}\n"
        output += f"**State:** {state}\n"
        output += f"**Current URL:** {page.url}\n"
        return output

    # Intentional: convert the failure into an error result for the caller.
    except _AUTOMATION_ERRORS as e:
        return (
            f"Wait condition not met (timeout after {timeout}s)\n\n"
            f"**Target:** {_target_label(selector, text)}\n"
            f"**State:** {state}\n"
            f"**Error:** {e}"
        )
