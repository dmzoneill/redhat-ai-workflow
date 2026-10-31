"""Red Hat SSO data model: flow/outcome enums, strategies, results and HTTP SAML configs."""

import asyncio
import importlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import NamedTuple

import httpx
from playwright.async_api import Error


def _optional_jwt_errors() -> tuple[type[Exception], ...]:
    """Return PyJWT's base error when PyJWT is installed."""
    errors: list[type[Exception]] = []
    try:
        errors.append(importlib.import_module("jwt").PyJWTError)
    except ImportError:
        pass  # PyJWT is optional; without it there is no JWT error type to catch
    return tuple(errors)


# Failures expected from browser automation, HTTP calls and local I/O.
_AUTOMATION_ERRORS: tuple[type[Exception], ...] = (
    Error,  # playwright.async_api.Error, base of Playwright's TimeoutError
    httpx.HTTPError,
    OSError,
    RuntimeError,
    ValueError,
    TypeError,
    KeyError,
    AttributeError,
    asyncio.TimeoutError,
)
# A response body that is not JSON, or JSON that is not an object.
_JSON_ERRORS: tuple[type[Exception], ...] = (ValueError, AttributeError, TypeError)
# Reading and decoding a JWT: cache unreadable, PyJWT missing or token malformed.
_JWT_ERRORS: tuple[type[Exception], ...] = (
    OSError,
    ImportError,
    ValueError,
    AttributeError,
    TypeError,
    *_optional_jwt_errors(),
)


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


class SSOStrategy(NamedTuple):
    """Configuration for authenticating to a specific site (immutable; use ``_replace`` to vary it)."""

    # Required
    name: str  # Identifier for this strategy (e.g., "reward_zone", "inscope")
    target_url: str  # URL to navigate to (may redirect to SSO)

    # Flow configuration
    flow_type: FlowType = FlowType.INLINE_REDIRECT

    # Success detection
    success_url_pattern: str = ""  # URL must contain this after auth
    success_element: str = ""  # Element that indicates success (CSS selector)
    sso_url_patterns: Sequence[str] = ("auth.redhat.com", "sso.redhat.com")

    # Outcome configuration
    outcome_type: OutcomeType = OutcomeType.REDIRECT_ONLY

    # For JWT_TOKEN outcome
    jwt_storage_keys: Sequence[str] = ("token", "access_token", "backstage-auth")
    jwt_cache_path: str = ""  # Where to save JWT (e.g., ~/.cache/inscope/token)

    # For SESSION_COOKIE outcome
    cookie_names: Sequence[str] = ()  # e.g., ["connect.sid"]
    cookie_cache_path: str = ""  # Where to save cookies

    # Custom selectors (optional)
    selectors: SSOSelectors = SSOSelectors()

    # Timeouts (milliseconds)
    navigation_timeout: int = 60000
    element_timeout: int = 15000
    redirect_timeout: int = 60000

    # Popup-specific (for POPUP flow)
    popup_trigger_selector: str = ""  # Button that opens popup
    popup_close_timeout: int = 30000  # Max wait for popup to close

    # Callback URL handling (for sites with intermediate redirects)
    callback_url_patterns: Sequence[str] = ()  # e.g., ["setsession", "signin"]
    final_redirect_url: str = ""  # Force navigate here if callback doesn't redirect


class SSOResult(NamedTuple):
    """Result of SSO authentication attempt (immutable; use ``_replace`` to add outcome data)."""

    success: bool
    strategy_name: str
    flow_type: FlowType
    outcome_type: OutcomeType

    # Outcome data
    jwt_token: str | None = None
    jwt_expires_at: int | None = None
    cookies: Mapping[str, str] = MappingProxyType({})
    final_url: str = ""

    # Error info
    error: str | None = None
    screenshot_path: str | None = None

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
        target_url=("https://auth.redhat.com/auth/realms/EmployeeIDP/protocol/saml/clients/concursolutions"),
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


# ==================== HTTP SAML Configuration ====================


@dataclass
class HTTPSAMLConfig:
    """Configuration for HTTP-based SAML authentication flows.

    Defines the URL paths used during the SAML redirect auth flow
    for sites that can be authenticated via pure HTTP (no browser).
    """

    init_url: str  # e.g., "/api/v1/Subprograms/init?subprogramId=102"
    saml_login_path: str  # e.g., "/saml/login"
    saml_acs_path: str  # e.g., "/saml/acs"
    sso_login_path: str  # e.g., "/api/v1/Sso/login"
    csrf_field: str = "_csrf"  # field name in JSON body


HTTP_SAML_CONFIGS: dict[str, HTTPSAMLConfig] = {
    "reward_zone": HTTPSAMLConfig(
        init_url="/api/v1/Subprograms/init?subprogramId=102",
        saml_login_path="/saml/login",
        saml_acs_path="/saml/acs",
        sso_login_path="/api/v1/Sso/login",
    ),
    # concur can be added later with its own config
}
