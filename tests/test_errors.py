"""Tests for server/errors.py - Standardized error handling for MCP tools."""

import pytest

from server.errors import (
    ErrorCodes,
    ToolResult,
    tool_error,
    tool_info,
    tool_success,
    tool_warning,
)

# ==================== ToolResult dataclass ====================


class TestToolResult:
    """Tests for the ToolResult dataclass."""

    def test_default_fields(self):
        r = ToolResult(success=True, message="OK")
        assert r.success is True
        assert r.message == "OK"
        assert r.error is None
        assert r.data is None
        assert r.code is None
        assert r.context == {}

    def test_success_to_string_simple(self):
        r = ToolResult(success=True, message="Done")
        s = r.to_string()
        assert s.startswith("\u2705")
        assert "Done" in s

    def test_failure_to_string_simple(self):
        r = ToolResult(success=False, message="Failed")
        s = r.to_string()
        assert s.startswith("\u274c")
        assert "Failed" in s

    def test_to_string_with_error(self):
        r = ToolResult(success=False, message="Oops", error="Timeout")
        s = r.to_string()
        assert "**Error:** Timeout" in s

    def test_to_string_with_code(self):
        r = ToolResult(success=False, message="Oops", code="NOT_FOUND")
        s = r.to_string()
        assert "**Code:** NOT_FOUND" in s

    def test_to_string_with_context(self):
        r = ToolResult(success=True, message="OK", context={"ns": "prod", "pod": "web"})
        s = r.to_string()
        assert "**Context:**" in s
        assert "ns=prod" in s
        assert "pod=web" in s

    def test_to_string_with_scalar_data(self):
        r = ToolResult(success=True, message="OK", data={"count": 5})
        s = r.to_string()
        assert "**count:** 5" in s

    def test_to_string_with_list_data(self):
        r = ToolResult(success=True, message="OK", data={"items": [1, 2, 3]})
        s = r.to_string()
        assert "**items:**" in s
        assert "```" in s

    def test_to_string_with_dict_data(self):
        r = ToolResult(success=True, message="OK", data={"info": {"a": 1}})
        s = r.to_string()
        assert "**info:**" in s
        assert "```" in s

    def test_to_string_all_fields(self):
        r = ToolResult(
            success=False,
            message="Deploy failed",
            error="Timeout",
            code="TIMEOUT",
            context={"namespace": "ns-123"},
            data={"pods": ["a", "b"]},
        )
        s = r.to_string()
        assert "\u274c" in s
        assert "Deploy failed" in s
        assert "**Error:** Timeout" in s
        assert "**Code:** TIMEOUT" in s
        assert "namespace=ns-123" in s
        assert "**pods:**" in s


# ==================== tool_error ====================


class TestToolError:
    def test_simple_error(self):
        s = tool_error("File not found")
        assert s == "\u274c File not found"

    def test_error_with_error_detail(self):
        s = tool_error("Deploy failed", error="Timeout")
        assert "\u274c Deploy failed" in s
        assert "**Error:** Timeout" in s

    def test_error_with_code(self):
        s = tool_error("Not found", code="NOT_FOUND")
        assert "[NOT_FOUND]" in s

    def test_error_with_context(self):
        s = tool_error("Fail", context={"namespace": "ns-123"})
        assert "**Context:** namespace=ns-123" in s

    def test_error_with_hint(self):
        s = tool_error("Auth failed", hint="Try kube_login()")
        assert "**Hint:** Try kube_login()" in s

    def test_error_all_params(self):
        s = tool_error(
            "Deploy failed",
            error="Connection refused",
            code="CONNECTION_FAILED",
            context={"host": "prod"},
            hint="Check VPN",
        )
        assert "\u274c Deploy failed" in s
        assert "Connection refused" in s
        assert "[CONNECTION_FAILED]" in s
        assert "host=prod" in s
        assert "Check VPN" in s


# ==================== tool_success ====================


class TestToolSuccess:
    def test_simple_success(self):
        s = tool_success("Deployment complete")
        assert s == "\u2705 Deployment complete"

    def test_success_with_context(self):
        s = tool_success("Done", context={"env": "stage"})
        assert "**Context:** env=stage" in s

    def test_success_with_scalar_data(self):
        s = tool_success("Created namespace", data={"name": "ns-123", "ttl": "4h"})
        assert "**name:** ns-123" in s
        assert "**ttl:** 4h" in s

    def test_success_with_list_data(self):
        s = tool_success("Found pods", data={"pods": ["a", "b"]})
        assert "**pods:**" in s
        assert "```" in s
        # json.dumps is used for list/dict
        assert '"a"' in s

    def test_success_with_dict_data(self):
        s = tool_success("Info", data={"config": {"key": "val"}})
        assert "```" in s
        assert '"key"' in s

    def test_success_with_context_and_data(self):
        s = tool_success("OK", context={"ns": "x"}, data={"count": 1})
        assert "ns=x" in s
        assert "**count:** 1" in s


# ==================== tool_warning ====================


class TestToolWarning:
    def test_simple_warning(self):
        s = tool_warning("Slow query")
        assert s.startswith("\u26a0\ufe0f")
        assert "Slow query" in s

    def test_warning_with_details(self):
        s = tool_warning("Slow", details="Took 30s")
        assert "Took 30s" in s

    def test_warning_with_context(self):
        s = tool_warning("Slow", context={"query": "SELECT *"})
        assert "query=SELECT *" in s

    def test_warning_all_params(self):
        s = tool_warning("Retry", details="3rd attempt", context={"job": "sync"})
        assert "Retry" in s
        assert "3rd attempt" in s
        assert "job=sync" in s


# ==================== tool_info ====================


class TestToolInfo:
    def test_simple_info(self):
        s = tool_info("Version 2.0")
        assert "\u2139\ufe0f" in s
        assert "Version 2.0" in s

    def test_info_with_data(self):
        s = tool_info("Status", data={"uptime": "2d", "mem": "512MB"})
        assert "**uptime:** 2d" in s
        assert "**mem:** 512MB" in s

    def test_info_no_data(self):
        s = tool_info("No extras")
        assert "No extras" in s


# ==================== ErrorCodes ====================


class TestErrorCodes:
    @pytest.mark.parametrize(
        "attr,expected",
        [
            # Auth codes
            ("AUTH_FAILED", "AUTH_FAILED"),
            ("AUTH_EXPIRED", "AUTH_EXPIRED"),
            ("PERMISSION_DENIED", "PERMISSION_DENIED"),
            # Resource codes
            ("NOT_FOUND", "NOT_FOUND"),
            ("ALREADY_EXISTS", "ALREADY_EXISTS"),
            ("CONFLICT", "CONFLICT"),
            # Operation codes
            ("TIMEOUT", "TIMEOUT"),
            ("RATE_LIMITED", "RATE_LIMITED"),
            ("INVALID_INPUT", "INVALID_INPUT"),
            ("INVALID_STATE", "INVALID_STATE"),
            # System codes
            ("INTERNAL_ERROR", "INTERNAL_ERROR"),
            ("SERVICE_UNAVAILABLE", "SERVICE_UNAVAILABLE"),
            ("DEPENDENCY_FAILED", "DEPENDENCY_FAILED"),
            # Network codes
            ("CONNECTION_FAILED", "CONNECTION_FAILED"),
            ("DNS_FAILED", "DNS_FAILED"),
        ],
    )
    def test_error_code_values(self, attr, expected):
        assert getattr(ErrorCodes, attr) == expected
