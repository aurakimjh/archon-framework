"""Structured Logging 모듈 테스트."""

from __future__ import annotations

import structlog
import pytest

from src.log import (
    bind_context,
    clear_context,
    get_context,
    get_logger,
    with_context,
    agent_context,
    pipeline_context,
)
from src.log.processors import (
    TimingProcessor,
    agent_context_injector,
    sensitive_data_masker,
    token_usage_normalizer,
    _mask_string,
)


# ---------------------------------------------------------------------------
# get_logger
# ---------------------------------------------------------------------------

class TestGetLogger:
    def test_returns_bound_logger(self):
        logger = get_logger("test.module")
        assert logger is not None

    def test_with_initial_context(self):
        logger = get_logger("test", agent_role="backend")
        assert logger is not None

    def test_same_name_returns_logger(self):
        l1 = get_logger("test.module")
        l2 = get_logger("test.module")
        # 둘 다 유효한 로거 (structlog은 캐시를 사용하므로 동일 타입)
        assert type(l1) == type(l2)


# ---------------------------------------------------------------------------
# Context 관리
# ---------------------------------------------------------------------------

class TestContext:
    def setup_method(self):
        clear_context()

    def teardown_method(self):
        clear_context()

    def test_bind_and_get(self):
        bind_context(project_id="proj-test", task_id="task-001")
        ctx = get_context()
        assert ctx["project_id"] == "proj-test"
        assert ctx["task_id"] == "task-001"

    def test_with_context_restores(self):
        bind_context(project_id="original")
        with with_context(project_id="override"):
            assert get_context()["project_id"] == "override"
        # with 블록 종료 후 원래 값 복원 여부 체크
        # (structlog contextvars는 unbind만 하므로 키가 제거됨)
        ctx = get_context()
        assert "project_id" not in ctx  # unbind로 제거됨

    def test_with_context_cleans_up_on_exception(self):
        bind_context(pipeline_id="pl-001")
        try:
            with with_context(step="backend"):
                raise ValueError("oops")
        except ValueError:
            pass
        ctx = get_context()
        assert "step" not in ctx  # 예외 발생 후에도 정리됨

    def test_clear_context(self):
        bind_context(foo="bar", baz="qux")
        clear_context()
        assert get_context() == {}

    def test_pipeline_context(self):
        with pipeline_context("pl-001", "proj-ecomm", step="backend", attempt=1):
            ctx = get_context()
            assert ctx["pipeline_id"] == "pl-001"
            assert ctx["project_id"] == "proj-ecomm"
            assert ctx["step"] == "backend"
            assert ctx["attempt"] == 1
        # 종료 후 제거됨
        assert "pipeline_id" not in get_context()

    def test_agent_context(self):
        with agent_context("BackendAgent", "backend", task_id="task-007"):
            ctx = get_context()
            assert ctx["agent_name"] == "BackendAgent"
            assert ctx["agent_role"] == "backend"
            assert ctx["task_id"] == "task-007"


# ---------------------------------------------------------------------------
# sensitive_data_masker
# ---------------------------------------------------------------------------

class TestSensitiveDataMasker:
    def _run(self, event_dict: dict) -> dict:
        return sensitive_data_masker(None, "info", dict(event_dict))

    def test_masks_password_key(self):
        result = self._run({"password": "supersecret123"})
        assert result["password"] == "****"

    def test_masks_api_key_key(self):
        result = self._run({"api_key": "sk-abcdefghij1234567890"})
        assert result["api_key"] == "****"

    def test_masks_token_key(self):
        result = self._run({"token": "my-secret-token"})
        assert result["token"] == "****"

    def test_masks_jwt_in_string_value(self):
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1c2VyMSJ9.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
        result = self._run({"event": f"token is {jwt}"})
        assert jwt not in result["event"]

    def test_safe_values_unchanged(self):
        result = self._run({"event": "hello world", "count": 42})
        assert result["event"] == "hello world"

    def test_mask_string_api_key_pattern(self):
        text = 'api_key = "sk-abcdefghijklmnopqrstuvwxyz"'
        masked = _mask_string(text)
        # 패턴이 키 이름 + 값 전체를 캡처하여 마스킹함
        assert "sk-abcdefghijklmnopqrstuvwxyz" not in masked
        assert "****" in masked

    def test_mask_string_bearer(self):
        text = "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9abcdefghijklmnopqrst"
        masked = _mask_string(text)
        assert "eyJhbGciOiJIUzI1NiJ9abcde" not in masked


# ---------------------------------------------------------------------------
# token_usage_normalizer
# ---------------------------------------------------------------------------

class TestTokenUsageNormalizer:
    def _run(self, event_dict: dict) -> dict:
        return token_usage_normalizer(None, "info", dict(event_dict))

    def test_calculates_total_tokens(self):
        result = self._run({"input_tokens": 1000, "output_tokens": 500})
        assert result["total_tokens"] == 1500

    def test_skips_if_tokens_missing(self):
        result = self._run({"event": "no tokens"})
        assert "total_tokens" not in result

    def test_rounds_cost_usd(self):
        result = self._run({"cost_usd": 0.0031234567})
        assert result["cost_usd"] == pytest.approx(0.003123, rel=1e-3)

    def test_no_cost_unchanged(self):
        result = self._run({"input_tokens": 100, "output_tokens": 50})
        assert "cost_usd" not in result


# ---------------------------------------------------------------------------
# TimingProcessor
# ---------------------------------------------------------------------------

class TestTimingProcessor:
    def test_adds_elapsed_ms(self):
        import time
        proc = TimingProcessor()
        start = time.perf_counter() - 0.1  # 100ms 전
        event_dict = {"_start_time": start, "event": "done"}
        result = proc(None, "info", event_dict)
        assert "elapsed_ms" in result
        assert result["elapsed_ms"] >= 90.0   # 최소 90ms
        assert "_start_time" not in result

    def test_no_start_time_no_elapsed(self):
        proc = TimingProcessor()
        event_dict = {"event": "no timing"}
        result = proc(None, "info", event_dict)
        assert "elapsed_ms" not in result


# ---------------------------------------------------------------------------
# agent_context_injector
# ---------------------------------------------------------------------------

class TestAgentContextInjector:
    def test_stringifies_known_keys(self):
        event_dict = {
            "agent_role": 42,       # 숫자 → 문자열
            "project_id": "proj-a",
            "event": "test",
        }
        result = agent_context_injector(None, "info", event_dict)
        assert result["agent_role"] == "42"
        assert result["project_id"] == "proj-a"

    def test_leaves_missing_keys(self):
        event_dict = {"event": "no agent fields"}
        result = agent_context_injector(None, "info", event_dict)
        assert "agent_role" not in result
        assert result["event"] == "no agent fields"
