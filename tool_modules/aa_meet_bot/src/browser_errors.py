"""Exception groups for Playwright-driven Google Meet automation.

Page lookups, clicks and waits raise Playwright errors (including its
TimeoutError), asyncio timeouts or OS-level errors. Catching this tuple instead
of bare ``Exception`` keeps genuine programming errors visible.
"""

import asyncio

try:
    from playwright.async_api import Error as PlaywrightError
except ImportError:  # pragma: no cover - playwright is optional at import time

    class PlaywrightError(Exception):  # type: ignore[no-redef]
        """Stand-in used when playwright is not installed."""


BROWSER_ERRORS: tuple[type[BaseException], ...] = (PlaywrightError, asyncio.TimeoutError, OSError)
