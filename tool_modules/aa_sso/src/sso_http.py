"""Persistent HTTP sessions and the pure-HTTP SAML login flow for the http_* tools."""

import asyncio
import atexit
import json
import logging
import re
import urllib.parse
from html.parser import HTMLParser
from typing import Any

import httpx

from tool_modules.aa_sso.src.sso_models import _AUTOMATION_ERRORS, _JSON_ERRORS, HTTP_SAML_CONFIGS, HTTPSAMLConfig
from tool_modules.common.redhat_sso import extract_form_action, extract_hidden_fields

logger = logging.getLogger(__name__)

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

    logger.info("HTTP session '%s' created (base_url=%s)", name, base_url)
    return client, meta


async def _close_http_session(name: str) -> None:
    """Close a named HTTP session."""
    if name in _http_sessions:
        try:
            await _http_sessions[name].aclose()
        # Intentional: log the failure and continue at this boundary.
        except _AUTOMATION_ERRORS as e:
            logger.warning("Error closing HTTP session '%s': %s", name, e)
        del _http_sessions[name]
        del _session_meta[name]
        logger.info("HTTP session '%s' closed", name)


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
        # Intentional: log the failure and continue at this boundary.
        except _AUTOMATION_ERRORS as exc:
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
        self.saml_response: str | None = None
        self.relay_state: str | None = None
        self.form_action: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_dict = dict(attrs)
        method = attr_dict.get("method") or ""
        if tag == "form" and method.lower() == "post":
            self.form_action = attr_dict.get("action")
        if tag == "input" and attr_dict.get("type") == "hidden":
            name = attr_dict.get("name", "")
            value = attr_dict.get("value", "")
            if name == "SAMLResponse":
                self.saml_response = value
            elif name == "RelayState":
                self.relay_state = value


# ==================== HTTP SAML Auth Flow ====================


class _SAMLStepError(Exception):
    """A SAML phase failed; the message is reported to the caller."""


_REDIRECT_CODES = (302, 303, 307)
_FORM_HEADERS = {"Content-Type": "application/x-www-form-urlencoded"}
_FINISH_LINK_PATTERNS = (
    r'id=["\']finishLoginLink["\'][^>]*href=["\']([^"\']+)["\']',
    r'href=["\']([^"\']+)["\'][^>]*id=["\']finishLoginLink["\']',
)


def _absolute(url: str, base: str) -> str:
    """Resolve a root-relative ``url`` against the scheme and host of ``base``."""
    if url.startswith("/"):
        parsed = urllib.parse.urlparse(base)
        return f"{parsed.scheme}://{parsed.netloc}{url}"
    return url


async def _saml_phase_init(client: httpx.AsyncClient, meta: dict, config: HTTPSAMLConfig) -> None:
    """Phase 1: GET init endpoint -> extract _csrf."""
    logger.info("SAML Phase 1: GET init endpoint")
    resp = await client.get(config.init_url, follow_redirects=True)
    if resp.status_code != 200:
        raise _SAMLStepError(f"Init failed: HTTP {resp.status_code}")

    try:
        csrf = resp.json().get(config.csrf_field)
        if csrf:
            meta["csrf"] = csrf
            logger.info("Extracted _csrf from init response")
        else:
            logger.warning("No _csrf in init response, continuing anyway")
    # Intentional: log the failure and continue at this boundary.
    except _JSON_ERRORS:
        logger.warning("Init response was not JSON, continuing anyway")


async def _saml_phase_sso_redirect(client: httpx.AsyncClient, config: HTTPSAMLConfig) -> str:
    """Phase 2: GET /saml/login -> the auth.redhat.com URL it redirects to."""
    logger.info("SAML Phase 2: GET SAML login endpoint")
    resp = await client.get(config.saml_login_path)
    if resp.status_code not in _REDIRECT_CODES:
        raise _SAMLStepError(f"SAML login did not redirect: HTTP {resp.status_code}")
    sso_url = resp.headers.get("location", "")
    if not sso_url:
        raise _SAMLStepError("No Location header from SAML login redirect")
    logger.info("Redirected to SSO: %s...", sso_url[:80])
    return sso_url


async def _saml_phase_login_page(sso_client: httpx.AsyncClient, sso_url: str) -> tuple[str, dict[str, str]]:
    """Phase 3: GET the SSO login page -> (form action URL, hidden fields)."""
    logger.info("SAML Phase 3: GET SSO login page")
    resp = await sso_client.get(sso_url)

    # Handle Kerberos negotiation fallback: auth.redhat.com returns 401
    # with a "Kerberos Unsupported" page containing an auto-submit form.
    # Browsers execute the onload JS to POST the form, which yields the
    # actual username/password login page. We replicate that here.
    if resp.status_code == 401 and "Kerberos" in resp.text:
        logger.info("SAML Phase 3: Kerberos fallback - submitting form")
        kerb_action = _extract_form_action(resp.text)
        if kerb_action:
            resp = await sso_client.post(
                _absolute(kerb_action, str(resp.url)),
                data=_extract_hidden_fields(resp.text),
                headers=_FORM_HEADERS,
                follow_redirects=True,
            )
            logger.info("SAML Phase 3: Kerberos fallback POST -> HTTP %s", resp.status_code)

    if resp.status_code != 200:
        raise _SAMLStepError(f"SSO login page failed: HTTP {resp.status_code}")

    login_html = resp.text
    form_action = _extract_form_action(login_html)
    if not form_action:
        raise _SAMLStepError("Could not find login form action URL")

    hidden_fields = _extract_hidden_fields(login_html)
    logger.info("Extracted form action and %s hidden fields", len(hidden_fields))
    return _absolute(form_action, sso_url), hidden_fields


def _finish_login_url(response_html: str) -> str | None:
    """The Keycloak finishLoginLink on a "successfully logged in" page, if any."""
    if "successfully logged in" not in response_html.lower():
        return None
    for pattern in _FINISH_LINK_PATTERNS:
        match = re.search(pattern, response_html)
        if match:
            return match.group(1).replace("&amp;", "&")
    return None


async def _saml_phase_credentials(
    sso_client: httpx.AsyncClient, form_action: str, form_data: dict[str, str]
) -> "_SAMLResponseParser":
    """Phases 4-5: POST credentials -> parsed SAMLResponse auto-submit form."""
    logger.info("SAML Phase 4: POST credentials to SSO")
    resp = await sso_client.post(form_action, data=form_data, headers=_FORM_HEADERS, follow_redirects=True)

    logger.info("SAML Phase 5: Extract SAMLResponse")
    if resp.status_code != 200:
        raise _SAMLStepError(f"Credentials POST failed: HTTP {resp.status_code}")

    response_html = resp.text
    for marker in ("Invalid username or password", "Account is disabled"):
        if marker in response_html:
            raise _SAMLStepError(marker)

    # Keycloak may return an intermediate page with a JS redirect
    # (window.setTimeout -> finishLoginLink) instead of the SAMLResponse.
    finish_url = _finish_login_url(response_html)
    if finish_url:
        logger.info("SAML Phase 5: Following finishLoginLink: %s...", finish_url[:80])
        resp = await sso_client.get(finish_url, follow_redirects=True)
        response_html = resp.text
        logger.info("SAML Phase 5: finishLoginLink response: HTTP %s", resp.status_code)

    parser = _SAMLResponseParser()
    parser.feed(response_html)
    if not parser.saml_response:
        raise _SAMLStepError("Could not extract SAMLResponse from SSO response")
    logger.info("Extracted SAMLResponse from auto-submit form")
    return parser


async def _saml_phase_acs(client: httpx.AsyncClient, config: HTTPSAMLConfig, parser: "_SAMLResponseParser") -> str:
    """Phase 6: POST SAMLResponse to the ACS -> session token from the /sso/{token} redirect."""
    logger.info("SAML Phase 6: POST SAMLResponse to ACS")
    acs_data = {"SAMLResponse": parser.saml_response or ""}
    if parser.relay_state:
        acs_data["RelayState"] = parser.relay_state

    resp = await client.post(config.saml_acs_path, data=acs_data, headers=_FORM_HEADERS)
    if resp.status_code not in _REDIRECT_CODES:
        raise _SAMLStepError(f"SAML ACS did not redirect: HTTP {resp.status_code}")

    sso_redirect = resp.headers.get("location", "")
    if not sso_redirect:
        raise _SAMLStepError("No Location header from ACS redirect")

    session_token = sso_redirect.rstrip("/").split("/")[-1]
    logger.info("Extracted session identifier from ACS redirect")

    # Follow the redirect to set cookies
    await client.get(sso_redirect, follow_redirects=True)
    return session_token


async def _saml_phase_login(client: httpx.AsyncClient, meta: dict, config: HTTPSAMLConfig, session_token: str) -> None:
    """Phases 7-8: POST the session token (+ _csrf) to the site's SSO login API; store pin/_csrf."""
    logger.info("SAML Phase 7: POST SSO login with session token")
    login_body: dict[str, Any] = {"sessionToken": session_token}
    if meta.get("csrf"):
        login_body[config.csrf_field] = meta["csrf"]

    resp = await client.post(
        config.sso_login_path,
        json=login_body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    if resp.status_code != 200:
        raise _SAMLStepError(f"SSO login POST failed: HTTP {resp.status_code} - {resp.text[:200]}")

    logger.info("SAML Phase 8: Extract pin from login response")
    try:
        login_data = resp.json()
        pin = login_data.get("pin") or login_data.get("data", {}).get("pin")
        if pin:
            meta["pin"] = pin
            logger.info("Authenticated as pin: %s", pin)
        new_csrf = login_data.get(config.csrf_field)
        if new_csrf:
            meta["csrf"] = new_csrf
    # Intentional: log the failure and continue at this boundary.
    except _JSON_ERRORS as e:
        logger.warning("Could not parse SSO login response: %s", e)


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
    try:
        await _saml_phase_init(client, meta, config)
        sso_url = await _saml_phase_sso_redirect(client, config)

        # Use a separate client for the SSO domain (different base URL)
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=httpx.Timeout(30.0),
            headers=client.headers,
        ) as sso_client:
            form_action, hidden_fields = await _saml_phase_login_page(sso_client, sso_url)
            form_data = {**hidden_fields, "username": username, "password": password}
            parser = await _saml_phase_credentials(sso_client, form_action, form_data)

        session_token = await _saml_phase_acs(client, config, parser)
        await _saml_phase_login(client, meta, config, session_token)
    except _SAMLStepError as e:
        return {"success": False, "error": str(e)}

    return {
        "success": True,
        "pin": meta.get("pin"),
        "session_token": session_token,
        "csrf": meta.get("csrf"),
    }


def _extract_form_action(html: str) -> str | None:
    """Extract the action URL from a login form in HTML.

    Prefers the Keycloak ``kc-form-login`` form, then a form posting to an
    "authenticate" URL, then any POST form. Delegates to the linear
    attribute parser in ``tool_modules.common.redhat_sso``.
    """
    return extract_form_action(html)


def _extract_hidden_fields(html: str) -> dict[str, str]:
    """Extract all named hidden input fields from HTML, in any attribute order."""
    return {name: value for name, value in extract_hidden_fields(html).items() if name}


async def _init_csrf_status(client: httpx.AsyncClient, meta: dict, name: str) -> str:
    """Hit the session's init endpoint (if configured) and store its _csrf token.

    Returns a short status for the tool output.
    """
    if name not in HTTP_SAML_CONFIGS:
        return "not attempted"
    config = HTTP_SAML_CONFIGS[name]
    try:
        resp = await client.get(config.init_url, follow_redirects=True)
    # Intentional: report the failure in the status and continue.
    except _AUTOMATION_ERRORS as e:
        return f"error: {e}"
    if resp.status_code != 200:
        return f"HTTP {resp.status_code}"
    try:
        csrf = resp.json().get(config.csrf_field)
    except _JSON_ERRORS:
        return "response not JSON"
    if not csrf:
        return "not in response"
    meta["csrf"] = csrf
    return "extracted"


def _parse_json_arg(raw: str) -> Any:
    """Parse an optional JSON tool argument; empty means None."""
    return json.loads(raw) if raw else None


_MAX_BODY_CHARS = 5000


def _format_response_body(resp: httpx.Response) -> str:
    """Pretty-print a JSON response or return its text, truncated."""
    if "application/json" in resp.headers.get("content-type", ""):
        try:
            body_str = json.dumps(resp.json(), indent=2)
        except _JSON_ERRORS:
            return resp.text[:_MAX_BODY_CHARS]
        if len(body_str) > _MAX_BODY_CHARS:
            body_str = body_str[:_MAX_BODY_CHARS] + "\n... (truncated)"
        return body_str
    body_str = resp.text[:_MAX_BODY_CHARS]
    if len(resp.text) > _MAX_BODY_CHARS:
        body_str += "\n... (truncated)"
    return body_str
