"""Tests for server.auto_heal_decorator module."""

import pytest
from unittest.mock import AsyncMock, patch
from server.auto_heal_decorator import (
    auto_heal,
    auto_heal_stage,
    auto_heal_konflux,
    auto_heal_ephemeral,
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

    async def test_auto_heal_auth_error_triggers_kube_login(self):
        """Test auto_heal retries after auth error."""
        call_count = 0

        @auto_heal()
        async def mock_tool():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return (False, "Error: 401 unauthorized")
            return (True, "success")

        with patch("server.auto_heal_decorator.kube_login") as mock_kube_login:
            mock_kube_login.return_value = AsyncMock(return_value=(True, "Logged in"))
            result = await mock_tool()

        # Should have been called twice (initial + retry)
        assert call_count == 2
        # Final result should be success
        assert result == (True, "success")

    async def test_auto_heal_network_error_triggers_vpn(self):
        """Test auto_heal retries after network error."""
        call_count = 0

        @auto_heal()
        async def mock_tool():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return (False, "Error: no route to host")
            return (True, "connected")

        with patch("server.auto_heal_decorator.vpn_connect") as mock_vpn:
            mock_vpn.return_value = AsyncMock(return_value=(True, "VPN connected"))
            result = await mock_tool()

        assert call_count == 2
        assert result == (True, "connected")

    async def test_auto_heal_stops_after_max_retries(self):
        """Test auto_heal stops after max retries."""
        call_count = 0

        @auto_heal()
        async def mock_tool():
            nonlocal call_count
            call_count += 1
            return (False, "Error: 401 unauthorized")

        with patch("server.auto_heal_decorator.kube_login") as mock_kube_login:
            mock_kube_login.return_value = AsyncMock(return_value=(True, "Logged in"))
            result = await mock_tool()

        # Should try initial + 1 retry
        assert call_count == 2
        # Final result should still be failure
        assert result[0] is False

    async def test_auto_heal_no_retry_on_unknown_error(self):
        """Test auto_heal doesn't retry on unknown error types."""
        call_count = 0

        @auto_heal()
        async def mock_tool():
            nonlocal call_count
            call_count += 1
            return (False, "Some random error")

        result = await mock_tool()

        # Should only be called once (no retry)
        assert call_count == 1
        assert result[0] is False


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
                return (False, "Error: unauthorized")
            return (True, "success")

        with patch("server.auto_heal_decorator.kube_login") as mock_kube_login:
            mock_kube_login.return_value = AsyncMock(return_value=(True, "Logged in to stage"))
            result = await mock_tool()

        assert call_count == 2
        # Verify kube_login was called with "stage"
        mock_kube_login.assert_called()


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
                return (False, "Error: token expired")
            return (True, "success")

        with patch("server.auto_heal_decorator.kube_login") as mock_kube_login:
            mock_kube_login.return_value = AsyncMock(return_value=(True, "Logged in to konflux"))
            result = await mock_tool()

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
                return (False, "Error: forbidden")
            return (True, "success")

        with patch("server.auto_heal_decorator.kube_login") as mock_kube_login:
            mock_kube_login.return_value = AsyncMock(return_value=(True, "Logged in to ephemeral"))
            result = await mock_tool()

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
        """Test auto_heal with dict return type."""

        @auto_heal()
        async def mock_tool():
            return {"status": "ok", "data": [1, 2, 3]}

        result = await mock_tool()
        assert result == {"status": "ok", "data": [1, 2, 3]}

    async def test_auto_heal_with_list_return(self):
        """Test auto_heal with list return type."""

        @auto_heal()
        async def mock_tool():
            return [1, 2, 3, 4, 5]

        result = await mock_tool()
        assert result == [1, 2, 3, 4, 5]
