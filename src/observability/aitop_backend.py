"""AITOP 모니터링 백엔드 — OTLP/HTTP로 트레이스·메트릭을 AITOP 서버에 전송한다."""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from src.log import get_logger
from src.observability.span import LLMCallRecord, SpanContext
from src.observability.tracer import ArchonTracer

logger = logging.getLogger(__name__)
_slog = get_logger(__name__)

# AITOP 기본 설정
DEFAULT_AITOP_URL = "http://localhost:8080"
TRACES_ENDPOINT = "/v1/traces"
METRICS_ENDPOINT = "/v1/metrics"


class AitopTracer(ArchonTracer):
    """AITOP Collection Server에 OTLP/HTTP로 트레이스를 전송하는 트레이서.

    AITOP의 OTLP/HTTP 수신기(/v1/traces, /v1/metrics)를 활용하여
    에이전트 실행 스팬과 LLM 호출 메트릭을 전송한다.
    httpx 기반이므로 추가 OTel SDK 의존성 없이 동작한다.
    """

    def __init__(
        self,
        server_url: str = DEFAULT_AITOP_URL,
        project_token: str | None = None,
        service_name: str = "archon-framework",
        timeout: float = 10.0,
        batch_size: int = 20,
    ) -> None:
        self._server_url = server_url.rstrip("/")
        self._project_token = project_token
        self._service_name = service_name
        self._timeout = timeout
        self._batch_size = batch_size

        # 스팬 버퍼 (batch 전송용)
        self._span_buffer: list[dict[str, Any]] = []
        self._metric_buffer: list[dict[str, Any]] = []
        self._spans: dict[str, SpanContext] = {}

        # 가용성 체크
        self._available = True

    @property
    def is_available(self) -> bool:
        return self._available

    def _headers(self) -> dict[str, str]:
        """AITOP API 요청 헤더."""
        headers = {"Content-Type": "application/json"}
        if self._project_token:
            headers["Authorization"] = f"Bearer {self._project_token}"
        return headers

    def _to_nano(self, mono_time: float) -> int:
        """monotonic 시간을 나노초 타임스탬프로 변환한다."""
        wall_offset = time.time() - time.monotonic()
        return int((mono_time + wall_offset) * 1_000_000_000)

    def _build_resource(self) -> dict[str, Any]:
        """OTLP Resource 속성."""
        return {
            "attributes": [
                {"key": "service.name", "value": {"stringValue": self._service_name}},
                {"key": "service.version", "value": {"stringValue": "0.1.0"}},
                {"key": "telemetry.sdk.name", "value": {"stringValue": "archon"}},
            ],
        }

    def _build_span_data(
        self,
        span: SpanContext,
        output: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        """SpanContext를 OTLP Span JSON으로 변환한다."""
        end_time = span._end_time or time.monotonic()
        attributes = [
            {"key": k, "value": {"stringValue": str(v)}}
            for k, v in span.metadata.items()
        ]

        span_data: dict[str, Any] = {
            "traceId": span.trace_id,
            "spanId": span.span_id,
            "name": span.name,
            "kind": 1,  # SPAN_KIND_INTERNAL
            "startTimeUnixNano": self._to_nano(span.start_time),
            "endTimeUnixNano": self._to_nano(end_time),
            "attributes": attributes,
            "status": {},
        }

        if span.parent_span_id:
            span_data["parentSpanId"] = span.parent_span_id

        if error:
            span_data["status"] = {
                "code": 2,  # STATUS_CODE_ERROR
                "message": error,
            }
        else:
            span_data["status"] = {"code": 1}  # STATUS_CODE_OK

        if output:
            for k, v in output.items():
                span_data["attributes"].append(
                    {"key": f"output.{k}", "value": {"stringValue": str(v)}},
                )

        return span_data

    def _build_metric_data(self, record: LLMCallRecord) -> list[dict[str, Any]]:
        """LLMCallRecord를 OTLP Metric 데이터포인트들로 변환한다."""
        now_nano = int(time.time() * 1_000_000_000)
        labels = [
            {"key": "model", "value": {"stringValue": record.model}},
            {"key": "service.name", "value": {"stringValue": self._service_name}},
            {"key": "status", "value": {"stringValue": record.status}},
        ]

        metrics = []
        for name, value in [
            ("llm.tokens.input", record.input_tokens),
            ("llm.tokens.output", record.output_tokens),
            ("llm.latency_ms", record.latency_ms),
            ("llm.cost_usd", record.cost_usd),
        ]:
            metrics.append({
                "name": name,
                "gauge": {
                    "dataPoints": [{
                        "timeUnixNano": now_nano,
                        "asDouble": float(value),
                        "attributes": labels,
                    }],
                },
            })

        return metrics

    # --- ArchonTracer ABC 구현 ---

    def start_trace(
        self, name: str, metadata: dict[str, Any] | None = None,
    ) -> SpanContext:
        span = SpanContext(name=name, metadata=metadata or {})
        self._spans[span.span_id] = span
        _slog.debug("aitop_trace_started", name=name, trace_id=span.trace_id)
        return span

    def start_span(
        self,
        parent: SpanContext,
        name: str,
        metadata: dict[str, Any] | None = None,
    ) -> SpanContext:
        span = parent.child(name, **(metadata or {}))
        self._spans[span.span_id] = span
        return span

    def end_span(
        self,
        span: SpanContext,
        output: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        span.finish()
        self._spans.pop(span.span_id, None)

        span_data = self._build_span_data(span, output, error)
        self._span_buffer.append(span_data)

        if len(self._span_buffer) >= self._batch_size:
            self.flush()

    def record_llm_call(
        self, span: SpanContext, record: LLMCallRecord,
    ) -> None:
        metrics = self._build_metric_data(record)
        self._metric_buffer.extend(metrics)

        _slog.debug(
            "aitop_llm_recorded",
            model=record.model,
            input_tokens=record.input_tokens,
            output_tokens=record.output_tokens,
            latency_ms=record.latency_ms,
        )

    def flush(self) -> None:
        """버퍼의 스팬과 메트릭을 AITOP 서버로 전송한다."""
        if self._span_buffer:
            self._send_traces(list(self._span_buffer))
            self._span_buffer.clear()

        if self._metric_buffer:
            self._send_metrics(list(self._metric_buffer))
            self._metric_buffer.clear()

    def shutdown(self) -> None:
        """잔여 데이터를 모두 전송하고 종료한다."""
        self.flush()
        self._spans.clear()
        _slog.info("aitop_tracer_shutdown")

    # --- HTTP 전송 ---

    def _send_traces(self, spans: list[dict[str, Any]]) -> None:
        """OTLP/HTTP로 트레이스를 전송한다."""
        payload = {
            "resourceSpans": [{
                "resource": self._build_resource(),
                "scopeSpans": [{
                    "scope": {"name": "archon.observability"},
                    "spans": spans,
                }],
            }],
        }

        url = f"{self._server_url}{TRACES_ENDPOINT}"
        try:
            resp = httpx.post(
                url,
                json=payload,
                headers=self._headers(),
                timeout=self._timeout,
            )
            if resp.status_code >= 400:
                logger.warning(
                    "AITOP trace export failed: HTTP %d", resp.status_code,
                )
            else:
                _slog.debug(
                    "aitop_traces_sent", count=len(spans),
                )
        except httpx.HTTPError as e:
            logger.warning("AITOP trace export error: %s", e)
            self._available = False

    def _send_metrics(self, metrics: list[dict[str, Any]]) -> None:
        """OTLP/HTTP로 메트릭을 전송한다."""
        payload = {
            "resourceMetrics": [{
                "resource": self._build_resource(),
                "scopeMetrics": [{
                    "scope": {"name": "archon.observability"},
                    "metrics": metrics,
                }],
            }],
        }

        url = f"{self._server_url}{METRICS_ENDPOINT}"
        try:
            resp = httpx.post(
                url,
                json=payload,
                headers=self._headers(),
                timeout=self._timeout,
            )
            if resp.status_code >= 400:
                logger.warning(
                    "AITOP metric export failed: HTTP %d",
                    resp.status_code,
                )
            else:
                _slog.debug(
                    "aitop_metrics_sent", count=len(metrics),
                )
        except httpx.HTTPError as e:
            logger.warning("AITOP metric export error: %s", e)
