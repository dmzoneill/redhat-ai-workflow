"""Tests for the split aa_sso modules: public API, outcome extraction and tool helpers."""

import inspect
import json
import time
from types import SimpleNamespace

from tool_modules.aa_sso.src import sso_authenticator, sso_browser, sso_http, sso_tool_impls, tools_basic
from tool_modules.aa_sso.src.sso_models import KNOWN_STRATEGIES, FlowType, OutcomeType, SSOResult, SSOStrategy

EXPECTED_TOOLS = [
    ("sso_authenticate", "strategy, headless"),
    ("sso_list_strategies", ""),
    ("sso_check_session", "strategy"),
    ("browser_navigate", "url, wait_for, timeout"),
    ("browser_click", "selector, text, timeout"),
    ("browser_fill", "selector, value, timeout"),
    ("browser_snapshot", "name, full_page"),
    ("browser_wait_for", "selector, text, timeout, state"),
    ("http_session_create", "name, base_url"),
    ("http_saml_auth", "session, strategy"),
    ("http_request", "session, method, path, params, json_body"),
]


def test_public_api_still_importable_from_tools_basic():
    """Names documented and used by callers are re-exported from tools_basic."""
    for name in ("SSOAuthenticator", "SSOStrategy", "SSOResult", "fill_sso_form", "get_sso_credentials"):
        assert hasattr(tools_basic, name)
    assert tools_basic.HTTP_SAML_CONFIGS is sso_http.HTTP_SAML_CONFIGS
    assert vars(tools_basic)["_http_sessions"] is vars(sso_http)["_http_sessions"]


def test_register_tools_snapshot(monkeypatch):
    """All 11 tools register in the original order with the original parameters and docstrings."""
    tools = {}

    def make_registry(_server):
        def tool(**_kwargs):
            def decorator(func):
                tools[func.__name__] = func
                return func

            return decorator

        return SimpleNamespace(tool=tool, count=len(tools))

    monkeypatch.setattr(tools_basic, "ToolRegistry", make_registry)
    tools_basic.register_tools(SimpleNamespace())
    assert [(n, ", ".join(inspect.signature(f).parameters)) for n, f in tools.items()] == EXPECTED_TOOLS
    assert all(inspect.getdoc(f) for f in tools.values())


def test_strategy_keyword_construction_and_defaults():
    """SSOStrategy keeps its keyword constructor and defaults."""
    strategy = SSOStrategy(name="x", target_url="https://t", success_url_pattern="t")
    assert strategy.flow_type is FlowType.INLINE_REDIRECT
    assert strategy.outcome_type is OutcomeType.REDIRECT_ONLY
    assert list(strategy.sso_url_patterns) == ["auth.redhat.com", "sso.redhat.com"]
    assert strategy.selectors.username == "#username"
    assert KNOWN_STRATEGIES["inscope"].cookie_names == ["connect.sid"]


def test_result_to_dict_and_immutable_default_cookies():
    """SSOResult serialises as before; the default cookie mapping cannot be mutated."""
    result = SSOResult(True, "s", FlowType.POPUP, OutcomeType.JWT_TOKEN, jwt_token="a" * 60)
    data = result.to_dict()
    assert data["jwt_token"] == "a" * 50 + "..."
    assert data["flow_type"] == "POPUP"
    assert not data["cookies"]
    assert not hasattr(result.cookies, "__setitem__")


def _authenticator(tmp_path, page=None, cookies=()):
    auth = sso_authenticator.SSOAuthenticator(screenshot_dir=tmp_path)

    async def get_cookies():
        return list(cookies)

    vars(auth)["_page"] = page
    vars(auth)["_context"] = SimpleNamespace(cookies=get_cookies)
    return auth


async def test_extract_cookies_returns_new_result(tmp_path):
    """Only configured cookies are kept, cached to disk, and returned on a new result."""
    cache = tmp_path / "cookies"
    strategy = SSOStrategy(name="s", target_url="t", cookie_names=["sid"], cookie_cache_path=str(cache))
    auth = _authenticator(tmp_path, cookies=[{"name": "sid", "value": "1"}, {"name": "other", "value": "2"}])
    base = SSOResult(True, "s", FlowType.INLINE_REDIRECT, OutcomeType.SESSION_COOKIE)
    result = await vars(type(auth))["_extract_cookies"](auth, strategy, base)
    assert dict(result.cookies) == {"sid": "1"}
    assert not base.cookies
    assert cache.read_text(encoding="utf-8") == "sid=1"


async def test_extract_jwt_from_storage(tmp_path, monkeypatch):
    """The first stored token is used, its expiry decoded and the cache written."""
    calls = []

    async def evaluate(script):
        calls.append(script)
        return "tok" if "sessionStorage.getItem('token')" in script else None

    cache = tmp_path / "token"
    strategy = SSOStrategy(name="s", target_url="t", jwt_cache_path=str(cache), outcome_type=OutcomeType.JWT_TOKEN)
    auth = _authenticator(tmp_path, page=SimpleNamespace(evaluate=evaluate))
    monkeypatch.setattr(sso_authenticator, "decode_jwt_expiry", lambda token: 1234)
    base = SSOResult(True, "s", FlowType.INLINE_REDIRECT, OutcomeType.JWT_TOKEN)
    result = await vars(type(auth))["_extract_jwt"](auth, strategy, base)
    assert (result.jwt_token, result.jwt_expires_at) == ("tok", 1234)
    assert json.loads(cache.read_text(encoding="utf-8"))["expires_at"] == 1234
    assert len(calls) == 4  # 3 localStorage keys, then the first sessionStorage key


async def test_take_screenshot_without_page(tmp_path):
    """No page means no screenshot."""
    assert await _authenticator(tmp_path).take_screenshot("x") is None


def test_check_session_reports_cache_state(tmp_path, monkeypatch):
    """Token and cookie cache states for sso_check_session."""
    token = tmp_path / "token"
    cookies = tmp_path / "cookies"
    strategy = SSOStrategy(name="demo", target_url="t", jwt_cache_path=str(token), cookie_cache_path=str(cookies))
    monkeypatch.setitem(KNOWN_STRATEGIES, "demo", strategy)

    out = sso_tool_impls.sso_check_session_impl("demo")
    assert "No cached token" in out
    assert "No cached cookies" in out

    token.write_text(json.dumps({"token": "t", "expires_at": int(time.time()) + 600}), encoding="utf-8")
    cookies.write_text("sid=1", encoding="utf-8")
    out = sso_tool_impls.sso_check_session_impl("demo")
    assert "✅ **Token Status:** Valid" in out
    assert "Cached at" in out

    token.write_text(json.dumps({"token": "t", "expires_at": None}), encoding="utf-8")
    assert "Error reading token" in sso_tool_impls.sso_check_session_impl("demo")
    assert sso_tool_impls.sso_check_session_impl("nope").startswith("❌ Unknown strategy: nope")


def test_request_kwargs_injects_csrf():
    """Write methods get _csrf in the JSON body; reads do not."""
    request_kwargs = vars(sso_tool_impls)["_request_kwargs"]
    meta = {"csrf": "c"}
    assert request_kwargs("POST", meta, None, None)["json"] == {"_csrf": "c"}
    assert request_kwargs("PUT", meta, None, {"_csrf": "keep"})["json"] == {"_csrf": "keep"}
    assert request_kwargs("GET", meta, {"q": 1}, None) == {"follow_redirects": True, "params": {"q": 1}}


def test_saml_helpers():
    """finishLoginLink extraction (either attribute order) and URL resolution."""
    finish = vars(sso_http)["_finish_login_url"]
    html = '<p>You are successfully logged in</p><a href="/x?a=1&amp;b=2" id="finishLoginLink">go</a>'
    assert finish(html) == "/x?a=1&b=2"
    assert finish('<a id="finishLoginLink" href="/y">') is None
    absolute = vars(sso_http)["_absolute"]
    assert absolute("/p", "https://h.example/q?x") == "https://h.example/p"
    assert absolute("https://o/p", "https://h") == "https://o/p"


async def test_browser_tool_validation_messages():
    """Argument validation happens before a browser is launched."""
    assert (await sso_browser.browser_click_impl("", "", 1)).startswith("At least one")
    assert (await sso_browser.browser_fill_impl("", "v", 1)) == "The 'selector' parameter is required."
    assert (await sso_browser.browser_navigate_impl("u", "bogus", 1)).startswith("Invalid wait_for value")
    assert (await sso_browser.browser_wait_for_impl("s", "", 1, "bogus")).startswith("Invalid state value")
    assert vars(sso_browser)["_snapshot_path"]("a b/c").name.startswith("a_b_c_")


async def test_browser_session_reuse_and_close(monkeypatch):
    """A live page is reused; closing clears the session."""
    session = vars(sso_browser)["_SESSION"]
    closed = []

    async def close():
        closed.append("browser")

    async def stop():
        closed.append("playwright")

    page = SimpleNamespace(url="https://x")
    monkeypatch.setattr(session, "page", page)
    monkeypatch.setattr(session, "browser", SimpleNamespace(close=close))
    monkeypatch.setattr(session, "playwright", SimpleNamespace(stop=stop))
    assert await vars(sso_browser)["_get_or_create_browser"]() is page
    await vars(sso_browser)["_close_browser"]()
    assert closed == ["browser", "playwright"]
    assert session.page is None
