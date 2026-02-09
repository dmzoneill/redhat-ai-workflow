"""Tests for scripts/common/auto_heal.py"""

from datetime import datetime
from unittest.mock import MagicMock

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
    @pytest.mark.parametrize(
        "output",
        [
            pytest.param("", id="empty"),
            pytest.param(None, id="none"),
            pytest.param("All pods running. Status OK.", id="normal_output"),
        ],
    )
    def test_non_failure_returns_not_failed(self, output):
        assert detect_failure(output) == {"failed": False}

    def test_auth_401_with_full_info(self):
        r = detect_failure("error: Unauthorized 401 from server", "bonfire_deploy")
        assert r["failed"] is True
        assert r["error_type"] == "auth"
        assert r["can_auto_fix"] is True
        assert r["fix_action"] == "kube_login"

    @pytest.mark.parametrize(
        "output",
        [
            pytest.param("Error: Forbidden access to namespace", id="forbidden"),
            pytest.param("Error - token expired for cluster", id="token_expired"),
            pytest.param(
                "Error: permission denied for resource", id="permission_denied"
            ),
        ],
    )
    def test_detects_auth_errors(self, output):
        r = detect_failure(output)
        assert r["failed"] is True
        assert r["error_type"] == "auth"

    def test_network_no_route_with_full_info(self):
        r = detect_failure("Error: no route to host 10.0.0.1")
        assert r["failed"] is True
        assert r["error_type"] == "network"
        assert r["can_auto_fix"] is True
        assert r["fix_action"] == "vpn_connect"

    @pytest.mark.parametrize(
        "output",
        [
            pytest.param(
                "Error: connection refused on port 443", id="connection_refused"
            ),
            pytest.param("Error: request timeout after 30s", id="timeout"),
            pytest.param("Error: dial tcp 10.0.0.1:443: i/o timeout", id="dial_tcp"),
            pytest.param("failed: connection reset by peer", id="connection_reset"),
            pytest.param("Error: unexpected eof", id="eof"),
        ],
    )
    def test_detects_network_errors(self, output):
        r = detect_failure(output)
        assert r["error_type"] == "network"

    @pytest.mark.parametrize(
        "output",
        [
            pytest.param("Error: manifest unknown for image", id="manifest_unknown"),
            pytest.param(
                "Error: pull access denied for quay.io/repo", id="pull_denied"
            ),
            pytest.param(
                "Error: image not found quay.io/repo:tag", id="image_not_found"
            ),
        ],
    )
    def test_detects_registry_errors(self, output):
        r = detect_failure(output)
        assert r["error_type"] == "registry"
        assert r["can_auto_fix"] is False

    @pytest.mark.parametrize(
        "output,tool_name",
        [
            pytest.param("Error: output is not a tty", "oc_tool", id="not_a_tty"),
            pytest.param("Error: not a terminal", None, id="not_a_terminal"),
        ],
    )
    def test_detects_tty_errors(self, output, tool_name):
        r = detect_failure(output, tool_name)
        assert r["error_type"] == "tty"
        assert r["can_auto_fix"] is False

    def test_unknown_error(self):
        r = detect_failure("Error: something completely different happened")
        assert r["failed"] is True
        assert r["error_type"] == "unknown"
        assert r["can_auto_fix"] is False

    @pytest.mark.parametrize(
        "output",
        [
            pytest.param("\u274c Deploy failed: unknown issue", id="emoji_indicator"),
            pytest.param("error: something broke", id="starts_with_error"),
            pytest.param(
                "Deploy failed with unknown error " + "x" * 200,
                id="failed_in_first_100",
            ),
            pytest.param(
                "An exception occurred during processing", id="exception_indicator"
            ),
        ],
    )
    def test_error_detection_heuristics(self, output):
        r = detect_failure(output)
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
    @pytest.mark.parametrize(
        "tool_name,output,expected",
        [
            ("bonfire_deploy", "", "ephemeral"),
            ("some_tool", "Error in ephemeral cluster", "ephemeral"),
            ("konflux_build", "", "konflux"),
            ("some_tool", "Error in production environment", "production"),
            ("some_tool", "some error", "stage"),
        ],
        ids=[
            "bonfire_tool",
            "ephemeral_output",
            "konflux_tool",
            "prod_output",
            "default_stage",
        ],
    )
    def test_cluster_guessing(self, tool_name, output, expected):
        assert _guess_cluster(tool_name, output) == expected


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
    @pytest.mark.parametrize(
        "failure,retry_count,max_retries,expected",
        [
            ({"can_auto_fix": True, "error_type": "auth"}, 0, 2, True),
            ({"can_auto_fix": True, "error_type": "network"}, 0, 2, True),
            ({"can_auto_fix": True, "error_type": "auth"}, 2, 2, False),
            ({"can_auto_fix": False, "error_type": "auth"}, 0, 2, False),
            ({"can_auto_fix": False, "error_type": "registry"}, 0, 2, False),
            ({"can_auto_fix": False, "error_type": "tty"}, 0, 2, False),
            ({"can_auto_fix": False, "error_type": "unknown"}, 0, 2, False),
            ({"can_auto_fix": True, "error_type": "auth"}, 4, 5, True),
            ({"can_auto_fix": True, "error_type": "auth"}, 5, 5, False),
        ],
        ids=[
            "auth_first_retry",
            "network_first_retry",
            "max_retries_exceeded",
            "not_auto_fixable",
            "registry_not_retried",
            "tty_not_retried",
            "unknown_not_retried",
            "custom_max_under",
            "custom_max_at_limit",
        ],
    )
    def test_should_retry(self, failure, retry_count, max_retries, expected):
        assert (
            should_retry(failure, retry_count=retry_count, max_retries=max_retries)
            is expected
        )


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
        log_failure("tool", "err", memory_helper=helper, fixed=True)
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
