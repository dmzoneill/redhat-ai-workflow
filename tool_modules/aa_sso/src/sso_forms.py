"""Red Hat SSO credentials and login-form helpers for existing Playwright pages."""

import asyncio
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from playwright.async_api import Page

from tool_modules.aa_sso.src.sso_models import _AUTOMATION_ERRORS, SSOSelectors

logger = logging.getLogger(__name__)


def get_sso_credentials(headless: bool = True) -> tuple[str, str]:
    """Get SSO credentials from redhatter service.

    Args:
        headless: Whether browser will run headless (affects OTP generation)

    Returns:
        Tuple of (username, password)

    Raises:
        RuntimeError: If credentials cannot be retrieved
    """
    # Read auth token
    token_path = Path.home() / ".cache" / "redhatter" / "auth_token"
    if not token_path.exists():
        raise RuntimeError(f"Auth token not found at {token_path}. Ensure redhatter service is running.")

    token = token_path.read_text(encoding="utf-8").strip()
    if not token:
        raise RuntimeError("Auth token is empty")

    # Fetch credentials
    params = urllib.parse.urlencode(
        {
            "context": "associate",
            "headless": str(headless).lower(),
        }
    )
    url = f"http://localhost:8009/get_creds?{params}"

    request = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}"},
    )

    # Local redhatter service over plain HTTP only: no file:, ftp: or data: handlers.
    opener = urllib.request.OpenerDirector()
    for handler in (
        urllib.request.HTTPHandler(),
        urllib.request.HTTPDefaultErrorHandler(),
        urllib.request.HTTPErrorProcessor(),
    ):
        opener.add_handler(handler)
    try:
        with opener.open(request, timeout=15) as response:
            payload = response.read().decode("utf-8")
    except urllib.error.URLError as e:
        raise RuntimeError(f"Failed to get credentials: {e}") from e

    # Parse response: "username,password"
    sanitized = payload.replace('"', "").replace("\n", "").strip()
    parts = sanitized.split(",")

    if len(parts) < 2:
        raise RuntimeError(f"Invalid credential response: {sanitized!r}")

    username, password = parts[0].strip(), parts[1].strip()
    if not username or not password:
        raise RuntimeError("Credentials missing username or password")

    logger.info("Fetched login details from redhatter")
    return username, password


# ==================== Standalone Helper Functions ====================


async def fill_sso_form(
    page: Page,
    username: str,
    password: str,
    selectors: SSOSelectors | None = None,
) -> None:
    """Fill Red Hat SSO login form on an existing Playwright page.

    This is a standalone helper for code that already has a Playwright page
    and just needs to fill the SSO form (e.g., meet_bot, gomo_to_concur).

    Uses Playwright's fill() which properly triggers JavaScript events.

    Args:
        page: Playwright Page object on SSO login page
        username: Kerberos ID
        password: PIN and token
        selectors: Optional custom selectors (defaults to standard SSO selectors)

    Example:
        from tool_modules.aa_sso.src.tools_basic import fill_sso_form, get_sso_credentials

        # In your existing Playwright code:
        username, password = get_sso_credentials()
        await fill_sso_form(page, username, password)
    """
    selectors = selectors or SSOSelectors()

    logger.info("Filling SSO form...")

    # Try primary selectors, then alternatives
    async def find_element(primary: str, alternatives: list[str]) -> str:
        try:
            await page.wait_for_selector(primary, timeout=5000)
            return primary
        # Intentional: log the failure and continue at this boundary.
        except _AUTOMATION_ERRORS as exc:
            logger.debug("Suppressed error: %s", exc)
        for alt in alternatives:
            try:
                await page.wait_for_selector(alt, timeout=2000)
                logger.info("Using an alternative login form selector")
                return alt
            # Intentional: skip this candidate when the optional step fails.
            except _AUTOMATION_ERRORS as exc:
                logger.debug("Candidate failed: %s", exc)
                continue
        return primary  # Return primary and let it fail with proper error

    username_sel = await find_element(selectors.username, selectors.username_alt)
    password_sel = await find_element(selectors.password, selectors.password_alt)
    submit_sel = await find_element(selectors.submit, selectors.submit_alt)

    # Fill username
    logger.info("Filling login form: user ID")
    await page.fill(username_sel, username)
    await asyncio.sleep(0.3)

    # Fill password
    logger.info("Filling login form: PIN + OTP")
    await page.fill(password_sel, password)
    await asyncio.sleep(0.3)

    # Click submit
    logger.info("Submitting login form")
    await page.click(submit_sel)

    logger.info("SSO form submitted")


def fill_sso_form_sync(
    page,  # playwright.sync_api.Page
    username: str,
    password: str,
    selectors: SSOSelectors | None = None,
) -> None:
    """Fill Red Hat SSO login form on an existing Playwright page (synchronous version).

    This is a standalone helper for code that uses synchronous Playwright
    (e.g., gomo_to_concur.py).

    Uses Playwright's fill() which properly triggers JavaScript events.

    Args:
        page: Playwright sync Page object on SSO login page
        username: Kerberos ID
        password: PIN and token
        selectors: Optional custom selectors (defaults to standard SSO selectors)

    Example:
        from tool_modules.aa_sso.src.tools_basic import fill_sso_form_sync, get_sso_credentials

        # In your existing sync Playwright code:
        username, password = get_sso_credentials()
        fill_sso_form_sync(page, username, password)
    """
    selectors = selectors or SSOSelectors()

    logger.info("Filling SSO form (sync)...")

    # Try primary selectors, then alternatives
    def find_element(primary: str, alternatives: list[str]) -> str:
        try:
            page.wait_for_selector(primary, timeout=5000)
            return primary
        # Intentional: log the failure and continue at this boundary.
        except _AUTOMATION_ERRORS as exc:
            logger.debug("Suppressed error: %s", exc)
        for alt in alternatives:
            try:
                page.wait_for_selector(alt, timeout=2000)
                logger.info("Using an alternative login form selector")
                return alt
            # Intentional: skip this candidate when the optional step fails.
            except _AUTOMATION_ERRORS as exc:
                logger.debug("Candidate failed: %s", exc)
                continue
        return primary  # Return primary and let it fail with proper error

    username_sel = find_element(selectors.username, selectors.username_alt)
    password_sel = find_element(selectors.password, selectors.password_alt)
    submit_sel = find_element(selectors.submit, selectors.submit_alt)

    # Fill username
    logger.info("Filling login form: user ID")
    page.fill(username_sel, username)
    time.sleep(0.3)

    # Fill password
    logger.info("Filling login form: PIN + OTP")
    page.fill(password_sel, password)
    time.sleep(0.3)

    # Click submit
    logger.info("Submitting login form")
    page.click(submit_sel)

    logger.info("SSO form submitted")


def is_sso_page(url: str) -> bool:
    """Check if URL is a Red Hat SSO login page.

    Args:
        url: Current page URL

    Returns:
        True if URL is an SSO login page
    """
    sso_patterns = ["auth.redhat.com", "sso.redhat.com"]
    return any(pattern in url for pattern in sso_patterns)
