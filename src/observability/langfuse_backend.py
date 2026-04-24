"""Langfuse 트레이싱 백엔드."""

from __future__ import annotations

import logging
from typing import Any

from src.observability.span import LLMCallRecord, SpanContext
from src.observability.tracer import ArchonTracer

logger = logging.getLogger(__name__)

try:
    from langfuse import Langfuse

    _HAS_LANGFUSE = True
except ImportError:
    _HAS_LANGFUSE = False


class LangfuseTracer(ArchonTracer):
    """Langfuse SDK 기반 트레이서.

    langfuse 패키지가 설치되지 않으면 NoOp으로 동작한다.
    """

    def __init__(
        self,
        public_key: str | None = None,
        secret_key: str | None = None,
        host: str | None = None,
    ) -> None:
        self._traces: dict[str, Any] = {}
        self._spans: dict[str, Any] = {}

        if not _HAS_LANGFUSE:
            logger.warning("langfuse 패키지 미설치 — LangfuseTracer가 no-op으로 동작합니다")
            self._client = None
            return

        try:
            kwargs: dict[str, Any] = {}
            if public_key:
                kwargs["public_key"] = public_key
            if secret_key:
                kwargs["secret_key"] = secret_key
            if host:
                kwargs["host"] = host
            self._client = Langfuse(**kwargs)
        except Exception as exc:
            logger.warning("Langfuse 클라이언트 초기화 실패: %s", exc)
            self._client = None

    @property
    def is_available(self) -> bool:
        return self._client is not None

    def start_trace(self, name: str, metadata: dict[str, Any] | None = None) -> SpanContext:
        span = SpanContext(name=name, metadata=metadata or {})
        if self._client and _HAS_LANGFUSE:
            try:
                trace = self._client.trace(name=name, metadata=metadata or {}, id=span.trace_id)
                self._traces[span.trace_id] = trace
            except Exception:
                logger.warning("Langfuse trace 시작 실패")
        return span

    def start_span(
        self, parent: SpanContext, name: str, metadata: dict[str, Any] | None = None
    ) -> SpanContext:
        span = parent.child(name, **(metadata or {}))
        if self._client and _HAS_LANGFUSE:
            trace = self._traces.get(parent.trace_id)
            if trace:
                try:
                    lf_span = trace.span(name=name, metadata=metadata or {}, id=span.span_id)
                    self._spans[span.span_id] = lf_span
                except Exception:
                    logger.warning("Langfuse span 시작 실패")
        return span

    def end_span(
        self, span: SpanContext, output: dict[str, Any] | None = None, error: str | None = None
    ) -> None:
        span.finish()
        lf_span = self._spans.pop(span.span_id, None)
        if lf_span and _HAS_LANGFUSE:
            try:
                end_kwargs: dict[str, Any] = {}
                if output:
                    end_kwargs["output"] = output
                if error:
                    end_kwargs["status_message"] = error
                    end_kwargs["level"] = "ERROR"
                lf_span.end(**end_kwargs)
            except Exception:
                logger.warning("Langfuse span 종료 실패")

    def record_llm_call(self, span: SpanContext, record: LLMCallRecord) -> None:
        trace = self._traces.get(span.trace_id)
        if trace and _HAS_LANGFUSE:
            try:
                trace.generation(
                    name=f"llm-{record.model}",
                    model=record.model,
                    usage={
                        "input": record.input_tokens,
                        "output": record.output_tokens,
                        "total": record.input_tokens + record.output_tokens,
                    },
                    metadata={
                        "latency_ms": record.latency_ms,
                        "cost_usd": record.cost_usd,
                        "status": record.status,
                    },
                )
            except Exception:
                logger.warning("Langfuse LLM 기록 실패")

    def flush(self) -> None:
        if self._client and _HAS_LANGFUSE:
            try:
                self._client.flush()
            except Exception:
                logger.warning("Langfuse flush 실패")

    def shutdown(self) -> None:
        self._traces.clear()
        self._spans.clear()
        if self._client and _HAS_LANGFUSE:
            try:
                self._client.shutdown()
            except Exception:
                logger.warning("Langfuse shutdown 실패")
