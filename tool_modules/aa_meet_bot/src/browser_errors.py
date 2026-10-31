"""Exception groups for Playwright-driven Google Meet automation.

Page lookups, clicks and waits raise Playwright errors (including its
TimeoutError), asyncio timeouts or OS-level errors. Catching this tuple instead
of bare ``Exception`` keeps genuine programming errors visible.
"""

import asyncio

from playwright.async_api import Error as PlaywrightError

BROWSER_ERRORS: tuple[type[BaseException], ...] = (PlaywrightError, asyncio.TimeoutError, OSError)
