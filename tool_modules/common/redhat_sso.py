"""Red Hat SAML SSO authentication via pure HTTP.

This module provides the reusable Keycloak authentication core that is
shared by all sites using Red Hat SSO (Concur, Reward Zone, InScope, etc.).

The SAML flow has three phases:
  1. **Pre-auth** (site-specific): Get the SAML entry point URL
  2. **Keycloak auth** (generic): Authenticate via Keycloak login form
  3. **Post-auth** (site-specific): Handle SAMLResponse and establish session

This module handles phase 2 -- the Keycloak core -- and provides helpers
for the common pieces of phases 1 and 3.

Usage::

    from tool_modules.common.redhat_sso import (
        keycloak_authenticate,
        extract_hidden_fields,
        SAMLFormParser,
    )

    # Phase 1: site gets a URL pointing at auth.redhat.com
    sso_url = ...

    # Phase 2: generic Keycloak auth
    result = await keycloak_authenticate(sso_url, username, password)
    # result.saml_response, result.relay_state, result.form_action

    # Phase 3: site POSTs SAMLResponse to its ACS endpoint
    ...
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

# Default User-Agent for all SSO HTTP requests
SSO_USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"

# Default timeout for SSO operations
SSO_TIMEOUT = httpx.Timeout(60.0)


# ==================== Data Classes ====================


@dataclass
class SAMLResult:
    """Result from Keycloak SAML authentication."""

    success: bool = False
    saml_response: str = ""
    relay_state: str = ""
    form_action: str = ""  # ACS URL from the SAMLResponse form
    error: str = ""


@dataclass
class SSOClientConfig:
    """Configuration for creating an SSO HTTP client."""

    follow_redirects: bool = False
    timeout: httpx.Timeout = field(default_factory=lambda: SSO_TIMEOUT)
    user_agent: str = SSO_USER_AGENT
    extra_headers: dict[str, str] = field(default_factory=dict)


# ==================== HTML Parsing ====================


class SAMLFormParser(HTMLParser):
    """Parse SAMLResponse and RelayState from an auto-submit HTML form.

    The IdP returns an HTML page with a form containing hidden
    SAMLResponse/RelayState fields that auto-submits via JavaScript.
    """

    def __init__(self):
        super().__init__()
        self.saml_response: str | None = None
        self.relay_state: str | None = None
        self.form_action: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_dict = dict(attrs)
        if tag == "form":
            action = attr_dict.get("action")
            if action:
                self.form_action = action
        if tag == "input" and (attr_dict.get("type") or "").lower() == "hidden":
            name = attr_dict.get("name") or ""
            value = attr_dict.get("value") or ""
            if name == "SAMLResponse":
                self.saml_response = value
            elif name == "RelayState":
                self.relay_state = value


def extract_hidden_fields(html: str) -> dict[str, str]:
    """Extract all hidden input fields from HTML.

    Handles any attribute ordering (name/type/value can appear in any order).
    Works with both lowercase and uppercase HTML tags.
    """
    fields: dict[str, str] = {}
    for tag_match in re.finditer(r"<input\b([^>]*)/??>", html, re.IGNORECASE | re.DOTALL):
        attrs_str = tag_match.group(1)
        name_m = re.search(r'name=["\']([^"\']*)["\']', attrs_str, re.IGNORECASE)
        type_m = re.search(r'type=["\']([^"\']*)["\']', attrs_str, re.IGNORECASE)
        value_m = re.search(r'value=["\']([^"\']*)["\']', attrs_str, re.IGNORECASE)

        if name_m and type_m and type_m.group(1).lower() == "hidden" and value_m:
            fields[name_m.group(1)] = value_m.group(1)
    return fields


# One quoted attribute (name="value" or name='value'). Each tag body is
# scanned with this single linear pattern rather than nested [^>]*
# wildcards, which backtrack polynomially on large pages.
_ATTR_RE = re.compile(r"""([\w:-]+)\s*=\s*(?:"([^"]*)"|'([^']*)')""")
_FORM_TAG_RE = re.compile(r"<form\b([^>]*)>", re.IGNORECASE)
_ANY_TAG_RE = re.compile(r"<[a-zA-Z]([^>]*)>")


def _tag_attrs(attrs_str: str) -> dict[str, str]:
    """Parse quoted attributes from a tag body; names are lower-cased."""
    attrs: dict[str, str] = {}
    for m in _ATTR_RE.finditer(attrs_str):
        attrs.setdefault(m.group(1).lower(), m.group(2) if m.group(2) is not None else m.group(3))
    return attrs


def _form_tags(html: str) -> list[dict[str, str]]:
    """Return the attributes of every <form> tag in ``html``, in order."""
    return [_tag_attrs(m.group(1)) for m in _FORM_TAG_RE.finditer(html)]


def _first_form_action(html: str) -> str | None:
    """Return the action of the first <form> that has one, unescaped."""
    for attrs in _form_tags(html):
        if attrs.get("action"):
            return attrs["action"].replace("&amp;", "&")
    return None


def extract_form_action(html: str) -> str | None:
    """Extract the action URL from a Keycloak login form.

    Tries in order:
      1. Form with id="kc-form-login"
      2. Any form with action containing "authenticate"
      3. Any form with a POST method
    """
    forms = [attrs for attrs in _form_tags(html) if attrs.get("action")]
    checks = (
        lambda attrs: attrs.get("id", "").lower() == "kc-form-login",
        lambda attrs: "authenticate" in attrs["action"].lower(),
        lambda attrs: attrs.get("method", "").lower() == "post",
    )
    for check in checks:
        for attrs in forms:
            if check(attrs):
                return attrs["action"].replace("&amp;", "&")
    return None


def _finish_login_url(html: str) -> str | None:
    """Return the href of the element with id="finishLoginLink", if any."""
    for m in _ANY_TAG_RE.finditer(html):
        attrs = _tag_attrs(m.group(1))
        if attrs.get("id") == "finishLoginLink" and attrs.get("href"):
            return attrs["href"].replace("&amp;", "&")
    return None


def _resolve_url(url: str, base_url: str) -> str:
    """Resolve a potentially relative URL against a base URL."""
    if url.startswith(("http://", "https://")):
        return url
    p = urlparse(base_url)
    return f"{p.scheme}://{p.netloc}{url}"


# ==================== Keycloak Auth Core ====================


async def keycloak_authenticate(
    sso_url: str,
    username: str,
    password: str,
    *,
    log_prefix: str = "SSO",
) -> SAMLResult:
    """Authenticate via Red Hat Keycloak and return SAMLResponse.

    This is the reusable core of the SAML SSO flow. It handles:
    - SAMLRequest auto-submit forms (some IdP proxies return HTML forms
      that the browser auto-submits, rather than direct redirects)
    - Kerberos 401 negotiation fallback (uppercase HTML tags)
    - Keycloak login form (username/password)
    - "Successfully logged in" intermediate pages
    - SAMLResponse extraction from the final auto-submit form

    Args:
        sso_url: URL that starts the SSO flow. This can be:
          - A direct auth.redhat.com URL
          - A URL that returns an HTML form with SAMLRequest (auto-submit)
          - A URL that 302-redirects to auth.redhat.com
        username: Red Hat Kerberos username (e.g., "daoneill")
        password: Password (PIN + OTP token)
        log_prefix: Prefix for log messages (e.g., "Concur SSO", "RewardZone SSO")

    Returns:
        SAMLResult with saml_response, relay_state, form_action on success,
        or error message on failure.
    """
    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=SSO_TIMEOUT,
        headers={
            "User-Agent": SSO_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    ) as sso_client:
        resp = await _open_login_page(sso_client, sso_url, log_prefix)
        if resp.status_code != 200:
            return SAMLResult(error=f"SSO login page failed: HTTP {resp.status_code}")

        # ── Step 3: Extract Keycloak login form ──────────────────────
        form_action = extract_form_action(resp.text)
        if not form_action:
            return SAMLResult(error="Could not find Keycloak login form action URL")

        # ── Step 4: POST credentials ─────────────────────────────────
        logger.info("%s: POST credentials to Keycloak", log_prefix)
        form_data = {**extract_hidden_fields(resp.text), "username": username, "password": password}
        resp = await _post_form(sso_client, _resolve_url(form_action, str(resp.url)), form_data)
        if resp.status_code != 200:
            return SAMLResult(error=f"Credentials POST failed: HTTP {resp.status_code}")

        for message in ("Invalid username or password", "Account is disabled"):
            if message in resp.text:
                return SAMLResult(error=message)

        # ── Step 5: Handle "successfully logged in" page ─────────────
        response_html = resp.text
        if "successfully logged in" in response_html.lower():
            logger.info("%s: Following 'successfully logged in' link", log_prefix)
            finish_url = _finish_login_url(response_html)
            if finish_url:
                resp = await sso_client.get(finish_url, follow_redirects=True)
                response_html = resp.text

        # ── Step 6: Extract SAMLResponse ─────────────────────────────
        logger.info("%s: Extracting SAMLResponse", log_prefix)
        result = _saml_result(response_html)
        if result.success:
            logger.info("%s: SAMLResponse extracted successfully", log_prefix)
        return result


async def _post_form(client: httpx.AsyncClient, action: str, data: dict[str, str]) -> httpx.Response:
    """POST url-encoded form data, following redirects."""
    return await client.post(
        action,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        follow_redirects=True,
    )


async def _submit_first_form(client: httpx.AsyncClient, resp: httpx.Response) -> httpx.Response:
    """Submit the first form on ``resp`` with its hidden fields, if it has one."""
    action = _first_form_action(resp.text)
    if not action:
        return resp
    return await _post_form(client, _resolve_url(action, str(resp.url)), extract_hidden_fields(resp.text))


async def _open_login_page(client: httpx.AsyncClient, sso_url: str, log_prefix: str) -> httpx.Response:
    """GET the SSO entry point and pass any SAMLRequest or Kerberos forms."""
    # ── Step 1: GET the SSO entry point ───────────────────────────
    logger.info("%s: GET SSO entry point", log_prefix)
    resp = await client.get(sso_url)

    # An HTML page with a SAMLRequest auto-submit form must be POSTed to
    # reach the actual Keycloak login.
    if resp.status_code == 200 and "SAMLRequest" in resp.text and "<form" in resp.text.lower():
        logger.info("%s: Submitting SAMLRequest auto-submit form", log_prefix)
        resp = await _submit_first_form(client, resp)

    # ── Step 2: Handle Kerberos 401 fallback ─────────────────────
    if resp.status_code == 401 and "Kerberos" in resp.text:
        logger.info("%s: Kerberos 401 fallback", log_prefix)
        resp = await _submit_first_form(client, resp)
    return resp


def _saml_result(response_html: str) -> SAMLResult:
    """Build a SAMLResult from the IdP's final auto-submit page."""
    parser = SAMLFormParser()
    parser.feed(response_html)
    if not parser.saml_response:
        return SAMLResult(error="Could not extract SAMLResponse from SSO response")
    return SAMLResult(
        success=True,
        saml_response=parser.saml_response,
        relay_state=parser.relay_state or "",
        form_action=parser.form_action or "",
    )


# ==================== Credential Helpers ====================


def get_redhatter_credentials(
    service_url: str = "http://localhost:8009",
    sso_key: str = "sso",
) -> tuple[str, str]:
    """Fetch SSO credentials from the redhatter service.

    Args:
        service_url: URL of the redhatter service
        sso_key: Key in the credentials response (default: "sso")

    Returns:
        Tuple of (username, password)

    Raises:
        RuntimeError: If credentials cannot be fetched
    """
    try:
        response = httpx.get(f"{service_url}/credentials", timeout=10)
        response.raise_for_status()
    except httpx.TimeoutException as exc:
        raise RuntimeError(f"redhatter service at {service_url} timed out") from exc
    except httpx.HTTPError as exc:
        raise RuntimeError(f"redhatter service request failed: {exc}") from exc

    try:
        creds = json.loads(response.text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON from redhatter service: {response.text[:100]}") from exc

    sso_creds = creds.get(sso_key, {})
    username = sso_creds.get("username", "")
    password = sso_creds.get("password", "")

    if not username or not password:
        available_keys = list(creds.keys())
        raise RuntimeError(f"No '{sso_key}' credentials in redhatter response. Available keys: {available_keys}")

    return username, password


def create_sso_client(**kwargs) -> httpx.AsyncClient:
    """Create an httpx client configured for SSO workflows.

    Args:
        **kwargs: Override any httpx.AsyncClient parameters

    Returns:
        Configured httpx.AsyncClient (caller must close)
    """
    defaults = {
        "follow_redirects": False,
        "timeout": SSO_TIMEOUT,
        "headers": {
            "User-Agent": SSO_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    }
    defaults.update(kwargs)
    return httpx.AsyncClient(**defaults)
