"""Tests for the aa_sso tools_basic parsing and HTTP helpers."""

import json
from types import SimpleNamespace

import httpx
import pytest

from tool_modules.aa_sso.src import tools_basic


def _private(name):
    """Return a private helper from tools_basic."""
    return vars(tools_basic)[name]


@pytest.mark.parametrize(
    ("html", "expected"),
    [
        ('<form id="kc-form-login" action="/a?x=1&amp;y=2" method="post">', "/a?x=1&y=2"),
        ('<form method="post" action="/login-actions/authenticate?s=1">', "/login-actions/authenticate?s=1"),
        ("<form action='/x' METHOD='POST'>", "/x"),
        ('<form id="other" action="/o"><form id="kc-form-login" action="/k">', "/k"),
        ('<form method="get" action="/q">', None),
        ("<div></div>", None),
    ],
)
def test_extract_form_action(html, expected):
    """The Keycloak form wins, then authenticate URLs, then POST forms."""
    assert _private("_extract_form_action")(html) == expected


def test_extract_hidden_fields_any_order():
    """Hidden inputs are found whatever the attribute order; others are skipped."""
    html = (
        '<input type="hidden" name="a" value="1">'
        '<input type="hidden" value="2" name="b">'
        '<input name="c" type="hidden" value="3">'
        '<input type="text" name="d" value="4">'
        '<input type="hidden" name="" value="5">'
    )
    assert _private("_extract_hidden_fields")(html) == {"a": "1", "b": "2", "c": "3"}


def test_extract_form_action_is_linear_on_hostile_input():
    """A huge unterminated tag does not trigger catastrophic backtracking."""
    html = "<form " + 'id="x" ' * 20000
    assert _private("_extract_form_action")(html) is None


def test_parse_json_arg():
    """Empty arguments are None; JSON is parsed; bad JSON raises."""
    parse = _private("_parse_json_arg")
    assert parse("") is None
    assert parse('{"a": 1}') == {"a": 1}
    with pytest.raises(json.JSONDecodeError):
        parse("{")


def _response(body, content_type):
    """Build an httpx response with the given body and content type."""
    return httpx.Response(200, content=body.encode(), headers={"content-type": content_type})


def test_format_response_body_json_and_text():
    """JSON is pretty-printed; text and broken JSON are passed through, truncated."""
    fmt = _private("_format_response_body")
    assert fmt(_response('{"a": 1}', "application/json")) == '{\n  "a": 1\n}'
    assert fmt(_response("{bad", "application/json")) == "{bad"
    long_text = "x" * 6000
    assert fmt(_response(long_text, "text/plain")) == "x" * 5000 + "\n... (truncated)"
    assert fmt(_response(json.dumps(["y" * 6000]), "application/json")).endswith("\n... (truncated)")


def _fake_client(result):
    """Build an async client stub whose get() returns or raises ``result``."""

    async def get(url, follow_redirects=False):
        assert url
        assert follow_redirects
        if isinstance(result, Exception):
            raise result
        return result

    return SimpleNamespace(get=get)


@pytest.fixture(name="saml_config")
def fixture_saml_config(monkeypatch):
    """Register a fake HTTP SAML config named 'demo'."""
    config = SimpleNamespace(init_url="https://example.test/init", csrf_field="_csrf")
    monkeypatch.setitem(tools_basic.HTTP_SAML_CONFIGS, "demo", config)
    return config


@pytest.mark.usefixtures("saml_config")
@pytest.mark.parametrize(
    ("result", "status", "csrf"),
    [
        (_response('{"_csrf": "tok"}', "application/json"), "extracted", "tok"),
        (_response("{}", "application/json"), "not in response", None),
        (_response("<html>", "text/html"), "response not JSON", None),
        (httpx.Response(500), "HTTP 500", None),
        (httpx.ConnectError("down"), "error: down", None),
    ],
)
async def test_init_csrf_status(result, status, csrf):
    """The init endpoint's outcome is reported and any _csrf is stored."""
    meta: dict = {}
    assert await _private("_init_csrf_status")(_fake_client(result), meta, "demo") == status
    assert meta.get("csrf") == csrf


async def test_init_csrf_status_without_config():
    """Sessions without a SAML config skip the init call."""
    assert await _private("_init_csrf_status")(_fake_client(None), {}, "no-such-session") == "not attempted"
