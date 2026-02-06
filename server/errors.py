"""Standardized error handling for MCP tools.

This module provides consistent error formatting and handling across all tool modules.
Use these helpers instead of ad-hoc error string formatting.

Usage:
    from server.errors import tool_error, tool_success, ToolResult

    # Simple error
    return tool_error("File not found", code="NOT_FOUND")

    # Error with context
    return tool_error("Failed to deploy", context={"namespace": ns, "error": str(e)})

    # Success with data
    return tool_success("Deployment complete", data={"pod_count": 3})

    # Check result type
    if isinstance(result, ToolResult):
        if result.success:
            print(result.data)
        else:
            print(result.error)
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolResult:
    """Structured result from a tool operation.

    Attributes:
        success: Whether the operation succeeded
        message: Human-readable message
        error: Error details if failed
        data: Result data if successful
        code: Error/status code for programmatic handling
        context: Additional context (namespace, file, etc.)
    """

    success: bool
    message: str
    error: str | None = None
    data: dict[str, Any] | None = None
    code: str | None = None
    context: dict[str, Any] = field(default_factory=dict)

    def to_string(self) -> str:
        """Convert to formatted string for MCP response."""
        if self.success:
            prefix = "✅"
        else:
            prefix = "❌"

        parts = [f"{prefix} {self.message}"]

        if self.error:
            parts.append(f"\n**Error:** {self.error}")

        if self.code:
            parts.append(f"\n**Code:** {self.code}")

        if self.context:
            context_str = ", ".join(f"{k}={v}" for k, v in self.context.items())
            parts.append(f"\n**Context:** {context_str}")

        if self.data:
            # Format data as key-value pairs
            for key, value in self.data.items():
                if isinstance(value, (list, dict)):
                    parts.append(f"\n**{key}:** ```\n{value}\n```")
                else:
                    parts.append(f"\n**{key}:** {value}")

        return "".join(parts)


def tool_error(
    message: str,
    error: str | None = None,
    code: str | None = None,
    context: dict[str, Any] | None = None,
    hint: str | None = None,
) -> str:
    """Create a standardized error response string.

    Args:
        message: Main error message (shown prominently)
        error: Detailed error text (e.g., exception message)
        code: Error code for programmatic handling (e.g., "NOT_FOUND", "AUTH_FAILED")
        context: Additional context dict (e.g., {"file": path, "line": 42})
        hint: Helpful hint for resolving the error

    Returns:
        Formatted error string with ❌ prefix

    Examples:
        >>> tool_error("File not found", code="NOT_FOUND")
        '❌ File not found'

        >>> tool_error("Deploy failed", error="Timeout", context={"namespace": "ns-123"})
        '❌ Deploy failed\\n**Error:** Timeout\\n**Context:** namespace=ns-123'
    """
    parts = [f"❌ {message}"]

    if error:
        parts.append(f"\n**Error:** {error}")

    if code:
        parts.append(f" [{code}]")

    if context:
        context_str = ", ".join(f"{k}={v}" for k, v in context.items())
        parts.append(f"\n**Context:** {context_str}")

    if hint:
        parts.append(f"\n💡 **Hint:** {hint}")

    return "".join(parts)


def tool_success(
    message: str,
    data: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
) -> str:
    """Create a standardized success response string.

    Args:
        message: Main success message
        data: Result data to include
        context: Additional context dict

    Returns:
        Formatted success string with ✅ prefix

    Examples:
        >>> tool_success("Deployment complete")
        '✅ Deployment complete'

        >>> tool_success("Created namespace", data={"name": "ns-123", "ttl": "4h"})
        '✅ Created namespace\\n**name:** ns-123\\n**ttl:** 4h'
    """
    parts = [f"✅ {message}"]

    if context:
        context_str = ", ".join(f"{k}={v}" for k, v in context.items())
        parts.append(f"\n**Context:** {context_str}")

    if data:
        for key, value in data.items():
            if isinstance(value, (list, dict)):
                import json

                formatted = json.dumps(value, indent=2)
                parts.append(f"\n**{key}:**\n```\n{formatted}\n```")
            else:
                parts.append(f"\n**{key}:** {value}")

    return "".join(parts)


def tool_warning(
    message: str,
    details: str | None = None,
    context: dict[str, Any] | None = None,
) -> str:
    """Create a standardized warning response string.

    Args:
        message: Main warning message
        details: Additional details
        context: Additional context dict

    Returns:
        Formatted warning string with ⚠️ prefix
    """
    parts = [f"⚠️ {message}"]

    if details:
        parts.append(f"\n{details}")

    if context:
        context_str = ", ".join(f"{k}={v}" for k, v in context.items())
        parts.append(f"\n**Context:** {context_str}")

    return "".join(parts)


def tool_info(
    message: str,
    data: dict[str, Any] | None = None,
) -> str:
    """Create a standardized info response string.

    Args:
        message: Main info message
        data: Additional data to include

    Returns:
        Formatted info string with ℹ️ prefix
    """
    parts = [f"ℹ️ {message}"]

    if data:
        for key, value in data.items():
            parts.append(f"\n**{key}:** {value}")

    return "".join(parts)


# Common error codes for consistency
class ErrorCodes:
    """Standard error codes for tool responses."""

    # Authentication/Authorization
    AUTH_FAILED = "AUTH_FAILED"
    AUTH_EXPIRED = "AUTH_EXPIRED"
    PERMISSION_DENIED = "PERMISSION_DENIED"

    # Resource errors
    NOT_FOUND = "NOT_FOUND"
    ALREADY_EXISTS = "ALREADY_EXISTS"
    CONFLICT = "CONFLICT"

    # Operation errors
    TIMEOUT = "TIMEOUT"
    RATE_LIMITED = "RATE_LIMITED"
    INVALID_INPUT = "INVALID_INPUT"
    INVALID_STATE = "INVALID_STATE"

    # System errors
    INTERNAL_ERROR = "INTERNAL_ERROR"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    DEPENDENCY_FAILED = "DEPENDENCY_FAILED"

    # Network errors
    CONNECTION_FAILED = "CONNECTION_FAILED"
    DNS_FAILED = "DNS_FAILED"
