"""Red Hat SSO Authentication Tools.

Provides reusable SSO authentication for Red Hat internal sites.

Supported Authentication Flows:
- INLINE_REDIRECT: Page redirects to SSO, then back to target
- POPUP: SSO opens in popup window, closes on success
- OAUTH_CHAIN: Multi-step OAuth flow (e.g., Google -> Red Hat SSO -> Google)
- ALREADY_AUTHENTICATED: Session exists, skip login

Supported Outcome Types:
- JWT_TOKEN: Extract JWT from browser storage/network
- SESSION_COOKIE: Extract specific cookies
- REDIRECT_ONLY: Just verify redirect to target URL

Usage:
    from tool_modules.aa_sso.src.tools_basic import SSOAuthenticator, SSOStrategy

    # Define strategy for your target site
    strategy = SSOStrategy(
        name="reward_zone",
        target_url="https://rewardzone.redhat.com/dash/0",
        flow_type="INLINE_REDIRECT",
        success_url_pattern="rewardzone.redhat.com",
        outcome_type="REDIRECT_ONLY",
    )

    # Authenticate
    auth = SSOAuthenticator()
    result = await auth.authenticate(strategy)
"""

import asyncio
import atexit
import json
import logging
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from enum import Enum
from html.parser import HTMLParser
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

import httpx

if TYPE_CHECKING:
    from fastmcp import FastMCP

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

logger = logging.getLogger(__name__)


# ==================== Enums ====================


class FlowType(str, Enum):
    """SSO authentication flow types."""

    INLINE_REDIRECT = "INLINE_REDIRECT"  # Page redirects to SSO then back
    POPUP = "POPUP"  # SSO opens in popup window
    OAUTH_CHAIN = "OAUTH_CHAIN"  # Multi-step OAuth (Google -> RH SSO -> Google)
    ALREADY_AUTHENTICATED = "ALREADY_AUTHENTICATED"  # Session exists


class OutcomeType(str, Enum):
    """What to extract after successful authentication."""

    JWT_TOKEN = "JWT_TOKEN"  # Extract JWT from storage/network
    SESSION_COOKIE = "SESSION_COOKIE"  # Extract specific cookies
    REDIRECT_ONLY = "REDIRECT_ONLY"  # Just verify redirect succeeded


# ==================== Data Classes ====================


@dataclass
class SSOSelectors:
    """CSS selectors for SSO form elements.

    Default selectors work for standard Red Hat SSO forms.
    Override for sites with different form structures.
    """

    # Standard Red Hat SSO selectors
    username: str = "#username"
    password: str = "#password"
    submit: str = "#submit"

    # Alternative selectors (tried if primary fails)
    username_alt: list[str] = field(
        default_factory=lambda: [
            "input[name='username']",
            "form#login-form input#username",
        ]
    )
    password_alt: list[str] = field(
        default_factory=lambda: [
            "input[name='password']",
            "form#login-form input#password",
        ]
    )
    submit_alt: list[str] = field(
        default_factory=lambda: [
            "input[name='submit']",
            "input[type='submit']",
            "form#login-form input#submit",
        ]
    )


@dataclass
class SSOStrategy:
    """Configuration for authenticating to a specific site."""

    # Required
    name: str  # Identifier for this strategy (e.g., "reward_zone", "inscope")
    target_url: str  # URL to navigate to (may redirect to SSO)

    # Flow configuration
    flow_type: FlowType = FlowType.INLINE_REDIRECT

    # Success detection
    success_url_pattern: str = ""  # URL must contain this after auth
    success_element: str = ""  # Element that indicates success (CSS selector)
    sso_url_patterns: list[str] = field(
        default_factory=lambda: [
            "auth.redhat.com",
            "sso.redhat.com",
        ]
    )

    # Outcome configuration
    outcome_type: OutcomeType = OutcomeType.REDIRECT_ONLY

    # For JWT_TOKEN outcome
    jwt_storage_keys: list[str] = field(
        default_factory=lambda: [
            "token",
            "access_token",
            "backstage-auth",
        ]
    )
    jwt_cache_path: str = ""  # Where to save JWT (e.g., ~/.cache/inscope/token)

    # For SESSION_COOKIE outcome
    cookie_names: list[str] = field(default_factory=list)  # e.g., ["connect.sid"]
    cookie_cache_path: str = ""  # Where to save cookies

    # Custom selectors (optional)
    selectors: SSOSelectors = field(default_factory=SSOSelectors)

    # Timeouts (milliseconds)
    navigation_timeout: int = 60000
    element_timeout: int = 15000
    redirect_timeout: int = 60000

    # Popup-specific (for POPUP flow)
    popup_trigger_selector: str = ""  # Button that opens popup
    popup_close_timeout: int = 30000  # Max wait for popup to close

    # Callback URL handling (for sites with intermediate redirects)
    callback_url_patterns: list[str] = field(
        default_factory=list
    )  # e.g., ["setsession", "signin"]
    final_redirect_url: str = ""  # Force navigate here if callback doesn't redirect


@dataclass
class SSOResult:
    """Result of SSO authentication attempt."""

    success: bool
    strategy_name: str
    flow_type: FlowType
    outcome_type: OutcomeType

    # Outcome data
    jwt_token: Optional[str] = None
    jwt_expires_at: Optional[int] = None
    cookies: dict[str, str] = field(default_factory=dict)
    final_url: str = ""

    # Error info
    error: Optional[str] = None
    screenshot_path: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "success": self.success,
            "strategy_name": self.strategy_name,
            "flow_type": self.flow_type.value,
            "outcome_type": self.outcome_type.value,
            "jwt_token": self.jwt_token[:50] + "..." if self.jwt_token else None,
            "jwt_expires_at": self.jwt_expires_at,
            "cookies": list(self.cookies.keys()),
            "final_url": self.final_url,
            "error": self.error,
            "screenshot_path": self.screenshot_path,
        }


# ==================== Pre-defined Strategies ====================


# Strategy definitions for known sites
KNOWN_STRATEGIES: dict[str, SSOStrategy] = {
    "reward_zone": SSOStrategy(
        name="reward_zone",
        target_url="https://rewardzone.redhat.com/dash/0",
        flow_type=FlowType.INLINE_REDIRECT,
        success_url_pattern="rewardzone.redhat.com/dash",
        outcome_type=OutcomeType.REDIRECT_ONLY,
    ),
    "inscope": SSOStrategy(
        name="inscope",
        target_url="https://inscope.corp.redhat.com/convo",
        flow_type=FlowType.POPUP,
        success_url_pattern="inscope.corp.redhat.com",
        outcome_type=OutcomeType.JWT_TOKEN,
        jwt_storage_keys=["token", "access_token", "backstage-auth"],
        jwt_cache_path="~/.cache/inscope/token",
        cookie_names=["connect.sid"],
        cookie_cache_path="~/.cache/inscope/cookies",
        popup_trigger_selector="button:has-text('Sign In')",
    ),
    "concur": SSOStrategy(
        name="concur",
        target_url="https://auth.redhat.com/auth/realms/EmployeeIDP/protocol/saml/clients/concursolutions",
        flow_type=FlowType.INLINE_REDIRECT,
        success_url_pattern="concursolutions.com",
        outcome_type=OutcomeType.REDIRECT_ONLY,
        callback_url_patterns=["setsession", "signin"],
        final_redirect_url="https://us2.concursolutions.com/home",
        selectors=SSOSelectors(
            username="form#login-form input#username",
            password="form#login-form input#password",
            submit="form#login-form input#submit",
        ),
    ),
}


# ==================== HTTP SAML Configuration ====================


@dataclass
class HTTPSAMLConfig:
    """Configuration for HTTP-based SAML authentication flows.

    Defines the URL paths used during the SAML redirect auth flow
    for sites that can be authenticated via pure HTTP (no browser).
    """

    init_url: str  # e.g., "/api/v1/Subprograms/init?subprogramId=102"
    saml_login_path: str  # e.g., "/saml/login"
    saml_acs_path: str  # e.g., "/saml/acs"
    sso_login_path: str  # e.g., "/api/v1/Sso/login"
    csrf_field: str = "_csrf"  # field name in JSON body


HTTP_SAML_CONFIGS: dict[str, HTTPSAMLConfig] = {
    "reward_zone": HTTPSAMLConfig(
        init_url="/api/v1/Subprograms/init?subprogramId=102",
        saml_login_path="/saml/login",
        saml_acs_path="/saml/acs",
        sso_login_path="/api/v1/Sso/login",
    ),
    # concur can be added later with its own config
}


# ==================== Credential Helper ====================


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
        raise RuntimeError(
            f"Auth token not found at {token_path}. "
            "Ensure redhatter service is running."
        )

    token = token_path.read_text().strip()
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

    try:
        with urllib.request.urlopen(request, timeout=15) as response:
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

    logger.info(f"Retrieved credentials for user: {username}")
    return username, password


# ==================== Standalone Helper Functions ====================


async def fill_sso_form(
    page: Page,
    username: str,
    password: str,
    selectors: Optional[SSOSelectors] = None,
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
        except Exception as exc:
            logger.debug("Suppressed error: %s", exc)
        for alt in alternatives:
            try:
                await page.wait_for_selector(alt, timeout=2000)
                logger.info(f"Using alternative selector: {alt}")
                return alt
            except Exception:
                continue
        return primary  # Return primary and let it fail with proper error

    username_sel = await find_element(selectors.username, selectors.username_alt)
    password_sel = await find_element(selectors.password, selectors.password_alt)
    submit_sel = await find_element(selectors.submit, selectors.submit_alt)

    # Fill username
    logger.info(f"Filling username with selector: {username_sel}")
    await page.fill(username_sel, username)
    await asyncio.sleep(0.3)

    # Fill password
    logger.info(f"Filling password with selector: {password_sel}")
    await page.fill(password_sel, password)
    await asyncio.sleep(0.3)

    # Click submit
    logger.info(f"Clicking submit with selector: {submit_sel}")
    await page.click(submit_sel)

    logger.info("SSO form submitted")


def fill_sso_form_sync(
    page,  # playwright.sync_api.Page
    username: str,
    password: str,
    selectors: Optional[SSOSelectors] = None,
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
    import time

    selectors = selectors or SSOSelectors()

    logger.info("Filling SSO form (sync)...")

    # Try primary selectors, then alternatives
    def find_element(primary: str, alternatives: list[str]) -> str:
        try:
            page.wait_for_selector(primary, timeout=5000)
            return primary
        except Exception as exc:
            logger.debug("Suppressed error: %s", exc)
        for alt in alternatives:
            try:
                page.wait_for_selector(alt, timeout=2000)
                logger.info(f"Using alternative selector: {alt}")
                return alt
            except Exception:
                continue
        return primary  # Return primary and let it fail with proper error

    username_sel = find_element(selectors.username, selectors.username_alt)
    password_sel = find_element(selectors.password, selectors.password_alt)
    submit_sel = find_element(selectors.submit, selectors.submit_alt)

    # Fill username
    logger.info(f"Filling username with selector: {username_sel}")
    page.fill(username_sel, username)
    time.sleep(0.3)

    # Fill password
    logger.info(f"Filling password with selector: {password_sel}")
    page.fill(password_sel, password)
    time.sleep(0.3)

    # Click submit
    logger.info(f"Clicking submit with selector: {submit_sel}")
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


# ==================== SSO Authenticator ====================


class SSOAuthenticator:
    """Handles SSO authentication using Playwright.

    Supports multiple authentication flows and outcome types.
    """

    def __init__(
        self,
        headless: bool = True,
        screenshot_dir: Optional[Path] = None,
    ):
        """Initialize authenticator.

        Args:
            headless: Run browser in headless mode
            screenshot_dir: Directory for error screenshots
        """
        self.headless = headless
        self.screenshot_dir = (
            screenshot_dir or Path.home() / ".cache" / "sso" / "screenshots"
        )
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)

        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None

    async def authenticate(
        self,
        strategy: SSOStrategy | str,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ) -> SSOResult:
        """Authenticate to a site using the specified strategy.

        Args:
            strategy: SSOStrategy object or name of known strategy
            username: Override username (default: fetch from redhatter)
            password: Override password (default: fetch from redhatter)

        Returns:
            SSOResult with authentication outcome
        """
        # Resolve strategy
        if isinstance(strategy, str):
            if strategy not in KNOWN_STRATEGIES:
                return SSOResult(
                    success=False,
                    strategy_name=strategy,
                    flow_type=FlowType.INLINE_REDIRECT,
                    outcome_type=OutcomeType.REDIRECT_ONLY,
                    error=f"Unknown strategy: {strategy}. Known: {list(KNOWN_STRATEGIES.keys())}",
                )
            strategy = KNOWN_STRATEGIES[strategy]

        logger.info(f"Starting SSO authentication: {strategy.name}")
        logger.info(f"  Flow: {strategy.flow_type.value}")
        logger.info(f"  Target: {strategy.target_url}")

        try:
            # Get credentials if not provided
            if not username or not password:
                logger.info("Fetching credentials from redhatter service...")
                username, password = get_sso_credentials(self.headless)

            # Launch browser
            async with async_playwright() as playwright:
                self._browser = await playwright.chromium.launch(headless=self.headless)
                self._context = await self._browser.new_context()
                self._page = await self._context.new_page()

                # Set default timeout
                self._page.set_default_timeout(strategy.element_timeout)

                # Execute appropriate flow
                if strategy.flow_type == FlowType.INLINE_REDIRECT:
                    result = await self._flow_inline_redirect(
                        strategy, username, password
                    )
                elif strategy.flow_type == FlowType.POPUP:
                    result = await self._flow_popup(strategy, username, password)
                elif strategy.flow_type == FlowType.OAUTH_CHAIN:
                    result = await self._flow_oauth_chain(strategy, username, password)
                else:
                    result = SSOResult(
                        success=False,
                        strategy_name=strategy.name,
                        flow_type=strategy.flow_type,
                        outcome_type=strategy.outcome_type,
                        error=f"Unsupported flow type: {strategy.flow_type}",
                    )

                # Extract outcome if successful
                if result.success:
                    result = await self._extract_outcome(strategy, result)

                return result

        except Exception as e:
            logger.exception(f"SSO authentication failed: {e}")
            screenshot_path = await self._take_screenshot(f"{strategy.name}_error")
            return SSOResult(
                success=False,
                strategy_name=strategy.name,
                flow_type=strategy.flow_type,
                outcome_type=strategy.outcome_type,
                error=str(e),
                screenshot_path=screenshot_path,
            )

    async def _flow_inline_redirect(
        self,
        strategy: SSOStrategy,
        username: str,
        password: str,
    ) -> SSOResult:
        """Handle inline redirect SSO flow.

        1. Navigate to target URL
        2. If redirected to SSO, fill credentials
        3. Submit and wait for redirect back to target
        """
        logger.info("Executing INLINE_REDIRECT flow")

        # Navigate to target
        try:
            await self._page.goto(
                strategy.target_url,
                wait_until="domcontentloaded",
                timeout=strategy.navigation_timeout,
            )
        except Exception as e:
            # Handle ERR_ABORTED (common with SSO redirects)
            if "net::ERR_ABORTED" not in str(e):
                raise
            logger.warning(f"Navigation aborted (expected for SSO): {e}")
            await self._page.wait_for_load_state(
                "domcontentloaded", timeout=strategy.navigation_timeout
            )

        await asyncio.sleep(2)  # Wait for potential redirect

        current_url = self._page.url
        logger.info(f"Current URL after navigation: {current_url}")

        # Check if we're on SSO page
        on_sso = any(pattern in current_url for pattern in strategy.sso_url_patterns)

        if not on_sso:
            # Check if already authenticated
            if (
                strategy.success_url_pattern
                and strategy.success_url_pattern in current_url
            ):
                logger.info("Already authenticated - session exists")
                return SSOResult(
                    success=True,
                    strategy_name=strategy.name,
                    flow_type=strategy.flow_type,
                    outcome_type=strategy.outcome_type,
                    final_url=current_url,
                )
            else:
                logger.warning(f"Not on SSO page and not on target. URL: {current_url}")

        # Fill SSO form
        if on_sso:
            await self._fill_sso_form(strategy.selectors, username, password)

            # Wait for redirect to target
            await self._wait_for_redirect(strategy)

        final_url = self._page.url
        success = (
            strategy.success_url_pattern in final_url
            if strategy.success_url_pattern
            else True
        )

        return SSOResult(
            success=success,
            strategy_name=strategy.name,
            flow_type=strategy.flow_type,
            outcome_type=strategy.outcome_type,
            final_url=final_url,
            error=None if success else f"Did not reach target URL. Final: {final_url}",
        )

    async def _flow_popup(
        self,
        strategy: SSOStrategy,
        username: str,
        password: str,
    ) -> SSOResult:
        """Handle popup SSO flow.

        1. Navigate to target URL
        2. Click button to open SSO popup
        3. Fill credentials in popup
        4. Wait for popup to close
        5. Main window is now authenticated
        """
        logger.info("Executing POPUP flow")

        # Navigate to target
        await self._page.goto(
            strategy.target_url,
            wait_until="domcontentloaded",
            timeout=strategy.navigation_timeout,
        )
        await asyncio.sleep(2)

        # Check if already authenticated
        current_url = self._page.url
        if strategy.success_url_pattern and strategy.success_url_pattern in current_url:
            # Check if sign-in button is missing (already logged in)
            if strategy.popup_trigger_selector:
                try:
                    await self._page.wait_for_selector(
                        strategy.popup_trigger_selector,
                        timeout=3000,
                    )
                except Exception:
                    logger.info("Sign-in button not found - already authenticated")
                    return SSOResult(
                        success=True,
                        strategy_name=strategy.name,
                        flow_type=strategy.flow_type,
                        outcome_type=strategy.outcome_type,
                        final_url=current_url,
                    )

        # Click popup trigger
        if strategy.popup_trigger_selector:
            logger.info(f"Clicking popup trigger: {strategy.popup_trigger_selector}")

            # Wait for new page (popup)
            async with self._context.expect_page(timeout=10000) as popup_info:
                await self._page.click(strategy.popup_trigger_selector)

            popup = await popup_info.value
            await popup.wait_for_load_state("domcontentloaded")

            popup_url = popup.url
            logger.info(f"Popup opened: {popup_url}")

            # Check if popup is SSO page
            if any(pattern in popup_url for pattern in strategy.sso_url_patterns):
                # Fill credentials in popup
                await self._fill_sso_form(
                    strategy.selectors, username, password, page=popup
                )

                # Wait for popup to close
                logger.info("Waiting for popup to close...")
                try:
                    await popup.wait_for_event(
                        "close", timeout=strategy.popup_close_timeout
                    )
                    logger.info("Popup closed - authentication successful")
                except Exception:
                    logger.warning("Popup did not close within timeout")

            # Refresh main page to get authenticated state
            await asyncio.sleep(2)
            await self._page.reload()
            await asyncio.sleep(2)

        final_url = self._page.url
        success = (
            strategy.success_url_pattern in final_url
            if strategy.success_url_pattern
            else True
        )

        return SSOResult(
            success=success,
            strategy_name=strategy.name,
            flow_type=strategy.flow_type,
            outcome_type=strategy.outcome_type,
            final_url=final_url,
        )

    async def _flow_oauth_chain(
        self,
        strategy: SSOStrategy,
        username: str,
        password: str,
    ) -> SSOResult:
        """Handle OAuth redirect chain flow.

        Used for flows like: Google -> Red Hat SSO -> Google -> Target
        """
        logger.info("Executing OAUTH_CHAIN flow")

        # This is a more complex flow - implement as needed
        # For now, treat similar to inline redirect
        return await self._flow_inline_redirect(strategy, username, password)

    async def _fill_sso_form(
        self,
        selectors: SSOSelectors,
        username: str,
        password: str,
        page: Optional[Page] = None,
    ) -> None:
        """Fill SSO login form.

        Uses Playwright's fill() which properly triggers input events.
        """
        page = page or self._page

        logger.info("Filling SSO form...")

        # Try primary selector, then alternatives
        username_selector = await self._find_element(
            page,
            selectors.username,
            selectors.username_alt,
        )
        password_selector = await self._find_element(
            page,
            selectors.password,
            selectors.password_alt,
        )
        submit_selector = await self._find_element(
            page,
            selectors.submit,
            selectors.submit_alt,
        )

        # Fill username
        logger.info(f"Filling username with selector: {username_selector}")
        await page.fill(username_selector, username)
        await asyncio.sleep(0.3)

        # Fill password
        logger.info(f"Filling password with selector: {password_selector}")
        await page.fill(password_selector, password)
        await asyncio.sleep(0.3)

        # Click submit
        logger.info(f"Clicking submit with selector: {submit_selector}")
        await page.click(submit_selector)

        logger.info("SSO form submitted")

    async def _find_element(
        self,
        page: Page,
        primary: str,
        alternatives: list[str],
    ) -> str:
        """Find element using primary selector or alternatives.

        Returns the first selector that finds an element.
        """
        # Try primary
        try:
            await page.wait_for_selector(primary, timeout=5000)
            return primary
        except Exception as exc:
            logger.debug("Suppressed error: %s", exc)

        # Try alternatives
        for alt in alternatives:
            try:
                await page.wait_for_selector(alt, timeout=2000)
                logger.info(f"Using alternative selector: {alt}")
                return alt
            except Exception:
                continue

        # Return primary and let it fail with proper error
        return primary

    async def _wait_for_redirect(self, strategy: SSOStrategy) -> None:
        """Wait for redirect to target URL after SSO submit."""
        logger.info("Waiting for redirect to target...")

        start_time = time.time()
        timeout_seconds = strategy.redirect_timeout / 1000

        while time.time() - start_time < timeout_seconds:
            await asyncio.sleep(1)
            current_url = self._page.url

            # Check for callback URLs that need handling
            if strategy.callback_url_patterns:
                if any(
                    pattern in current_url for pattern in strategy.callback_url_patterns
                ):
                    logger.info(f"On callback URL: {current_url}")
                    # Wait for redirect away from callback
                    continue

            # Check if we've reached target
            if (
                strategy.success_url_pattern
                and strategy.success_url_pattern in current_url
            ):
                logger.info(f"Reached target URL: {current_url}")
                return

            # Check if we're still on SSO
            if any(pattern in current_url for pattern in strategy.sso_url_patterns):
                logger.debug(f"Still on SSO page: {current_url}")
                continue

        # Timeout - try final redirect if configured
        if strategy.final_redirect_url:
            logger.warning(
                f"Redirect timeout, forcing navigation to: {strategy.final_redirect_url}"
            )
            await self._page.goto(
                strategy.final_redirect_url,
                wait_until="networkidle",
                timeout=strategy.navigation_timeout,
            )

    async def _extract_outcome(
        self,
        strategy: SSOStrategy,
        result: SSOResult,
    ) -> SSOResult:
        """Extract authentication outcome (tokens, cookies, etc.)."""

        if strategy.outcome_type == OutcomeType.JWT_TOKEN:
            result = await self._extract_jwt(strategy, result)

        elif strategy.outcome_type == OutcomeType.SESSION_COOKIE:
            result = await self._extract_cookies(strategy, result)

        # REDIRECT_ONLY doesn't need extraction

        return result

    async def _extract_jwt(
        self,
        strategy: SSOStrategy,
        result: SSOResult,
    ) -> SSOResult:
        """Extract JWT token from browser storage or network."""
        logger.info("Extracting JWT token...")

        token = None

        # Try localStorage and sessionStorage
        for storage_type in ["localStorage", "sessionStorage"]:
            for key in strategy.jwt_storage_keys:
                try:
                    value = await self._page.evaluate(
                        f"""
                        () => {{
                            const val = {storage_type}.getItem('{key}');
                            if (!val) return null;
                            // Handle JSON-wrapped tokens
                            try {{
                                const parsed = JSON.parse(val);
                                return parsed.token || parsed.access_token || val;
                            }} catch {{
                                return val;
                            }}
                        }}
                    """
                    )
                    if value:
                        token = value
                        logger.info(f"Found token in {storage_type}['{key}']")
                        break
                except Exception:
                    continue
            if token:
                break

        if token:
            result.jwt_token = token

            # Decode to get expiry
            try:
                import jwt

                claims = jwt.decode(token, options={"verify_signature": False})
                result.jwt_expires_at = claims.get("exp")
                logger.info(f"Token expires at: {result.jwt_expires_at}")
            except Exception as e:
                logger.warning(f"Could not decode JWT: {e}")

            # Save to cache if configured
            if strategy.jwt_cache_path:
                cache_path = Path(strategy.jwt_cache_path).expanduser()
                cache_path.parent.mkdir(parents=True, exist_ok=True)

                token_data = {
                    "token": token,
                    "expires_at": result.jwt_expires_at,
                    "saved_at": int(time.time()),
                }
                cache_path.write_text(json.dumps(token_data, indent=2))
                logger.info(f"Saved token to: {cache_path}")
        else:
            logger.warning("Could not extract JWT token")

        # Also extract cookies if configured
        if strategy.cookie_names:
            result = await self._extract_cookies(strategy, result)

        return result

    async def _extract_cookies(
        self,
        strategy: SSOStrategy,
        result: SSOResult,
    ) -> SSOResult:
        """Extract specific cookies from browser."""
        logger.info("Extracting cookies...")

        cookies = await self._context.cookies()

        for cookie in cookies:
            if cookie["name"] in strategy.cookie_names:
                result.cookies[cookie["name"]] = cookie["value"]
                logger.info(f"Found cookie: {cookie['name']}")

        # Save to cache if configured
        if strategy.cookie_cache_path and result.cookies:
            cache_path = Path(strategy.cookie_cache_path).expanduser()
            cache_path.parent.mkdir(parents=True, exist_ok=True)

            cookie_str = "; ".join(f"{k}={v}" for k, v in result.cookies.items())
            cache_path.write_text(cookie_str)
            logger.info(f"Saved cookies to: {cache_path}")

        return result

    async def _take_screenshot(self, name: str) -> Optional[str]:
        """Take screenshot for debugging."""
        if not self._page:
            return None

        try:
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            path = self.screenshot_dir / f"{name}_{timestamp}.png"
            await self._page.screenshot(path=str(path))
            logger.info(f"Screenshot saved: {path}")
            return str(path)
        except Exception as e:
            logger.warning(f"Failed to take screenshot: {e}")
            return None


# ==================== Persistent Browser Session ====================

# Module-level browser session for browser_* tools.
# These persist across tool calls within a session, enabling multi-step
# browser automation (navigate, click, wait, screenshot).

_browser_playwright = None  # Playwright instance
_browser_instance: Optional[Browser] = None  # Browser instance
_browser_context: Optional[BrowserContext] = None  # Browser context
_browser_page: Optional[Page] = None  # Active page

# Screenshot output directory - use tempfile.gettempdir() for portability
import tempfile as _tempfile  # noqa: E402

BROWSER_SNAPSHOT_DIR = Path(_tempfile.gettempdir()) / "browser_snapshots"


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
    global _browser_playwright, _browser_instance, _browser_context, _browser_page

    # Return existing page if browser is still connected
    if _browser_page is not None and _browser_instance is not None:
        try:
            # Verify the browser is still alive by checking the page URL
            _ = _browser_page.url
            return _browser_page
        except Exception:
            logger.warning("Browser session expired, creating new one")
            await _close_browser()

    try:
        from playwright.async_api import async_playwright as _async_playwright
    except ImportError as e:
        raise RuntimeError(
            "Playwright is not installed. "
            "Install it with: uv add playwright && playwright install chromium"
        ) from e

    logger.info(f"Launching browser (headless={headless})")
    _browser_playwright = await _async_playwright().start()
    _browser_instance = await _browser_playwright.chromium.launch(headless=headless)
    _browser_context = await _browser_instance.new_context(
        viewport={"width": 1280, "height": 720},
    )
    _browser_page = await _browser_context.new_page()

    logger.info("Browser session created")
    return _browser_page


async def _close_browser() -> None:
    """Close the persistent browser session and clean up resources."""
    global _browser_playwright, _browser_instance, _browser_context, _browser_page

    if _browser_instance is not None:
        try:
            await _browser_instance.close()
        except Exception as e:
            logger.warning(f"Error closing browser: {e}")

    if _browser_playwright is not None:
        try:
            await _browser_playwright.stop()
        except Exception as e:
            logger.warning(f"Error stopping playwright: {e}")

    _browser_playwright = None
    _browser_instance = None
    _browser_context = None
    _browser_page = None
    logger.info("Browser session closed")


def _cleanup_browser_sync() -> None:
    """Synchronous atexit handler to clean up browser on process exit."""
    if _browser_instance is not None:
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(_close_browser())
            else:
                loop.run_until_complete(_close_browser())
        except Exception as exc:
            logger.debug("Suppressed error: %s", exc)


atexit.register(_cleanup_browser_sync)


# ==================== Persistent HTTP Session ====================

# Module-level HTTP sessions for http_* tools.
# These persist across tool calls within a session, enabling multi-step
# HTTP automation (create session, SAML auth, API calls).

_http_sessions: dict[str, httpx.AsyncClient] = {}
_session_meta: dict[str, dict] = {}  # csrf token, pin, base_url per session


async def _get_http_session(name: str) -> tuple[httpx.AsyncClient, dict]:
    """Get an existing HTTP session by name.

    Args:
        name: Session name (e.g., "reward_zone")

    Returns:
        Tuple of (httpx client, session metadata dict)

    Raises:
        KeyError: If session does not exist
    """
    if name not in _http_sessions:
        raise KeyError(
            f"HTTP session '{name}' not found. "
            f"Available: {list(_http_sessions.keys())}. "
            "Create one with http_session_create first."
        )
    return _http_sessions[name], _session_meta[name]


async def _create_http_session(
    name: str,
    base_url: str,
) -> tuple[httpx.AsyncClient, dict]:
    """Create a named HTTP session with cookie jar.

    Args:
        name: Session name (e.g., "reward_zone")
        base_url: Base URL for the session (e.g., "https://rewardzone.redhat.com")

    Returns:
        Tuple of (httpx client, session metadata dict)
    """
    # Close existing session with this name if any
    if name in _http_sessions:
        await _close_http_session(name)

    client = httpx.AsyncClient(
        base_url=base_url,
        follow_redirects=False,
        timeout=httpx.Timeout(30.0),
        headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept": "application/json, text/html, */*",
        },
    )

    meta: dict[str, Any] = {
        "base_url": base_url,
        "csrf": None,
        "pin": None,
    }

    _http_sessions[name] = client
    _session_meta[name] = meta

    logger.info(f"HTTP session '{name}' created (base_url={base_url})")
    return client, meta


async def _close_http_session(name: str) -> None:
    """Close a named HTTP session."""
    if name in _http_sessions:
        try:
            await _http_sessions[name].aclose()
        except Exception as e:
            logger.warning(f"Error closing HTTP session '{name}': {e}")
        del _http_sessions[name]
        del _session_meta[name]
        logger.info(f"HTTP session '{name}' closed")


async def _close_all_http_sessions() -> None:
    """Close all HTTP sessions."""
    for name in list(_http_sessions.keys()):
        await _close_http_session(name)


def _cleanup_http_sessions_sync() -> None:
    """Synchronous atexit handler to clean up HTTP sessions on process exit."""
    if _http_sessions:
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(_close_all_http_sessions())
            else:
                loop.run_until_complete(_close_all_http_sessions())
        except Exception as exc:
            logger.debug("Suppressed error: %s", exc)


atexit.register(_cleanup_http_sessions_sync)


# ==================== SAML Form Parser ====================


class _SAMLResponseParser(HTMLParser):
    """Parse the SAMLResponse value from an auto-submit HTML form.

    The IdP returns an HTML page with a form containing a hidden
    SAMLResponse field that auto-submits via JavaScript. We extract
    the SAMLResponse value from the hidden input.
    """

    def __init__(self):
        super().__init__()
        self.saml_response: Optional[str] = None
        self.relay_state: Optional[str] = None
        self.form_action: Optional[str] = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        attr_dict = dict(attrs)
        if tag == "form" and attr_dict.get("method", "").lower() == "post":
            self.form_action = attr_dict.get("action")
        if tag == "input" and attr_dict.get("type") == "hidden":
            name = attr_dict.get("name", "")
            value = attr_dict.get("value", "")
            if name == "SAMLResponse":
                self.saml_response = value
            elif name == "RelayState":
                self.relay_state = value


# ==================== HTTP SAML Auth Flow ====================


async def _saml_auth_http(
    client: httpx.AsyncClient,
    meta: dict,
    config: HTTPSAMLConfig,
    username: str,
    password: str,
) -> dict:
    """Perform the full SAML authentication flow using pure HTTP.

    8-phase flow:
      1. GET init endpoint -> extract _csrf
      2. GET /saml/login -> follow 302 to auth.redhat.com
      3. Parse login form HTML -> extract session_code, execution, tab_id
      4. POST credentials as application/x-www-form-urlencoded
      5. Follow redirects -> extract SAMLResponse from HTML auto-submit form
      6. POST SAMLResponse to /saml/acs -> follow 302 to /sso/{token}
      7. POST /api/v1/Sso/login with {sessionToken, _csrf}
      8. Store pin and session cookies in meta

    Args:
        client: httpx.AsyncClient with cookie jar
        meta: Session metadata dict (mutated in place)
        config: HTTPSAMLConfig with URL paths
        username: Kerberos ID
        password: PIN + OTP token

    Returns:
        Dict with success status and auth details
    """
    # Phase 1: GET init endpoint -> extract _csrf
    logger.info("SAML Phase 1: GET init endpoint")
    resp = await client.get(config.init_url, follow_redirects=True)
    if resp.status_code != 200:
        return {"success": False, "error": f"Init failed: HTTP {resp.status_code}"}

    try:
        init_data = resp.json()
        csrf = init_data.get(config.csrf_field)
        if csrf:
            meta["csrf"] = csrf
            logger.info("Extracted _csrf from init response")
        else:
            logger.warning("No _csrf in init response, continuing anyway")
    except Exception:
        logger.warning("Init response was not JSON, continuing anyway")

    # Phase 2: GET /saml/login -> follow 302 to auth.redhat.com
    logger.info("SAML Phase 2: GET SAML login endpoint")
    resp = await client.get(config.saml_login_path)
    if resp.status_code not in (302, 303, 307):
        return {
            "success": False,
            "error": f"SAML login did not redirect: HTTP {resp.status_code}",
        }

    sso_url = resp.headers.get("location", "")
    if not sso_url:
        return {
            "success": False,
            "error": "No Location header from SAML login redirect",
        }

    logger.info(f"Redirected to SSO: {sso_url[:80]}...")

    # Phase 3: GET SSO login page -> parse form fields
    logger.info("SAML Phase 3: GET SSO login page")
    # Use a separate client for the SSO domain (different base URL)
    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=httpx.Timeout(30.0),
        headers=client.headers,
    ) as sso_client:
        resp = await sso_client.get(sso_url)

        # Handle Kerberos negotiation fallback: auth.redhat.com returns 401
        # with a "Kerberos Unsupported" page containing an auto-submit form.
        # Browsers execute the onload JS to POST the form, which yields the
        # actual username/password login page. We replicate that here.
        if resp.status_code == 401 and "Kerberos" in resp.text:
            logger.info("SAML Phase 3: Kerberos fallback - submitting form")
            kerb_action = _extract_form_action(resp.text)
            if kerb_action:
                if kerb_action.startswith("/"):
                    parsed = urllib.parse.urlparse(str(resp.url))
                    kerb_action = f"{parsed.scheme}://{parsed.netloc}{kerb_action}"
                kerb_fields = _extract_hidden_fields(resp.text)
                resp = await sso_client.post(
                    kerb_action,
                    data=kerb_fields,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    follow_redirects=True,
                )
                logger.info(
                    f"SAML Phase 3: Kerberos fallback POST -> HTTP {resp.status_code}"
                )

        if resp.status_code != 200:
            return {
                "success": False,
                "error": f"SSO login page failed: HTTP {resp.status_code}",
            }

        login_html = resp.text

        # Extract form action URL and hidden fields
        form_action = _extract_form_action(login_html)
        if not form_action:
            return {"success": False, "error": "Could not find login form action URL"}

        # Resolve relative form action against SSO URL
        if form_action.startswith("/"):
            parsed_sso = urllib.parse.urlparse(sso_url)
            form_action = f"{parsed_sso.scheme}://{parsed_sso.netloc}{form_action}"

        hidden_fields = _extract_hidden_fields(login_html)
        logger.info(f"Extracted form action and {len(hidden_fields)} hidden fields")

        # Phase 4: POST credentials
        logger.info("SAML Phase 4: POST credentials to SSO")
        form_data = {
            **hidden_fields,
            "username": username,
            "password": password,
        }

        resp = await sso_client.post(
            form_action,
            data=form_data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            follow_redirects=True,
        )

        # Phase 5: Extract SAMLResponse from HTML auto-submit form
        logger.info("SAML Phase 5: Extract SAMLResponse")
        if resp.status_code != 200:
            return {
                "success": False,
                "error": f"Credentials POST failed: HTTP {resp.status_code}",
            }

        response_html = resp.text

        # Check for login error (wrong credentials)
        if "Invalid username or password" in response_html:
            return {"success": False, "error": "Invalid username or password"}
        if "Account is disabled" in response_html:
            return {"success": False, "error": "Account is disabled"}

        # Handle SSO intermediate "successfully logged in" page.
        # Keycloak returns an HTML page with a JS redirect
        # (window.setTimeout -> finishLoginLink) instead of the
        # SAMLResponse directly. Follow the link to get the SAML form.
        if "successfully logged in" in response_html.lower():
            finish_match = re.search(
                r'id=["\']finishLoginLink["\'][^>]*href=["\']([^"\']+)["\']',
                response_html,
            )
            if not finish_match:
                finish_match = re.search(
                    r'href=["\']([^"\']+)["\'][^>]*id=["\']finishLoginLink["\']',
                    response_html,
                )
            if finish_match:
                finish_url = finish_match.group(1).replace("&amp;", "&")
                logger.info(
                    f"SAML Phase 5: Following finishLoginLink: {finish_url[:80]}..."
                )
                resp = await sso_client.get(finish_url, follow_redirects=True)
                response_html = resp.text
                logger.info(
                    f"SAML Phase 5: finishLoginLink response: HTTP {resp.status_code}"
                )

        parser = _SAMLResponseParser()
        parser.feed(response_html)

        if not parser.saml_response:
            return {
                "success": False,
                "error": "Could not extract SAMLResponse from SSO response",
            }

        logger.info("Extracted SAMLResponse from auto-submit form")

    # Phase 6: POST SAMLResponse to /saml/acs
    logger.info("SAML Phase 6: POST SAMLResponse to ACS")
    acs_data = {"SAMLResponse": parser.saml_response}
    if parser.relay_state:
        acs_data["RelayState"] = parser.relay_state

    resp = await client.post(
        config.saml_acs_path,
        data=acs_data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    if resp.status_code not in (302, 303, 307):
        return {
            "success": False,
            "error": f"SAML ACS did not redirect: HTTP {resp.status_code}",
        }

    # Follow redirect to /sso/{token}
    sso_redirect = resp.headers.get("location", "")
    if not sso_redirect:
        return {"success": False, "error": "No Location header from ACS redirect"}

    # Extract session token from redirect URL path: /sso/{token}
    session_token = sso_redirect.rstrip("/").split("/")[-1]
    logger.info(f"Extracted session token: {session_token[:20]}...")

    # Follow the redirect to set cookies
    resp = await client.get(sso_redirect, follow_redirects=True)

    # Phase 7: POST /api/v1/Sso/login with session token and _csrf
    logger.info("SAML Phase 7: POST SSO login with session token")
    login_body: dict[str, Any] = {"sessionToken": session_token}
    if meta.get("csrf"):
        login_body[config.csrf_field] = meta["csrf"]

    resp = await client.post(
        config.sso_login_path,
        json=login_body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )

    if resp.status_code != 200:
        return {
            "success": False,
            "error": f"SSO login POST failed: HTTP {resp.status_code} - {resp.text[:200]}",
        }

    # Phase 8: Extract pin and update meta
    logger.info("SAML Phase 8: Extract pin from login response")
    try:
        login_data = resp.json()
        pin = login_data.get("pin") or login_data.get("data", {}).get("pin")
        if pin:
            meta["pin"] = pin
            logger.info(f"Authenticated as pin: {pin}")

        # Update _csrf if returned
        new_csrf = login_data.get(config.csrf_field)
        if new_csrf:
            meta["csrf"] = new_csrf
    except Exception as e:
        logger.warning(f"Could not parse SSO login response: {e}")

    return {
        "success": True,
        "pin": meta.get("pin"),
        "session_token": session_token,
        "csrf": meta.get("csrf"),
    }


def _extract_form_action(html: str) -> Optional[str]:
    """Extract the action URL from a login form in HTML."""
    # Look for form with id="kc-form-login" (Keycloak) or generic login form
    match = re.search(
        r'<form[^>]*id=["\']kc-form-login["\'][^>]*action=["\']([^"\']+)["\']',
        html,
    )
    if match:
        return match.group(1).replace("&amp;", "&")

    # Fallback: any form with action containing "authenticate"
    match = re.search(
        r'<form[^>]*action=["\']([^"\']*authenticate[^"\']*)["\']',
        html,
    )
    if match:
        return match.group(1).replace("&amp;", "&")

    # Fallback: first form with POST method
    match = re.search(
        r'<form[^>]*method=["\']post["\'][^>]*action=["\']([^"\']+)["\']',
        html,
        re.IGNORECASE,
    )
    if match:
        return match.group(1).replace("&amp;", "&")

    return None


def _extract_hidden_fields(html: str) -> dict[str, str]:
    """Extract all hidden input fields from HTML."""
    fields = {}
    for match in re.finditer(
        r'<input[^>]*type=["\']hidden["\'][^>]*name=["\']([^"\']+)["\'][^>]*value=["\']([^"\']*)["\']',
        html,
    ):
        fields[match.group(1)] = match.group(2)

    # Also check reverse attribute order (value before name)
    for match in re.finditer(
        r'<input[^>]*type=["\']hidden["\'][^>]*value=["\']([^"\']*)["\'][^>]*name=["\']([^"\']+)["\']',
        html,
    ):
        fields[match.group(2)] = match.group(1)

    return fields


# ==================== MCP Tool Registration ====================


def register_tools(server: "FastMCP") -> int:
    """Register SSO tools with the MCP server.

    Args:
        server: FastMCP server instance

    Returns:
        Number of tools registered
    """
    from mcp.types import TextContent

    from server.auto_heal_decorator import auto_heal
    from server.tool_registry import ToolRegistry

    registry = ToolRegistry(server)

    @auto_heal()
    @registry.tool()
    async def sso_authenticate(
        strategy: str,
        headless: bool = True,
    ) -> list[TextContent]:
        """Authenticate to a Red Hat internal site using SSO.

        Handles the full SSO flow including:
        - Navigating to the target site
        - Detecting SSO redirect
        - Filling credentials (from redhatter service)
        - Waiting for successful authentication
        - Extracting tokens/cookies if applicable

        Args:
            strategy: Name of authentication strategy. Known strategies:
                - "reward_zone": Red Hat Reward Zone
                - "inscope": InScope AI assistant
                - "concur": SAP Concur expenses
            headless: Run browser in headless mode (default: True)

        Returns:
            Authentication result with status and any extracted tokens.

        Examples:
            sso_authenticate("reward_zone")
            sso_authenticate("inscope", headless=False)
        """
        auth = SSOAuthenticator(headless=headless)
        result = await auth.authenticate(strategy)

        if result.success:
            output = "✅ SSO authentication successful\n\n"
            output += f"**Strategy:** {result.strategy_name}\n"
            output += f"**Flow:** {result.flow_type.value}\n"
            output += f"**Final URL:** {result.final_url}\n"

            if result.jwt_token:
                output += "\n**JWT Token:** Extracted and saved\n"
                if result.jwt_expires_at:
                    import datetime

                    exp_time = datetime.datetime.fromtimestamp(result.jwt_expires_at)
                    output += f"**Expires:** {exp_time}\n"

            if result.cookies:
                output += f"\n**Cookies:** {', '.join(result.cookies.keys())}\n"
        else:
            output = "❌ SSO authentication failed\n\n"
            output += f"**Strategy:** {result.strategy_name}\n"
            output += f"**Error:** {result.error}\n"

            if result.screenshot_path:
                output += f"\n**Screenshot:** {result.screenshot_path}\n"

        return [TextContent(type="text", text=output)]

    @auto_heal()
    @registry.tool()
    async def sso_list_strategies() -> list[TextContent]:
        """List available SSO authentication strategies.

        Returns:
            List of known strategies with their configurations.
        """
        parts = ["## Available SSO Strategies\n"]

        for name, strategy in KNOWN_STRATEGIES.items():
            parts.append(
                f"### {name}\n"
                f"- **Target:** {strategy.target_url}\n"
                f"- **Flow:** {strategy.flow_type.value}\n"
                f"- **Outcome:** {strategy.outcome_type.value}\n"
                f"- **Success Pattern:** {strategy.success_url_pattern}\n"
            )

        return [TextContent(type="text", text="\n".join(parts))]

    @auto_heal()
    @registry.tool()
    async def sso_check_session(
        strategy: str,
    ) -> list[TextContent]:
        """Check if there's an existing authenticated session for a strategy.

        For strategies that cache tokens (like inscope), checks if the
        cached token is still valid.

        Args:
            strategy: Name of authentication strategy

        Returns:
            Session status and expiry information.
        """
        if strategy not in KNOWN_STRATEGIES:
            return [
                TextContent(
                    type="text",
                    text=f"❌ Unknown strategy: {strategy}\n\nKnown: {list(KNOWN_STRATEGIES.keys())}",
                )
            ]

        strat = KNOWN_STRATEGIES[strategy]
        output = f"## Session Status: {strategy}\n\n"

        # Check JWT cache
        if strat.jwt_cache_path:
            cache_path = Path(strat.jwt_cache_path).expanduser()
            if cache_path.exists():
                try:
                    content = cache_path.read_text().strip()
                    if content.startswith("{"):
                        data = json.loads(content)
                        token = data.get("token")
                        expires_at = data.get("expires_at", 0)
                    else:
                        token = content
                        import jwt

                        claims = jwt.decode(token, options={"verify_signature": False})
                        expires_at = claims.get("exp", 0)

                    remaining = expires_at - time.time()
                    if remaining > 0:
                        output += "✅ **Token Status:** Valid\n"
                        output += f"**Expires in:** {int(remaining / 60)} minutes\n"
                    else:
                        output += "❌ **Token Status:** Expired\n"
                        output += f"**Expired:** {int(-remaining / 60)} minutes ago\n"
                except Exception as e:
                    output += "⚠️ **Token Status:** Error reading token\n"
                    output += f"**Error:** {e}\n"
            else:
                output += "❌ **Token Status:** No cached token\n"
                output += f"**Cache Path:** {cache_path}\n"
        else:
            output += "ℹ️ This strategy does not cache tokens\n"

        # Check cookie cache
        if strat.cookie_cache_path:
            cache_path = Path(strat.cookie_cache_path).expanduser()
            if cache_path.exists():
                output += f"\n✅ **Cookies:** Cached at {cache_path}\n"
            else:
                output += "\n❌ **Cookies:** No cached cookies\n"

        return [TextContent(type="text", text=output)]

    _register_browser_tools(registry)
    _register_http_session_tools(registry)

    return registry.count


def _register_http_session_tools(registry) -> None:  # noqa: C901
    """Register HTTP session management tools."""
    from mcp.types import TextContent

    from server.auto_heal_decorator import auto_heal

    @auto_heal()
    @registry.tool()
    async def http_session_create(
        name: str,
        base_url: str,
    ) -> list[TextContent]:
        """Create a named HTTP session with cookie jar for API automation.

        Creates a persistent httpx.AsyncClient session that maintains cookies
        across requests. Use this before http_saml_auth or http_request.

        Args:
            name: Session name (e.g., "reward_zone", "concur")
            base_url: Base URL for the session (e.g., "https://rewardzone.redhat.com")

        Returns:
            Session creation status.

        Examples:
            http_session_create("reward_zone", "https://rewardzone.redhat.com")
        """
        try:
            client, meta = await _create_http_session(name, base_url)

            # Try to hit init endpoint if we have a config for this session
            csrf_status = "not attempted"
            if name in HTTP_SAML_CONFIGS:
                config = HTTP_SAML_CONFIGS[name]
                try:
                    resp = await client.get(config.init_url, follow_redirects=True)
                    if resp.status_code == 200:
                        try:
                            init_data = resp.json()
                            csrf = init_data.get(config.csrf_field)
                            if csrf:
                                meta["csrf"] = csrf
                                csrf_status = "extracted"
                            else:
                                csrf_status = "not in response"
                        except Exception:
                            csrf_status = "response not JSON"
                    else:
                        csrf_status = f"HTTP {resp.status_code}"
                except Exception as e:
                    csrf_status = f"error: {e}"

            output = "HTTP session created\n\n"
            output += f"**Name:** {name}\n"
            output += f"**Base URL:** {base_url}\n"
            output += f"**CSRF status:** {csrf_status}\n"

            return [TextContent(type="text", text=output)]

        except Exception as e:
            return [
                TextContent(
                    type="text",
                    text=f"HTTP session creation failed\n\n**Name:** {name}\n**Error:** {e}",
                )
            ]

    @auto_heal()
    @registry.tool()
    async def http_saml_auth(
        session: str,
        strategy: str = "",
    ) -> list[TextContent]:
        """Authenticate an HTTP session via SAML (pure HTTP, no browser).

        Performs the full SAML redirect authentication flow using HTTP
        requests only. No browser is launched. The session must have been
        created first with http_session_create.

        The flow:
        1. GET init endpoint -> extract _csrf token
        2. GET /saml/login -> follow redirect to auth.redhat.com
        3. Parse SSO login form -> extract hidden fields
        4. POST credentials (from redhatter service)
        5. Extract SAMLResponse from auto-submit form
        6. POST SAMLResponse to /saml/acs -> extract session token
        7. POST session token + _csrf to SSO login API
        8. Store pin and session cookies

        Args:
            session: Name of the HTTP session to authenticate
            strategy: SAML config name (defaults to session name).
                Known configs: "reward_zone"

        Returns:
            Authentication result with status and user pin.

        Examples:
            http_saml_auth("reward_zone")
        """
        try:
            client, meta = await _get_http_session(session)
        except KeyError as e:
            return [TextContent(type="text", text=f"Session error: {e}")]

        # Resolve strategy
        config_name = strategy or session
        if config_name not in HTTP_SAML_CONFIGS:
            return [
                TextContent(
                    type="text",
                    text=(
                        f"Unknown HTTP SAML config: {config_name!r}\n\n"
                        f"Known configs: {list(HTTP_SAML_CONFIGS.keys())}"
                    ),
                )
            ]

        config = HTTP_SAML_CONFIGS[config_name]

        try:
            # Get credentials from redhatter service
            username, password = get_sso_credentials(headless=True)

            # Run the SAML flow
            result = await _saml_auth_http(client, meta, config, username, password)

            if result["success"]:
                output = "HTTP SAML authentication successful\n\n"
                output += f"**Session:** {session}\n"
                output += f"**Config:** {config_name}\n"
                if result.get("pin"):
                    output += f"**Pin:** {result['pin']}\n"
                output += f"**CSRF:** {'present' if meta.get('csrf') else 'none'}\n"
            else:
                output = "HTTP SAML authentication failed\n\n"
                output += f"**Session:** {session}\n"
                output += f"**Error:** {result.get('error', 'unknown')}\n"

            return [TextContent(type="text", text=output)]

        except Exception as e:
            logger.exception(f"HTTP SAML auth failed: {e}")
            return [
                TextContent(
                    type="text",
                    text=f"HTTP SAML authentication failed\n\n**Session:** {session}\n**Error:** {e}",
                )
            ]

    @auto_heal()
    @registry.tool()
    async def http_request(
        session: str,
        method: str,
        path: str,
        params: str = "",
        json_body: str = "",
    ) -> list[TextContent]:
        """Make an HTTP request using a named session.

        Uses an existing HTTP session (created with http_session_create)
        to make API requests. Automatically injects the _csrf token into
        JSON body for POST/PUT/PATCH requests.

        Args:
            session: Name of the HTTP session to use
            method: HTTP method (GET, POST, PUT, PATCH, DELETE)
            path: URL path (relative to session base_url, e.g., "/api/v1/Members/search")
            params: JSON string of query parameters (e.g., '{"searchText": "Aparna"}')
            json_body: JSON string of request body for POST/PUT/PATCH

        Returns:
            Response status code and body (parsed JSON or text).

        Examples:
            http_request(
                "reward_zone", "GET",
                "/api/v1/Members/advancedMemberSearch",
                params='{"searchText": "Aparna"}')
            http_request("reward_zone", "POST", "/api/v1/Awards/submitNomination", json_body='{"nomineePin": "12345"}')
        """
        try:
            client, meta = await _get_http_session(session)
        except KeyError as e:
            return [TextContent(type="text", text=f"Session error: {e}")]

        method = method.upper()

        # Parse params
        query_params = None
        if params:
            try:
                query_params = json.loads(params)
            except json.JSONDecodeError as e:
                return [
                    TextContent(
                        type="text",
                        text=f"Invalid params JSON: {e}\n\nReceived: {params}",
                    )
                ]

        # Parse body
        body = None
        if json_body:
            try:
                body = json.loads(json_body)
            except json.JSONDecodeError as e:
                return [
                    TextContent(
                        type="text",
                        text=f"Invalid json_body JSON: {e}\n\nReceived: {json_body}",
                    )
                ]

        # Auto-inject _csrf for write methods
        if method in ("POST", "PUT", "PATCH") and meta.get("csrf"):
            if body is None:
                body = {}
            if "_csrf" not in body:
                body["_csrf"] = meta["csrf"]

        try:
            # Build request kwargs
            kwargs: dict[str, Any] = {"follow_redirects": True}
            if query_params:
                kwargs["params"] = query_params
            if body is not None:
                kwargs["json"] = body
                kwargs["headers"] = {
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                }

            resp = await client.request(method, path, **kwargs)

            # Format response
            status = resp.status_code
            content_type = resp.headers.get("content-type", "")

            if "application/json" in content_type:
                try:
                    resp_body = resp.json()
                    body_str = json.dumps(resp_body, indent=2)
                    # Truncate if very large
                    if len(body_str) > 5000:
                        body_str = body_str[:5000] + "\n... (truncated)"
                except Exception:
                    body_str = resp.text[:5000]
            else:
                body_str = resp.text[:5000]
                if len(resp.text) > 5000:
                    body_str += "\n... (truncated)"

            output = f"**{method} {path}** -> HTTP {status}\n\n"
            output += f"```\n{body_str}\n```"

            return [TextContent(type="text", text=output)]

        except Exception as e:
            return [
                TextContent(
                    type="text",
                    text=f"HTTP request failed\n\n**{method} {path}**\n**Error:** {e}",
                )
            ]


def _register_browser_tools(registry) -> None:  # noqa: C901
    """Register browser automation tools."""
    from mcp.types import TextContent

    from server.auto_heal_decorator import auto_heal

    @auto_heal()
    @registry.tool()
    async def browser_navigate(
        url: str,
        wait_for: str = "load",
        timeout: int = 30,
    ) -> list[TextContent]:
        """Navigate to a URL in a browser.

        Opens a persistent browser session (or reuses an existing one) and
        navigates to the specified URL. The browser session persists across
        tool calls, enabling multi-step automation workflows.

        Args:
            url: URL to navigate to
            wait_for: Wait condition - "load", "domcontentloaded", or "networkidle"
            timeout: Timeout in seconds

        Returns:
            Page title and URL after navigation.

        Examples:
            browser_navigate("https://example.com")
            browser_navigate("https://example.com", wait_for="networkidle")
        """
        # Validate wait_for parameter
        valid_wait_conditions = ("load", "domcontentloaded", "networkidle")
        if wait_for not in valid_wait_conditions:
            return [
                TextContent(
                    type="text",
                    text=(
                        f"Invalid wait_for value: {wait_for!r}. "
                        f"Must be one of: {', '.join(valid_wait_conditions)}"
                    ),
                )
            ]

        try:
            page = await _get_or_create_browser()
            await page.goto(
                url,
                wait_until=wait_for,
                timeout=timeout * 1000,
            )
            title = await page.title()
            final_url = page.url

            output = "Browser navigation successful\n\n"
            output += f"**URL:** {final_url}\n"
            output += f"**Title:** {title}\n"
            output += f"**Wait condition:** {wait_for}\n"

            return [TextContent(type="text", text=output)]

        except Exception as e:
            return [
                TextContent(
                    type="text",
                    text=f"Browser navigation failed\n\n**URL:** {url}\n**Error:** {e}",
                )
            ]

    @auto_heal()
    @registry.tool()
    async def browser_click(
        selector: str = "",
        text: str = "",
        timeout: int = 10,
    ) -> list[TextContent]:
        """Click an element on the page.

        Clicks an element identified by CSS selector or by its text content.
        If both selector and text are provided, text takes precedence (uses
        Playwright text selector). At least one of selector or text must be
        provided.

        Args:
            selector: CSS selector for the element to click
            text: If provided, click element containing this text (uses text selector)
            timeout: Timeout in seconds waiting for element

        Returns:
            Confirmation of click action.

        Examples:
            browser_click(selector="#submit-button")
            browser_click(text="Sign In")
            browser_click(selector="button.primary", text="Submit")
        """
        if not selector and not text:
            return [
                TextContent(
                    type="text",
                    text="At least one of 'selector' or 'text' must be provided.",
                )
            ]

        try:
            page = await _get_or_create_browser()

            # Determine the effective selector
            if text:
                effective_selector = f"text={text}"
            else:
                effective_selector = selector

            # Wait for element then click
            await page.wait_for_selector(
                effective_selector,
                timeout=timeout * 1000,
                state="visible",
            )
            await page.click(effective_selector, timeout=timeout * 1000)

            current_url = page.url
            output = "Click action successful\n\n"
            if text:
                output += f"**Clicked text:** {text!r}\n"
            else:
                output += f"**Clicked selector:** {selector!r}\n"
            output += f"**Current URL:** {current_url}\n"

            return [TextContent(type="text", text=output)]

        except Exception as e:
            target = f"text={text!r}" if text else f"selector={selector!r}"
            return [
                TextContent(
                    type="text",
                    text=f"Click action failed\n\n**Target:** {target}\n**Error:** {e}",
                )
            ]

    @auto_heal()
    @registry.tool()
    async def browser_fill(
        selector: str,
        value: str,
        timeout: int = 10,
    ) -> list[TextContent]:
        """Fill a text input, textarea, or contenteditable element.

        Uses Playwright's fill() which clears existing content and properly
        triggers JavaScript input/change events. For checkboxes or radio
        buttons, use browser_click instead.

        Args:
            selector: CSS selector for the input element (e.g., "#username", "textarea#message")
            value: The text value to fill into the element
            timeout: Timeout in seconds waiting for element

        Returns:
            Confirmation of fill action.

        Examples:
            browser_fill(selector="#username", value="jdoe")
            browser_fill(selector="#basic-search", value="Aparna")
            browser_fill(selector="textarea#desc-label", value="Great work!")
        """
        if not selector:
            return [
                TextContent(
                    type="text",
                    text="The 'selector' parameter is required.",
                )
            ]

        try:
            page = await _get_or_create_browser()

            # Wait for element to be visible
            await page.wait_for_selector(
                selector,
                timeout=timeout * 1000,
                state="visible",
            )
            await page.fill(selector, value, timeout=timeout * 1000)

            current_url = page.url
            # Truncate displayed value for security (passwords, etc.)
            display_value = value[:30] + "..." if len(value) > 30 else value
            output = "Fill action successful\n\n"
            output += f"**Selector:** {selector!r}\n"
            output += f"**Value:** {display_value!r}\n"
            output += f"**Current URL:** {current_url}\n"

            return [TextContent(type="text", text=output)]

        except Exception as e:
            return [
                TextContent(
                    type="text",
                    text=f"Fill action failed\n\n**Selector:** {selector!r}\n**Error:** {e}",
                )
            ]

    @auto_heal()
    @registry.tool()
    async def browser_snapshot(
        name: str = "screenshot",
        full_page: bool = False,
    ) -> list[TextContent]:
        """Take a screenshot of the current page.

        Captures a screenshot of the current browser page and saves it to
        /tmp/browser_snapshots/. The browser must have been opened with a
        prior browser_navigate call.

        Args:
            name: Name for the screenshot file (without extension)
            full_page: Capture full page scroll (True) or just the viewport (False)

        Returns:
            Path to the saved screenshot.

        Examples:
            browser_snapshot()
            browser_snapshot(name="login_page", full_page=True)
        """
        try:
            page = await _get_or_create_browser()

            # Create snapshot directory
            BROWSER_SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)

            # Generate filename with timestamp
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            # Sanitize the name to be filesystem-safe
            safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
            filename = f"{safe_name}_{timestamp}.png"
            filepath = BROWSER_SNAPSHOT_DIR / filename

            await page.screenshot(
                path=str(filepath),
                full_page=full_page,
            )

            title = await page.title()
            current_url = page.url

            output = "Screenshot captured\n\n"
            output += f"**Path:** {filepath}\n"
            output += f"**Page:** {title}\n"
            output += f"**URL:** {current_url}\n"
            output += f"**Full page:** {full_page}\n"

            return [TextContent(type="text", text=output)]

        except Exception as e:
            return [
                TextContent(
                    type="text",
                    text=f"Screenshot failed\n\n**Name:** {name}\n**Error:** {e}",
                )
            ]

    @auto_heal()
    @registry.tool()
    async def browser_wait_for(
        selector: str = "",
        text: str = "",
        timeout: int = 30,
        state: str = "visible",
    ) -> list[TextContent]:
        """Wait for an element or condition on the page.

        Waits for an element matching a CSS selector or text content to reach
        the desired state. At least one of selector or text must be provided.

        Args:
            selector: CSS selector to wait for
            text: Text content to wait for (uses Playwright text selector)
            timeout: Timeout in seconds
            state: Element state to wait for - "visible", "hidden", "attached", "detached"

        Returns:
            Confirmation that condition was met.

        Examples:
            browser_wait_for(selector="#content", state="visible")
            browser_wait_for(text="Loading complete")
            browser_wait_for(selector=".spinner", state="hidden", timeout=60)
        """
        if not selector and not text:
            return [
                TextContent(
                    type="text",
                    text="At least one of 'selector' or 'text' must be provided.",
                )
            ]

        valid_states = ("visible", "hidden", "attached", "detached")
        if state not in valid_states:
            return [
                TextContent(
                    type="text",
                    text=(
                        f"Invalid state value: {state!r}. "
                        f"Must be one of: {', '.join(valid_states)}"
                    ),
                )
            ]

        try:
            page = await _get_or_create_browser()

            # Determine the effective selector
            if text:
                effective_selector = f"text={text}"
            else:
                effective_selector = selector

            await page.wait_for_selector(
                effective_selector,
                timeout=timeout * 1000,
                state=state,
            )

            current_url = page.url
            output = "Wait condition met\n\n"
            if text:
                output += f"**Waited for text:** {text!r}\n"
            else:
                output += f"**Waited for selector:** {selector!r}\n"
            output += f"**State:** {state}\n"
            output += f"**Current URL:** {current_url}\n"

            return [TextContent(type="text", text=output)]

        except Exception as e:
            target = f"text={text!r}" if text else f"selector={selector!r}"
            return [
                TextContent(
                    type="text",
                    text=(
                        f"Wait condition not met (timeout after {timeout}s)\n\n"
                        f"**Target:** {target}\n"
                        f"**State:** {state}\n"
                        f"**Error:** {e}"
                    ),
                )
            ]
