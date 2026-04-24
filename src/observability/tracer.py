"""트레이서 추상 클래스 및 구현체 — NoOp, Composite."""

from __future__ import annotations

import abc
import logging
import random
from typing import Any

from src.log import get_logger
from src.observability.span import LLMCallRecord, SpanContext

logger = logging.getLogger(__name__)
_slog = get_logger(__name__)


class ArchonTracer(abc.ABC):
    """트레이싱 추상 인터페이스.

    모든 트레이서 백엔드는 이 클래스를 상속한다.
    """

    @abc.abstractmethod
    def start_trace(self, name: str, metadata: dict[str, Any] | None = None) -> SpanContext:
        """새 트레이스를 시작하고 루트 스팬을 반환한다."""

    @abc.abstractmethod
    def start_span(
        self, parent: SpanContext, name: str, metadata: dict[str, Any] | None = None
    ) -> SpanContext:
        """부모 스팬의 자식 스팬을 시작한다."""

    @abc.abstractmethod
    def end_span(
        self, span: SpanContext, output: dict[str, Any] | None = None, error: str | None = None
    ) -> None:
        """스팬을 종료한다."""

    @abc.abstractmethod
    def record_llm_call(self, span: SpanContext, record: LLMCallRecord) -> None:
        """LLM 호출 기록을 스팬에 첨부한다."""

    def flush(self) -> None:
        """버퍼된 트레이스를 전송한다. 기본 no-op."""

    def shutdown(self) -> None:
        """트레이서를 종료한다. 기본 no-op."""


class NoOpTracer(ArchonTracer):
    """설정 없을 때 사용하는 No-Op 트레이서."""

    def start_trace(self, name: str, metadata: dict[str, Any] | None = None) -> SpanContext:
        return SpanContext(name=name, metadata=metadata or {})

    def start_span(
        self, parent: SpanContext, name: str, metadata: dict[str, Any] | None = None
    ) -> SpanContext:
        return parent.child(name, **(metadata or {}))

    def end_span(
        self, span: SpanContext, output: dict[str, Any] | None = None, error: str | None = None
    ) -> None:
        span.finish()

    def record_llm_call(self, span: SpanContext, record: LLMCallRecord) -> None:
        pass


class CompositeTracer(ArchonTracer):
    """여러 트레이서 백엔드를 동시에 사용하는 복합 트레이서."""

    def __init__(self, tracers: list[ArchonTracer]) -> None:
        self._tracers = tracers

    @property
    def tracers(self) -> list[ArchonTracer]:
        return list(self._tracers)

    def start_trace(self, name: str, metadata: dict[str, Any] | None = None) -> SpanContext:
        span = SpanContext(name=name, metadata=metadata or {})
        for tracer in self._tracers:
            try:
                tracer.start_trace(name, metadata)
            except Exception:
                logger.warning("Tracer %s failed to start trace", type(tracer).__name__)
        return span

    def start_span(
        self, parent: SpanContext, name: str, metadata: dict[str, Any] | None = None
    ) -> SpanContext:
        span = parent.child(name, **(metadata or {}))
        for tracer in self._tracers:
            try:
                tracer.start_span(parent, name, metadata)
            except Exception:
                logger.warning("Tracer %s failed to start span", type(tracer).__name__)
        return span

    def end_span(
        self, span: SpanContext, output: dict[str, Any] | None = None, error: str | None = None
    ) -> None:
        span.finish()
        for tracer in self._tracers:
            try:
                tracer.end_span(span, output, error)
            except Exception:
                logger.warning("Tracer %s failed to end span", type(tracer).__name__)

    def record_llm_call(self, span: SpanContext, record: LLMCallRecord) -> None:
        for tracer in self._tracers:
            try:
                tracer.record_llm_call(span, record)
            except Exception:
                logger.warning("Tracer %s failed to record LLM call", type(tracer).__name__)

    def flush(self) -> None:
        for tracer in self._tracers:
            try:
                tracer.flush()
            except Exception:
                logger.warning("Tracer %s failed to flush", type(tracer).__name__)

    def shutdown(self) -> None:
        for tracer in self._tracers:
            try:
                tracer.shutdown()
            except Exception:
                logger.warning("Tracer %s failed to shutdown", type(tracer).__name__)


class SamplingTracer(ArchonTracer):
    """샘플링 래퍼 — sample_rate에 따라 트레이스를 확률적으로 수집한다."""

    def __init__(self, inner: ArchonTracer, sample_rate: float = 1.0) -> None:
        self._inner = inner
        self._sample_rate = max(0.0, min(1.0, sample_rate))
        self._sampled_traces: set[str] = set()

    def _should_sample(self, trace_id: str) -> bool:
        if trace_id in self._sampled_traces:
            return True
        if self._sample_rate >= 1.0:
            self._sampled_traces.add(trace_id)
            return True
        if self._sample_rate <= 0.0:
            return False
        if random.random() < self._sample_rate:  # noqa: S311
            self._sampled_traces.add(trace_id)
            return True
        return False

    def start_trace(self, name: str, metadata: dict[str, Any] | None = None) -> SpanContext:
        span = self._inner.start_trace(name, metadata)
        self._should_sample(span.trace_id)
        return span

    def start_span(
        self, parent: SpanContext, name: str, metadata: dict[str, Any] | None = None
    ) -> SpanContext:
        if self._should_sample(parent.trace_id):
            return self._inner.start_span(parent, name, metadata)
        return parent.child(name, **(metadata or {}))

    def end_span(
        self, span: SpanContext, output: dict[str, Any] | None = None, error: str | None = None
    ) -> None:
        if self._should_sample(span.trace_id):
            self._inner.end_span(span, output, error)
        else:
            span.finish()

    def record_llm_call(self, span: SpanContext, record: LLMCallRecord) -> None:
        if self._should_sample(span.trace_id):
            self._inner.record_llm_call(span, record)

    def flush(self) -> None:
        self._inner.flush()

    def shutdown(self) -> None:
        self._sampled_traces.clear()
        self._inner.shutdown()
