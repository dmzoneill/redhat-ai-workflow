"""Tests for HTTP session management and SAML auth in aa_sso.

Tests the HTTP session store, SAML HTML parsing helpers, and the
full SAML auth flow with mocked HTTP responses.
"""

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from tool_modules.aa_sso.src.tools_basic import (
    HTTP_SAML_CONFIGS,
    HTTPSAMLConfig,
    _close_all_http_sessions,
    _close_http_session,
    _create_http_session,
    _extract_form_action,
    _extract_hidden_fields,
    _get_http_session,
    _http_sessions,
    _saml_auth_http,
    _SAMLResponseParser,
    _session_meta,
)

# ==================== HTTPSAMLConfig ====================


class TestHTTPSAMLConfig:
    def test_default_csrf_field(self):
        config = HTTPSAMLConfig(
            init_url="/init",
            saml_login_path="/saml/login",
            saml_acs_path="/saml/acs",
            sso_login_path="/sso/login",
        )
        assert config.csrf_field == "_csrf"

    def test_custom_csrf_field(self):
        config = HTTPSAMLConfig(
            init_url="/init",
            saml_login_path="/saml/login",
            saml_acs_path="/saml/acs",
            sso_login_path="/sso/login",
            csrf_field="csrfToken",
        )
        assert config.csrf_field == "csrfToken"

    def test_reward_zone_config_exists(self):
        assert "reward_zone" in HTTP_SAML_CONFIGS
        config = HTTP_SAML_CONFIGS["reward_zone"]
        assert config.init_url == "/api/v1/Subprograms/init?subprogramId=102"
        assert config.saml_login_path == "/saml/login"
        assert config.saml_acs_path == "/saml/acs"
        assert config.sso_login_path == "/api/v1/Sso/login"
        assert config.csrf_field == "_csrf"


# ==================== _SAMLResponseParser ====================


class TestSAMLResponseParser:
    def test_extracts_saml_response(self):
        html = """
        <html><body>
        <form method="post" action="https://example.com/saml/acs">
            <input type="hidden" name="SAMLResponse" value="PHNhbWw+dGVzdDwvc2FtbD4=" />
            <input type="hidden" name="RelayState" value="relay123" />
            <input type="submit" value="Submit" />
        </form>
        </body></html>
        """
        parser = _SAMLResponseParser()
        parser.feed(html)
        assert parser.saml_response == "PHNhbWw+dGVzdDwvc2FtbD4="
        assert parser.relay_state == "relay123"
        assert parser.form_action == "https://example.com/saml/acs"

    def test_no_saml_response(self):
        html = "<html><body><p>Not a SAML form</p></body></html>"
        parser = _SAMLResponseParser()
        parser.feed(html)
        assert parser.saml_response is None
        assert parser.relay_state is None

    def test_saml_response_without_relay_state(self):
        html = """
        <form method="post" action="/acs">
            <input type="hidden" name="SAMLResponse" value="abc123" />
        </form>
        """
        parser = _SAMLResponseParser()
        parser.feed(html)
        assert parser.saml_response == "abc123"
        assert parser.relay_state is None

    def test_extracts_form_action(self):
        html = """
        <form method="post" action="https://sp.example.com/saml/acs">
            <input type="hidden" name="SAMLResponse" value="data" />
        </form>
        """
        parser = _SAMLResponseParser()
        parser.feed(html)
        assert parser.form_action == "https://sp.example.com/saml/acs"


# ==================== _extract_form_action ====================


class TestExtractFormAction:
    def test_keycloak_form(self):
        html = (
            '<form id="kc-form-login"'
            ' action="https://auth.example.com/auth/realms/'
            "SSO/login-actions/authenticate"
            '?session_code=abc&amp;execution=123"'
            ' method="post">'
        )
        result = _extract_form_action(html)
        assert result is not None
        assert "authenticate" in result
        assert "session_code=abc" in result
        # &amp; should be unescaped
        assert "&amp;" not in result

    def test_generic_authenticate_form(self):
        html = '<form method="post" action="/login/authenticate?code=xyz">'
        result = _extract_form_action(html)
        assert result == "/login/authenticate?code=xyz"

    def test_fallback_post_form(self):
        html = '<form method="post" action="/submit">'
        result = _extract_form_action(html)
        assert result == "/submit"

    def test_no_form(self):
        html = "<html><body>No form here</body></html>"
        result = _extract_form_action(html)
        assert result is None

    def test_get_form_ignored_unless_fallback(self):
        # A GET form shouldn't match the POST fallback
        html = '<form method="get" action="/search">'
        result = _extract_form_action(html)
        assert result is None


# ==================== _extract_hidden_fields ====================


class TestExtractHiddenFields:
    def test_extracts_hidden_inputs(self):
        html = """
        <form>
            <input type="hidden" name="session_code" value="abc123" />
            <input type="hidden" name="execution" value="exec456" />
            <input type="hidden" name="tab_id" value="tab789" />
            <input type="text" name="username" value="" />
        </form>
        """
        fields = _extract_hidden_fields(html)
        assert fields["session_code"] == "abc123"
        assert fields["execution"] == "exec456"
        assert fields["tab_id"] == "tab789"
        assert "username" not in fields  # not hidden

    def test_empty_value(self):
        html = '<input type="hidden" name="token" value="" />'
        fields = _extract_hidden_fields(html)
        assert fields["token"] == ""

    def test_no_hidden_fields(self):
        html = '<form><input type="text" name="q" value="test" /></form>'
        fields = _extract_hidden_fields(html)
        assert fields == {}

    def test_reverse_attribute_order(self):
        # value before name
        html = '<input type="hidden" value="val123" name="field1" />'
        fields = _extract_hidden_fields(html)
        assert fields["field1"] == "val123"


# ==================== HTTP Session Lifecycle ====================


class TestHTTPSessionLifecycle:
    @pytest.fixture(autouse=True)
    async def cleanup_sessions(self):
        """Clean up any sessions created during tests."""
        yield
        await _close_all_http_sessions()

    async def test_create_session(self):
        client, meta = await _create_http_session("test_session", "https://example.com")
        assert isinstance(client, httpx.AsyncClient)
        assert meta["base_url"] == "https://example.com"
        assert meta["csrf"] is None
        assert meta["pin"] is None
        assert "test_session" in _http_sessions

    async def test_get_existing_session(self):
        await _create_http_session("test_session", "https://example.com")
        client, meta = await _get_http_session("test_session")
        assert isinstance(client, httpx.AsyncClient)
        assert meta["base_url"] == "https://example.com"

    async def test_get_nonexistent_session_raises(self):
        with pytest.raises(KeyError, match="not found"):
            await _get_http_session("nonexistent")

    async def test_close_session(self):
        await _create_http_session("test_session", "https://example.com")
        assert "test_session" in _http_sessions
        await _close_http_session("test_session")
        assert "test_session" not in _http_sessions
        assert "test_session" not in _session_meta

    async def test_close_nonexistent_session_is_noop(self):
        # Should not raise
        await _close_http_session("nonexistent")

    async def test_recreate_replaces_session(self):
        await _create_http_session("test_session", "https://example.com")
        client2, meta2 = await _create_http_session("test_session", "https://other.com")
        assert meta2["base_url"] == "https://other.com"
        # Old client should have been closed, new one stored
        assert _http_sessions["test_session"] is client2

    async def test_close_all_sessions(self):
        await _create_http_session("s1", "https://a.com")
        await _create_http_session("s2", "https://b.com")
        assert len(_http_sessions) == 2
        await _close_all_http_sessions()
        assert len(_http_sessions) == 0
        assert len(_session_meta) == 0


# ==================== _saml_auth_http ====================


class TestSAMLAuthHTTP:
    """Test the 8-phase SAML auth flow with mocked HTTP responses."""

    @pytest.fixture
    def config(self):
        return HTTPSAMLConfig(
            init_url="/api/v1/init",
            saml_login_path="/saml/login",
            saml_acs_path="/saml/acs",
            sso_login_path="/api/v1/Sso/login",
        )

    @pytest.fixture
    def keycloak_login_html(self):
        """Simulated Keycloak SSO login page HTML."""
        return """
        <html>
        <body>
        <form id="kc-form-login" method="post"
              action="https://auth.redhat.com/auth/realms/EmployeeIDP/login-actions/authenticate?session_code=sess123&amp;execution=exec456&amp;tab_id=tab789">
            <input type="hidden" name="session_code" value="sess123" />
            <input type="hidden" name="execution" value="exec456" />
            <input type="hidden" name="tab_id" value="tab789" />
            <input id="username" name="username" type="text" />
            <input id="password" name="password" type="password" />
            <input id="submit" type="submit" value="Log In" />
        </form>
        </body>
        </html>
        """

    @pytest.fixture
    def saml_response_html(self):
        """Simulated SAML response auto-submit form HTML."""
        return """
        <html>
        <body onload="document.forms[0].submit()">
        <form method="post" action="https://rewardzone.redhat.com/saml/acs">
            <input type="hidden" name="SAMLResponse" value="PHNhbWxSZXNwb25zZT5kYXRhPC9zYW1sUmVzcG9uc2U+" />
            <input type="hidden" name="RelayState" value="relay_state_value" />
        </form>
        </body>
        </html>
        """

    async def test_successful_auth_flow(
        self, config, keycloak_login_html, saml_response_html
    ):
        """Test the full SAML flow with mocked responses at each phase."""
        meta = {"base_url": "https://rewardzone.redhat.com", "csrf": None, "pin": None}

        # Build mock responses for each phase
        # Phase 1: init -> returns JSON with _csrf
        init_response = httpx.Response(
            200,
            json={"_csrf": "csrf_token_123", "subprogram": {"id": 102}},
            request=httpx.Request("GET", "https://rewardzone.redhat.com/api/v1/init"),
        )

        # Phase 2: SAML login -> 302 redirect to SSO
        saml_login_response = httpx.Response(
            302,
            headers={
                "location": "https://auth.redhat.com/auth/realms/EmployeeIDP/protocol/saml?SAMLRequest=xxx"
            },
            request=httpx.Request("GET", "https://rewardzone.redhat.com/saml/login"),
        )

        # Phase 3: SSO login page -> returns HTML form
        sso_page_response = httpx.Response(
            200,
            text=keycloak_login_html,
            request=httpx.Request(
                "GET", "https://auth.redhat.com/auth/realms/EmployeeIDP/protocol/saml"
            ),
        )

        # Phase 4+5: POST credentials -> returns SAML response HTML
        credentials_response = httpx.Response(
            200,
            text=saml_response_html,
            request=httpx.Request(
                "POST",
                "https://auth.redhat.com/auth/realms/EmployeeIDP/login-actions/authenticate",
            ),
        )

        # Phase 6: POST SAMLResponse to ACS -> 302 to /sso/{token}
        acs_response = httpx.Response(
            302,
            headers={"location": "/sso/session_token_abc"},
            request=httpx.Request("POST", "https://rewardzone.redhat.com/saml/acs"),
        )

        # Phase 6b: Follow redirect to /sso/{token}
        sso_redirect_response = httpx.Response(
            200,
            text="OK",
            request=httpx.Request(
                "GET", "https://rewardzone.redhat.com/sso/session_token_abc"
            ),
        )

        # Phase 7: POST SSO login with session token
        sso_login_response = httpx.Response(
            200,
            json={"pin": "12345", "_csrf": "new_csrf_456"},
            request=httpx.Request(
                "POST", "https://rewardzone.redhat.com/api/v1/Sso/login"
            ),
        )

        # Set up the client mock
        client = AsyncMock(spec=httpx.AsyncClient)
        client.base_url = httpx.URL("https://rewardzone.redhat.com")
        client.headers = {}

        # Configure get/post responses in order
        client.get = AsyncMock(
            side_effect=[init_response, saml_login_response, sso_redirect_response]
        )
        client.post = AsyncMock(side_effect=[acs_response, sso_login_response])

        # Mock the SSO client (used for phases 3-5)
        mock_sso_client = AsyncMock()
        mock_sso_client.get = AsyncMock(return_value=sso_page_response)
        mock_sso_client.post = AsyncMock(return_value=credentials_response)

        # We need to mock httpx.AsyncClient context manager for the SSO client
        with patch(
            "tool_modules.aa_sso.src.tools_basic.httpx.AsyncClient"
        ) as MockClient:
            mock_cm = AsyncMock()
            mock_cm.__aenter__ = AsyncMock(return_value=mock_sso_client)
            mock_cm.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_cm

            result = await _saml_auth_http(
                client, meta, config, "testuser", "testpass123"
            )

        assert result["success"] is True
        assert result["pin"] == "12345"
        assert result["session_token"] == "session_token_abc"
        assert meta["pin"] == "12345"
        assert meta["csrf"] == "new_csrf_456"

    async def test_init_failure(self, config):
        """Test that init endpoint failure returns error."""
        meta = {"base_url": "https://example.com", "csrf": None, "pin": None}

        client = AsyncMock(spec=httpx.AsyncClient)
        client.base_url = httpx.URL("https://example.com")

        init_response = httpx.Response(
            500,
            text="Internal Server Error",
            request=httpx.Request("GET", "https://example.com/api/v1/init"),
        )
        client.get = AsyncMock(return_value=init_response)

        result = await _saml_auth_http(client, meta, config, "testuser", "testpass")
        assert result["success"] is False
        assert "Init failed" in result["error"]

    async def test_saml_login_no_redirect(self, config):
        """Test that SAML login without redirect returns error."""
        meta = {"base_url": "https://example.com", "csrf": None, "pin": None}

        client = AsyncMock(spec=httpx.AsyncClient)
        client.base_url = httpx.URL("https://example.com")

        init_response = httpx.Response(
            200,
            json={"_csrf": "token"},
            request=httpx.Request("GET", "https://example.com/api/v1/init"),
        )
        saml_response = httpx.Response(
            200,
            text="<html>Not a redirect</html>",
            request=httpx.Request("GET", "https://example.com/saml/login"),
        )
        client.get = AsyncMock(side_effect=[init_response, saml_response])

        result = await _saml_auth_http(client, meta, config, "testuser", "testpass")
        assert result["success"] is False
        assert "did not redirect" in result["error"]

    async def test_invalid_credentials(self, config, keycloak_login_html):
        """Test that invalid credentials error is detected."""
        meta = {"base_url": "https://example.com", "csrf": None, "pin": None}

        client = AsyncMock(spec=httpx.AsyncClient)
        client.base_url = httpx.URL("https://example.com")
        client.headers = {}

        init_response = httpx.Response(
            200,
            json={"_csrf": "token"},
            request=httpx.Request("GET", "https://example.com/api/v1/init"),
        )
        saml_login_response = httpx.Response(
            302,
            headers={"location": "https://auth.redhat.com/login"},
            request=httpx.Request("GET", "https://example.com/saml/login"),
        )
        client.get = AsyncMock(side_effect=[init_response, saml_login_response])

        sso_page_response = httpx.Response(
            200,
            text=keycloak_login_html,
            request=httpx.Request("GET", "https://auth.redhat.com/login"),
        )
        error_html = """
        <html><body>
        <div class="alert-error">
            <span>Invalid username or password.</span>
        </div>
        </body></html>
        """
        credentials_response = httpx.Response(
            200,
            text=error_html,
            request=httpx.Request("POST", "https://auth.redhat.com/authenticate"),
        )

        mock_sso_client = AsyncMock()
        mock_sso_client.get = AsyncMock(return_value=sso_page_response)
        mock_sso_client.post = AsyncMock(return_value=credentials_response)

        with patch(
            "tool_modules.aa_sso.src.tools_basic.httpx.AsyncClient"
        ) as MockClient:
            mock_cm = AsyncMock()
            mock_cm.__aenter__ = AsyncMock(return_value=mock_sso_client)
            mock_cm.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_cm

            result = await _saml_auth_http(
                client, meta, config, "testuser", "wrongpass"
            )

        assert result["success"] is False
        assert "Invalid username or password" in result["error"]

    async def test_no_saml_response_in_html(self, config, keycloak_login_html):
        """Test that missing SAMLResponse in credentials response returns error."""
        meta = {"base_url": "https://example.com", "csrf": None, "pin": None}

        client = AsyncMock(spec=httpx.AsyncClient)
        client.base_url = httpx.URL("https://example.com")
        client.headers = {}

        init_response = httpx.Response(
            200,
            json={"_csrf": "token"},
            request=httpx.Request("GET", "https://example.com/api/v1/init"),
        )
        saml_login_response = httpx.Response(
            302,
            headers={"location": "https://auth.redhat.com/login"},
            request=httpx.Request("GET", "https://example.com/saml/login"),
        )
        client.get = AsyncMock(side_effect=[init_response, saml_login_response])

        sso_page_response = httpx.Response(
            200,
            text=keycloak_login_html,
            request=httpx.Request("GET", "https://auth.redhat.com/login"),
        )
        # Response without SAMLResponse (e.g., MFA page or other intermediate page)
        no_saml_html = "<html><body><p>Some other page</p></body></html>"
        credentials_response = httpx.Response(
            200,
            text=no_saml_html,
            request=httpx.Request("POST", "https://auth.redhat.com/authenticate"),
        )

        mock_sso_client = AsyncMock()
        mock_sso_client.get = AsyncMock(return_value=sso_page_response)
        mock_sso_client.post = AsyncMock(return_value=credentials_response)

        with patch(
            "tool_modules.aa_sso.src.tools_basic.httpx.AsyncClient"
        ) as MockClient:
            mock_cm = AsyncMock()
            mock_cm.__aenter__ = AsyncMock(return_value=mock_sso_client)
            mock_cm.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_cm

            result = await _saml_auth_http(client, meta, config, "testuser", "testpass")

        assert result["success"] is False
        assert "SAMLResponse" in result["error"]

    async def test_acs_no_redirect(
        self, config, keycloak_login_html, saml_response_html
    ):
        """Test that ACS not redirecting returns error."""
        meta = {"base_url": "https://example.com", "csrf": None, "pin": None}

        client = AsyncMock(spec=httpx.AsyncClient)
        client.base_url = httpx.URL("https://example.com")
        client.headers = {}

        init_response = httpx.Response(
            200,
            json={"_csrf": "token"},
            request=httpx.Request("GET", "https://example.com/api/v1/init"),
        )
        saml_login_response = httpx.Response(
            302,
            headers={"location": "https://auth.redhat.com/login"},
            request=httpx.Request("GET", "https://example.com/saml/login"),
        )
        # ACS returns 200 instead of 302
        acs_response = httpx.Response(
            200,
            text="Error",
            request=httpx.Request("POST", "https://example.com/saml/acs"),
        )
        client.get = AsyncMock(side_effect=[init_response, saml_login_response])
        client.post = AsyncMock(return_value=acs_response)

        sso_page_response = httpx.Response(
            200,
            text=keycloak_login_html,
            request=httpx.Request("GET", "https://auth.redhat.com/login"),
        )
        credentials_response = httpx.Response(
            200,
            text=saml_response_html,
            request=httpx.Request("POST", "https://auth.redhat.com/authenticate"),
        )

        mock_sso_client = AsyncMock()
        mock_sso_client.get = AsyncMock(return_value=sso_page_response)
        mock_sso_client.post = AsyncMock(return_value=credentials_response)

        with patch(
            "tool_modules.aa_sso.src.tools_basic.httpx.AsyncClient"
        ) as MockClient:
            mock_cm = AsyncMock()
            mock_cm.__aenter__ = AsyncMock(return_value=mock_sso_client)
            mock_cm.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_cm

            result = await _saml_auth_http(client, meta, config, "testuser", "testpass")

        assert result["success"] is False
        assert "ACS did not redirect" in result["error"]

    async def test_csrf_stored_from_init(self, config):
        """Test that _csrf extracted from init is stored in meta."""
        meta = {"base_url": "https://example.com", "csrf": None, "pin": None}

        client = AsyncMock(spec=httpx.AsyncClient)
        client.base_url = httpx.URL("https://example.com")

        init_response = httpx.Response(
            200,
            json={"_csrf": "my_csrf_token", "data": {}},
            request=httpx.Request("GET", "https://example.com/api/v1/init"),
        )
        # SAML login returns non-redirect to stop flow early
        saml_response = httpx.Response(
            200,
            text="Not a redirect",
            request=httpx.Request("GET", "https://example.com/saml/login"),
        )
        client.get = AsyncMock(side_effect=[init_response, saml_response])

        await _saml_auth_http(client, meta, config, "testuser", "testpass")
        # Flow fails at phase 2, but csrf should be stored from phase 1
        assert meta["csrf"] == "my_csrf_token"
