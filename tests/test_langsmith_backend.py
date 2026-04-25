"""LangSmith 트레이싱 백엔드 테스트 — SDK 미설치 시 no-op, 모킹 기반 동작 검증."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.observability.span import LLMCallRecord, SpanContext


# ---------------------------------------------------------------------------
# SDK 미설치 시 no-op 동작
# ---------------------------------------------------------------------------


class TestLangSmithTracerNoSDK:
    """langsmith 패키지가 없을 때 graceful no-op으로 동작하는지 검증."""

    def test_no_sdk_is_not_available(self):
        with patch.dict("sys.modules", {"langsmith": None, "langsmith.run_trees": None}):
            # 모듈 리로드하여 _HAS_LANGSMITH=False 상태로 만듦
            import importlib
            import src.observability.langsmith_backend as mod
            importlib.reload(mod)

            tracer = mod.LangSmithTracer(api_key="test")
            assert tracer.is_available is False

    def test_no_sdk_start_trace(self):
        with patch.dict("sys.modules", {"langsmith": None, "langsmith.run_trees": None}):
            import importlib
            import src.observability.langsmith_backend as mod
            importlib.reload(mod)

            tracer = mod.LangSmithTracer()
            span = tracer.start_trace("test-trace", {"key": "val"})
            assert isinstance(span, SpanContext)
            assert span.name == "test-trace"

    def test_no_sdk_start_span(self):
        with patch.dict("sys.modules", {"langsmith": None, "langsmith.run_trees": None}):
            import importlib
            import src.observability.langsmith_backend as mod
            importlib.reload(mod)

            tracer = mod.LangSmithTracer()
            parent = tracer.start_trace("parent")
            child = tracer.start_span(parent, "child")
            assert child.parent_span_id == parent.span_id

    def test_no_sdk_end_span(self):
        with patch.dict("sys.modules", {"langsmith": None, "langsmith.run_trees": None}):
            import importlib
            import src.observability.langsmith_backend as mod
            importlib.reload(mod)

            tracer = mod.LangSmithTracer()
            span = tracer.start_trace("trace")
            tracer.end_span(span, output={"result": "ok"})
            assert span.duration_ms is not None

    def test_no_sdk_record_llm_call(self):
        with patch.dict("sys.modules", {"langsmith": None, "langsmith.run_trees": None}):
            import importlib
            import src.observability.langsmith_backend as mod
            importlib.reload(mod)

            tracer = mod.LangSmithTracer()
            span = tracer.start_trace("trace")
            record = LLMCallRecord(span_id="s1", model="gpt-4", input_tokens=100, output_tokens=50)
            tracer.record_llm_call(span, record)  # should not raise

    def test_no_sdk_flush_and_shutdown(self):
        with patch.dict("sys.modules", {"langsmith": None, "langsmith.run_trees": None}):
            import importlib
            import src.observability.langsmith_backend as mod
            importlib.reload(mod)

            tracer = mod.LangSmithTracer()
            tracer.flush()
            tracer.shutdown()
            assert tracer._runs == {}


# ---------------------------------------------------------------------------
# SDK 있을 때 (모킹)
# ---------------------------------------------------------------------------


class TestLangSmithTracerWithSDK:
    """langsmith 패키지가 있을 때 실제 호출 흐름 검증 (모킹)."""

    def _make_tracer(self):
        """_HAS_LANGSMITH=True 상태에서 모킹된 클라이언트로 트레이서 생성."""
        import src.observability.langsmith_backend as mod

        mock_client = MagicMock()
        with patch.object(mod, "_HAS_LANGSMITH", True):
            tracer = mod.LangSmithTracer.__new__(mod.LangSmithTracer)
            tracer._project_name = "test-project"
            tracer._runs = {}
            tracer._client = mock_client
        return tracer, mod

    def test_is_available(self):
        tracer, _ = self._make_tracer()
        assert tracer.is_available is True

    def test_start_trace_creates_run(self):
        tracer, mod = self._make_tracer()
        mock_run = MagicMock()
        with patch.object(mod, "_HAS_LANGSMITH", True), \
             patch.object(mod, "RunTree", return_value=mock_run, create=True):
            span = tracer.start_trace("my-trace", {"foo": "bar"})
        assert span.name == "my-trace"
        assert span.span_id in tracer._runs

    def test_end_span_posts_run(self):
        tracer, mod = self._make_tracer()
        mock_run = MagicMock()
        span = SpanContext(name="test")
        tracer._runs[span.span_id] = mock_run

        with patch.object(mod, "_HAS_LANGSMITH", True):
            tracer.end_span(span, output={"result": "ok"})

        mock_run.end.assert_called_once_with(outputs={"result": "ok"})
        mock_run.post.assert_called_once()
        assert span.span_id not in tracer._runs

    def test_end_span_with_error(self):
        tracer, mod = self._make_tracer()
        mock_run = MagicMock()
        span = SpanContext(name="test")
        tracer._runs[span.span_id] = mock_run

        with patch.object(mod, "_HAS_LANGSMITH", True):
            tracer.end_span(span, error="something failed")

        mock_run.end.assert_called_once_with(error="something failed")

    def test_record_llm_call(self):
        tracer, mod = self._make_tracer()
        mock_run = MagicMock()
        mock_run.inputs = {}
        mock_run.outputs = {}
        span = SpanContext(name="test")
        tracer._runs[span.span_id] = mock_run

        record = LLMCallRecord(
            span_id=span.span_id, model="claude-3", input_tokens=200, output_tokens=100,
            latency_ms=500, cost_usd=0.01, status="success",
        )
        with patch.object(mod, "_HAS_LANGSMITH", True):
            tracer.record_llm_call(span, record)

        assert mock_run.inputs["model"] == "claude-3"
        assert mock_run.outputs["input_tokens"] == 200

    def test_shutdown_clears_runs(self):
        tracer, _ = self._make_tracer()
        tracer._runs["span-1"] = MagicMock()
        tracer.shutdown()
        assert tracer._runs == {}
