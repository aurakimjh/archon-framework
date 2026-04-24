"""트레이싱 스팬 컨텍스트 — 트레이스/스팬 라이프사이클 관리."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SpanContext:
    """단일 트레이싱 스팬의 컨텍스트."""

    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    span_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    parent_span_id: str | None = None
    name: str = ""
    start_time: float = field(default_factory=time.monotonic)
    metadata: dict[str, Any] = field(default_factory=dict)
    _end_time: float | None = field(default=None, repr=False)

    def finish(self) -> None:
        """스팬을 종료하고 소요 시간을 기록한다."""
        self._end_time = time.monotonic()

    @property
    def duration_ms(self) -> float | None:
        """스팬 소요 시간(ms). 종료 전이면 None."""
        if self._end_time is None:
            return None
        return (self._end_time - self.start_time) * 1000

    def child(self, name: str, **metadata: Any) -> SpanContext:
        """현재 스팬의 자식 스팬을 생성한다."""
        return SpanContext(
            trace_id=self.trace_id,
            parent_span_id=self.span_id,
            name=name,
            metadata=metadata,
        )


@dataclass
class LLMCallRecord:
    """LLM 호출 기록."""

    span_id: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0
    cost_usd: float = 0.0
    status: str = "success"
    error: str | None = None
