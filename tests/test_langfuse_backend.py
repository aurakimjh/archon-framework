"""Langfuse 트레이싱 백엔드 테스트 — SDK 미설치 시 no-op, 모킹 기반 동작 검증."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.observability.span import LLMCallRecord, SpanContext


# ---------------------------------------------------------------------------
# SDK 미설치 시 no-op 동작
# ---------------------------------------------------------------------------


class TestLangfuseTracerNoSDK:
    def test_no_sdk_is_not_available(self):
        with patch.dict("sys.modules", {"langfuse": None}):
            import importlib
            import src.observability.langfuse_backend as mod
            importlib.reload(mod)

            tracer = mod.LangfuseTracer(public_key="pk", secret_key="sk")
            assert tracer.is_available is False

    def test_no_sdk_start_trace(self):
        with patch.dict("sys.modules", {"langfuse": None}):
            import importlib
            import src.observability.langfuse_backend as mod
            importlib.reload(mod)

            tracer = mod.LangfuseTracer()
            span = tracer.start_trace("trace", {"k": "v"})
            assert isinstance(span, SpanContext)

    def test_no_sdk_start_span(self):
        with patch.dict("sys.modules", {"langfuse": None}):
            import importlib
            import src.observability.langfuse_backend as mod
            importlib.reload(mod)

            tracer = mod.LangfuseTracer()
            parent = tracer.start_trace("parent")
            child = tracer.start_span(parent, "child")
            assert child.trace_id == parent.trace_id

    def test_no_sdk_end_span(self):
        with patch.dict("sys.modules", {"langfuse": None}):
            import importlib
            import src.observability.langfuse_backend as mod
            importlib.reload(mod)

            tracer = mod.LangfuseTracer()
            span = tracer.start_trace("trace")
            tracer.end_span(span, output={"ok": True})
            assert span.duration_ms is not None

    def test_no_sdk_record_llm_call(self):
        with patch.dict("sys.modules", {"langfuse": None}):
            import importlib
            import src.observability.langfuse_backend as mod
            importlib.reload(mod)

            tracer = mod.LangfuseTracer()
            span = tracer.start_trace("trace")
            record = LLMCallRecord(span_id="s1", model="gpt-4", input_tokens=100, output_tokens=50)
            tracer.record_llm_call(span, record)

    def test_no_sdk_flush_and_shutdown(self):
        with patch.dict("sys.modules", {"langfuse": None}):
            import importlib
            import src.observability.langfuse_backend as mod
            importlib.reload(mod)

            tracer = mod.LangfuseTracer()
            tracer.flush()
            tracer.shutdown()


# ---------------------------------------------------------------------------
# SDK 있을 때 (모킹)
# ---------------------------------------------------------------------------


class TestLangfuseTracerWithSDK:
    def _make_tracer(self):
        import src.observability.langfuse_backend as mod

        mock_client = MagicMock()
        with patch.object(mod, "_HAS_LANGFUSE", True):
            tracer = mod.LangfuseTracer.__new__(mod.LangfuseTracer)
            tracer._traces = {}
            tracer._spans = {}
            tracer._client = mock_client
        return tracer, mod, mock_client

    def test_is_available(self):
        tracer, _, _ = self._make_tracer()
        assert tracer.is_available is True

    def test_start_trace_creates_trace(self):
        tracer, mod, mock_client = self._make_tracer()
        mock_trace = MagicMock()
        mock_client.trace.return_value = mock_trace

        with patch.object(mod, "_HAS_LANGFUSE", True):
            span = tracer.start_trace("my-trace", {"key": "val"})

        assert span.name == "my-trace"
        assert span.trace_id in tracer._traces
        mock_client.trace.assert_called_once()

    def test_start_span_creates_child(self):
        tracer, mod, mock_client = self._make_tracer()
        mock_trace = MagicMock()
        mock_lf_span = MagicMock()
        mock_trace.span.return_value = mock_lf_span

        parent = SpanContext(name="parent")
        tracer._traces[parent.trace_id] = mock_trace

        with patch.object(mod, "_HAS_LANGFUSE", True):
            child = tracer.start_span(parent, "child", {"meta": "data"})

        assert child.parent_span_id == parent.span_id
        assert child.span_id in tracer._spans

    def test_start_span_no_parent_trace(self):
        tracer, mod, _ = self._make_tracer()
        parent = SpanContext(name="orphan")
        # No trace registered for parent

        with patch.object(mod, "_HAS_LANGFUSE", True):
            child = tracer.start_span(parent, "child")

        assert child.parent_span_id == parent.span_id
        assert child.span_id not in tracer._spans  # no lf_span created

    def test_end_span(self):
        tracer, mod, _ = self._make_tracer()
        mock_lf_span = MagicMock()
        span = SpanContext(name="test")
        tracer._spans[span.span_id] = mock_lf_span

        with patch.object(mod, "_HAS_LANGFUSE", True):
            tracer.end_span(span, output={"result": "ok"})

        mock_lf_span.end.assert_called_once()
        assert span.span_id not in tracer._spans

    def test_end_span_with_error(self):
        tracer, mod, _ = self._make_tracer()
        mock_lf_span = MagicMock()
        span = SpanContext(name="test")
        tracer._spans[span.span_id] = mock_lf_span

        with patch.object(mod, "_HAS_LANGFUSE", True):
            tracer.end_span(span, error="something broke")

        call_kwargs = mock_lf_span.end.call_args[1]
        assert call_kwargs["level"] == "ERROR"
        assert call_kwargs["status_message"] == "something broke"

    def test_record_llm_call(self):
        tracer, mod, _ = self._make_tracer()
        mock_trace = MagicMock()
        span = SpanContext(name="test")
        tracer._traces[span.trace_id] = mock_trace

        record = LLMCallRecord(
            span_id=span.span_id, model="claude-3", input_tokens=200, output_tokens=100,
            latency_ms=500, cost_usd=0.01, status="success",
        )
        with patch.object(mod, "_HAS_LANGFUSE", True):
            tracer.record_llm_call(span, record)

        mock_trace.generation.assert_called_once()
        call_kwargs = mock_trace.generation.call_args[1]
        assert call_kwargs["model"] == "claude-3"
        assert call_kwargs["usage"]["input"] == 200

    def test_flush(self):
        tracer, mod, mock_client = self._make_tracer()
        with patch.object(mod, "_HAS_LANGFUSE", True):
            tracer.flush()
        mock_client.flush.assert_called_once()

    def test_shutdown(self):
        tracer, mod, mock_client = self._make_tracer()
        tracer._traces["t1"] = MagicMock()
        tracer._spans["s1"] = MagicMock()

        with patch.object(mod, "_HAS_LANGFUSE", True):
            tracer.shutdown()

        assert tracer._traces == {}
        assert tracer._spans == {}
        mock_client.shutdown.assert_called_once()
