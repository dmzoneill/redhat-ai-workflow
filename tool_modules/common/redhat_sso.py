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
        if tag == "input" and attr_dict.get("type", "").lower() == "hidden":
            name = attr_dict.get("name", "")
            value = attr_dict.get("value", "")
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
    for tag_match in re.finditer(
        r"<input\b([^>]*)/??>", html, re.IGNORECASE | re.DOTALL
    ):
        attrs_str = tag_match.group(1)
        name_m = re.search(r'name=["\']([^"\']*)["\']', attrs_str, re.IGNORECASE)
        type_m = re.search(r'type=["\']([^"\']*)["\']', attrs_str, re.IGNORECASE)
        value_m = re.search(r'value=["\']([^"\']*)["\']', attrs_str, re.IGNORECASE)

        if name_m and type_m and type_m.group(1).lower() == "hidden" and value_m:
            fields[name_m.group(1)] = value_m.group(1)
    return fields


def extract_form_action(html: str) -> str | None:
    """Extract the action URL from a Keycloak login form.

    Tries in order:
      1. Form with id="kc-form-login"
      2. Any form with action containing "authenticate"
      3. Any form with a POST method
    """
    # Keycloak-specific form
    m = re.search(
        r'<form[^>]*id=["\']kc-form-login["\'][^>]*action=["\']([^"\']+)["\']',
        html,
        re.IGNORECASE,
    )
    if m:
        return m.group(1).replace("&amp;", "&")

    # Fallback: form with "authenticate" in action
    m = re.search(
        r'<form[^>]*action=["\']([^"\']*authenticate[^"\']*)["\']',
        html,
        re.IGNORECASE,
    )
    if m:
        return m.group(1).replace("&amp;", "&")

    # Fallback: any POST form
    m = re.search(
        r'<form[^>]*method=["\']post["\'][^>]*action=["\']([^"\']+)["\']',
        html,
        re.IGNORECASE,
    )
    if m:
        return m.group(1).replace("&amp;", "&")

    return None


def _resolve_url(url: str, base_url: str) -> str:
    """Resolve a potentially relative URL against a base URL."""
    if url.startswith("http://") or url.startswith("https://"):
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
    result = SAMLResult()

    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=SSO_TIMEOUT,
        headers={
            "User-Agent": SSO_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    ) as sso_client:

        # ── Step 1: GET the SSO entry point ───────────────────────────
        logger.info(f"{log_prefix}: GET SSO entry point")
        resp = await sso_client.get(sso_url)

        # If the response is an HTML page with a SAMLRequest auto-submit
        # form, we need to POST it to get to the actual Keycloak login.
        if (
            resp.status_code == 200
            and "SAMLRequest" in resp.text
            and "<form" in resp.text.lower()
        ):
            logger.info(f"{log_prefix}: Submitting SAMLRequest auto-submit form")
            form_action_url = re.search(
                r'<form[^>]*action=["\']([^"\']+)["\']', resp.text, re.IGNORECASE
            )
            if form_action_url:
                action = form_action_url.group(1).replace("&amp;", "&")
                action = _resolve_url(action, str(resp.url))
                fields = extract_hidden_fields(resp.text)
                resp = await sso_client.post(
                    action,
                    data=fields,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    follow_redirects=True,
                )

        # ── Step 2: Handle Kerberos 401 fallback ─────────────────────
        if resp.status_code == 401 and "Kerberos" in resp.text:
            logger.info(f"{log_prefix}: Kerberos 401 fallback")
            kerb_action = re.search(
                r'<form[^>]*action=["\']([^"\']+)["\']', resp.text, re.IGNORECASE
            )
            if kerb_action:
                action = kerb_action.group(1).replace("&amp;", "&")
                action = _resolve_url(action, str(resp.url))
                hidden = extract_hidden_fields(resp.text)
                resp = await sso_client.post(
                    action,
                    data=hidden,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    follow_redirects=True,
                )

        if resp.status_code != 200:
            result.error = f"SSO login page failed: HTTP {resp.status_code}"
            return result

        login_html = resp.text

        # ── Step 3: Extract Keycloak login form ──────────────────────
        form_action = extract_form_action(login_html)
        if not form_action:
            result.error = "Could not find Keycloak login form action URL"
            return result

        form_action = _resolve_url(form_action, str(resp.url))
        hidden_fields = extract_hidden_fields(login_html)

        # ── Step 4: POST credentials ─────────────────────────────────
        logger.info(f"{log_prefix}: POST credentials to Keycloak")
        form_data = {**hidden_fields, "username": username, "password": password}
        resp = await sso_client.post(
            form_action,
            data=form_data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            follow_redirects=True,
        )

        if resp.status_code != 200:
            result.error = f"Credentials POST failed: HTTP {resp.status_code}"
            return result

        response_html = resp.text

        # Check for login errors
        if "Invalid username or password" in response_html:
            result.error = "Invalid username or password"
            return result
        if "Account is disabled" in response_html:
            result.error = "Account is disabled"
            return result

        # ── Step 5: Handle "successfully logged in" page ─────────────
        if "successfully logged in" in response_html.lower():
            logger.info(f"{log_prefix}: Following 'successfully logged in' link")
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
                resp = await sso_client.get(finish_url, follow_redirects=True)
                response_html = resp.text

        # ── Step 6: Extract SAMLResponse ─────────────────────────────
        logger.info(f"{log_prefix}: Extracting SAMLResponse")
        parser = SAMLFormParser()
        parser.feed(response_html)

        if not parser.saml_response:
            result.error = "Could not extract SAMLResponse from SSO response"
            return result

        result.success = True
        result.saml_response = parser.saml_response
        result.relay_state = parser.relay_state or ""
        result.form_action = parser.form_action or ""

        logger.info(f"{log_prefix}: SAMLResponse extracted successfully")

    return result


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
    import subprocess

    try:
        result = subprocess.run(
            ["curl", "-sf", f"{service_url}/credentials"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"redhatter service returned exit code {result.returncode}"
            )
    except FileNotFoundError:
        raise RuntimeError("curl not found")
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"redhatter service at {service_url} timed out")

    import json

    try:
        creds = json.loads(result.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(
            f"Invalid JSON from redhatter service: {result.stdout[:100]}"
        )

    sso_creds = creds.get(sso_key, {})
    username = sso_creds.get("username", "")
    password = sso_creds.get("password", "")

    if not username or not password:
        available_keys = list(creds.keys())
        raise RuntimeError(
            f"No '{sso_key}' credentials in redhatter response. "
            f"Available keys: {available_keys}"
        )

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
