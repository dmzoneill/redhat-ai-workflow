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

The implementation lives in focused modules; this module registers the MCP
tools and re-exports the public API (and the helpers existing callers and
tests import from here):

- sso_models: enums, SSOStrategy/SSOResult, known strategies, HTTP SAML configs
- sso_forms: credentials and login-form helpers
- sso_authenticator: SSOAuthenticator
- sso_browser: persistent browser session and browser_* tool bodies
- sso_http: persistent HTTP sessions and the pure-HTTP SAML flow
- sso_tool_impls: sso_* and http_* tool bodies
"""

from typing import TYPE_CHECKING

from mcp.types import TextContent

from server.auto_heal_decorator import auto_heal
from server.tool_registry import ToolRegistry
from tool_modules.aa_sso.src.sso_authenticator import (
    SSOAuthenticator,
)
from tool_modules.aa_sso.src.sso_browser import (
    BROWSER_SNAPSHOT_DIR,
    _cleanup_browser_sync,
    _close_browser,
    _get_or_create_browser,
    browser_click_impl,
    browser_fill_impl,
    browser_navigate_impl,
    browser_snapshot_impl,
    browser_wait_for_impl,
)
from tool_modules.aa_sso.src.sso_forms import (
    fill_sso_form,
    fill_sso_form_sync,
    get_sso_credentials,
    is_sso_page,
)
from tool_modules.aa_sso.src.sso_http import (
    _MAX_BODY_CHARS,
    _cleanup_http_sessions_sync,
    _close_all_http_sessions,
    _close_http_session,
    _create_http_session,
    _extract_form_action,
    _extract_hidden_fields,
    _format_response_body,
    _get_http_session,
    _http_sessions,
    _init_csrf_status,
    _parse_json_arg,
    _saml_auth_http,
    _SAMLResponseParser,
    _session_meta,
)
from tool_modules.aa_sso.src.sso_models import (
    _AUTOMATION_ERRORS,
    _JSON_ERRORS,
    _JWT_ERRORS,
    HTTP_SAML_CONFIGS,
    KNOWN_STRATEGIES,
    FlowType,
    HTTPSAMLConfig,
    OutcomeType,
    SSOResult,
    SSOSelectors,
    SSOStrategy,
    _optional_jwt_errors,
)
from tool_modules.aa_sso.src.sso_tool_impls import (
    http_request_impl,
    http_saml_auth_impl,
    http_session_create_impl,
    sso_authenticate_impl,
    sso_check_session_impl,
    sso_list_strategies_impl,
)

if TYPE_CHECKING:
    from fastmcp import FastMCP

__all__ = [
    "BROWSER_SNAPSHOT_DIR",
    "HTTP_SAML_CONFIGS",
    "KNOWN_STRATEGIES",
    "_AUTOMATION_ERRORS",
    "_JSON_ERRORS",
    "_JWT_ERRORS",
    "_MAX_BODY_CHARS",
    "FlowType",
    "HTTPSAMLConfig",
    "OutcomeType",
    "SSOAuthenticator",
    "SSOResult",
    "SSOSelectors",
    "SSOStrategy",
    "_SAMLResponseParser",
    "_cleanup_browser_sync",
    "_cleanup_http_sessions_sync",
    "_close_all_http_sessions",
    "_close_browser",
    "_close_http_session",
    "_create_http_session",
    "_extract_form_action",
    "_extract_hidden_fields",
    "_format_response_body",
    "_get_http_session",
    "_get_or_create_browser",
    "_http_sessions",
    "_init_csrf_status",
    "_optional_jwt_errors",
    "_parse_json_arg",
    "_saml_auth_http",
    "_session_meta",
    "fill_sso_form",
    "fill_sso_form_sync",
    "get_sso_credentials",
    "is_sso_page",
    "register_tools",
]


def register_tools(server: "FastMCP") -> int:
    """Register SSO tools with the MCP server.

    Args:
        server: FastMCP server instance

    Returns:
        Number of tools registered
    """
    registry = ToolRegistry(server)

    _register_sso_tools(registry)
    _register_browser_tools(registry)
    _register_http_session_tools(registry)

    return registry.count


def _register_sso_tools(registry) -> None:
    """Register the sso_* tools."""

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
        return [TextContent(type="text", text=await sso_authenticate_impl(strategy, headless))]

    @auto_heal()
    @registry.tool()
    async def sso_list_strategies() -> list[TextContent]:
        """List available SSO authentication strategies.

        Returns:
            List of known strategies with their configurations.
        """
        return [TextContent(type="text", text=sso_list_strategies_impl())]

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
        return [TextContent(type="text", text=sso_check_session_impl(strategy))]


def _register_http_session_tools(registry) -> None:
    """Register HTTP session management tools."""

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
        return [TextContent(type="text", text=await http_session_create_impl(name, base_url))]

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
        return [TextContent(type="text", text=await http_saml_auth_impl(session, strategy))]

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
            http_request(
                "reward_zone",
                "POST",
                "/api/v1/Awards/submitNomination",
                json_body='{"nomineePin": "12345"}',
            )
        """
        return [TextContent(type="text", text=await http_request_impl(session, method, path, params, json_body))]


def _register_browser_tools(registry) -> None:
    """Register browser automation tools."""

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
        return [TextContent(type="text", text=await browser_navigate_impl(url, wait_for, timeout))]

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
        return [TextContent(type="text", text=await browser_click_impl(selector, text, timeout))]

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
        return [TextContent(type="text", text=await browser_fill_impl(selector, value, timeout))]

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
        return [TextContent(type="text", text=await browser_snapshot_impl(name, full_page))]

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
        return [TextContent(type="text", text=await browser_wait_for_impl(selector, text, timeout, state))]
