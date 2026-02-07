"""Tests for scripts/common/auto_heal.py"""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from scripts.common.auto_heal import (
    _guess_cluster,
    build_auto_heal_block,
    detect_failure,
    get_quick_fix,
    log_failure,
    should_retry,
)

# ---------------------------------------------------------------------------
# detect_failure
# ---------------------------------------------------------------------------


class TestDetectFailure:
    def test_empty_result_is_not_failed(self):
        assert detect_failure("") == {"failed": False}

    def test_none_result_is_not_failed(self):
        assert detect_failure(None) == {"failed": False}

    def test_normal_output_is_not_failed(self):
        assert detect_failure("All pods running. Status OK.") == {"failed": False}

    # Auth patterns
    def test_auth_401(self):
        r = detect_failure("error: Unauthorized 401 from server", "bonfire_deploy")
        assert r["failed"] is True
        assert r["error_type"] == "auth"
        assert r["can_auto_fix"] is True
        assert r["fix_action"] == "kube_login"

    def test_auth_forbidden(self):
        r = detect_failure("Error: Forbidden access to namespace", "kube_tool")
        assert r["failed"] is True
        assert r["error_type"] == "auth"

    def test_auth_token_expired(self):
        r = detect_failure("Error - token expired for cluster")
        assert r["error_type"] == "auth"

    def test_auth_permission_denied(self):
        r = detect_failure("Error: permission denied for resource")
        assert r["error_type"] == "auth"

    # Network patterns
    def test_network_no_route(self):
        r = detect_failure("Error: no route to host 10.0.0.1")
        assert r["failed"] is True
        assert r["error_type"] == "network"
        assert r["can_auto_fix"] is True
        assert r["fix_action"] == "vpn_connect"

    def test_network_connection_refused(self):
        r = detect_failure("Error: connection refused on port 443")
        assert r["error_type"] == "network"

    def test_network_timeout(self):
        r = detect_failure("Error: request timeout after 30s")
        assert r["error_type"] == "network"

    def test_network_dial_tcp(self):
        r = detect_failure("Error: dial tcp 10.0.0.1:443: i/o timeout")
        assert r["error_type"] == "network"

    def test_network_connection_reset(self):
        r = detect_failure("failed: connection reset by peer")
        assert r["error_type"] == "network"

    def test_network_eof(self):
        r = detect_failure("Error: unexpected eof")
        assert r["error_type"] == "network"

    # Registry patterns
    def test_registry_manifest_unknown(self):
        r = detect_failure("Error: manifest unknown for image")
        assert r["error_type"] == "registry"
        assert r["can_auto_fix"] is False

    def test_registry_pull_denied(self):
        r = detect_failure("Error: pull access denied for quay.io/repo")
        assert r["error_type"] == "registry"

    def test_registry_image_not_found(self):
        r = detect_failure("Error: image not found quay.io/repo:tag")
        assert r["error_type"] == "registry"

    # TTY patterns
    def test_tty_not_a_tty(self):
        r = detect_failure("Error: output is not a tty", "oc_tool")
        assert r["error_type"] == "tty"
        assert r["can_auto_fix"] is False

    def test_tty_not_a_terminal(self):
        r = detect_failure("Error: not a terminal")
        assert r["error_type"] == "tty"

    # Unknown error
    def test_unknown_error(self):
        r = detect_failure("Error: something completely different happened")
        assert r["failed"] is True
        assert r["error_type"] == "unknown"
        assert r["can_auto_fix"] is False

    # Error detection heuristics
    def test_error_indicator_emoji(self):
        r = detect_failure("\u274c Deploy failed: unknown issue")
        assert r["failed"] is True

    def test_error_starts_with_error(self):
        r = detect_failure("error: something broke")
        assert r["failed"] is True

    def test_failed_in_first_100_chars(self):
        r = detect_failure("Deploy failed with unknown error " + "x" * 200)
        assert r["failed"] is True

    def test_exception_in_first_100_chars(self):
        r = detect_failure("An exception occurred during processing")
        assert r["failed"] is True

    def test_failed_later_in_text_not_detected(self):
        # "failed" beyond first 100 chars is not an error indicator
        r = detect_failure("x" * 101 + "failed later")
        assert r == {"failed": False}

    def test_error_text_truncated_to_300_chars(self):
        long_msg = "Error: " + "a" * 500
        r = detect_failure(long_msg)
        assert len(r["error_text"]) == 300


# ---------------------------------------------------------------------------
# _guess_cluster
# ---------------------------------------------------------------------------


class TestGuessCluster:
    def test_bonfire_tool(self):
        assert _guess_cluster("bonfire_deploy", "") == "ephemeral"

    def test_ephemeral_in_result(self):
        assert _guess_cluster("some_tool", "Error in ephemeral cluster") == "ephemeral"

    def test_konflux_tool(self):
        assert _guess_cluster("konflux_build", "") == "konflux"

    def test_prod_in_result(self):
        assert (
            _guess_cluster("some_tool", "Error in production environment")
            == "production"
        )

    def test_default_stage(self):
        assert _guess_cluster("some_tool", "some error") == "stage"


# ---------------------------------------------------------------------------
# get_quick_fix
# ---------------------------------------------------------------------------


class TestGetQuickFix:
    def test_auth_fix(self):
        failure = {
            "can_auto_fix": True,
            "fix_action": "kube_login",
            "fix_args": {"cluster": "ephemeral"},
        }
        result = get_quick_fix(failure)
        assert result == ("kube_login", {"cluster": "ephemeral"})

    def test_vpn_fix(self):
        failure = {
            "can_auto_fix": True,
            "fix_action": "vpn_connect",
            "fix_args": {},
        }
        result = get_quick_fix(failure)
        assert result == ("vpn_connect", {})

    def test_no_fix_when_not_auto_fixable(self):
        failure = {"can_auto_fix": False, "fix_action": "debug_tool"}
        assert get_quick_fix(failure) is None

    def test_no_fix_when_empty_dict(self):
        assert get_quick_fix({}) is None

    def test_auth_fix_defaults_cluster_to_stage(self):
        failure = {
            "can_auto_fix": True,
            "fix_action": "kube_login",
            "fix_args": {},
        }
        result = get_quick_fix(failure)
        assert result == ("kube_login", {"cluster": "stage"})

    def test_unknown_action_returns_none(self):
        failure = {
            "can_auto_fix": True,
            "fix_action": "some_unknown",
            "fix_args": {},
        }
        assert get_quick_fix(failure) is None


# ---------------------------------------------------------------------------
# should_retry
# ---------------------------------------------------------------------------


class TestShouldRetry:
    def test_auth_first_retry(self):
        failure = {"can_auto_fix": True, "error_type": "auth"}
        assert should_retry(failure, retry_count=0) is True

    def test_network_first_retry(self):
        failure = {"can_auto_fix": True, "error_type": "network"}
        assert should_retry(failure, retry_count=0) is True

    def test_max_retries_exceeded(self):
        failure = {"can_auto_fix": True, "error_type": "auth"}
        assert should_retry(failure, retry_count=2, max_retries=2) is False

    def test_not_auto_fixable(self):
        failure = {"can_auto_fix": False, "error_type": "auth"}
        assert should_retry(failure) is False

    def test_registry_not_retried(self):
        failure = {"can_auto_fix": False, "error_type": "registry"}
        assert should_retry(failure) is False

    def test_tty_not_retried(self):
        failure = {"can_auto_fix": False, "error_type": "tty"}
        assert should_retry(failure) is False

    def test_unknown_not_retried(self):
        failure = {"can_auto_fix": False, "error_type": "unknown"}
        assert should_retry(failure) is False

    def test_custom_max_retries(self):
        failure = {"can_auto_fix": True, "error_type": "auth"}
        assert should_retry(failure, retry_count=4, max_retries=5) is True
        assert should_retry(failure, retry_count=5, max_retries=5) is False


# ---------------------------------------------------------------------------
# log_failure
# ---------------------------------------------------------------------------


class TestLogFailure:
    def test_basic_log_entry(self):
        entry = log_failure("my_tool", "some error text")
        assert entry["tool"] == "my_tool"
        assert entry["error"] == "some error text"
        assert entry["auto_fixed"] is False
        assert entry["skill"] == ""
        # timestamp should parse as ISO
        datetime.fromisoformat(entry["timestamp"])

    def test_with_skill_and_fixed(self):
        entry = log_failure("tool", "err", skill_name="deploy_skill", fixed=True)
        assert entry["skill"] == "deploy_skill"
        assert entry["auto_fixed"] is True

    def test_error_truncated_to_100(self):
        entry = log_failure("tool", "e" * 200)
        assert len(entry["error"]) == 100

    def test_with_memory_helper(self):
        helper = MagicMock()
        entry = log_failure("tool", "err", memory_helper=helper, fixed=True)
        helper.append_to_list.assert_called_once()
        # Two increment calls: total_failures + auto_fixed
        assert helper.increment_field.call_count == 2

    def test_with_memory_helper_not_fixed(self):
        helper = MagicMock()
        log_failure("tool", "err", memory_helper=helper, fixed=False)
        calls = [c[0] for c in helper.increment_field.call_args_list]
        assert ("learned/tool_failures", "stats.total_failures") in calls
        assert ("learned/tool_failures", "stats.manual_required") in calls

    def test_memory_helper_exception_is_swallowed(self):
        helper = MagicMock()
        helper.append_to_list.side_effect = RuntimeError("broken")
        # Should not raise
        entry = log_failure("tool", "err", memory_helper=helper)
        assert entry["tool"] == "tool"


# ---------------------------------------------------------------------------
# build_auto_heal_block
# ---------------------------------------------------------------------------


class TestBuildAutoHealBlock:
    def test_produces_yaml_string(self):
        result = build_auto_heal_block("reserve_ns", "bonfire_reserve", "ns_result")
        assert isinstance(result, str)

    def test_contains_step_names(self):
        result = build_auto_heal_block("reserve_ns", "bonfire_reserve", "ns_result")
        assert "detect_failure_reserve_ns" in result
        assert "quick_fix_auth_reserve_ns" in result
        assert "quick_fix_vpn_reserve_ns" in result
        assert "log_failure_reserve_ns" in result

    def test_contains_tool_name(self):
        result = build_auto_heal_block("step", "my_tool", "out")
        assert "my_tool" in result

    def test_contains_output_var(self):
        result = build_auto_heal_block("step", "my_tool", "my_output")
        assert "my_output" in result

    def test_explicit_cluster_hint(self):
        result = build_auto_heal_block("step", "tool", "out", cluster_hint="ephemeral")
        assert 'cluster: "ephemeral"' in result

    def test_auto_cluster_defaults_to_stage(self):
        result = build_auto_heal_block("step", "tool", "out", cluster_hint="auto")
        assert 'cluster: "stage"' in result
