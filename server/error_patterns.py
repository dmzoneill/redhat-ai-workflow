"""Canonical error pattern lists for failure detection.

These patterns are used across the server package for detecting
authentication and network errors. All modules should import from
here instead of defining their own copies.

Used by:
- auto_heal_decorator.py (Layer 3 auto-heal)
- usage_pattern_classifier.py (Layer 5 classification)
- debuggable.py (remediation hints)
- utils.py (is_auth_error helper)
"""

# Authentication / authorization failure patterns
AUTH_PATTERNS: list[str] = [
    "unauthorized",
    "401",
    "forbidden",
    "403",
    "token expired",
    "authentication required",
    "not authorized",
    "permission denied",
    "the server has asked for the client to provide credentials",
    "provide credentials",
    # Additional patterns used by utils.is_auth_error
    "token has expired",
    "login required",
    "must be logged in",
    "no valid authentication",
    "403 forbidden",
]

# Network / connectivity failure patterns
NETWORK_PATTERNS: list[str] = [
    "no route to host",
    "connection refused",
    "network unreachable",
    "timeout",
    "dial tcp",
    "connection reset",
    "eof",
    "cannot connect",
]

# VPN-specific connectivity patterns (superset of NETWORK_PATTERNS
# focused on VPN-related failures)
VPN_PATTERNS: list[str] = [
    "no route to host",
    "network is unreachable",
    "connection timed out",
    "could not resolve host",
    "name or service not known",
    "connection refused",
    "failed to connect",
    "enetunreach",
]

# Kubernetes authentication patterns
K8S_AUTH_PATTERNS: list[str] = [
    "unauthorized",
    "token expired",
    "token is expired",
    "the server has asked for the client to provide credentials",
    "you must be logged in to the server",
    "forbidden",
    "error: you must be logged in",
    "no valid credentials found",
]

# GitLab authentication patterns
GITLAB_AUTH_PATTERNS: list[str] = [
    "401 unauthorized",
    "403 forbidden",
    "authentication required",
    "invalid token",
]

# Slack authentication patterns
SLACK_AUTH_PATTERNS: list[str] = [
    "invalid_auth",
    "token_expired",
    "not_authed",
    "xoxc",
]
