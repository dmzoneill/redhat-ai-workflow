"""Tests for the Alertmanager tool implementations (tool_modules/aa_alertmanager)."""

from datetime import datetime, timezone
from unittest import mock

import pytest

from tool_modules.aa_alertmanager.src import tools_basic

# The tool implementations are module-private; look them up by name.
CREATE_SILENCE = vars(tools_basic)["_alertmanager_create_silence_impl"]
LIST_ALERTS = vars(tools_basic)["_alertmanager_alerts_impl"]
FIXED_NOW = datetime(2026, 10, 31, 14, 0, 5, 123456, tzinfo=timezone.utc)


class _FrozenDatetime(datetime):
    """datetime whose now() is fixed, so silence windows are predictable."""

    @classmethod
    def now(cls, tz=None):
        """Return the fixed instant in ``tz``."""
        return FIXED_NOW.astimezone(tz) if tz else FIXED_NOW.replace(tzinfo=None)


@pytest.fixture(name="api")
def api_fixture(monkeypatch):
    """Patch config lookup and the HTTP helper; return the request mock."""
    monkeypatch.setattr(tools_basic, "get_alertmanager_config", mock.AsyncMock(return_value=("https://am", "tok")))
    request = mock.AsyncMock()
    monkeypatch.setattr(tools_basic, "alertmanager_request", request)
    monkeypatch.setattr(tools_basic, "datetime", _FrozenDatetime)
    return request


def _alert(name, namespace="ns", severity="critical", **annotations):
    return {
        "labels": {"alertname": name, "namespace": namespace, "severity": severity},
        "annotations": annotations,
        "startsAt": "2026-10-31T13:00:00.000Z",
    }


async def test_create_silence_sends_utc_window(api):
    """The silence starts now (UTC) and ends after the duration, both with a Z suffix."""
    api.return_value = (True, {"silenceID": "abc"})
    result = await CREATE_SILENCE("alertname=Down, namespace=~tower.*", "2h", "maint", "stage")
    data = api.call_args.kwargs["data"]
    assert data["startsAt"] == "2026-10-31T14:00:05.123456Z"
    assert data["endsAt"] == "2026-10-31T16:00:05.123456Z"
    assert data["matchers"] == [
        {"name": "alertname", "value": "Down", "isRegex": False, "isEqual": True},
        {"name": "namespace", "value": "tower.*", "isRegex": True, "isEqual": True},
    ]
    assert "`abc`" in result[0].text
    assert "(until 2026-10-31T16:00:05.123456Z)" in result[0].text


async def test_create_silence_rejects_bad_matchers(api):
    """Matchers without = are rejected before calling Alertmanager."""
    result = await CREATE_SILENCE("nothing", "1h", "c", "stage")
    assert "Invalid matchers" in result[0].text
    api.assert_not_called()


async def test_alerts_query_filter_and_format(api):
    """Alerts are fetched with the right filters, matched by name or summary, and formatted."""
    api.return_value = (
        True,
        [
            _alert("PodDown", summary="Automation Analytics pod down", runbook_url="https://rb"),
            _alert("DiskFull", namespace="other", severity="warning"),
        ],
    )
    result = await LIST_ALERTS("stage", "analytics", False, True)
    assert api.call_args.args[1] == "/alerts?silenced=false&inhibited=true&active=true"
    text = result[0].text
    assert "**Count:** 1" in text
    assert "🔴 **PodDown** (critical)" in text
    assert "   [Runbook](https://rb)" in text
    assert "DiskFull" not in text


async def test_alerts_empty_and_errors(api):
    """No matches, API failures and odd responses each get a clear message."""
    api.return_value = (True, [])
    assert (await LIST_ALERTS("prod", "x", True, False))[0].text == "✅ No active alerts in prod matching 'x'"
    api.return_value = (False, "timeout")
    assert (await LIST_ALERTS("prod", "", True, False))[0].text == "❌ Failed to get alerts: timeout"
    api.return_value = (True, {"oops": 1})
    assert (await LIST_ALERTS("prod", "", True, False))[0].text.startswith("⚠️ Unexpected response")
