"""LangSmith 트레이싱 백엔드."""

from __future__ import annotations

import logging
from typing import Any

from src.observability.span import LLMCallRecord, SpanContext
from src.observability.tracer import ArchonTracer

logger = logging.getLogger(__name__)

try:
    from langsmith import Client as LangSmithClient
    from langsmith.run_trees import RunTree

    _HAS_LANGSMITH = True
except ImportError:
    _HAS_LANGSMITH = False


class LangSmithTracer(ArchonTracer):
    """LangSmith SDK 기반 트레이서.

    langsmith 패키지가 설치되지 않으면 NoOp으로 동작한다.
    """

    def __init__(
        self,
        api_key: str | None = None,
        project_name: str = "archon",
        endpoint: str | None = None,
    ) -> None:
        self._project_name = project_name
        self._runs: dict[str, Any] = {}

        if not _HAS_LANGSMITH:
            logger.warning("langsmith 패키지 미설치 — LangSmithTracer가 no-op으로 동작합니다")
            self._client = None
            return

        try:
            kwargs: dict[str, Any] = {}
            if api_key:
                kwargs["api_key"] = api_key
            if endpoint:
                kwargs["api_url"] = endpoint
            self._client = LangSmithClient(**kwargs)
        except Exception as exc:
            logger.warning("LangSmith 클라이언트 초기화 실패: %s", exc)
            self._client = None

    @property
    def is_available(self) -> bool:
        return self._client is not None

    def start_trace(self, name: str, metadata: dict[str, Any] | None = None) -> SpanContext:
        span = SpanContext(name=name, metadata=metadata or {})
        if self._client and _HAS_LANGSMITH:
            try:
                run = RunTree(
                    name=name,
                    run_type="chain",
                    project_name=self._project_name,
                    inputs=metadata or {},
                )
                self._runs[span.span_id] = run
            except Exception:
                logger.warning("LangSmith trace 시작 실패")
        return span

    def start_span(
        self, parent: SpanContext, name: str, metadata: dict[str, Any] | None = None
    ) -> SpanContext:
        span = parent.child(name, **(metadata or {}))
        if self._client and _HAS_LANGSMITH:
            parent_run = self._runs.get(parent.span_id)
            if parent_run:
                try:
                    child_run = parent_run.create_child(
                        name=name,
                        run_type="llm" if "llm" in name.lower() else "chain",
                        inputs=metadata or {},
                    )
                    self._runs[span.span_id] = child_run
                except Exception:
                    logger.warning("LangSmith span 시작 실패")
        return span

    def end_span(
        self, span: SpanContext, output: dict[str, Any] | None = None, error: str | None = None
    ) -> None:
        span.finish()
        run = self._runs.pop(span.span_id, None)
        if run and _HAS_LANGSMITH:
            try:
                if error:
                    run.end(error=error)
                else:
                    run.end(outputs=output or {})
                run.post()
            except Exception:
                logger.warning("LangSmith span 종료 실패")

    def record_llm_call(self, span: SpanContext, record: LLMCallRecord) -> None:
        run = self._runs.get(span.span_id)
        if run and _HAS_LANGSMITH:
            try:
                run.inputs["model"] = record.model
                run.outputs = {
                    "input_tokens": record.input_tokens,
                    "output_tokens": record.output_tokens,
                    "latency_ms": record.latency_ms,
                    "cost_usd": record.cost_usd,
                    "status": record.status,
                }
                if record.error:
                    run.outputs["error"] = record.error
            except Exception:
                logger.warning("LangSmith LLM 기록 실패")

    def flush(self) -> None:
        pass

    def shutdown(self) -> None:
        self._runs.clear()
