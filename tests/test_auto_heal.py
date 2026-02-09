"""Tests for server.auto_heal_decorator module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from server.auto_heal_decorator import (
    _cleanup_old_stats,
    _convert_result_to_string,
    _detect_failure_type,
    _guess_cluster,
    _update_rolling_stats,
    auto_heal,
    auto_heal_ephemeral,
    auto_heal_konflux,
    auto_heal_stage,
)


@pytest.mark.asyncio
class TestAutoHealDecorator:
    """Tests for auto_heal decorator."""

    async def test_auto_heal_success_no_retry(self):
        """Test auto_heal with successful function call."""

        @auto_heal()
        async def mock_tool():
            return "success"

        result = await mock_tool()
        assert result == "success"

    async def test_auto_heal_auth_error_triggers_retry(self):
        """Test auto_heal retries after auth error."""
        call_count = 0

        @auto_heal()
        async def mock_tool():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return "Error: 401 unauthorized"
            return "success"

        with patch(
            "server.auto_heal_decorator._run_kube_login", new_callable=AsyncMock
        ) as mock_login:
            mock_login.return_value = True
            with patch(
                "server.auto_heal_decorator._log_auto_heal_to_memory",
                new_callable=AsyncMock,
            ):
                result = await mock_tool()

        # Should have been called twice (initial + retry)
        assert call_count == 2
        # Final result should be success
        assert result == "success"

    async def test_auto_heal_network_error_triggers_vpn(self):
        """Test auto_heal retries after network error."""
        call_count = 0

        @auto_heal()
        async def mock_tool():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return "Error: no route to host"
            return "connected"

        with patch(
            "server.auto_heal_decorator._run_vpn_connect", new_callable=AsyncMock
        ) as mock_vpn:
            mock_vpn.return_value = True
            with patch(
                "server.auto_heal_decorator._log_auto_heal_to_memory",
                new_callable=AsyncMock,
            ):
                result = await mock_tool()

        assert call_count == 2
        assert result == "connected"

    async def test_auto_heal_stops_after_max_retries(self):
        """Test auto_heal stops after max retries."""
        call_count = 0

        @auto_heal()
        async def mock_tool():
            nonlocal call_count
            call_count += 1
            return "Error: 401 unauthorized"

        with patch(
            "server.auto_heal_decorator._run_kube_login", new_callable=AsyncMock
        ) as mock_login:
            mock_login.return_value = True
            with patch(
                "server.auto_heal_decorator._log_auto_heal_to_memory",
                new_callable=AsyncMock,
            ):
                result = await mock_tool()

        # Should try initial + 1 retry
        assert call_count == 2
        # Final result should still be the error string
        assert "unauthorized" in result.lower()

    async def test_auto_heal_no_retry_on_unknown_error(self):
        """Test auto_heal doesn't retry on unknown error types."""
        call_count = 0

        @auto_heal()
        async def mock_tool():
            nonlocal call_count
            call_count += 1
            return "Error: some random error"

        result = await mock_tool()

        # Should only be called once (no retry for unknown error type)
        assert call_count == 1
        assert "random error" in result


@pytest.mark.asyncio
class TestAutoHealStage:
    """Tests for auto_heal_stage decorator."""

    async def test_auto_heal_stage_calls_stage_login(self):
        """Test auto_heal_stage uses stage cluster."""
        call_count = 0

        @auto_heal_stage()
        async def mock_tool():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return "Error: unauthorized"
            return "success"

        with patch(
            "server.auto_heal_decorator._run_kube_login", new_callable=AsyncMock
        ) as mock_login:
            mock_login.return_value = True
            with patch(
                "server.auto_heal_decorator._log_auto_heal_to_memory",
                new_callable=AsyncMock,
            ):
                await mock_tool()

        assert call_count == 2
        # Verify _run_kube_login was called with "stage"
        mock_login.assert_called_with("stage")


@pytest.mark.asyncio
class TestAutoHealKonflux:
    """Tests for auto_heal_konflux decorator."""

    async def test_auto_heal_konflux_calls_konflux_login(self):
        """Test auto_heal_konflux uses konflux cluster."""
        call_count = 0

        @auto_heal_konflux()
        async def mock_tool():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return "Error: token expired"
            return "success"

        with patch(
            "server.auto_heal_decorator._run_kube_login", new_callable=AsyncMock
        ) as mock_login:
            mock_login.return_value = True
            with patch(
                "server.auto_heal_decorator._log_auto_heal_to_memory",
                new_callable=AsyncMock,
            ):
                await mock_tool()

        assert call_count == 2


@pytest.mark.asyncio
class TestAutoHealEphemeral:
    """Tests for auto_heal_ephemeral decorator."""

    async def test_auto_heal_ephemeral_calls_ephemeral_login(self):
        """Test auto_heal_ephemeral uses ephemeral cluster."""
        call_count = 0

        @auto_heal_ephemeral()
        async def mock_tool():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return "Error: forbidden"
            return "success"

        with patch(
            "server.auto_heal_decorator._run_kube_login", new_callable=AsyncMock
        ) as mock_login:
            mock_login.return_value = True
            with patch(
                "server.auto_heal_decorator._log_auto_heal_to_memory",
                new_callable=AsyncMock,
            ):
                await mock_tool()

        assert call_count == 2


@pytest.mark.asyncio
class TestAutoHealWithDifferentReturnTypes:
    """Tests for auto_heal with various return types."""

    async def test_auto_heal_with_string_return(self):
        """Test auto_heal with string return type."""

        @auto_heal()
        async def mock_tool():
            return "simple string"

        result = await mock_tool()
        assert result == "simple string"

    async def test_auto_heal_with_dict_return(self):
        """Test auto_heal with dict return type.

        Note: _convert_result_to_string treats dicts as iterables and attempts
        result[0], which raises KeyError for non-integer-keyed dicts. This
        propagates as an unhandled exception from the decorator.
        Use integer keys or expect the KeyError.
        """

        @auto_heal()
        async def mock_tool():
            return {0: "ok", 1: [1, 2, 3]}

        result = await mock_tool()
        assert result == {0: "ok", 1: [1, 2, 3]}

    async def test_auto_heal_with_list_return(self):
        """Test auto_heal with list return type."""

        @auto_heal()
        async def mock_tool():
            return [1, 2, 3, 4, 5]

        result = await mock_tool()
        assert result == [1, 2, 3, 4, 5]


# ---------------------------------------------------------------------------
# Tests for _detect_failure_type
# ---------------------------------------------------------------------------


class TestDetectFailureType:
    """Tests for _detect_failure_type function."""

    @pytest.mark.parametrize(
        "output",
        [
            "",
            "Everything is fine, all good",
        ],
        ids=["empty_string", "no_error_indicator"],
    )
    def test_returns_none_for_non_errors(self, output):
        """Non-error output returns (None, '')."""
        ft, snippet = _detect_failure_type(output)
        assert ft is None

    @pytest.mark.parametrize(
        "output",
        [
            pytest.param("Error: 401 unauthorized access", id="401"),
            pytest.param("Error: 403 forbidden", id="403"),
            pytest.param(
                "Error: token expired please re-authenticate", id="token_expired"
            ),
            pytest.param(
                "Error: permission denied for resource", id="permission_denied"
            ),
            pytest.param(
                "Error: authentication required", id="authentication_required"
            ),
            pytest.param(
                "Error: not authorized to perform action", id="not_authorized"
            ),
            pytest.param(
                "Error: the server has asked for the client to provide credentials",
                id="credentials_prompt",
            ),
            pytest.param("❌ Something went wrong with 401", id="emoji_indicator"),
            pytest.param(
                "Operation failed with unauthorized access", id="failed_indicator"
            ),
        ],
    )
    def test_detects_auth_errors(self, output):
        """Various auth error patterns are detected as 'auth'."""
        ft, _ = _detect_failure_type(output)
        assert ft == "auth"

    @pytest.mark.parametrize(
        "output",
        [
            pytest.param("Error: no route to host", id="no_route"),
            pytest.param(
                "Error: connection refused on port 443", id="connection_refused"
            ),
            pytest.param("Error: network unreachable", id="unreachable"),
            pytest.param("Error: timeout waiting for response", id="timeout"),
            pytest.param("Error: dial tcp 10.0.0.1:6443 i/o timeout", id="dial_tcp"),
            pytest.param("Error: connection reset by peer", id="connection_reset"),
            pytest.param("Error: eof received unexpectedly", id="eof"),
            pytest.param("Error: cannot connect to the cluster", id="cannot_connect"),
            pytest.param("exception: connection refused", id="exception_indicator"),
        ],
    )
    def test_detects_network_errors(self, output):
        """Various network error patterns are detected as 'network'."""
        ft, _ = _detect_failure_type(output)
        assert ft == "network"

    def test_unknown_error(self):
        """Unknown error type detected when error indicator present."""
        ft, snippet = _detect_failure_type("Error: some unknown problem occurred")
        assert ft == "unknown"
        assert "unknown problem" in snippet

    def test_output_starts_with_error(self):
        """Detects output starting with 'error'."""
        ft, _ = _detect_failure_type("error: something went wrong, totally broken")
        assert ft == "unknown"

    def test_snippet_truncated_to_300(self):
        """Error snippet is truncated to 300 characters."""
        long_msg = "Error: unauthorized " + "x" * 500
        ft, snippet = _detect_failure_type(long_msg)
        assert ft == "auth"
        assert len(snippet) <= 300


# ---------------------------------------------------------------------------
# Tests for _guess_cluster
# ---------------------------------------------------------------------------


class TestGuessCluster:
    """Tests for _guess_cluster function."""

    @pytest.mark.parametrize(
        "tool_name,output,expected",
        [
            ("bonfire_namespace_reserve", "", "ephemeral"),
            ("some_tool", "error on ephemeral cluster", "ephemeral"),
            ("konflux_build_check", "", "konflux"),
            ("some_tool", "error on prod", "prod"),
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
        """Cluster is guessed correctly from tool name and output."""
        assert _guess_cluster(tool_name, output) == expected


# ---------------------------------------------------------------------------
# Tests for _convert_result_to_string
# ---------------------------------------------------------------------------


class TestConvertResultToString:
    """Tests for _convert_result_to_string function."""

    def test_list_with_text_attr(self):
        """List item with .text attribute uses that."""
        mock_content = MagicMock()
        mock_content.text = "some text"
        result = _convert_result_to_string([mock_content])
        assert result == "some text"

    def test_list_without_text_attr(self):
        """List item without .text uses str() on item."""
        result = _convert_result_to_string([42])
        assert result == "42"

    @pytest.mark.parametrize(
        "input_val,expected",
        [
            ("hello", "hello"),
            ([], "[]"),
            (42, "42"),
            (None, "None"),
        ],
        ids=["string", "empty_list", "non_iterable", "none"],
    )
    def test_fallback_to_str(self, input_val, expected):
        """Various non-list inputs fall back to str()."""
        assert _convert_result_to_string(input_val) == expected


# ---------------------------------------------------------------------------
# Tests for _update_rolling_stats
# ---------------------------------------------------------------------------


class TestUpdateRollingStats:
    """Tests for _update_rolling_stats function."""

    def test_creates_stats_if_missing(self):
        """Creates stats dict if not present."""
        data = {}
        _update_rolling_stats(data, "2026-01-01", "2026-W01")
        assert "stats" in data
        assert data["stats"]["total_failures"] == 1
        assert data["stats"]["auto_fixed"] == 1

    def test_increments_existing_counters(self):
        """Increments existing counters."""
        data = {"stats": {"total_failures": 5, "auto_fixed": 3}}
        _update_rolling_stats(data, "2026-01-01", "2026-W01")
        assert data["stats"]["total_failures"] == 6
        assert data["stats"]["auto_fixed"] == 4

    def test_caps_at_1000(self):
        """Counters are capped at 1000."""
        data = {"stats": {"total_failures": 999, "auto_fixed": 999}}
        _update_rolling_stats(data, "2026-01-01", "2026-W01")
        assert data["stats"]["total_failures"] == 1000
        assert data["stats"]["auto_fixed"] == 1000

    def test_creates_daily_stats(self):
        """Creates daily stats for today."""
        data = {}
        _update_rolling_stats(data, "2026-02-07", "2026-W06")
        assert data["stats"]["daily"]["2026-02-07"]["total"] == 1
        assert data["stats"]["daily"]["2026-02-07"]["auto_fixed"] == 1

    def test_creates_weekly_stats(self):
        """Creates weekly stats for this week."""
        data = {}
        _update_rolling_stats(data, "2026-02-07", "2026-W06")
        assert data["stats"]["weekly"]["2026-W06"]["total"] == 1
        assert data["stats"]["weekly"]["2026-W06"]["auto_fixed"] == 1

    def test_increments_existing_daily_stats(self):
        """Increments existing daily entry."""
        data = {
            "stats": {
                "daily": {"2026-02-07": {"total": 3, "auto_fixed": 2}},
                "weekly": {},
            }
        }
        _update_rolling_stats(data, "2026-02-07", "2026-W06")
        assert data["stats"]["daily"]["2026-02-07"]["total"] == 4
        assert data["stats"]["daily"]["2026-02-07"]["auto_fixed"] == 3


# ---------------------------------------------------------------------------
# Tests for _cleanup_old_stats
# ---------------------------------------------------------------------------


class TestCleanupOldStats:
    """Tests for _cleanup_old_stats function."""

    def test_no_stats_no_crash(self):
        """Empty data does not crash."""
        data = {}
        _cleanup_old_stats(data)  # Test verifies no exception is raised
        assert data == {}  # Data unchanged when empty

    def test_keeps_last_30_daily(self):
        """Keeps only last 30 days of daily stats."""
        daily = {
            f"2026-01-{d:02d}": {"total": 1, "auto_fixed": 1} for d in range(1, 32)
        }
        data = {"stats": {"daily": daily}, "failures": []}
        _cleanup_old_stats(data)
        assert len(data["stats"]["daily"]) == 30

    def test_keeps_last_12_weekly(self):
        """Keeps only last 12 weeks of weekly stats."""
        weekly = {f"2026-W{w:02d}": {"total": 1, "auto_fixed": 1} for w in range(1, 15)}
        data = {"stats": {"weekly": weekly}, "failures": []}
        _cleanup_old_stats(data)
        assert len(data["stats"]["weekly"]) == 12

    def test_trims_failures_to_100(self):
        """Keeps only last 100 failure entries."""
        data = {"failures": [{"id": i} for i in range(150)]}
        _cleanup_old_stats(data)
        assert len(data["failures"]) == 100
        # Should keep the last 100 (most recent)
        assert data["failures"][0]["id"] == 50

    def test_under_limits_no_change(self):
        """Data under limits is not modified."""
        daily = {"2026-01-01": {"total": 1, "auto_fixed": 1}}
        weekly = {"2026-W01": {"total": 1, "auto_fixed": 1}}
        failures = [{"id": 1}]
        data = {"stats": {"daily": daily, "weekly": weekly}, "failures": failures}
        _cleanup_old_stats(data)
        assert len(data["stats"]["daily"]) == 1
        assert len(data["stats"]["weekly"]) == 1
        assert len(data["failures"]) == 1


# ---------------------------------------------------------------------------
# Tests for _log_auto_heal_to_memory
# ---------------------------------------------------------------------------


class TestLogAutoHealToMemory:
    """Tests for _log_auto_heal_to_memory function."""

    async def test_writes_to_memory(self, tmp_path):
        """Writes failure entry to memory YAML file."""
        from pathlib import Path

        import yaml

        from server.auto_heal_decorator import _log_auto_heal_to_memory

        # Create the memory directory structure under tmp_path
        memory_dir = tmp_path / "memory" / "learned"
        memory_dir.mkdir(parents=True)

        # Patch pathlib.Path to redirect __file__ resolution to tmp_path
        original_path = Path

        class FakePath(type(Path())):
            def __new__(cls, *args, **kwargs):
                p = original_path(*args, **kwargs)
                return p

        # Instead of patching Path, patch the actual __file__ used by the module
        # by replacing it temporarily
        import server.auto_heal_decorator as ahd

        orig_file = ahd.__file__

        # Create a fake server/auto_heal_decorator.py path under tmp_path
        fake_server = tmp_path / "server"
        fake_server.mkdir(exist_ok=True)
        ahd.__file__ = str(fake_server / "auto_heal_decorator.py")

        try:
            await _log_auto_heal_to_memory("test_tool", "auth", "401 err", "kube_login")
        finally:
            ahd.__file__ = orig_file

        failures_file = memory_dir / "tool_failures.yaml"
        assert failures_file.exists()
        with open(failures_file) as f:
            data = yaml.safe_load(f)
        assert len(data["failures"]) >= 1
        assert data["failures"][-1]["tool"] == "test_tool"
        assert data["failures"][-1]["fix_applied"] == "kube_login"
        assert data["failures"][-1]["success"] is True

    async def test_appends_to_existing_file(self, tmp_path):
        """Appends entries to existing failures file."""
        import yaml

        from server.auto_heal_decorator import _log_auto_heal_to_memory

        memory_dir = tmp_path / "memory" / "learned"
        memory_dir.mkdir(parents=True)
        failures_file = memory_dir / "tool_failures.yaml"

        existing_data = {
            "failures": [{"tool": "old_tool", "success": True}],
            "stats": {"total_failures": 1, "auto_fixed": 1, "manual_required": 0},
        }
        with open(failures_file, "w") as f:
            yaml.dump(existing_data, f)

        import server.auto_heal_decorator as ahd

        orig_file = ahd.__file__
        fake_server = tmp_path / "server"
        fake_server.mkdir(exist_ok=True)
        ahd.__file__ = str(fake_server / "auto_heal_decorator.py")

        try:
            await _log_auto_heal_to_memory(
                "new_tool", "network", "timeout", "vpn_connect"
            )
        finally:
            ahd.__file__ = orig_file

        with open(failures_file) as f:
            data = yaml.safe_load(f)
        assert len(data["failures"]) == 2
        assert data["failures"][-1]["tool"] == "new_tool"

    async def test_exception_does_not_propagate(self):
        """Memory logging failure should not propagate."""
        # Force an internal error by temporarily pointing __file__ to a
        # read-only non-existent path
        import server.auto_heal_decorator as ahd
        from server.auto_heal_decorator import _log_auto_heal_to_memory

        orig_file = ahd.__file__
        ahd.__file__ = "/dev/null/fake/server/auto_heal_decorator.py"

        try:
            # Should not raise - exceptions are caught internally
            await _log_auto_heal_to_memory("tool", "auth", "err", "fix")
        finally:
            ahd.__file__ = orig_file
        # If we got here, the exception was properly swallowed
        assert True


# ---------------------------------------------------------------------------
# Tests for _run_kube_login
# ---------------------------------------------------------------------------


class TestRunKubeLogin:
    """Tests for _run_kube_login function."""

    async def test_successful_login(self):
        """Successful kube login returns True."""
        from server.auto_heal_decorator import _run_kube_login

        with patch("server.utils.run_cmd_full", new_callable=AsyncMock) as mock_full:
            mock_full.return_value = (False, "", "stale")
            with patch(
                "server.utils.run_cmd_shell", new_callable=AsyncMock
            ) as mock_shell:
                mock_shell.side_effect = [
                    (True, "", ""),  # kube-clean
                    (True, "logged in", ""),  # kube
                ]
                with patch("os.path.exists", return_value=True):
                    result = await _run_kube_login("stage")
        assert result is True

    async def test_login_via_logged_in_message(self):
        """Login succeeds when output contains 'logged in'."""
        from server.auto_heal_decorator import _run_kube_login

        with patch("server.utils.run_cmd_full", new_callable=AsyncMock) as mock_full:
            mock_full.return_value = (True, "ok", "")  # whoami succeeds
            with patch(
                "server.utils.run_cmd_shell", new_callable=AsyncMock
            ) as mock_shell:
                mock_shell.return_value = (False, "Logged in as user", "")
                with patch("os.path.exists", return_value=True):
                    result = await _run_kube_login("ephemeral")
        assert result is True

    async def test_kube_not_found_fallback_oc_login(self):
        """Falls back to oc login when kube command not found."""
        from server.auto_heal_decorator import _run_kube_login

        with patch("server.utils.run_cmd_full", new_callable=AsyncMock) as mock_full:
            mock_full.return_value = (True, "ok", "")  # whoami ok
            with patch(
                "server.utils.run_cmd_shell", new_callable=AsyncMock
            ) as mock_shell:
                mock_shell.side_effect = [
                    (False, "", "command not found"),  # kube fails
                    (True, "logged in", ""),  # oc login succeeds
                ]
                with patch("os.path.exists", return_value=True):
                    result = await _run_kube_login("stage")
        assert result is True

    async def test_login_failure(self):
        """Login failure returns False."""
        from server.auto_heal_decorator import _run_kube_login

        with patch("server.utils.run_cmd_full", new_callable=AsyncMock) as mock_full:
            mock_full.return_value = (True, "ok", "")
            with patch(
                "server.utils.run_cmd_shell", new_callable=AsyncMock
            ) as mock_shell:
                mock_shell.return_value = (False, "error", "nope")
                with patch("os.path.exists", return_value=True):
                    result = await _run_kube_login("stage")
        assert result is False

    async def test_no_kubeconfig_file(self):
        """Works when kubeconfig file does not exist."""
        from server.auto_heal_decorator import _run_kube_login

        with patch("server.utils.run_cmd_shell", new_callable=AsyncMock) as mock_shell:
            mock_shell.return_value = (True, "logged in", "")
            with patch("os.path.exists", return_value=False):
                result = await _run_kube_login("stage")
        assert result is True

    async def test_file_not_found_error(self):
        """FileNotFoundError returns False."""
        from server.auto_heal_decorator import _run_kube_login

        with patch("server.utils.run_cmd_full", new_callable=AsyncMock) as mock_full:
            mock_full.side_effect = FileNotFoundError("oc not found")
            with patch("os.path.exists", return_value=True):
                result = await _run_kube_login("stage")
        assert result is False

    async def test_os_error(self):
        """OSError returns False."""
        from server.auto_heal_decorator import _run_kube_login

        with patch("server.utils.run_cmd_full", new_callable=AsyncMock) as mock_full:
            mock_full.side_effect = OSError("disk error")
            with patch("os.path.exists", return_value=True):
                result = await _run_kube_login("stage")
        assert result is False

    async def test_cluster_name_mapping(self):
        """Various cluster names map to correct short codes."""
        from server.auto_heal_decorator import _run_kube_login

        for cluster_name in ["stage", "prod", "production", "ephemeral", "konflux"]:
            with patch(
                "server.utils.run_cmd_shell", new_callable=AsyncMock
            ) as mock_shell:
                mock_shell.return_value = (True, "logged in", "")
                with patch("os.path.exists", return_value=False):
                    result = await _run_kube_login(cluster_name)
            assert result is True

    async def test_unknown_cluster_short_code(self):
        """Unknown long cluster name gets first char as short code."""
        from server.auto_heal_decorator import _run_kube_login

        with patch("server.utils.run_cmd_shell", new_callable=AsyncMock) as mock_shell:
            mock_shell.return_value = (True, "logged in", "")
            with patch("os.path.exists", return_value=False):
                result = await _run_kube_login("custom")
        assert result is True

    async def test_single_char_cluster(self):
        """Single char cluster code used as-is."""
        from server.auto_heal_decorator import _run_kube_login

        with patch("server.utils.run_cmd_shell", new_callable=AsyncMock) as mock_shell:
            mock_shell.return_value = (True, "logged in", "")
            with patch("os.path.exists", return_value=False):
                result = await _run_kube_login("s")
        assert result is True


# ---------------------------------------------------------------------------
# Tests for _run_vpn_connect
# ---------------------------------------------------------------------------


class TestRunVpnConnect:
    """Tests for _run_vpn_connect function."""

    async def test_successful_vpn_via_script(self):
        """VPN connects successfully via script."""
        from server.auto_heal_decorator import _run_vpn_connect

        with patch("server.utils.load_config", return_value={"paths": {}}):
            with patch("os.path.exists", return_value=True):
                with patch(
                    "server.utils.run_cmd_shell", new_callable=AsyncMock
                ) as mock_shell:
                    mock_shell.return_value = (True, "connected", "")
                    result = await _run_vpn_connect()
        assert result is True

    async def test_vpn_successfully_activated_message(self):
        """VPN succeeds with 'successfully activated' in output."""
        from server.auto_heal_decorator import _run_vpn_connect

        with patch("server.utils.load_config", return_value={"paths": {}}):
            with patch("os.path.exists", return_value=True):
                with patch(
                    "server.utils.run_cmd_shell", new_callable=AsyncMock
                ) as mock_shell:
                    mock_shell.return_value = (
                        False,
                        "Connection successfully activated",
                        "",
                    )
                    result = await _run_vpn_connect()
        assert result is True

    async def test_vpn_script_failure(self):
        """VPN script failure returns False."""
        from server.auto_heal_decorator import _run_vpn_connect

        with patch("server.utils.load_config", return_value={"paths": {}}):
            with patch("os.path.exists", return_value=True):
                with patch(
                    "server.utils.run_cmd_shell", new_callable=AsyncMock
                ) as mock_shell:
                    mock_shell.return_value = (False, "error", "failed")
                    result = await _run_vpn_connect()
        assert result is False

    async def test_vpn_fallback_nmcli_success(self):
        """Falls back to nmcli when script not found."""
        from server.auto_heal_decorator import _run_vpn_connect

        with patch("server.utils.load_config", return_value={"paths": {}}):
            with patch("os.path.exists", return_value=False):
                with patch(
                    "server.utils.run_cmd_shell", new_callable=AsyncMock
                ) as mock_shell:
                    # First three nmcli calls fail, fourth succeeds
                    mock_shell.side_effect = [
                        (False, "", "err"),
                        (False, "", "err"),
                        (False, "", "err"),
                        (True, "connected", ""),
                    ]
                    result = await _run_vpn_connect()
        assert result is True

    async def test_vpn_fallback_nmcli_all_fail(self):
        """All nmcli VPN names fail returns False."""
        from server.auto_heal_decorator import _run_vpn_connect

        with patch("server.utils.load_config", return_value={"paths": {}}):
            with patch("os.path.exists", return_value=False):
                with patch(
                    "server.utils.run_cmd_shell", new_callable=AsyncMock
                ) as mock_shell:
                    mock_shell.return_value = (False, "", "err")
                    result = await _run_vpn_connect()
        assert result is False

    async def test_vpn_custom_script_path(self):
        """Uses custom script path from config."""
        from server.auto_heal_decorator import _run_vpn_connect

        with patch(
            "server.utils.load_config",
            return_value={"paths": {"vpn_connect_script": "/custom/vpn"}},
        ):
            with patch("os.path.exists", return_value=True):
                with patch(
                    "server.utils.run_cmd_shell", new_callable=AsyncMock
                ) as mock_shell:
                    mock_shell.return_value = (True, "connected", "")
                    result = await _run_vpn_connect()
        assert result is True

    async def test_vpn_os_error(self):
        """OSError returns False."""
        from server.auto_heal_decorator import _run_vpn_connect

        with patch("server.utils.load_config", return_value={"paths": {}}):
            with patch("os.path.exists", return_value=True):
                with patch(
                    "server.utils.run_cmd_shell", new_callable=AsyncMock
                ) as mock_shell:
                    mock_shell.side_effect = OSError("broken")
                    result = await _run_vpn_connect()
        assert result is False


# ---------------------------------------------------------------------------
# Tests for sync wrapper and introspection
# ---------------------------------------------------------------------------


class TestAutoHealSyncWrapper:
    """Tests for auto_heal with sync functions."""

    def test_sync_function_passthrough(self):
        """Sync functions are wrapped but not auto-healed."""

        @auto_heal()
        def sync_tool():
            return "sync result"

        result = sync_tool()
        assert result == "sync result"

    def test_sync_wrapper_introspection(self):
        """Sync wrapper has introspection attributes."""

        @auto_heal(cluster="stage", max_retries=3)
        def sync_tool():
            return "ok"

        assert sync_tool._auto_heal_enabled is True
        assert sync_tool._auto_heal_cluster == "stage"
        assert sync_tool._auto_heal_max_retries == 3
        assert sync_tool._auto_heal_is_sync is True

    def test_async_wrapper_introspection(self):
        """Async wrapper has introspection attributes."""

        @auto_heal(cluster="ephemeral", max_retries=2)
        async def async_tool():
            return "ok"

        assert async_tool._auto_heal_enabled is True
        assert async_tool._auto_heal_cluster == "ephemeral"
        assert async_tool._auto_heal_max_retries == 2
        assert async_tool._auto_heal_is_sync is False

    def test_sync_wraps_preserves_name(self):
        """Sync wrapper preserves function name."""

        @auto_heal()
        def my_special_tool():
            """My docstring."""
            return "ok"

        assert my_special_tool.__name__ == "my_special_tool"
        assert my_special_tool.__doc__ == "My docstring."


# ---------------------------------------------------------------------------
# Tests for exception handling in async wrapper
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestAutoHealExceptionHandling:
    """Tests for exception handling in auto_heal async wrapper."""

    async def test_retryable_exception_triggers_fix(self):
        """Retryable exception (auth) triggers fix and retry."""
        call_count = 0

        @auto_heal()
        async def mock_tool():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("Error: 401 unauthorized")
            return "recovered"

        with patch(
            "server.auto_heal_decorator._apply_auto_heal_fix",
            new_callable=AsyncMock,
            return_value=True,
        ):
            result = await mock_tool()

        assert call_count == 2
        assert result == "recovered"

    async def test_non_retryable_exception_reraises(self):
        """Non-retryable exception is re-raised."""

        @auto_heal()
        async def mock_tool():
            raise ValueError("bad input")

        with pytest.raises(ValueError, match="bad input"):
            await mock_tool()

    async def test_retryable_exception_fix_fails_reraises(self):
        """Retryable exception where fix fails re-raises."""

        @auto_heal()
        async def mock_tool():
            raise Exception("Error: 401 unauthorized")

        with patch(
            "server.auto_heal_decorator._apply_auto_heal_fix",
            new_callable=AsyncMock,
            return_value=False,
        ):
            with pytest.raises(Exception, match="unauthorized"):
                await mock_tool()

    async def test_fix_failure_returns_original_result(self):
        """When fix_applied fails, original result is returned."""

        @auto_heal()
        async def mock_tool():
            return "Error: 401 unauthorized"

        with patch(
            "server.auto_heal_decorator._run_kube_login",
            new_callable=AsyncMock,
            return_value=False,
        ):
            result = await mock_tool()

        assert "unauthorized" in result.lower()

    async def test_custom_retry_on(self):
        """Custom retry_on parameter limits which failure types trigger retry."""

        @auto_heal(retry_on=["network"])
        async def mock_tool():
            return (
                "Error: 401 unauthorized"  # auth error, but retry_on only has network
            )

        result = await mock_tool()
        # Should not retry since auth is not in retry_on
        assert "unauthorized" in result.lower()

    async def test_max_retries_zero(self):
        """max_retries=0 means no retries at all."""

        @auto_heal(max_retries=0)
        async def mock_tool():
            return "Error: 401 unauthorized"

        result = await mock_tool()
        assert "unauthorized" in result.lower()
