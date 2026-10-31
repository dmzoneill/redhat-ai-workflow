"""Tests for the Red Hat Keycloak SAML helpers."""

import asyncio
import time

import httpx
import pytest

from tool_modules.common import redhat_sso

KC_FORM = '<form id="kc-form-login" class="x" action="/realms/rh/login-actions/authenticate?a=1&amp;b=2" method="post">'
SAML_PAGE = (
    '<form method="post" action="https://acs.example.com/saml">'
    '<input type="hidden" name="SAMLResponse" value="UkVTUA=="/>'
    '<input type="hidden" name="RelayState" value="state1"/></form>'
)


@pytest.mark.parametrize(
    ("html", "expected"),
    [
        (KC_FORM, "/realms/rh/login-actions/authenticate?a=1&b=2"),
        ('<form action="/kc" id="kc-form-login">', "/kc"),
        ('<form action="/a"><form ACTION="/x/Authenticate">', "/x/Authenticate"),
        ("<FORM method='POST' action='/p'>", "/p"),
        ('<form action="/get-only">', None),
        ("no forms here", None),
    ],
)
def test_extract_form_action(html, expected):
    """The Keycloak form wins, then authenticate actions, then POST forms."""
    assert redhat_sso.extract_form_action(html) == expected


def test_extract_form_action_is_fast_on_hostile_input():
    """Unclosed form tags with many attributes don't backtrack badly."""
    html = "<form " + 'id="a" ' * 20000
    start = time.perf_counter()
    assert redhat_sso.extract_form_action(html) is None
    assert time.perf_counter() - start < 1.0


@pytest.mark.parametrize(
    "html",
    [
        '<a id="finishLoginLink" class="b" href="https://x/finish?a=1&amp;b=2">',
        '<a href="https://x/finish?a=1&amp;b=2" class="b" id="finishLoginLink">',
    ],
)
def test_finish_login_url_any_attribute_order(html):
    """The finish link is found whichever attribute comes first."""
    assert vars(redhat_sso)["_finish_login_url"](html) == "https://x/finish?a=1&b=2"


def test_extract_hidden_fields():
    """Only hidden inputs with values are returned."""
    html = '<input value="v" type="HIDDEN" name="n"><input type="text" name="t" value="x">'
    assert redhat_sso.extract_hidden_fields(html) == {"n": "v"}


def _patch_client(monkeypatch, handler):
    real_client = httpx.AsyncClient

    def factory(**kwargs):
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(redhat_sso.httpx, "AsyncClient", factory)


def test_keycloak_authenticate_full_flow(monkeypatch):
    """SAMLRequest form, login form, finish link and SAMLResponse."""
    seen = []

    def handler(request):
        seen.append((request.method, request.url.path))
        path = request.url.path
        if path == "/start":
            return httpx.Response(
                200,
                html='<form action="/idp"><input type="hidden" name="SAMLRequest" value="req"></form>',
            )
        if path == "/idp":
            return httpx.Response(200, html=KC_FORM + '<input type="hidden" name="session" value="s1">')
        if path.endswith("/authenticate"):
            body = request.content.decode()
            assert "username=me" in body and "password=pw" in body and "session=s1" in body
            return httpx.Response(
                200, html='Successfully logged in <a id="finishLoginLink" href="https://sso.example.com/done">'
            )
        if path == "/done":
            return httpx.Response(200, html=SAML_PAGE)
        return httpx.Response(404)

    _patch_client(monkeypatch, handler)
    result = asyncio.run(redhat_sso.keycloak_authenticate("https://sso.example.com/start", "me", "pw"))
    assert result.success, result.error
    assert (result.saml_response, result.relay_state, result.form_action) == (
        "UkVTUA==",
        "state1",
        "https://acs.example.com/saml",
    )
    assert seen[1] == ("POST", "/idp")


@pytest.mark.parametrize(
    ("pages", "error"),
    [
        ({"/start": (500, "")}, "SSO login page failed: HTTP 500"),
        ({"/start": (200, "<p>nothing</p>")}, "Could not find Keycloak login form action URL"),
        ({"/start": (200, KC_FORM), "auth": (200, "Invalid username or password")}, "Invalid username or password"),
        ({"/start": (200, KC_FORM), "auth": (403, "")}, "Credentials POST failed: HTTP 403"),
        ({"/start": (200, KC_FORM), "auth": (200, "ok")}, "Could not extract SAMLResponse from SSO response"),
    ],
)
def test_keycloak_authenticate_errors(monkeypatch, pages, error):
    """Each failure step reports its own error message."""

    def handler(request):
        key = "auth" if request.url.path.endswith("/authenticate") else request.url.path
        status, html = pages.get(key, (404, ""))
        return httpx.Response(status, html=html)

    _patch_client(monkeypatch, handler)
    result = asyncio.run(redhat_sso.keycloak_authenticate("https://sso.example.com/start", "u", "p"))
    assert not result.success
    assert result.error == error


def _patch_get(monkeypatch, handler):
    def fake_get(url, timeout):
        assert timeout == 10
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            return client.get(url)

    monkeypatch.setattr(redhat_sso.httpx, "get", fake_get)


def test_get_redhatter_credentials(monkeypatch):
    """Credentials are read from the redhatter /credentials endpoint."""
    _patch_get(monkeypatch, lambda request: httpx.Response(200, json={"sso": {"username": "u", "password": "p"}}))
    assert redhat_sso.get_redhatter_credentials("http://svc") == ("u", "p")


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (httpx.Response(500), "request failed"),
        (httpx.Response(200, text="not json"), "Invalid JSON"),
        (httpx.Response(200, json={"other": {}}), "No 'sso' credentials"),
    ],
)
def test_get_redhatter_credentials_errors(monkeypatch, response, message):
    """HTTP, JSON and missing-key failures raise RuntimeError."""
    _patch_get(monkeypatch, lambda request: response)
    with pytest.raises(RuntimeError, match=message):
        redhat_sso.get_redhatter_credentials("http://svc")


def test_get_redhatter_credentials_timeout(monkeypatch):
    """A timeout names the service URL."""

    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    _patch_get(monkeypatch, handler)
    with pytest.raises(RuntimeError, match="http://svc timed out"):
        redhat_sso.get_redhatter_credentials("http://svc")
