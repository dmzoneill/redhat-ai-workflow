"""Implementations of the sso_* and http_* MCP tools (return the tool's text output)."""

import datetime
import json
import logging
import time
from pathlib import Path
from typing import Any

from tool_modules.aa_sso.src.sso_authenticator import SSOAuthenticator, decode_jwt_expiry
from tool_modules.aa_sso.src.sso_forms import get_sso_credentials
from tool_modules.aa_sso.src.sso_http import (
    _create_http_session,
    _format_response_body,
    _get_http_session,
    _init_csrf_status,
    _parse_json_arg,
    _saml_auth_http,
)
from tool_modules.aa_sso.src.sso_models import _AUTOMATION_ERRORS, _JWT_ERRORS, HTTP_SAML_CONFIGS, KNOWN_STRATEGIES

logger = logging.getLogger(__name__)

_WRITE_METHODS = ("POST", "PUT", "PATCH")


# ==================== sso_* tools ====================


async def sso_authenticate_impl(strategy: str, headless: bool) -> str:
    """Run an SSO strategy and describe the outcome."""
    auth = SSOAuthenticator(headless=headless)
    result = await auth.authenticate(strategy)

    if not result.success:
        output = "❌ SSO authentication failed\n\n"
        output += f"**Strategy:** {result.strategy_name}\n"
        output += f"**Error:** {result.error}\n"
        if result.screenshot_path:
            output += f"\n**Screenshot:** {result.screenshot_path}\n"
        return output

    output = "✅ SSO authentication successful\n\n"
    output += f"**Strategy:** {result.strategy_name}\n"
    output += f"**Flow:** {result.flow_type.value}\n"
    output += f"**Final URL:** {result.final_url}\n"

    if result.jwt_token:
        output += "\n**JWT Token:** Extracted and saved\n"
        if result.jwt_expires_at:
            exp_time = datetime.datetime.fromtimestamp(result.jwt_expires_at, tz=datetime.UTC).astimezone()
            output += f"**Expires:** {exp_time}\n"

    if result.cookies:
        output += f"\n**Cookies:** {', '.join(result.cookies.keys())}\n"
    return output


def sso_list_strategies_impl() -> str:
    """Describe the known strategies."""
    parts = ["## Available SSO Strategies\n"]
    for name, strategy in KNOWN_STRATEGIES.items():
        parts.append(
            f"### {name}\n"
            f"- **Target:** {strategy.target_url}\n"
            f"- **Flow:** {strategy.flow_type.value}\n"
            f"- **Outcome:** {strategy.outcome_type.value}\n"
            f"- **Success Pattern:** {strategy.success_url_pattern}\n"
        )
    return "\n".join(parts)


def _cached_token_expiry(cache_path: Path) -> int:
    """Expiry of a cached token file: JSON ``{"token", "expires_at"}`` or a raw JWT."""
    content = cache_path.read_text(encoding="utf-8").strip()
    if content.startswith("{"):
        return json.loads(content).get("expires_at", 0)
    return decode_jwt_expiry(content) or 0


def _jwt_cache_status(jwt_cache_path: str) -> str:
    """Token section of sso_check_session."""
    if not jwt_cache_path:
        return "ℹ️ This strategy does not cache tokens\n"
    cache_path = Path(jwt_cache_path).expanduser()
    if not cache_path.exists():
        return f"❌ **Token Status:** No cached token\n**Cache Path:** {cache_path}\n"
    try:
        remaining = _cached_token_expiry(cache_path) - time.time()
    # Intentional: report the failure in the status and continue.
    except _JWT_ERRORS as e:
        return f"⚠️ **Token Status:** Error reading token\n**Error:** {e}\n"
    if remaining > 0:
        return f"✅ **Token Status:** Valid\n**Expires in:** {int(remaining / 60)} minutes\n"
    return f"❌ **Token Status:** Expired\n**Expired:** {int(-remaining / 60)} minutes ago\n"


def _cookie_cache_status(cookie_cache_path: str) -> str:
    """Cookie section of sso_check_session."""
    if not cookie_cache_path:
        return ""
    cache_path = Path(cookie_cache_path).expanduser()
    if cache_path.exists():
        return f"\n✅ **Cookies:** Cached at {cache_path}\n"
    return "\n❌ **Cookies:** No cached cookies\n"


def sso_check_session_impl(strategy: str) -> str:
    """Report cached token/cookie state for a strategy."""
    if strategy not in KNOWN_STRATEGIES:
        return f"❌ Unknown strategy: {strategy}\n\nKnown: {list(KNOWN_STRATEGIES.keys())}"

    strategy_config = KNOWN_STRATEGIES[strategy]
    output = f"## Session Status: {strategy}\n\n"
    output += _jwt_cache_status(strategy_config.jwt_cache_path)
    output += _cookie_cache_status(strategy_config.cookie_cache_path)
    return output


# ==================== http_* tools ====================


async def http_session_create_impl(name: str, base_url: str) -> str:
    """Create a named HTTP session and try to fetch its _csrf."""
    try:
        client, meta = await _create_http_session(name, base_url)
        csrf_status = await _init_csrf_status(client, meta, name)

        output = "HTTP session created\n\n"
        output += f"**Name:** {name}\n"
        output += f"**Base URL:** {base_url}\n"
        output += f"**CSRF status:** {csrf_status}\n"
        return output

    # Intentional: convert the failure into an error result for the caller.
    except _AUTOMATION_ERRORS as e:
        return f"HTTP session creation failed\n\n**Name:** {name}\n**Error:** {e}"


async def http_saml_auth_impl(session: str, strategy: str) -> str:
    """Authenticate an HTTP session with the pure-HTTP SAML flow."""
    try:
        client, meta = await _get_http_session(session)
    except KeyError as e:
        return f"Session error: {e}"

    config_name = strategy or session
    if config_name not in HTTP_SAML_CONFIGS:
        return f"Unknown HTTP SAML config: {config_name!r}\n\nKnown configs: {list(HTTP_SAML_CONFIGS.keys())}"

    try:
        username, password = get_sso_credentials(headless=True)
        result = await _saml_auth_http(client, meta, HTTP_SAML_CONFIGS[config_name], username, password)
    # Intentional: convert the failure into an error result for the caller.
    except _AUTOMATION_ERRORS as e:
        logger.exception("HTTP SAML auth failed")
        return f"HTTP SAML authentication failed\n\n**Session:** {session}\n**Error:** {e}"

    if not result["success"]:
        output = "HTTP SAML authentication failed\n\n"
        output += f"**Session:** {session}\n"
        output += f"**Error:** {result.get('error', 'unknown')}\n"
        return output

    output = "HTTP SAML authentication successful\n\n"
    output += f"**Session:** {session}\n"
    output += f"**Config:** {config_name}\n"
    if result.get("pin"):
        output += f"**Pin:** {result['pin']}\n"
    output += f"**CSRF:** {'present' if meta.get('csrf') else 'none'}\n"
    return output


def _request_kwargs(method: str, meta: dict, query_params: Any, body: Any) -> dict[str, Any]:
    """httpx request kwargs; write methods get the session's _csrf injected into the JSON body."""
    if method in _WRITE_METHODS and meta.get("csrf"):
        if body is None:
            body = {}
        if "_csrf" not in body:
            body["_csrf"] = meta["csrf"]

    kwargs: dict[str, Any] = {"follow_redirects": True}
    if query_params:
        kwargs["params"] = query_params
    if body is not None:
        kwargs["json"] = body
        kwargs["headers"] = {"Content-Type": "application/json", "Accept": "application/json"}
    return kwargs


async def http_request_impl(session: str, method: str, path: str, params: str, json_body: str) -> str:
    """Make a request with a named HTTP session."""
    try:
        client, meta = await _get_http_session(session)
    except KeyError as e:
        return f"Session error: {e}"

    method = method.upper()

    try:
        query_params = _parse_json_arg(params)
    except json.JSONDecodeError as e:
        return f"Invalid params JSON: {e}\n\nReceived: {params}"
    try:
        body = _parse_json_arg(json_body)
    except json.JSONDecodeError as e:
        return f"Invalid json_body JSON: {e}\n\nReceived: {json_body}"

    try:
        resp = await client.request(method, path, **_request_kwargs(method, meta, query_params, body))
    # Intentional: convert the failure into an error result for the caller.
    except _AUTOMATION_ERRORS as e:
        return f"HTTP request failed\n\n**{method} {path}**\n**Error:** {e}"

    output = f"**{method} {path}** -> HTTP {resp.status_code}\n\n"
    output += f"```\n{_format_response_body(resp)}\n```"
    return output
