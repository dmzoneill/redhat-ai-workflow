"""
Google Meet Sign-In Handler.

Handles the Google OAuth + Red Hat SSO authentication flow:
1. Click "Sign in" on Meet page
2. Enter email on Google login
3. Redirect to Red Hat SSO
4. Enter username/password
5. Return to Meet

Extracted from GoogleMeetController to separate auth concerns.
"""

import asyncio
import logging
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from tool_modules.aa_meet_bot.src.browser_errors import BROWSER_ERRORS

if TYPE_CHECKING:
    from tool_modules.aa_meet_bot.src.browser_controller import GoogleMeetController

logger = logging.getLogger(__name__)


def _is_meet_url(url: str) -> bool:
    """True only if *url* is actually on meet.google.com (not just containing it)."""
    try:
        return urlparse(url).hostname == "meet.google.com"
    except ValueError:
        return False


class MeetSignIn:
    """Handles Google Meet sign-in via Red Hat SSO.

    Uses composition: receives a reference to the GoogleMeetController
    to access page, config, and state.
    """

    def __init__(self, controller: "GoogleMeetController"):
        self._controller = controller

    @property
    def page(self):
        """Playwright page of the owning controller."""
        return self._controller.page

    @property
    def config(self):
        """Bot configuration of the owning controller."""
        return self._controller.config

    @property
    def state(self):
        """Meeting state of the owning controller."""
        return self._controller.state

    @property
    def _instance_id(self):
        return getattr(self._controller, "_instance_id", None)

    async def sign_in_google(self) -> bool:
        """
        Sign in to Google using Red Hat SSO.

        Handles the OAuth flow:
        1. Click "Sign in" on Meet page
        2. Enter email on Google login
        3. Redirect to Red Hat SSO
        4. Enter username/password
        5. Return to Meet

        Returns:
            True if sign-in successful, False otherwise.
        """
        from tool_modules.aa_meet_bot.src.config import (  # pylint: disable=import-outside-toplevel
            get_google_credentials,
        )

        if not self.page:
            logger.error("Browser not initialized")
            return False

        try:
            # Get credentials from redhatter API
            logger.info("Fetching credentials from redhatter API...")
            username, password = await get_google_credentials(self.config.bot_account.email)

            sign_in_button = await self._find_sign_in_button()
            if sign_in_button:
                logger.info("Clicking Sign in button...")
                await sign_in_button.click()
                await asyncio.sleep(3)

            # Step 1: Wait for Google login page and enter email
            if not await self._enter_google_email():
                return False

            # Step 2: Wait for Red Hat SSO page and enter credentials
            try:
                if await self._sso_login(username, password):
                    return True
            except BROWSER_ERRORS as e:
                logger.warning("Red Hat SSO login failed: %s", e)
                self.state.errors.append(f"SSO login failed: {e}")
                return False

            # Check if we're now signed in (back on Meet page) and the sign-in link is gone
            selector = self._controller.SELECTORS["sign_in_link"]
            if _is_meet_url(self.page.url) and not await self.page.query_selector(selector):
                logger.info("Sign-in appears successful")
            else:
                logger.warning("Sign-in flow completed but status unclear")
            return True

        except Exception as e:  # pylint: disable=broad-exception-caught
            error_msg = f"Sign-in failed: {e}"
            logger.exception(error_msg)
            self.state.errors.append(error_msg)
            return False

    async def _find_sign_in_button(self):
        """Return the Meet "Sign in" button locator, or None if not shown."""
        # Google Meet uses a div[role="button"] with "Sign in" text
        try:
            locator = self.page.locator('div[role="button"]:has-text("Sign in")')
            if await locator.count() > 0:
                logger.info("Found Sign in button (div role=button)")
                return locator.first
        except BROWSER_ERRORS as e:
            logger.debug("Locator search failed: %s", e)

        # Fallback: try span with Sign in text
        try:
            locator = self.page.locator('span:has-text("Sign in")').first
            if await locator.count() > 0:
                logger.info("Found Sign in span")
                return locator
        except BROWSER_ERRORS as e:
            logger.debug("Suppressed error in _handle_sign_in (span search): %s", e)
        return None

    async def _enter_google_email(self) -> bool:
        """Fill the Google email step. Returns False if the page never appeared."""
        try:
            logger.info("Waiting for Google login page...")
            # Specific Google email input ID
            email_input = await self.page.wait_for_selector("#identifierId", timeout=15000)
            if email_input:
                logger.info("Entering email: %s", self.config.bot_account.email)
                await email_input.fill(self.config.bot_account.email)
                await asyncio.sleep(1)

                # Click Next button
                next_button = await self.page.wait_for_selector("#identifierNext", timeout=5000)
                if next_button:
                    logger.info("Clicking Next...")
                    await next_button.click()
                    await asyncio.sleep(5)  # Wait for redirect to SSO
        except BROWSER_ERRORS as e:
            logger.warning("Google email input not found: %s", e)
            return False
        return True

    async def _sso_login(self, username: str, password: str) -> bool:
        """Complete the Red Hat SSO form; True once redirected back to Meet."""
        logger.info("Waiting for Red Hat SSO page...")
        # Red Hat SSO username field
        saml_username = await self.page.wait_for_selector("#username", timeout=15000)
        if not saml_username:
            return False
        logger.info("Red Hat SSO page detected - using aa_sso helper")

        # Use the centralized SSO form filler from aa_sso module
        try:
            from tool_modules.aa_sso.src.tools_basic import (  # pylint: disable=import-outside-toplevel
                fill_sso_form,
            )

            await fill_sso_form(self.page, username, password)
        except ImportError:
            # Fallback to inline implementation if aa_sso not available
            logger.warning("aa_sso module not available, using inline SSO form fill")
            await saml_username.fill(username)
            await asyncio.sleep(0.5)
            saml_password = await self.page.wait_for_selector("#password", timeout=5000)
            if saml_password:
                await saml_password.fill(password)
                await asyncio.sleep(0.5)
            submit_button = await self.page.wait_for_selector("#submit", timeout=5000)
            if submit_button:
                await submit_button.click()

        await asyncio.sleep(10)  # Wait for SSO processing and redirect
        logger.info("SSO login submitted, waiting for redirect to Meet...")
        try:
            return await self._wait_for_meet_redirect()
        except BROWSER_ERRORS:
            # Check if we're already on meet
            if _is_meet_url(self.page.url):
                logger.info("Already on Meet page after SSO")
                return True
            raise

    async def _wait_for_meet_redirect(self) -> bool:
        """Wait up to 30s for Meet, handling Google's verification page."""
        for _ in range(30):
            await asyncio.sleep(1)
            current_url = self.page.url

            # Check for Google "Verify it's you" / account confirmation page
            if "speedbump" in current_url or "samlconfirmaccount" in current_url:
                logger.info("Google verification page detected, clicking Continue...")
                await self._click_verification_continue()

            # Check if we're back on Meet
            if _is_meet_url(self.page.url):
                logger.info("Successfully signed in via Red Hat SSO")
                return True

        # Timeout - check final state
        if _is_meet_url(self.page.url):
            logger.info("Already on Meet page after SSO")
            return True
        raise TimeoutError("Timeout waiting for redirect to Meet")

    async def _click_verification_continue(self) -> None:
        """Click "Continue" on Google's verification page."""
        # The Continue button has nested structure: button > span.VfPpkd-vQzf8d with text
        continue_selectors = [
            'button:has(span:text-is("Continue"))',  # Button with span exact text
            'button.VfPpkd-LgbsSe:has-text("Continue")',  # Google's Material button class
            'button[jsname="LgbsSe"]:has-text("Continue")',  # Button with jsname
            'span.VfPpkd-vQzf8d:text-is("Continue")',  # The span itself (click it)
        ]
        try:
            for selector in continue_selectors:
                if await self._click_if_present(selector):
                    logger.info("Clicked Continue on verification page")
                    await asyncio.sleep(3)
                    return

            # Last resort: find by role and text
            logger.info("Trying role-based selector for Continue...")
            await self.page.get_by_role("button", name="Continue").click(timeout=5000)
            logger.info("Clicked Continue via role selector")
            await asyncio.sleep(3)
        except BROWSER_ERRORS as e:
            logger.warning("Failed to click Continue: %s", e)

    async def _click_if_present(self, selector: str) -> bool:
        """Click the first element matching *selector*; False if absent or the click fails."""
        try:
            btn = self.page.locator(selector).first
            if await btn.count() > 0:
                logger.info("Found Continue button with selector: %s", selector)
                await btn.click(force=True, timeout=5000)
                return True
        except BROWSER_ERRORS as e:
            logger.debug("Selector %s failed: %s", selector, e)
        return False

    async def dismiss_chrome_sync_dialog(self) -> bool:
        """
        Dismiss the "Sign in to Chromium?" dialog that appears after Google SSO login.

        This dialog offers to sync Chrome with the Google account. We dismiss it by
        clicking "Use Chromium without an account" or pressing Escape.

        Returns:
            True if dialog was dismissed, False if not present.
        """
        if not self.page:
            return False

        try:
            # Wait a moment for the dialog to appear (it can be delayed)
            logger.info("Checking for Chrome sync dialog (waiting up to 5s)...")
            await asyncio.sleep(2)

            # Look for the "Sign in to Chromium?" dialog - check page content
            page_content = await self.page.content()
            dialog_found = False

            if "Sign in to Chromium" in page_content or "Sign in to Chrome" in page_content:
                dialog_found = True
                logger.info("Chrome sync dialog detected via page content")

            if not dialog_found:
                # Also try locator-based detection
                dialog_selectors = [
                    'text="Sign in to Chromium?"',
                    'text="Sign in to Chrome?"',
                    'text="Turn on sync?"',
                    ':text("Sign in to Chromium")',
                ]

                for selector in dialog_selectors:
                    try:
                        if await self.page.locator(selector).count() > 0:
                            dialog_found = True
                            logger.info("Chrome sync dialog detected: %s", selector)
                            break
                    except BROWSER_ERRORS as e:
                        logger.debug("Suppressed error in _dismiss_chrome_sync_dialog (selector check): %s", e)

            if not dialog_found:
                logger.info("No Chrome sync dialog found")
                return False

            # Try to click "Use Chromium without an account" or similar dismiss button
            dismiss_selectors = [
                # Exact button text matches
                'button:has-text("Use Chromium without an account")',
                'button:has-text("Use Chrome without an account")',
                # Role-based
                'role=button[name="Use Chromium without an account"]',
                # Partial text matches
                'button:has-text("without an account")',
                'button:has-text("No thanks")',
                'button:has-text("Cancel")',
                'button:has-text("Not now")',
                # The X close button
                'button[aria-label="Close"]',
                'button[aria-label="Dismiss"]',
            ]

            for selector in dismiss_selectors:
                try:
                    btn = self.page.locator(selector)
                    count = await btn.count()
                    if count > 0:
                        logger.info("Found dismiss button: %s (count=%s)", selector, count)
                        await btn.first.click(force=True, timeout=5000)
                        await asyncio.sleep(1)
                        logger.info("Chrome sync dialog dismissed")
                        return True
                except BROWSER_ERRORS as e:
                    logger.debug("Dismiss button %s failed: %s", selector, e)

            # Try Playwright's get_by_role
            try:
                logger.info("Trying get_by_role for dismiss button...")
                await self.page.get_by_role("button", name="Use Chromium without an account").click(timeout=3000)
                logger.info("Chrome sync dialog dismissed via get_by_role")
                return True
            except BROWSER_ERRORS as e:
                logger.debug("get_by_role failed: %s", e)

            # Fallback: press Escape to close
            logger.info("Trying Escape key to dismiss Chrome sync dialog")
            await self.page.keyboard.press("Escape")
            await asyncio.sleep(1)
            return True

        except BROWSER_ERRORS as e:
            logger.warning("Error handling Chrome sync dialog: %s", e)
            return False
