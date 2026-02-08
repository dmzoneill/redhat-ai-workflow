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

if TYPE_CHECKING:
    from tool_modules.aa_meet_bot.src.browser_controller import GoogleMeetController

logger = logging.getLogger(__name__)


class MeetSignIn:
    """Handles Google Meet sign-in via Red Hat SSO.

    Uses composition: receives a reference to the GoogleMeetController
    to access page, config, and state.
    """

    def __init__(self, controller: "GoogleMeetController"):
        self._controller = controller

    @property
    def page(self):
        return self._controller.page

    @property
    def config(self):
        return self._controller.config

    @property
    def state(self):
        return self._controller.state

    @property
    def _instance_id(self):
        return self._controller._instance_id

    async def sign_in_google(self) -> bool:  # noqa: C901
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
        from tool_modules.aa_meet_bot.src.config import get_google_credentials

        if not self.page:
            logger.error("Browser not initialized")
            return False

        try:
            # Get credentials from redhatter API
            logger.info("Fetching credentials from redhatter API...")
            username, password = await get_google_credentials(
                self.config.bot_account.email
            )

            # Check if we need to sign in - look for Sign in button on Meet page
            # Google Meet uses a div[role="button"] with "Sign in" text
            sign_in_button = None

            # Try to find the Sign in button using Playwright locator (better for text matching)
            try:
                # Use locator for better text matching
                locator = self.page.locator('div[role="button"]:has-text("Sign in")')
                if await locator.count() > 0:
                    sign_in_button = locator.first
                    logger.info("Found Sign in button (div role=button)")
            except Exception as e:
                logger.debug(f"Locator search failed: {e}")

            # Fallback: try span with Sign in text
            if not sign_in_button:
                try:
                    locator = self.page.locator('span:has-text("Sign in")').first
                    if await locator.count() > 0:
                        sign_in_button = locator
                        logger.info("Found Sign in span")
                except Exception as e:
                    logger.debug(
                        f"Suppressed error in _handle_sign_in (span search): {e}"
                    )

            if sign_in_button:
                logger.info("Clicking Sign in button...")
                await sign_in_button.click()
                await asyncio.sleep(3)

            # Step 1: Wait for Google login page and enter email
            try:
                logger.info("Waiting for Google login page...")
                email_input = await self.page.wait_for_selector(
                    "#identifierId", timeout=15000  # Specific Google email input ID
                )
                if email_input:
                    logger.info(f"Entering email: {self.config.bot_account.email}")
                    await email_input.fill(self.config.bot_account.email)
                    await asyncio.sleep(1)

                    # Click Next button
                    next_button = await self.page.wait_for_selector(
                        "#identifierNext", timeout=5000
                    )
                    if next_button:
                        logger.info("Clicking Next...")
                        await next_button.click()
                        await asyncio.sleep(5)  # Wait for redirect to SSO
            except Exception as e:
                logger.warning(f"Google email input not found: {e}")
                return False

            # Step 2: Wait for Red Hat SSO page and enter credentials
            try:
                logger.info("Waiting for Red Hat SSO page...")
                saml_username = await self.page.wait_for_selector(
                    "#username", timeout=15000  # Red Hat SSO username field
                )
                if saml_username:
                    logger.info("Red Hat SSO page detected - using aa_sso helper")

                    # Use the centralized SSO form filler from aa_sso module
                    try:
                        from tool_modules.aa_sso.src.tools_basic import fill_sso_form

                        await fill_sso_form(self.page, username, password)
                    except ImportError:
                        # Fallback to inline implementation if aa_sso not available
                        logger.warning(
                            "aa_sso module not available, using inline SSO form fill"
                        )
                        await saml_username.fill(username)
                        await asyncio.sleep(0.5)
                        saml_password = await self.page.wait_for_selector(
                            "#password", timeout=5000
                        )
                        if saml_password:
                            await saml_password.fill(password)
                            await asyncio.sleep(0.5)
                        submit_button = await self.page.wait_for_selector(
                            "#submit", timeout=5000
                        )
                        if submit_button:
                            await submit_button.click()

                    await asyncio.sleep(10)  # Wait for SSO processing and redirect
                    logger.info("SSO login submitted, waiting for redirect to Meet...")

                    # Wait for redirect back to Meet (or intermediate verification page)
                    try:
                        # Wait up to 30s for either Meet or a verification page
                        for _ in range(30):
                            await asyncio.sleep(1)
                            current_url = self.page.url

                            # Check for Google "Verify it's you" / account confirmation page
                            if (
                                "speedbump" in current_url
                                or "samlconfirmaccount" in current_url
                            ):
                                logger.info(
                                    "Google verification page detected, clicking Continue..."
                                )
                                try:
                                    # The Continue button has nested structure: button > span.VfPpkd-vQzf8d with text
                                    # Try multiple selectors to find the actual clickable button
                                    continue_selectors = [
                                        'button:has(span:text-is("Continue"))',  # Button with span exact text
                                        'button.VfPpkd-LgbsSe:has-text("Continue")',  # Google's Material button class
                                        'button[jsname="LgbsSe"]:has-text("Continue")',  # Button with jsname
                                        'span.VfPpkd-vQzf8d:text-is("Continue")',  # The span itself (click it)
                                    ]

                                    clicked = False
                                    for selector in continue_selectors:
                                        try:
                                            btn = self.page.locator(selector).first
                                            if await btn.count() > 0:
                                                logger.info(
                                                    f"Found Continue button with selector: {selector}"
                                                )
                                                await btn.click(
                                                    force=True, timeout=5000
                                                )
                                                logger.info(
                                                    "Clicked Continue on verification page"
                                                )
                                                clicked = True
                                                await asyncio.sleep(3)
                                                break
                                        except Exception as e:
                                            logger.debug(
                                                f"Selector {selector} failed: {e}"
                                            )

                                    if not clicked:
                                        # Last resort: find by role and text
                                        logger.info(
                                            "Trying role-based selector for Continue..."
                                        )
                                        await self.page.get_by_role(
                                            "button", name="Continue"
                                        ).click(timeout=5000)
                                        logger.info(
                                            "Clicked Continue via role selector"
                                        )
                                        await asyncio.sleep(3)

                                except Exception as e:
                                    logger.warning(f"Failed to click Continue: {e}")

                            # Check if we're back on Meet
                            if "meet.google.com" in self.page.url:
                                logger.info("Successfully signed in via Red Hat SSO")
                                return True

                        # Timeout - check final state
                        if "meet.google.com" in self.page.url:
                            logger.info("Already on Meet page after SSO")
                            return True
                        raise Exception("Timeout waiting for redirect to Meet")
                    except Exception:
                        # Check if we're already on meet
                        if "meet.google.com" in self.page.url:
                            logger.info("Already on Meet page after SSO")
                            return True
                        raise

            except Exception as e:
                logger.warning(f"Red Hat SSO login failed: {e}")
                self.state.errors.append(f"SSO login failed: {e}")
                return False

            # Check if we're now signed in (back on Meet page)
            current_url = self.page.url
            if "meet.google.com" in current_url:
                # Check if sign-in link is gone
                sign_in_link = await self.page.query_selector(
                    self._controller.SELECTORS["sign_in_link"]
                )
                if not sign_in_link:
                    logger.info("Sign-in appears successful")
                    return True

            logger.warning("Sign-in flow completed but status unclear")
            return True

        except Exception as e:
            error_msg = f"Sign-in failed: {e}"
            logger.error(error_msg)
            self.state.errors.append(error_msg)
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

            if (
                "Sign in to Chromium" in page_content
                or "Sign in to Chrome" in page_content
            ):
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
                            logger.info(f"Chrome sync dialog detected: {selector}")
                            break
                    except Exception as e:
                        logger.debug(
                            f"Suppressed error in _dismiss_chrome_sync_dialog (selector check): {e}"
                        )

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
                        logger.info(f"Found dismiss button: {selector} (count={count})")
                        await btn.first.click(force=True, timeout=5000)
                        await asyncio.sleep(1)
                        logger.info("Chrome sync dialog dismissed")
                        return True
                except Exception as e:
                    logger.debug(f"Dismiss button {selector} failed: {e}")

            # Try Playwright's get_by_role
            try:
                logger.info("Trying get_by_role for dismiss button...")
                await self.page.get_by_role(
                    "button", name="Use Chromium without an account"
                ).click(timeout=3000)
                logger.info("Chrome sync dialog dismissed via get_by_role")
                return True
            except Exception as e:
                logger.debug(f"get_by_role failed: {e}")

            # Fallback: press Escape to close
            logger.info("Trying Escape key to dismiss Chrome sync dialog")
            await self.page.keyboard.press("Escape")
            await asyncio.sleep(1)
            return True

        except Exception as e:
            logger.warning(f"Error handling Chrome sync dialog: {e}")
            return False
