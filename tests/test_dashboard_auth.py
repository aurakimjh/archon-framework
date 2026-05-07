"""Dashboard 인증 테스트 — auth 모듈 + REST/WebSocket 인증 통합."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from src.dashboard.auth import (
    extract_bearer_token,
    extract_ws_token,
    get_dashboard_token,
    verify_token,
)


# ---------------------------------------------------------------------------
# get_dashboard_token
# ---------------------------------------------------------------------------


class TestGetDashboardToken:
    def test_returns_none_when_unset(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("ARCHON_DASHBOARD_TOKEN", None)
            assert get_dashboard_token() is None

    def test_returns_token_when_set(self):
        with patch.dict(os.environ, {"ARCHON_DASHBOARD_TOKEN": "secret123"}):
            assert get_dashboard_token() == "secret123"

    def test_empty_string_returns_none(self):
        with patch.dict(os.environ, {"ARCHON_DASHBOARD_TOKEN": ""}):
            assert get_dashboard_token() is None


# ---------------------------------------------------------------------------
# verify_token
# ---------------------------------------------------------------------------


class TestVerifyToken:
    def test_no_expected_always_passes(self):
        assert verify_token(None, None) is True
        assert verify_token("anything", None) is True

    def test_no_provided_fails(self):
        assert verify_token(None, "secret") is False

    def test_matching_tokens(self):
        assert verify_token("my-secret", "my-secret") is True

    def test_mismatched_tokens(self):
        assert verify_token("wrong", "secret") is False

    def test_timing_safe(self):
        # verify_token uses hmac.compare_digest
        assert verify_token("a" * 100, "a" * 100) is True
        assert verify_token("a" * 100, "b" * 100) is False


# ---------------------------------------------------------------------------
# extract_bearer_token
# ---------------------------------------------------------------------------


class TestExtractBearerToken:
    def test_none_header(self):
        assert extract_bearer_token(None) is None

    def test_empty_header(self):
        assert extract_bearer_token("") is None

    def test_valid_bearer(self):
        assert extract_bearer_token("Bearer my-token-123") == "my-token-123"

    def test_case_insensitive(self):
        assert extract_bearer_token("bearer my-token") == "my-token"
        assert extract_bearer_token("BEARER my-token") == "my-token"

    def test_no_bearer_prefix(self):
        assert extract_bearer_token("Basic dXNlcjpwYXNz") is None

    def test_bearer_only(self):
        # "Bearer " with no token
        assert extract_bearer_token("Bearer ") == ""

    def test_strips_whitespace(self):
        assert extract_bearer_token("Bearer  my-token  ") == "my-token"


# ---------------------------------------------------------------------------
# extract_ws_token
# ---------------------------------------------------------------------------


class TestExtractWsToken:
    def test_from_params_dict(self):
        assert extract_ws_token(params={"token": "abc123"}) == "abc123"

    def test_from_params_list(self):
        assert extract_ws_token(params={"token": ["abc123"]}) == "abc123"

    def test_from_query_string(self):
        assert extract_ws_token(query_string="token=abc123") == "abc123"

    def test_from_query_string_multiple_params(self):
        assert extract_ws_token(query_string="foo=bar&token=secret&baz=1") == "secret"

    def test_no_token_in_query(self):
        assert extract_ws_token(query_string="foo=bar&baz=1") is None

    def test_none_inputs(self):
        assert extract_ws_token() is None

    def test_params_takes_precedence(self):
        result = extract_ws_token(
            query_string="token=from_qs",
            params={"token": "from_params"},
        )
        assert result == "from_params"


# ---------------------------------------------------------------------------
# REST API 인증 통합 (FastAPI TestClient)
# ---------------------------------------------------------------------------


try:
    from fastapi.testclient import TestClient

    _HAS_TESTCLIENT = True
except ImportError:
    _HAS_TESTCLIENT = False


@pytest.mark.skipif(not _HAS_TESTCLIENT, reason="fastapi not installed")
class TestRESTAuth:
    def _make_app(self, token: str | None = None):
        """토큰이 설정된 상태에서 앱을 생성한다. DB는 in-memory 격리."""
        from src.dashboard.app import DashboardApp
        env = {"ARCHON_DASHBOARD_DB_PATH": ":memory:"}
        if token:
            env["ARCHON_DASHBOARD_TOKEN"] = token
        with patch.dict(os.environ, env, clear=False):
            if not token:
                os.environ.pop("ARCHON_DASHBOARD_TOKEN", None)
            app = DashboardApp()
            return app.create_app()

    def test_no_token_all_open(self):
        app = self._make_app(token=None)
        client = TestClient(app)
        resp = client.get("/api/projects")
        assert resp.status_code == 200

    def test_with_token_no_header_401(self):
        app = self._make_app(token="secret123")
        client = TestClient(app)
        with patch.dict(os.environ, {"ARCHON_DASHBOARD_TOKEN": "secret123"}):
            resp = client.get("/api/projects")
        assert resp.status_code == 401

    def test_with_token_wrong_header_401(self):
        app = self._make_app(token="secret123")
        client = TestClient(app)
        with patch.dict(os.environ, {"ARCHON_DASHBOARD_TOKEN": "secret123"}):
            resp = client.get("/api/projects", headers={"Authorization": "Bearer wrong"})
        assert resp.status_code == 401

    def test_with_token_correct_header_200(self):
        app = self._make_app(token="secret123")
        client = TestClient(app)
        with patch.dict(os.environ, {"ARCHON_DASHBOARD_TOKEN": "secret123"}):
            resp = client.get("/api/projects", headers={"Authorization": "Bearer secret123"})
        assert resp.status_code == 200

    def test_auth_on_all_endpoints(self):
        app = self._make_app(token="tok")
        client = TestClient(app)
        endpoints = [
            ("GET", "/api/projects"),
            ("GET", "/api/agents"),
            ("GET", "/api/cost"),
            ("GET", "/api/gates/queue"),
            ("GET", "/api/metrics"),
        ]
        with patch.dict(os.environ, {"ARCHON_DASHBOARD_TOKEN": "tok"}):
            for method, path in endpoints:
                resp = client.request(method, path)
                assert resp.status_code == 401, f"{method} {path} should require auth"

            for method, path in endpoints:
                resp = client.request(method, path, headers={"Authorization": "Bearer tok"})
                assert resp.status_code == 200, f"{method} {path} should pass with correct token"


# ---------------------------------------------------------------------------
# WebSocket 인증 통합
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _HAS_TESTCLIENT, reason="fastapi not installed")
class TestWebSocketAuth:
    def _make_app(self, token: str | None = None):
        from src.dashboard.app import DashboardApp
        env = {"ARCHON_DASHBOARD_DB_PATH": ":memory:"}
        if token:
            env["ARCHON_DASHBOARD_TOKEN"] = token
        with patch.dict(os.environ, env, clear=False):
            if not token:
                os.environ.pop("ARCHON_DASHBOARD_TOKEN", None)
            app = DashboardApp()
            return app.create_app()

    def test_ws_no_token_required_connects(self):
        app = self._make_app(token=None)
        client = TestClient(app)
        with client.websocket_connect("/ws") as ws:
            assert ws is not None

    def test_ws_token_required_no_token_rejected(self):
        app = self._make_app(token="ws-secret")
        client = TestClient(app)
        with patch.dict(os.environ, {"ARCHON_DASHBOARD_TOKEN": "ws-secret"}):
            with pytest.raises(Exception):
                with client.websocket_connect("/ws"):
                    pass

    def test_ws_token_required_wrong_token_rejected(self):
        app = self._make_app(token="ws-secret")
        client = TestClient(app)
        with patch.dict(os.environ, {"ARCHON_DASHBOARD_TOKEN": "ws-secret"}):
            with pytest.raises(Exception):
                with client.websocket_connect("/ws?token=wrong"):
                    pass

    def test_ws_token_required_correct_token_connects(self):
        app = self._make_app(token="ws-secret")
        client = TestClient(app)
        with patch.dict(os.environ, {"ARCHON_DASHBOARD_TOKEN": "ws-secret"}):
            with client.websocket_connect("/ws?token=ws-secret") as ws:
                assert ws is not None
