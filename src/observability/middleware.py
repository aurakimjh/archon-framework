"""트레이싱 미들웨어 — BaseAgent와 Orchestrator에 트레이싱을 주입한다."""

from __future__ import annotations

from typing import Any

from src.log import get_logger
from src.observability.span import LLMCallRecord, SpanContext
from src.observability.tracer import ArchonTracer, NoOpTracer

_slog = get_logger(__name__)


class TracingMiddleware:
    """에이전트 실행과 파이프라인에 트레이싱 스팬을 주입하는 미들웨어."""

    def __init__(self, tracer: ArchonTracer | None = None) -> None:
        self._tracer = tracer or NoOpTracer()

    @property
    def tracer(self) -> ArchonTracer:
        return self._tracer

    def start_pipeline_trace(
        self,
        project_id: str,
        task_id: str,
        **metadata: Any,
    ) -> SpanContext:
        """파이프라인 레벨 트레이스를 시작한다."""
        return self._tracer.start_trace(
            name=f"pipeline:{project_id}/{task_id}",
            metadata={"project_id": project_id, "task_id": task_id, **metadata},
        )

    def start_agent_span(
        self,
        parent: SpanContext,
        agent_role: str,
        model: str,
        **metadata: Any,
    ) -> SpanContext:
        """에이전트 실행 스팬을 시작한다."""
        return self._tracer.start_span(
            parent=parent,
            name=f"agent:{agent_role}",
            metadata={"agent_role": agent_role, "model": model, **metadata},
        )

    def start_qa_span(self, parent: SpanContext, **metadata: Any) -> SpanContext:
        """QA 파이프라인 스팬을 시작한다."""
        return self._tracer.start_span(
            parent=parent,
            name="qa_pipeline",
            metadata=metadata,
        )

    def start_gate_span(self, parent: SpanContext, **metadata: Any) -> SpanContext:
        """Gate 평가 스팬을 시작한다."""
        return self._tracer.start_span(
            parent=parent,
            name="gate_evaluation",
            metadata=metadata,
        )

    def end_span(
        self,
        span: SpanContext,
        output: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        """스팬을 종료한다."""
        self._tracer.end_span(span, output=output, error=error)

    def record_llm_call(
        self,
        span: SpanContext,
        model: str,
        input_tokens: int,
        output_tokens: int,
        latency_ms: float,
        cost_usd: float = 0.0,
        status: str = "success",
        error: str | None = None,
    ) -> None:
        """LLM 호출을 기록한다."""
        record = LLMCallRecord(
            span_id=span.span_id,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            cost_usd=cost_usd,
            status=status,
            error=error,
        )
        self._tracer.record_llm_call(span, record)
        _slog.debug(
            "llm_call_traced",
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
        )

    def flush(self) -> None:
        self._tracer.flush()

    def shutdown(self) -> None:
        self._tracer.shutdown()


def create_tracer_from_config(config: Any) -> ArchonTracer:
    """TracingConfig로부터 적절한 트레이서를 생성한다."""
    from src.observability.config import TracingConfig

    if not isinstance(config, TracingConfig) or not config.is_enabled:
        return NoOpTracer()

    tracers: list[ArchonTracer] = []

    if config.use_langsmith:
        from src.observability.langsmith_backend import LangSmithTracer

        tracer = LangSmithTracer(
            api_key=config.langsmith_api_key,
            project_name=config.langsmith_project,
            endpoint=config.langsmith_endpoint,
        )
        if tracer.is_available:
            tracers.append(tracer)

    if config.use_langfuse:
        from src.observability.langfuse_backend import LangfuseTracer

        tracer = LangfuseTracer(
            public_key=config.langfuse_public_key,
            secret_key=config.langfuse_secret_key,
            host=config.langfuse_host,
        )
        if tracer.is_available:
            tracers.append(tracer)

    if not tracers:
        return NoOpTracer()

    if len(tracers) == 1:
        inner = tracers[0]
    else:
        from src.observability.tracer import CompositeTracer

        inner = CompositeTracer(tracers)

    if config.sample_rate < 1.0:
        from src.observability.tracer import SamplingTracer

        return SamplingTracer(inner, config.sample_rate)

    return inner
