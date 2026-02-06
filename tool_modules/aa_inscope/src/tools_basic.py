"""InScope AI Assistant tools - Query Red Hat's domain-specific AI assistants.

InScope (https://inscope.corp.redhat.com/convo) provides AI assistants trained
on specific Red Hat documentation and knowledge bases. This module enables
AI-to-AI conversations where our workflow agent can query these specialized
assistants for domain-specific information.

Provides:
- inscope_query: Query an InScope assistant with a question
- inscope_list_assistants: List available InScope assistants
- inscope_auth_status: Check authentication status

Authentication:
- Uses Red Hat SSO (OIDC) via browser session cookies
- Tokens are extracted from Chrome browser profile
- Tokens expire and need periodic refresh
"""

import json
import logging
import time
import uuid
import warnings
from pathlib import Path
from typing import Any

import httpx

# Suppress SSL warnings for internal Red Hat sites
warnings.filterwarnings("ignore", message="Unverified HTTPS request")

from fastmcp import FastMCP  # noqa: E402

from tool_modules.common import PROJECT_ROOT  # noqa: E402

__project_root__ = PROJECT_ROOT

from server.auto_heal_decorator import auto_heal  # noqa: E402
from server.tool_registry import ToolRegistry  # noqa: E402
from server.utils import load_config  # noqa: E402

logger = logging.getLogger(__name__)

# InScope API configuration
INSCOPE_BASE_URL = "https://inscope.corp.redhat.com"
INSCOPE_API_URL = f"{INSCOPE_BASE_URL}/api/proxy/tangerine/api"

# Default timeouts (in seconds)
DEFAULT_CONNECT_TIMEOUT = 10
DEFAULT_READ_TIMEOUT = 120  # AI responses can take a while
DEFAULT_TOTAL_TIMEOUT = 180  # Total request timeout

# Known InScope assistants (ID -> name mapping)
# Updated 2026-02-03 from InScope API /api/proxy/tangerine/api/assistants
KNOWN_ASSISTANTS = {
    1: {"name": "Clowder", "description": "Answers questions based on Clowder documentation"},
    3: {"name": "Consoledot Pages", "description": "Answers questions based on ConsoleDot documentation"},
    4: {"name": "Firelink", "description": "Answers questions related to Firelink"},
    5: {"name": "Hccm", "description": "Answers questions related to HCCM App"},
    6: {"name": "Notifications", "description": "Answers questions related to Notifications App"},
    7: {"name": "Yuptoo", "description": "Answers questions related to Yuptoo App"},
    8: {"name": "Inscope All Docs Agent", "description": "Agent that has all documents in its knowledgebase"},
    10: {"name": "Inscope Onboarding Guide", "description": "Answers questions based on inScope Onboarding Guide"},
    11: {
        "name": "Frontend Experience",
        "description": "Answers questions related to frontend-experience documentation",
    },
    12: {"name": "Incident Management", "description": "Answers questions related to Incident Management"},
    13: {"name": "Roms Onboarding Guide", "description": "Answers questions related to ROMS Onboarding Guide"},
    15: {"name": "Managed Openshift", "description": "Answers questions related to Managed OpenShift documentation"},
    16: {"name": "Openshift Ci", "description": "Answers questions related to OpenShift CI documentation"},
    17: {"name": "App Sre App Interface", "description": "Answers questions related to app-interface"},
    18: {"name": "App Sre Dev Guidelines", "description": "Answers questions related to AppSRE Dev Guidelines"},
    19: {"name": "App Sre Contract", "description": "Answers questions related to AppSRE Contract"},
    21: {"name": "Konflux", "description": "Answers questions related to Konflux documentation"},
    22: {
        "name": "Ocm Clusters Service",
        "description": "Answers questions related to OCM Clusters Service documentation",
    },
    23: {"name": "HCM Architecture Documents", "description": "Answers questions related to HCM architecture"},
    24: {
        "name": "Forum Openshift Monitoring",
        "description": "Answers questions related to forum openshift monitoring documentation",
    },
}

# Alias mapping for convenience
# Updated 2026-02-03 to match new InScope API IDs
ASSISTANT_ALIASES = {
    "app-interface": 17,
    "appinterface": 17,
    "app_interface": 17,
    "clowder": 1,
    "konflux": 21,
    "all": 8,
    "all-docs": 8,
    "incident": 12,
    "incidents": 12,
    "frontend": 11,
    "hccm": 5,
    "cost": 5,
    "monitoring": 24,
    "openshift-ci": 16,
    "ci": 16,
    "notifications": 6,
    "ocm": 22,
    "consoledot": 3,
    "firelink": 4,
    "yuptoo": 7,
    "managed-openshift": 15,
    "hcm": 23,
}

# Keyword to assistant mapping for auto-selection
# Format: keyword -> (assistant_id, weight)
# Higher weight = stronger signal
# Updated 2026-02-03 to match new InScope API IDs
KEYWORD_ASSISTANT_MAP_WEIGHTED = {
    # App Interface / SaaS deployment (ID 17)
    "rds": (17, 3),
    "database": (17, 1),
    "saas": (17, 2),
    "namespace": (17, 1),
    "deploy": (17, 1),
    "app-interface": (17, 5),
    "appinterface": (17, 5),
    "sre": (17, 2),
    "secret": (17, 2),
    "vault": (17, 3),
    "terraform": (17, 3),
    "aws": (17, 2),
    "s3": (17, 2),
    "elasticache": (17, 3),
    # Clowder (ID 1)
    "clowdapp": (1, 5),
    "clowdenv": (1, 5),
    "clowder": (1, 5),
    "cdappconfig": (1, 4),
    "ephemeral": (1, 3),
    "bonfire": (1, 4),
    # Konflux (ID 21)
    "konflux": (21, 5),
    "release": (21, 2),
    "tekton": (21, 4),
    "snapshot": (21, 3),
    # OpenShift CI (ID 16)
    "openshift-ci": (16, 5),
    "prow": (16, 4),
    "prowjob": (16, 4),
    # Monitoring (ID 24)
    "prometheus": (24, 4),
    "alertmanager": (24, 4),
    "grafana": (24, 4),
    "monitoring": (24, 3),
    "metrics": (24, 2),
    "slo": (24, 3),
    "sli": (24, 3),
    # Incident (ID 12)
    "incident": (12, 4),
    "outage": (12, 4),
    "postmortem": (12, 5),
    "escalation": (12, 4),
    "oncall": (12, 4),
    "pagerduty": (12, 5),
    # Cost / HCCM (ID 5)
    "cost": (5, 3),
    "billing": (5, 3),
    "hccm": (5, 5),
    "metering": (5, 4),
    # Frontend (ID 11)
    "frontend": (11, 4),
    "chrome": (11, 3),
    "patternfly": (11, 5),
    "react": (11, 2),
    "ui": (11, 2),
    # Notifications (ID 6)
    "notification": (6, 4),
    "email": (6, 2),
    "webhook": (6, 3),
    # OCM (ID 22)
    "ocm": (22, 5),
    "managed openshift": (15, 4),
}

# Simple keyword map for backward compatibility
KEYWORD_ASSISTANT_MAP = {k: v[0] for k, v in KEYWORD_ASSISTANT_MAP_WEIGHTED.items()}


def _get_inscope_config() -> dict:
    """Get InScope configuration from config.json."""
    config = load_config()
    return config.get("inscope", {})


def _resolve_assistant_id(assistant: str | int) -> int:
    """Resolve assistant name/alias to ID.

    Args:
        assistant: Assistant ID (int), name, or alias

    Returns:
        Assistant ID

    Raises:
        ValueError: If assistant cannot be resolved
    """
    if isinstance(assistant, int):
        if assistant in KNOWN_ASSISTANTS:
            return assistant
        raise ValueError(f"Unknown assistant ID: {assistant}")

    # Try alias first
    assistant_lower = assistant.lower().strip()
    if assistant_lower in ASSISTANT_ALIASES:
        return ASSISTANT_ALIASES[assistant_lower]

    # Try matching by name
    for aid, info in KNOWN_ASSISTANTS.items():
        if assistant_lower in info["name"].lower():
            return aid

    raise ValueError(
        f"Unknown assistant: {assistant}. "
        f"Available: {', '.join(ASSISTANT_ALIASES.keys())} or IDs 1-{max(KNOWN_ASSISTANTS.keys())}"
    )


def _auto_select_assistant(query: str) -> int:
    """Auto-select the best assistant based on query keywords.

    Uses weighted keyword matching to select the most appropriate assistant.
    Higher weights indicate stronger signals for a particular assistant.

    Args:
        query: The user's question

    Returns:
        Assistant ID (defaults to 12 "all-docs" if no keywords match)
    """
    query_lower = query.lower()

    # Sum weighted scores per assistant
    assistant_scores: dict[int, int] = {}
    for keyword, (assistant_id, weight) in KEYWORD_ASSISTANT_MAP_WEIGHTED.items():
        if keyword in query_lower:
            assistant_scores[assistant_id] = assistant_scores.get(assistant_id, 0) + weight

    if assistant_scores:
        # Return assistant with highest weighted score
        return max(assistant_scores.items(), key=lambda x: x[1])[0]

    # Default to "all docs" assistant for general queries (ID 8)
    return 8


async def _get_auth_token(auto_refresh: bool = True) -> str | None:
    """Get authentication token for InScope.

    InScope uses Backstage auth which requires:
    1. A valid session cookie from browser login
    2. The session provides a JWT token for API calls

    Args:
        auto_refresh: If True, attempt auto-login when token is expired/expiring

    Returns:
        Bearer token string or None if not available
    """
    config = _get_inscope_config()

    # Check for manually configured token
    if "bearer_token" in config:
        return config["bearer_token"]

    # Check for token file
    token_file = config.get("token_file", "~/.cache/inscope/token")
    token_path = Path(token_file).expanduser()

    token = None
    needs_refresh = False

    if token_path.exists():
        try:
            content = token_path.read_text().strip()
            # Handle both JSON format and raw token
            if content.startswith("{"):
                token_data = json.loads(content)
                token = token_data.get("token")
                expires_at = token_data.get("expires_at", 0)
            else:
                token = content
                # Decode to get expiry
                try:
                    import jwt

                    claims = jwt.decode(token, options={"verify_signature": False})
                    expires_at = claims.get("exp", 0)
                except Exception:
                    expires_at = 0

            # Check if token is valid and not expiring soon (5 min buffer)
            time_remaining = expires_at - time.time()
            if time_remaining > 300:  # More than 5 minutes remaining
                return token
            elif time_remaining > 0:
                logger.info(f"InScope token expiring in {time_remaining/60:.0f} minutes, will refresh")
                needs_refresh = True
            else:
                logger.warning("InScope token expired")
                needs_refresh = True

        except Exception as e:
            logger.warning(f"Failed to read token file: {e}")
            needs_refresh = True
    else:
        needs_refresh = True

    # Attempt auto-refresh if needed
    if needs_refresh and auto_refresh:
        logger.info("Attempting InScope auto-login...")
        try:
            refresh_result = await _inscope_auto_login_impl(headless=True)
            result_data = json.loads(refresh_result)
            if result_data.get("success"):
                logger.info("InScope token refreshed successfully")
                # Re-read the token
                if token_path.exists():
                    content = token_path.read_text().strip()
                    if content.startswith("{"):
                        token_data = json.loads(content)
                        return token_data.get("token")
                    else:
                        return content
            else:
                logger.warning(f"Auto-login failed: {result_data.get('error')}")
        except Exception as e:
            logger.warning(f"Auto-refresh failed: {e}")

    return token if token and not needs_refresh else None


async def _get_session_cookie() -> str | None:
    """Get session cookie for InScope.

    The connect.sid cookie is required for authenticated requests.

    Returns:
        Cookie string or None if not available
    """
    config = _get_inscope_config()

    # Check for manually configured cookie
    if "session_cookie" in config:
        return config["session_cookie"]

    # Check for cookie file
    cookie_file = config.get("cookie_file", "~/.cache/inscope/cookies")
    cookie_path = Path(cookie_file).expanduser()
    if cookie_path.exists():
        try:
            return cookie_path.read_text().strip()
        except Exception as e:
            logger.warning(f"Failed to read cookie file: {e}")

    return None


async def _extract_browser_credentials() -> dict[str, str]:
    """Extract InScope credentials from Chrome browser.

    Extracts:
    - Bearer token from localStorage/sessionStorage
    - Session cookie (connect.sid)

    Returns:
        Dict with 'token' and 'cookie' keys
    """
    # This would use browser automation or cookie extraction
    # For now, return empty - user needs to configure manually
    return {}


async def _stream_response(response: httpx.Response) -> tuple[str, list[dict]]:
    """Parse SSE streaming response from InScope.

    InScope returns Server-Sent Events with format:
    data: {"text_content": "..."}
    data: {"search_metadata": [...]}

    Args:
        response: httpx Response object

    Returns:
        Tuple of (full_text, search_metadata)
    """
    full_text = ""
    search_metadata = []

    async for line in response.aiter_lines():
        if not line:
            continue

        if line.startswith("data: "):
            try:
                data = json.loads(line[6:])  # Skip "data: " prefix
                if "text_content" in data:
                    full_text += data["text_content"]
                elif "search_metadata" in data:
                    search_metadata = data["search_metadata"]
            except json.JSONDecodeError:
                logger.debug(f"Failed to parse SSE data: {line}")
                continue

    return full_text, search_metadata


async def _inscope_query_impl(
    query: str,
    assistant: str | int = "app-interface",
    timeout_secs: int = DEFAULT_TOTAL_TIMEOUT,
    include_sources: bool = True,
) -> str:
    """Implementation of inscope_query tool."""
    try:
        # Resolve assistant
        assistant_id = _resolve_assistant_id(assistant)
        assistant_info = KNOWN_ASSISTANTS.get(assistant_id, {})
        assistant_name = assistant_info.get("name", f"Assistant {assistant_id}")

        # Get auth
        token = await _get_auth_token()
        cookie = await _get_session_cookie()

        if not token:
            return json.dumps(
                {
                    "success": False,
                    "error": "No authentication token available",
                    "hint": "Configure inscope.bearer_token in config.json or run inscope_auth_setup()",
                }
            )

        # Build request
        url = f"{INSCOPE_API_URL}/assistants/{assistant_id}/chat"
        config = _get_inscope_config()

        headers = {
            "accept": "*/*",
            "authorization": f"Bearer {token}",
            "content-type": "application/json",
            "origin": INSCOPE_BASE_URL,
        }

        if cookie:
            headers["cookie"] = cookie

        # Generate unique IDs for this conversation
        interaction_id = str(uuid.uuid4())
        session_id = str(uuid.uuid4())
        user = config.get("user", "daoneill@redhat.com")

        payload = {
            "query": query,
            "stream": "true",
            "prevMsgs": [],
            "client": "convo",
            "interactionId": interaction_id,
            "sessionId": session_id,
            "user": user,
        }

        # Make request with streaming
        timeout = httpx.Timeout(
            connect=DEFAULT_CONNECT_TIMEOUT,
            read=timeout_secs,
            write=30.0,
            pool=10.0,
        )

        # InScope uses internal Red Hat certs - allow self-signed
        # This is safe because we're only connecting to inscope.corp.redhat.com
        async with httpx.AsyncClient(timeout=timeout, verify=False) as client:
            async with client.stream(
                "POST",
                url,
                headers=headers,
                json=payload,
            ) as response:
                if response.status_code == 401:
                    return json.dumps(
                        {
                            "success": False,
                            "error": "Authentication failed - token may be expired",
                            "hint": "Refresh your InScope token",
                        }
                    )

                if response.status_code != 200:
                    body = await response.aread()
                    return json.dumps(
                        {
                            "success": False,
                            "error": f"HTTP {response.status_code}",
                            "details": body.decode()[:500],
                        }
                    )

                # Parse streaming response
                full_text, search_metadata = await _stream_response(response)

        # Build result
        result: dict[str, Any] = {
            "success": True,
            "assistant": assistant_name,
            "assistant_id": assistant_id,
            "query": query,
            "response": full_text.strip(),
        }

        if include_sources and search_metadata:
            result["sources"] = [
                {
                    "title": m.get("metadata", {}).get("title", ""),
                    "url": m.get("metadata", {}).get("citation_url", ""),
                    "relevance": m.get("metadata", {}).get("relevance_score", 0),
                }
                for m in search_metadata[:5]  # Top 5 sources
            ]

        return json.dumps(result, indent=2)

    except httpx.TimeoutException:
        return json.dumps(
            {
                "success": False,
                "error": f"Request timed out after {timeout_secs}s",
                "hint": "Try increasing timeout_secs or simplify the query",
            }
        )
    except Exception as e:
        logger.exception("InScope query failed")
        return json.dumps(
            {
                "success": False,
                "error": str(e),
            }
        )


async def _inscope_list_assistants_impl() -> str:
    """Implementation of inscope_list_assistants tool."""
    assistants = []
    for aid, info in sorted(KNOWN_ASSISTANTS.items()):
        assistants.append(
            {
                "id": aid,
                "name": info["name"],
                "description": info["description"],
            }
        )

    aliases = {}
    for alias, aid in ASSISTANT_ALIASES.items():
        if aid not in aliases:
            aliases[aid] = []
        aliases[aid].append(alias)

    return json.dumps(
        {
            "success": True,
            "count": len(assistants),
            "assistants": assistants,
            "aliases": {
                KNOWN_ASSISTANTS[aid]["name"]: alias_list
                for aid, alias_list in aliases.items()
                if aid in KNOWN_ASSISTANTS
            },
        },
        indent=2,
    )


async def _inscope_auth_status_impl() -> str:
    """Implementation of inscope_auth_status tool."""
    token = await _get_auth_token()
    cookie = await _get_session_cookie()

    status = {
        "has_token": token is not None,
        "has_cookie": cookie is not None,
        "authenticated": token is not None,
    }

    if token:
        # Try to decode JWT to get expiry (without verification)
        try:
            import jwt

            # Decode without verification to read claims
            claims = jwt.decode(token, options={"verify_signature": False})
            exp = claims.get("exp")
            if exp:
                status["token_expires_at"] = exp
                status["token_expires_in_seconds"] = max(0, exp - int(time.time()))
                status["token_expired"] = exp < time.time()
            status["user"] = claims.get("sub", "").replace("user:default/", "")
        except Exception as e:
            status["token_decode_error"] = str(e)

    config = _get_inscope_config()
    status["config"] = {
        "token_file": config.get("token_file", "~/.cache/inscope/token"),
        "cookie_file": config.get("cookie_file", "~/.cache/inscope/cookies"),
        "user": config.get("user", "not configured"),
    }

    return json.dumps(status, indent=2)


async def _inscope_ask_impl(
    query: str,
    timeout_secs: int = DEFAULT_TOTAL_TIMEOUT,
    include_sources: bool = True,
) -> str:
    """Implementation of inscope_ask tool - auto-selects assistant."""
    # Auto-select assistant based on query
    assistant_id = _auto_select_assistant(query)
    assistant_info = KNOWN_ASSISTANTS.get(assistant_id, {})

    logger.info(f"Auto-selected assistant: {assistant_info.get('name', assistant_id)} for query: {query[:50]}...")

    # Delegate to inscope_query
    return await _inscope_query_impl(query, assistant_id, timeout_secs, include_sources)


async def _inscope_save_token_impl(token: str, cookie: str = "") -> str:
    """Implementation of inscope_save_token tool."""
    config = _get_inscope_config()

    # Save token
    token_file = config.get("token_file", "~/.cache/inscope/token")
    token_path = Path(token_file).expanduser()
    token_path.parent.mkdir(parents=True, exist_ok=True)

    # Try to get expiry from token
    expires_at = int(time.time()) + 3600  # Default 1 hour
    try:
        import jwt

        claims = jwt.decode(token, options={"verify_signature": False})
        if "exp" in claims:
            expires_at = claims["exp"]
    except Exception:
        pass

    token_data = {
        "token": token,
        "expires_at": expires_at,
        "saved_at": int(time.time()),
    }
    token_path.write_text(json.dumps(token_data, indent=2))

    # Save cookie if provided
    if cookie:
        cookie_file = config.get("cookie_file", "~/.cache/inscope/cookies")
        cookie_path = Path(cookie_file).expanduser()
        cookie_path.parent.mkdir(parents=True, exist_ok=True)
        cookie_path.write_text(cookie)

    return json.dumps(
        {
            "success": True,
            "token_saved": str(token_path),
            "cookie_saved": (
                str(Path(config.get("cookie_file", "~/.cache/inscope/cookies")).expanduser()) if cookie else None
            ),
            "expires_at": expires_at,
        },
        indent=2,
    )


def register_tools(server: FastMCP) -> int:
    """Register InScope tools with the MCP server."""
    registry = ToolRegistry(server)

    @auto_heal()
    @registry.tool()
    async def inscope_ask(
        query: str,
        timeout_secs: int = DEFAULT_TOTAL_TIMEOUT,
        include_sources: bool = True,
    ) -> str:
        """Ask InScope a question - auto-selects the best assistant.

        This is the recommended way to query InScope. It automatically
        selects the most appropriate assistant based on keywords in your query.

        For example:
        - "How do I configure RDS?" -> App Interface assistant
        - "What is a ClowdApp?" -> Clowder assistant
        - "How do I set up a Konflux pipeline?" -> Konflux assistant

        Args:
            query: The question to ask
            timeout_secs: Request timeout (default 180s)
            include_sources: Include source document references

        Returns:
            JSON with assistant response and sources.

        Examples:
            inscope_ask("How do I configure RDS for my ClowdApp?")
            inscope_ask("What is the Konflux release process?")
            inscope_ask("How do I set up Prometheus alerts?")
        """
        return await _inscope_ask_impl(query, timeout_secs, include_sources)

    @auto_heal()
    @registry.tool()
    async def inscope_query(
        query: str,
        assistant: str = "app-interface",
        timeout_secs: int = DEFAULT_TOTAL_TIMEOUT,
        include_sources: bool = True,
    ) -> str:
        """Query an InScope AI assistant for domain-specific information.

        InScope provides AI assistants trained on Red Hat internal documentation.
        Use this to get authoritative answers about App Interface, Clowder,
        Konflux, and other Red Hat services.

        Args:
            query: The question to ask the assistant
            assistant: Assistant name/alias (e.g., 'app-interface', 'clowder', 'konflux')
                      or ID (1-20). Use inscope_list_assistants() to see all options.
            timeout_secs: Request timeout (default 180s - AI responses can be slow)
            include_sources: Include source document references in response

        Returns:
            JSON with assistant response and optional source citations.

        Examples:
            inscope_query("How do I configure RDS for a ClowdApp?", "app-interface")
            inscope_query("What is the Konflux release process?", "konflux")
            inscope_query("How do I set up monitoring alerts?", "all")
        """
        return await _inscope_query_impl(query, assistant, timeout_secs, include_sources)

    @auto_heal()
    @registry.tool()
    async def inscope_list_assistants() -> str:
        """List available InScope AI assistants.

        Shows all assistants with their IDs, names, descriptions, and aliases.
        Use the aliases for convenient querying (e.g., 'clowder' instead of ID 4).

        Returns:
            JSON with list of assistants and their aliases.
        """
        return await _inscope_list_assistants_impl()

    @auto_heal()
    @registry.tool()
    async def inscope_auth_status() -> str:
        """Check InScope authentication status.

        Shows whether you have valid credentials configured and when they expire.
        If not authenticated, provides hints on how to set up credentials.

        Returns:
            JSON with authentication status and configuration.
        """
        return await _inscope_auth_status_impl()

    @auto_heal()
    @registry.tool()
    async def inscope_save_token(
        token: str,
        cookie: str = "",
    ) -> str:
        """Save InScope authentication credentials.

        Save a Bearer token (and optionally session cookie) extracted from
        browser developer tools. The token is a JWT from the Authorization header.

        To get credentials:
        1. Open https://inscope.corp.redhat.com/convo in Chrome
        2. Log in via OIDC
        3. Open DevTools > Network
        4. Ask a question to any assistant
        5. Find the /chat request
        6. Copy the 'authorization: Bearer ...' header value (without 'Bearer ')
        7. Optionally copy the 'cookie' header value

        Args:
            token: The JWT token from the Authorization header
            cookie: Optional session cookie string

        Returns:
            JSON confirming credentials were saved.
        """
        return await _inscope_save_token_impl(token, cookie)

    @auto_heal()
    @registry.tool()
    async def inscope_auto_login(
        headless: bool = True,
    ) -> str:
        """Automatically login to InScope using browser automation.

        Uses the same Chrome profile as rhtoken to leverage existing
        Red Hat SSO sessions. Extracts and saves the JWT token automatically.

        Args:
            headless: Run browser in headless mode (default True)

        Returns:
            JSON with login status and token expiry info.
        """
        return await _inscope_auto_login_impl(headless)

    return registry.count


async def _inscope_auto_login_impl(headless: bool = True) -> str:
    """Implementation of inscope_auto_login tool using aa_sso module."""
    try:
        from tool_modules.aa_sso.src.tools_basic import SSOAuthenticator

        logger.info(f"Starting InScope auto-login via aa_sso (headless={headless})")

        auth = SSOAuthenticator(headless=headless)
        result = await auth.authenticate("inscope")

        if result.success:
            response = {
                "success": True,
                "message": "InScope authentication successful",
                "final_url": result.final_url,
            }

            if result.jwt_token:
                response["token_saved"] = str(Path.home() / ".cache" / "inscope" / "token")
                if result.jwt_expires_at:
                    response["expires_at"] = result.jwt_expires_at
                    response["expires_in_seconds"] = max(0, result.jwt_expires_at - int(time.time()))

            if result.cookies:
                response["cookies"] = list(result.cookies.keys())

            return json.dumps(response, indent=2)
        else:
            return json.dumps(
                {
                    "success": False,
                    "error": result.error or "Authentication failed",
                    "screenshot": result.screenshot_path,
                },
                indent=2,
            )

    except ImportError as e:
        logger.error(f"aa_sso module not available: {e}")
        return json.dumps(
            {
                "success": False,
                "error": f"aa_sso module not available: {e}",
                "hint": "Install playwright: pip install playwright && playwright install chromium",
            }
        )
    except Exception as e:
        logger.exception("InScope auto-login failed")
        return json.dumps(
            {
                "success": False,
                "error": str(e),
            }
        )
