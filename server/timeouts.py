"""Centralized timeout configuration and type definitions.

Use these constants instead of hardcoded values to ensure consistency
and make it easy to tune timeouts across the project.
"""

from typing import Literal

# Type alias for valid environment names
Environment = Literal["stage", "prod", "ephemeral", "konflux"]

# Default environment when not specified
DEFAULT_ENVIRONMENT: Environment = "stage"

# Set of all valid environments
VALID_ENVIRONMENTS = {"stage", "prod", "ephemeral", "konflux"}


class Timeouts:
    """Standard timeout values in seconds.

    Usage:
        from server.timeouts import Timeouts

        success, output = await run_cmd(cmd, timeout=Timeouts.DEFAULT)
    """

    # Instant operations (< 5 seconds expected)
    INSTANT = 2  # UI operations (wmctrl, paplay)
    QUICK = 5  # Quick subprocess calls, simple queries
    SHORT = 10  # Short DB queries, config reads

    # Quick operations (< 1 minute expected)
    FAST = 30  # Simple commands, API calls
    DEFAULT = 60  # Standard git/CLI operations

    # Medium operations (1-5 minutes expected)
    LINT = 300  # Linting, type checking
    BUILD = 600  # Building, bundling

    # Long operations (5+ minutes expected)
    DEPLOY = 900  # Deployments, namespace reservation
    TEST_SUITE = 1200  # Full test runs

    # Network-dependent operations
    HTTP_REQUEST = 30  # HTTP API calls
    CLUSTER_LOGIN = 120  # Kubernetes login with potential MFA

    # Bonfire-specific (often needs more time)
    BONFIRE_RESERVE = 660  # Namespace reservation
    BONFIRE_DEPLOY = 960  # Full deploy
    BONFIRE_IQE = 900  # IQE test run

    # Database operations
    DB_CONNECT = 10  # SQLite connection timeout
    DB_QUERY = 30  # Standard database query

    # Process management
    PROCESS_WAIT = 60  # Waiting for subprocess to complete


class OutputLimits:
    """Standard output truncation limits in characters.

    Usage:
        from server.timeouts import OutputLimits
        from server.utils import truncate_output

        truncated = truncate_output(output, max_length=OutputLimits.STANDARD)
    """

    SHORT = 1000  # Error messages, short snippets
    MEDIUM = 2000  # Command output, formatted results
    STANDARD = 5000  # Default for most tools
    LONG = 10000  # Pipeline logs, kubectl describe
    FULL = 15000  # Complete output when needed
    EXTENDED = 20000  # Very long logs (konflux builds)


# Duration parsing for Prometheus/Alertmanager queries
DURATION_MINUTES = {
    "s": 1 / 60,  # seconds to minutes
    "m": 1,  # minutes
    "h": 60,  # hours to minutes
    "d": 1440,  # days to minutes
    "w": 10080,  # weeks to minutes
}


def parse_duration_to_minutes(duration_str: str) -> int:
    """Parse duration string like '30m', '2h', '1d' to minutes.

    Args:
        duration_str: Duration string (e.g., "30m", "2h", "1d", "1w")

    Returns:
        Duration in minutes

    Examples:
        >>> parse_duration_to_minutes("30m")
        30
        >>> parse_duration_to_minutes("2h")
        120
        >>> parse_duration_to_minutes("1d")
        1440
    """
    if not duration_str:
        return 60  # Default 1 hour

    # Handle pure numbers as minutes
    if duration_str.isdigit():
        return int(duration_str)

    unit = duration_str[-1].lower()
    try:
        value = int(duration_str[:-1])
    except ValueError:
        return 60  # Default on parse error

    return int(value * DURATION_MINUTES.get(unit, 1))
