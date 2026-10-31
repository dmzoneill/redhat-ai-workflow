"""Tests for the extra Kibana tool implementations (tool_modules/aa_kibana/src/tools_extra.py)."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest import mock

import pytest

from tool_modules.aa_kibana.src import tools_basic, tools_extra

# The tool implementations are module-private; look them up by name.
SEARCH_LOGS = vars(tools_extra)["_kibana_search_logs_impl"]
LIST_DASHBOARDS = vars(tools_extra)["_kibana_list_dashboards_impl"]
STATUS = vars(tools_extra)["_kibana_status_impl"]

FIXED_NOW = datetime(2026, 10, 31, 14, 0, 0, tzinfo=timezone.utc)
ENV = SimpleNamespace(namespace="tower", index_pattern="app-*", url="https://kibana", kubeconfig="~/.kube/config.s")


class _FrozenDatetime(datetime):
    """datetime whose now() is fixed, so the search window is predictable."""

    @classmethod
    def now(cls, tz=None):
        """Return the fixed instant in ``tz``."""
        return FIXED_NOW.astimezone(tz) if tz else FIXED_NOW.replace(tzinfo=None)


@pytest.fixture(name="kibana")
def kibana_fixture(monkeypatch):
    """Patch environment config, token lookup and the Kibana request helper."""
    request = mock.AsyncMock()
    monkeypatch.setattr(tools_extra, "kibana_request", request)
    monkeypatch.setattr(tools_extra, "get_cached_kibana_config", lambda _env: ENV)
    monkeypatch.setattr(tools_extra, "get_token", lambda _kubeconfig: "token")
    monkeypatch.setattr(tools_basic, "datetime", _FrozenDatetime)
    return request


async def test_search_uses_aware_utc_window(kibana):
    """The Elasticsearch range is an aware UTC window ending now."""
    kibana.return_value = (True, {"hits": {"total": {"value": 2}, "hits": [{"_source": {"message": "boom"}}]}})
    result = await SEARCH_LOGS("stage", query="error", time_range="2h", size=10)
    es_query = kibana.call_args.kwargs["data"]
    window = es_query["query"]["bool"]["must"][1]["range"]["@timestamp"]
    assert window == {"gte": "2026-10-31T12:00:00+00:00", "lte": "2026-10-31T14:00:00+00:00"}
    assert es_query["query"]["bool"]["must"][2] == {"match": {"kubernetes.namespace_name": "tower"}}
    assert es_query["size"] == 10
    text = result[0].text
    assert "**Results:** 1 of 2 total" in text
    assert "| INFO | boom |" in text


async def test_search_failure_links_to_kibana(kibana):
    """A failed proxy search returns the error and a Kibana link."""
    kibana.return_value = (False, "forbidden")
    text = (await SEARCH_LOGS("stage"))[0].text
    assert text.startswith("❌ Direct search failed: forbidden")
    assert "**Open in Kibana:**" in text


async def test_dashboards_and_status(kibana):
    """Dashboards link to their view; status reports version and state."""
    kibana.return_value = (True, {"saved_objects": [{"id": "d1", "attributes": {"title": "Errors"}}]})
    text = (await LIST_DASHBOARDS("stage", "err"))[0].text
    assert kibana.call_args.args[1].endswith("&search=err")
    assert "- **Errors**: [Open](https://kibana/app/dashboards#/view/d1)" in text

    kibana.return_value = (True, {"status": {"overall": {"state": "green"}}, "version": {"number": "8.1"}})
    assert "✅ Connected (v8.1, status: green)" in (await STATUS("stage"))[0].text
