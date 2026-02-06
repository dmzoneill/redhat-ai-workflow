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
import json
import logging
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Optional

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
    callback_url_patterns: list[str] = field(default_factory=list)  # e.g., ["setsession", "signin"]
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
        raise RuntimeError(f"Auth token not found at {token_path}. " "Ensure redhatter service is running.")

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
        raise RuntimeError(f"Failed to get credentials: {e}")

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
        except Exception:
            pass
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
        except Exception:
            pass
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
        self.screenshot_dir = screenshot_dir or Path.home() / ".cache" / "sso" / "screenshots"
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
                    result = await self._flow_inline_redirect(strategy, username, password)
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
            await self._page.wait_for_load_state("domcontentloaded", timeout=strategy.navigation_timeout)

        await asyncio.sleep(2)  # Wait for potential redirect

        current_url = self._page.url
        logger.info(f"Current URL after navigation: {current_url}")

        # Check if we're on SSO page
        on_sso = any(pattern in current_url for pattern in strategy.sso_url_patterns)

        if not on_sso:
            # Check if already authenticated
            if strategy.success_url_pattern and strategy.success_url_pattern in current_url:
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
        success = strategy.success_url_pattern in final_url if strategy.success_url_pattern else True

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
                await self._fill_sso_form(strategy.selectors, username, password, page=popup)

                # Wait for popup to close
                logger.info("Waiting for popup to close...")
                try:
                    await popup.wait_for_event("close", timeout=strategy.popup_close_timeout)
                    logger.info("Popup closed - authentication successful")
                except Exception:
                    logger.warning("Popup did not close within timeout")

            # Refresh main page to get authenticated state
            await asyncio.sleep(2)
            await self._page.reload()
            await asyncio.sleep(2)

        final_url = self._page.url
        success = strategy.success_url_pattern in final_url if strategy.success_url_pattern else True

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
        except Exception:
            pass

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
                if any(pattern in current_url for pattern in strategy.callback_url_patterns):
                    logger.info(f"On callback URL: {current_url}")
                    # Wait for redirect away from callback
                    continue

            # Check if we've reached target
            if strategy.success_url_pattern and strategy.success_url_pattern in current_url:
                logger.info(f"Reached target URL: {current_url}")
                return

            # Check if we're still on SSO
            if any(pattern in current_url for pattern in strategy.sso_url_patterns):
                logger.debug(f"Still on SSO page: {current_url}")
                continue

        # Timeout - try final redirect if configured
        if strategy.final_redirect_url:
            logger.warning(f"Redirect timeout, forcing navigation to: {strategy.final_redirect_url}")
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
                        """
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
        output = "## Available SSO Strategies\n\n"

        for name, strategy in KNOWN_STRATEGIES.items():
            output += f"### {name}\n"
            output += f"- **Target:** {strategy.target_url}\n"
            output += f"- **Flow:** {strategy.flow_type.value}\n"
            output += f"- **Outcome:** {strategy.outcome_type.value}\n"
            output += f"- **Success Pattern:** {strategy.success_url_pattern}\n"
            output += "\n"

        return [TextContent(type="text", text=output)]

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

    return registry.count
