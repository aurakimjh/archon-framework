"""Observability 모듈 테스트 — 트레이싱 설정, 스팬, 트레이서, 미들웨어."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from src.observability.config import TracingBackend, TracingConfig
from src.observability.middleware import TracingMiddleware, create_tracer_from_config
from src.observability.span import LLMCallRecord, SpanContext
from src.observability.tracer import ArchonTracer, CompositeTracer, NoOpTracer, SamplingTracer


# ---------------------------------------------------------------------------
# SpanContext
# ---------------------------------------------------------------------------


class TestSpanContext:
    def test_default_fields(self):
        span = SpanContext()
        assert span.trace_id
        assert span.span_id
        assert span.parent_span_id is None
        assert span.name == ""
        assert span.duration_ms is None

    def test_finish_records_duration(self):
        span = SpanContext()
        time.sleep(0.01)
        span.finish()
        assert span.duration_ms is not None
        assert span.duration_ms >= 0

    def test_child_inherits_trace_id(self):
        parent = SpanContext(name="parent")
        child = parent.child("child", foo="bar")
        assert child.trace_id == parent.trace_id
        assert child.parent_span_id == parent.span_id
        assert child.name == "child"
        assert child.metadata.get("foo") == "bar"

    def test_unique_span_ids(self):
        spans = [SpanContext() for _ in range(10)]
        ids = {s.span_id for s in spans}
        assert len(ids) == 10


class TestLLMCallRecord:
    def test_defaults(self):
        rec = LLMCallRecord(span_id="abc", model="gpt-4")
        assert rec.input_tokens == 0
        assert rec.output_tokens == 0
        assert rec.latency_ms == 0.0
        assert rec.status == "success"
        assert rec.error is None

    def test_with_error(self):
        rec = LLMCallRecord(span_id="abc", model="gpt-4", status="error", error="timeout")
        assert rec.status == "error"
        assert rec.error == "timeout"


# ---------------------------------------------------------------------------
# TracingConfig
# ---------------------------------------------------------------------------


class TestTracingConfig:
    def test_default_disabled(self):
        cfg = TracingConfig()
        assert cfg.backend == TracingBackend.NONE
        assert not cfg.is_enabled
        assert not cfg.use_langsmith
        assert not cfg.use_langfuse

    def test_langsmith_enabled(self):
        cfg = TracingConfig(backend=TracingBackend.LANGSMITH, langsmith_api_key="key")
        assert cfg.is_enabled
        assert cfg.use_langsmith
        assert not cfg.use_langfuse

    def test_langfuse_enabled(self):
        cfg = TracingConfig(backend=TracingBackend.LANGFUSE)
        assert cfg.is_enabled
        assert not cfg.use_langsmith
        assert cfg.use_langfuse

    def test_both_enabled(self):
        cfg = TracingConfig(backend=TracingBackend.BOTH)
        assert cfg.use_langsmith
        assert cfg.use_langfuse

    def test_sample_rate_bounds(self):
        cfg = TracingConfig(sample_rate=0.5)
        assert cfg.sample_rate == 0.5
        with pytest.raises(Exception):
            TracingConfig(sample_rate=1.5)
        with pytest.raises(Exception):
            TracingConfig(sample_rate=-0.1)

    def test_default_project_name(self):
        cfg = TracingConfig()
        assert cfg.langsmith_project == "archon"


# ---------------------------------------------------------------------------
# NoOpTracer
# ---------------------------------------------------------------------------


class TestNoOpTracer:
    def test_start_trace(self):
        tracer = NoOpTracer()
        span = tracer.start_trace("test", {"key": "value"})
        assert span.name == "test"
        assert span.metadata == {"key": "value"}

    def test_start_span(self):
        tracer = NoOpTracer()
        parent = SpanContext(name="parent")
        child = tracer.start_span(parent, "child", {"x": 1})
        assert child.trace_id == parent.trace_id
        assert child.parent_span_id == parent.span_id

    def test_end_span(self):
        tracer = NoOpTracer()
        span = SpanContext(name="test")
        tracer.end_span(span, output={"result": "ok"})
        assert span.duration_ms is not None

    def test_record_llm_call_noop(self):
        tracer = NoOpTracer()
        span = SpanContext()
        record = LLMCallRecord(span_id=span.span_id, model="gpt-4")
        tracer.record_llm_call(span, record)  # no error

    def test_flush_and_shutdown_noop(self):
        tracer = NoOpTracer()
        tracer.flush()
        tracer.shutdown()


# ---------------------------------------------------------------------------
# CompositeTracer
# ---------------------------------------------------------------------------


class TestCompositeTracer:
    def _make_mock_tracer(self) -> MagicMock:
        mock = MagicMock(spec=ArchonTracer)
        mock.start_trace.return_value = SpanContext(name="mock")
        mock.start_span.return_value = SpanContext(name="mock_child")
        return mock

    def test_delegates_start_trace(self):
        t1, t2 = self._make_mock_tracer(), self._make_mock_tracer()
        composite = CompositeTracer([t1, t2])
        span = composite.start_trace("test", {"k": "v"})
        assert span.name == "test"
        t1.start_trace.assert_called_once()
        t2.start_trace.assert_called_once()

    def test_delegates_start_span(self):
        t1 = self._make_mock_tracer()
        composite = CompositeTracer([t1])
        parent = SpanContext(name="parent")
        composite.start_span(parent, "child")
        t1.start_span.assert_called_once()

    def test_delegates_end_span(self):
        t1 = self._make_mock_tracer()
        composite = CompositeTracer([t1])
        span = SpanContext(name="test")
        composite.end_span(span, output={"r": 1})
        t1.end_span.assert_called_once()
        assert span.duration_ms is not None

    def test_delegates_record_llm_call(self):
        t1 = self._make_mock_tracer()
        composite = CompositeTracer([t1])
        span = SpanContext()
        record = LLMCallRecord(span_id=span.span_id, model="gpt-4")
        composite.record_llm_call(span, record)
        t1.record_llm_call.assert_called_once()

    def test_handles_child_failure_gracefully(self):
        t1 = self._make_mock_tracer()
        t1.start_trace.side_effect = RuntimeError("boom")
        t2 = self._make_mock_tracer()
        composite = CompositeTracer([t1, t2])
        span = composite.start_trace("test")
        assert span.name == "test"
        t2.start_trace.assert_called_once()

    def test_tracers_property(self):
        t1, t2 = self._make_mock_tracer(), self._make_mock_tracer()
        composite = CompositeTracer([t1, t2])
        assert len(composite.tracers) == 2

    def test_flush_delegates(self):
        t1 = self._make_mock_tracer()
        composite = CompositeTracer([t1])
        composite.flush()
        t1.flush.assert_called_once()

    def test_shutdown_delegates(self):
        t1 = self._make_mock_tracer()
        composite = CompositeTracer([t1])
        composite.shutdown()
        t1.shutdown.assert_called_once()


# ---------------------------------------------------------------------------
# SamplingTracer
# ---------------------------------------------------------------------------


class TestSamplingTracer:
    def test_sample_rate_1_always_samples(self):
        inner = MagicMock(spec=ArchonTracer)
        inner.start_trace.return_value = SpanContext(name="t")
        inner.start_span.return_value = SpanContext(name="s")
        sampler = SamplingTracer(inner, sample_rate=1.0)
        span = sampler.start_trace("test")
        sampler.start_span(span, "child")
        inner.start_span.assert_called_once()

    def test_sample_rate_0_never_delegates_spans(self):
        inner = MagicMock(spec=ArchonTracer)
        inner.start_trace.return_value = SpanContext(name="t")
        sampler = SamplingTracer(inner, sample_rate=0.0)
        span = sampler.start_trace("test")
        sampler.start_span(span, "child")
        inner.start_span.assert_not_called()

    def test_end_span_consistent_with_sampling(self):
        inner = MagicMock(spec=ArchonTracer)
        inner.start_trace.return_value = SpanContext(name="t")
        sampler = SamplingTracer(inner, sample_rate=0.0)
        span = sampler.start_trace("test")
        sampler.end_span(span)
        inner.end_span.assert_not_called()
        assert span.duration_ms is not None

    def test_record_llm_call_respects_sampling(self):
        inner = MagicMock(spec=ArchonTracer)
        inner.start_trace.return_value = SpanContext(name="t")
        sampler = SamplingTracer(inner, sample_rate=0.0)
        span = sampler.start_trace("test")
        record = LLMCallRecord(span_id=span.span_id, model="m")
        sampler.record_llm_call(span, record)
        inner.record_llm_call.assert_not_called()

    def test_clamps_sample_rate(self):
        inner = MagicMock(spec=ArchonTracer)
        s = SamplingTracer(inner, sample_rate=2.0)
        assert s._sample_rate == 1.0
        s = SamplingTracer(inner, sample_rate=-1.0)
        assert s._sample_rate == 0.0

    def test_shutdown_clears_state(self):
        inner = MagicMock(spec=ArchonTracer)
        inner.start_trace.return_value = SpanContext(name="t")
        sampler = SamplingTracer(inner, sample_rate=1.0)
        sampler.start_trace("test")
        sampler.shutdown()
        inner.shutdown.assert_called_once()


# ---------------------------------------------------------------------------
# LangSmith Backend (mocked)
# ---------------------------------------------------------------------------


class TestLangSmithBackend:
    def test_unavailable_when_no_package(self):
        with patch.dict("sys.modules", {"langsmith": None}):
            # Reimport would be needed but we test the guard pattern
            from src.observability.langsmith_backend import LangSmithTracer

            tracer = LangSmithTracer.__new__(LangSmithTracer)
            tracer._client = None
            tracer._runs = {}
            tracer._project_name = "test"
            assert not tracer.is_available

    def test_start_trace_without_client(self):
        from src.observability.langsmith_backend import LangSmithTracer

        tracer = LangSmithTracer.__new__(LangSmithTracer)
        tracer._client = None
        tracer._runs = {}
        tracer._project_name = "test"
        span = tracer.start_trace("test")
        assert span.name == "test"

    def test_end_span_without_client(self):
        from src.observability.langsmith_backend import LangSmithTracer

        tracer = LangSmithTracer.__new__(LangSmithTracer)
        tracer._client = None
        tracer._runs = {}
        tracer._project_name = "test"
        span = SpanContext(name="test")
        tracer.end_span(span)
        assert span.duration_ms is not None

    def test_shutdown_clears_runs(self):
        from src.observability.langsmith_backend import LangSmithTracer

        tracer = LangSmithTracer.__new__(LangSmithTracer)
        tracer._client = None
        tracer._runs = {"a": 1}
        tracer._project_name = "test"
        tracer.shutdown()
        assert len(tracer._runs) == 0


# ---------------------------------------------------------------------------
# Langfuse Backend (mocked)
# ---------------------------------------------------------------------------


class TestLangfuseBackend:
    def test_unavailable_when_no_client(self):
        from src.observability.langfuse_backend import LangfuseTracer

        tracer = LangfuseTracer.__new__(LangfuseTracer)
        tracer._client = None
        tracer._traces = {}
        tracer._spans = {}
        assert not tracer.is_available

    def test_start_trace_without_client(self):
        from src.observability.langfuse_backend import LangfuseTracer

        tracer = LangfuseTracer.__new__(LangfuseTracer)
        tracer._client = None
        tracer._traces = {}
        tracer._spans = {}
        span = tracer.start_trace("test", {"k": "v"})
        assert span.name == "test"

    def test_end_span_without_client(self):
        from src.observability.langfuse_backend import LangfuseTracer

        tracer = LangfuseTracer.__new__(LangfuseTracer)
        tracer._client = None
        tracer._traces = {}
        tracer._spans = {}
        span = SpanContext(name="test")
        tracer.end_span(span)
        assert span.duration_ms is not None

    def test_shutdown_clears_state(self):
        from src.observability.langfuse_backend import LangfuseTracer

        tracer = LangfuseTracer.__new__(LangfuseTracer)
        tracer._client = None
        tracer._traces = {"t": 1}
        tracer._spans = {"s": 2}
        tracer.shutdown()
        assert len(tracer._traces) == 0
        assert len(tracer._spans) == 0


# ---------------------------------------------------------------------------
# TracingMiddleware
# ---------------------------------------------------------------------------


class TestTracingMiddleware:
    def test_default_noop_tracer(self):
        mw = TracingMiddleware()
        assert isinstance(mw.tracer, NoOpTracer)

    def test_start_pipeline_trace(self):
        mw = TracingMiddleware()
        span = mw.start_pipeline_trace("proj-1", "task-1", extra="data")
        assert "proj-1" in span.name
        assert "task-1" in span.name

    def test_start_agent_span(self):
        mw = TracingMiddleware()
        parent = SpanContext(name="pipeline")
        span = mw.start_agent_span(parent, "backend", "gpt-4")
        assert span.trace_id == parent.trace_id
        assert "backend" in span.name

    def test_start_qa_span(self):
        mw = TracingMiddleware()
        parent = SpanContext(name="pipeline")
        span = mw.start_qa_span(parent)
        assert span.trace_id == parent.trace_id

    def test_start_gate_span(self):
        mw = TracingMiddleware()
        parent = SpanContext(name="pipeline")
        span = mw.start_gate_span(parent)
        assert span.trace_id == parent.trace_id

    def test_end_span(self):
        mw = TracingMiddleware()
        span = SpanContext(name="test")
        mw.end_span(span, output={"result": "ok"})
        assert span.duration_ms is not None

    def test_record_llm_call(self):
        mock_tracer = MagicMock(spec=ArchonTracer)
        mw = TracingMiddleware(tracer=mock_tracer)
        span = SpanContext()
        mw.record_llm_call(span, "gpt-4", 100, 50, 1500.0, 0.01)
        mock_tracer.record_llm_call.assert_called_once()
        call_args = mock_tracer.record_llm_call.call_args
        record = call_args[0][1]
        assert record.model == "gpt-4"
        assert record.input_tokens == 100
        assert record.output_tokens == 50

    def test_flush_and_shutdown(self):
        mock_tracer = MagicMock(spec=ArchonTracer)
        mw = TracingMiddleware(tracer=mock_tracer)
        mw.flush()
        mw.shutdown()
        mock_tracer.flush.assert_called_once()
        mock_tracer.shutdown.assert_called_once()


# ---------------------------------------------------------------------------
# create_tracer_from_config
# ---------------------------------------------------------------------------


class TestCreateTracerFromConfig:
    def test_none_config_returns_noop(self):
        tracer = create_tracer_from_config(None)
        assert isinstance(tracer, NoOpTracer)

    def test_disabled_config_returns_noop(self):
        cfg = TracingConfig(backend=TracingBackend.NONE)
        tracer = create_tracer_from_config(cfg)
        assert isinstance(tracer, NoOpTracer)

    def test_langsmith_without_package_returns_noop(self):
        cfg = TracingConfig(backend=TracingBackend.LANGSMITH)
        # LangSmithTracer will have _client=None since langsmith isn't installed
        tracer = create_tracer_from_config(cfg)
        assert isinstance(tracer, (NoOpTracer, SamplingTracer))

    def test_non_config_object_returns_noop(self):
        tracer = create_tracer_from_config("invalid")
        assert isinstance(tracer, NoOpTracer)
