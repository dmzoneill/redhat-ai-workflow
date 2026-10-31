"""Playwright-driven Red Hat SSO authenticator (inline redirect, popup and OAuth chain flows)."""

import asyncio
import importlib
import json
import logging
import time
from collections.abc import Sequence
from pathlib import Path

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from tool_modules.aa_sso.src.sso_forms import get_sso_credentials
from tool_modules.aa_sso.src.sso_models import (
    _AUTOMATION_ERRORS,
    _JWT_ERRORS,
    KNOWN_STRATEGIES,
    FlowType,
    OutcomeType,
    SSOResult,
    SSOSelectors,
    SSOStrategy,
)

logger = logging.getLogger(__name__)


def decode_jwt_expiry(token: str) -> int | None:
    """Return the ``exp`` claim of a JWT without verifying its signature.

    Raises one of ``_JWT_ERRORS`` if PyJWT is missing or the token is malformed.
    """
    jwt_module = importlib.import_module("jwt")
    claims = jwt_module.decode(token, options={"verify_signature": False})
    return claims.get("exp")


class SSOAuthenticator:
    """Handles SSO authentication using Playwright.

    Supports multiple authentication flows and outcome types.
    """

    def __init__(
        self,
        headless: bool = True,
        screenshot_dir: Path | None = None,
    ):
        """Initialize authenticator.

        Args:
            headless: Run browser in headless mode
            screenshot_dir: Directory for error screenshots
        """
        self.headless = headless
        self.screenshot_dir = screenshot_dir or Path.home() / ".cache" / "sso" / "screenshots"
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)

        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    async def authenticate(
        self,
        strategy: SSOStrategy | str,
        username: str | None = None,
        password: str | None = None,
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

        logger.info("Starting SSO authentication: %s", strategy.name)
        logger.info("  Flow: %s", strategy.flow_type.value)
        logger.info("  Target: %s", strategy.target_url)

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

        # Intentional: convert the failure into an error result for the caller.
        except _AUTOMATION_ERRORS as e:
            logger.exception("SSO authentication failed")
            screenshot_path = await self.take_screenshot(f"{strategy.name}_error")
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

        page = self._page
        if page is None:
            raise RuntimeError("Browser page is not initialized")

        # Navigate to target
        try:
            await page.goto(
                strategy.target_url,
                wait_until="domcontentloaded",
                timeout=strategy.navigation_timeout,
            )
        # Intentional: re-raise unexpected errors after handling known cases.
        except _AUTOMATION_ERRORS as e:
            # Handle ERR_ABORTED (common with SSO redirects)
            if "net::ERR_ABORTED" not in str(e):
                raise
            logger.warning("Navigation aborted (expected for SSO): %s", e)
            await page.wait_for_load_state("domcontentloaded", timeout=strategy.navigation_timeout)

        await asyncio.sleep(2)  # Wait for potential redirect

        current_url = page.url
        logger.info("Current URL after navigation: %s", current_url)

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
            logger.warning("Not on SSO page and not on target. URL: %s", current_url)

        # Fill SSO form
        if on_sso:
            await self._fill_sso_form(strategy.selectors, username, password)

            # Wait for redirect to target
            await self._wait_for_redirect(strategy)

        final_url = page.url
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

        page = self._page
        context = self._context
        if page is None or context is None:
            raise RuntimeError("Browser page is not initialized")

        # Navigate to target
        await page.goto(
            strategy.target_url,
            wait_until="domcontentloaded",
            timeout=strategy.navigation_timeout,
        )
        await asyncio.sleep(2)

        # Check if already authenticated
        current_url = page.url
        # Already authenticated if on the success URL and the sign-in button is missing
        if (
            strategy.success_url_pattern
            and strategy.success_url_pattern in current_url
            and strategy.popup_trigger_selector
        ):
            try:
                await page.wait_for_selector(
                    strategy.popup_trigger_selector,
                    timeout=3000,
                )
            # Intentional: convert the failure into an error result for the caller.
            except _AUTOMATION_ERRORS:
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
            logger.info("Clicking popup trigger: %s", strategy.popup_trigger_selector)

            # Wait for new page (popup)
            async with context.expect_page(timeout=10000) as popup_info:
                await page.click(strategy.popup_trigger_selector)

            popup = await popup_info.value
            await popup.wait_for_load_state("domcontentloaded")

            popup_url = popup.url
            logger.info("Popup opened: %s", popup_url)

            # Check if popup is SSO page
            if any(pattern in popup_url for pattern in strategy.sso_url_patterns):
                # Fill credentials in popup
                await self._fill_sso_form(strategy.selectors, username, password, page=popup)

                # Wait for popup to close
                logger.info("Waiting for popup to close...")
                try:
                    await popup.wait_for_event("close", timeout=strategy.popup_close_timeout)
                    logger.info("Popup closed - authentication successful")
                # Intentional: log the failure and continue at this boundary.
                except _AUTOMATION_ERRORS:
                    logger.warning("Popup did not close within timeout")

            # Refresh main page to get authenticated state
            await asyncio.sleep(2)
            await page.reload()
            await asyncio.sleep(2)

        final_url = page.url
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
        page: Page | None = None,
    ) -> None:
        """Fill SSO login form.

        Uses Playwright's fill() which properly triggers input events.
        """
        page = page or self._page
        if page is None:
            raise RuntimeError("Browser page is not initialized")

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
        logger.info("Filling username with selector: %s", username_selector)
        await page.fill(username_selector, username)
        await asyncio.sleep(0.3)

        # Fill password
        logger.info("Filling password with selector: %s", password_selector)
        await page.fill(password_selector, password)
        await asyncio.sleep(0.3)

        # Click submit
        logger.info("Clicking submit with selector: %s", submit_selector)
        await page.click(submit_selector)

        logger.info("SSO form submitted")

    async def _find_element(
        self,
        page: Page,
        primary: str,
        alternatives: Sequence[str],
    ) -> str:
        """Find element using primary selector or alternatives.

        Returns the first selector that finds an element.
        """
        # Try primary
        try:
            await page.wait_for_selector(primary, timeout=5000)
            return primary
        # Intentional: log the failure and continue at this boundary.
        except _AUTOMATION_ERRORS as exc:
            logger.debug("Suppressed error: %s", exc)

        # Try alternatives
        for alt in alternatives:
            try:
                await page.wait_for_selector(alt, timeout=2000)
                logger.info("Using alternative selector: %s", alt)
                return alt
            # Intentional: skip this candidate when the optional step fails.
            except _AUTOMATION_ERRORS as exc:
                logger.debug("Candidate failed: %s", exc)
                continue

        # Return primary and let it fail with proper error
        return primary

    async def _wait_for_redirect(self, strategy: SSOStrategy) -> None:
        """Wait for redirect to target URL after SSO submit."""
        logger.info("Waiting for redirect to target...")

        page = self._page
        if page is None:
            raise RuntimeError("Browser page is not initialized")

        start_time = time.time()
        timeout_seconds = strategy.redirect_timeout / 1000

        while time.time() - start_time < timeout_seconds:
            await asyncio.sleep(1)
            current_url = page.url

            # Check for callback URLs that need handling
            if strategy.callback_url_patterns and any(
                pattern in current_url for pattern in strategy.callback_url_patterns
            ):
                logger.info("On callback URL: %s", current_url)
                # Wait for redirect away from callback
                continue

            # Check if we've reached target
            if strategy.success_url_pattern and strategy.success_url_pattern in current_url:
                logger.info("Reached target URL: %s", current_url)
                return

            # Check if we're still on SSO
            if any(pattern in current_url for pattern in strategy.sso_url_patterns):
                logger.debug("Still on SSO page: %s", current_url)
                continue

        # Timeout - try final redirect if configured
        if strategy.final_redirect_url:
            logger.warning(
                "Redirect timeout, forcing navigation to: %s",
                strategy.final_redirect_url,
            )
            await page.goto(
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

        page = self._page
        if page is None:
            raise RuntimeError("Browser page is not initialized")

        token = await self._find_storage_token(page, strategy.jwt_storage_keys)

        if token:
            expires_at = None
            try:
                expires_at = decode_jwt_expiry(token)
                logger.info("Token expires at: %s", expires_at)
            # Intentional: log the failure and continue at this boundary.
            except _JWT_ERRORS as e:
                logger.warning("Could not decode JWT: %s", e)
            result = result._replace(jwt_token=token, jwt_expires_at=expires_at)

            # Save to cache if configured
            if strategy.jwt_cache_path:
                cache_path = Path(strategy.jwt_cache_path).expanduser()
                cache_path.parent.mkdir(parents=True, exist_ok=True)

                token_data = {
                    "token": token,
                    "expires_at": expires_at,
                    "saved_at": int(time.time()),
                }
                cache_path.write_text(json.dumps(token_data, indent=2), encoding="utf-8")
                logger.info("Saved token to: %s", cache_path)
        else:
            logger.warning("Could not extract JWT token")

        # Also extract cookies if configured
        if strategy.cookie_names:
            result = await self._extract_cookies(strategy, result)

        return result

    @staticmethod
    async def _find_storage_token(page: Page, keys: Sequence[str]) -> str | None:
        """Return the first token found in localStorage/sessionStorage under ``keys``."""
        for storage_type in ["localStorage", "sessionStorage"]:
            for key in keys:
                try:
                    value = await page.evaluate(f"""
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
                    """)
                # Intentional: skip this candidate when the optional step fails.
                except _AUTOMATION_ERRORS as exc:
                    logger.debug("Candidate failed: %s", exc)
                    continue
                if value:
                    logger.info("Found token in %s['%s']", storage_type, key)
                    return value
        return None

    async def _extract_cookies(
        self,
        strategy: SSOStrategy,
        result: SSOResult,
    ) -> SSOResult:
        """Extract specific cookies from browser."""
        logger.info("Extracting cookies...")

        context = self._context
        if context is None:
            raise RuntimeError("Browser context is not initialized")

        found = dict(result.cookies)
        for cookie in await context.cookies():
            name = cookie.get("name", "")
            if name in strategy.cookie_names:
                found[name] = cookie.get("value", "")
                logger.info("Found cookie: %s", name)

        # Save to cache if configured
        if strategy.cookie_cache_path and found:
            cache_path = Path(strategy.cookie_cache_path).expanduser()
            cache_path.parent.mkdir(parents=True, exist_ok=True)

            cookie_str = "; ".join(f"{k}={v}" for k, v in found.items())
            cache_path.write_text(cookie_str, encoding="utf-8")
            logger.info("Saved cookies to: %s", cache_path)

        return result._replace(cookies=found)

    async def take_screenshot(self, name: str) -> str | None:
        """Save a screenshot of the current page (for debugging); return its path or None."""
        if not self._page:
            return None

        try:
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            path = self.screenshot_dir / f"{name}_{timestamp}.png"
            await self._page.screenshot(path=str(path))
            logger.info("Screenshot saved: %s", path)
            return str(path)
        # Intentional: convert the failure into an error result for the caller.
        except _AUTOMATION_ERRORS as e:
            logger.warning("Failed to take screenshot: %s", e)
            return None
