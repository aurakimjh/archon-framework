"""AgentHealthMonitor — 에이전트 상태 모니터링 및 헬스 히스토리 관리."""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from src.log import get_logger

slog = get_logger(__name__)


class AgentHealthStatus(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"      # 응답 지연 또는 간헐적 실패
    UNHEALTHY = "unhealthy"    # 연속 실패, 기능 저하 상태
    DEAD = "dead"              # 완전 불응, 복구 불가로 판단


@dataclass
class HealthCheckResult:
    """단일 헬스 체크 결과."""

    success: bool
    latency_ms: float = 0.0
    error: str = ""
    timestamp: float = field(default_factory=time.monotonic)


@dataclass
class AgentHealthThresholds:
    """상태 전이 임계값."""

    degraded_consecutive_failures: int = 3     # N회 연속 실패 → DEGRADED
    unhealthy_consecutive_failures: int = 5    # N회 연속 실패 → UNHEALTHY
    dead_consecutive_failures: int = 8         # N회 연속 실패 → DEAD
    degraded_latency_ms: float = 5_000.0       # 5초 이상 → DEGRADED 후보
    unhealthy_error_rate: float = 0.7          # 최근 70% 이상 실패 → UNHEALTHY
    history_window: int = 10                   # 최근 N회 결과를 상태 평가에 사용


class AgentHealthMonitor:
    """에이전트 한 개의 헬스 상태를 추적한다.

    execute() 성공/실패 결과를 record()로 입력받아 상태를 자동으로 전이한다.
    resilience.CircuitBreaker와 연동하여 OPEN 상태를 UNHEALTHY로 반영할 수 있다.
    """

    def __init__(
        self,
        agent_role: str,
        thresholds: AgentHealthThresholds | None = None,
    ) -> None:
        self.agent_role = agent_role
        self._thresholds = thresholds or AgentHealthThresholds()
        self._history: deque[HealthCheckResult] = deque(
            maxlen=self._thresholds.history_window
        )
        self._status = AgentHealthStatus.HEALTHY
        self._consecutive_failures = 0
        self._total_checks = 0
        self._total_failures = 0

    @property
    def status(self) -> AgentHealthStatus:
        return self._status

    @property
    def consecutive_failures(self) -> int:
        return self._consecutive_failures

    def record_success(self, latency_ms: float = 0.0) -> AgentHealthStatus:
        """성공 결과를 기록하고 갱신된 상태를 반환한다."""
        result = HealthCheckResult(success=True, latency_ms=latency_ms)
        self._history.append(result)
        self._total_checks += 1
        self._consecutive_failures = 0
        previous = self._status
        self._status = self._evaluate()
        self._log_transition(previous, self._status, latency_ms=latency_ms)
        return self._status

    def record_failure(self, error: str = "", latency_ms: float = 0.0) -> AgentHealthStatus:
        """실패 결과를 기록하고 갱신된 상태를 반환한다."""
        result = HealthCheckResult(success=False, latency_ms=latency_ms, error=error)
        self._history.append(result)
        self._total_checks += 1
        self._total_failures += 1
        self._consecutive_failures += 1
        previous = self._status
        self._status = self._evaluate()
        self._log_transition(previous, self._status, error=error)
        return self._status

    def record_circuit_open(self) -> AgentHealthStatus:
        """Circuit Breaker OPEN 상태를 헬스에 반영한다."""
        previous = self._status
        if self._status in (AgentHealthStatus.HEALTHY, AgentHealthStatus.DEGRADED):
            self._status = AgentHealthStatus.UNHEALTHY
            self._log_transition(previous, self._status, reason="circuit_breaker_open")
        return self._status

    def reset(self) -> None:
        """헬스 상태를 HEALTHY로 리셋한다 (복구 후 호출)."""
        previous = self._status
        self._status = AgentHealthStatus.HEALTHY
        self._consecutive_failures = 0
        self._history.clear()
        slog.info(
            "health_reset",
            agent_role=self.agent_role,
            previous_status=previous,
        )

    def get_summary(self) -> dict[str, Any]:
        """현재 헬스 요약 딕셔너리를 반환한다."""
        recent = list(self._history)
        recent_failures = sum(1 for r in recent if not r.success)
        avg_latency = (
            sum(r.latency_ms for r in recent) / len(recent) if recent else 0.0
        )
        return {
            "agent_role": self.agent_role,
            "status": self._status,
            "consecutive_failures": self._consecutive_failures,
            "total_checks": self._total_checks,
            "total_failures": self._total_failures,
            "recent_failure_rate": recent_failures / len(recent) if recent else 0.0,
            "avg_latency_ms": round(avg_latency, 2),
            "history_size": len(recent),
        }

    def _evaluate(self) -> AgentHealthStatus:
        """현재 히스토리를 바탕으로 상태를 재계산한다."""
        t = self._thresholds
        consec = self._consecutive_failures

        if consec >= t.dead_consecutive_failures:
            return AgentHealthStatus.DEAD

        if consec >= t.unhealthy_consecutive_failures:
            return AgentHealthStatus.UNHEALTHY

        # 최근 에러율 체크
        recent = list(self._history)
        if len(recent) >= 3:
            error_rate = sum(1 for r in recent if not r.success) / len(recent)
            if error_rate >= t.unhealthy_error_rate:
                return AgentHealthStatus.UNHEALTHY

        if consec >= t.degraded_consecutive_failures:
            return AgentHealthStatus.DEGRADED

        # 최근 평균 지연 체크
        if recent:
            avg_latency = sum(r.latency_ms for r in recent) / len(recent)
            if avg_latency >= t.degraded_latency_ms:
                return AgentHealthStatus.DEGRADED

        return AgentHealthStatus.HEALTHY

    def _log_transition(
        self,
        previous: AgentHealthStatus,
        current: AgentHealthStatus,
        **extra: Any,
    ) -> None:
        if previous == current:
            return
        level = "warning" if current != AgentHealthStatus.HEALTHY else "info"
        getattr(slog, level)(
            "health_transition",
            agent_role=self.agent_role,
            from_status=previous,
            to_status=current,
            consecutive_failures=self._consecutive_failures,
            **extra,
        )


class HealthMonitorRegistry:
    """전체 에이전트의 헬스 모니터를 한 곳에서 관리한다."""

    def __init__(self, thresholds: AgentHealthThresholds | None = None) -> None:
        self._thresholds = thresholds or AgentHealthThresholds()
        self._monitors: dict[str, AgentHealthMonitor] = {}

    def get(self, agent_role: str) -> AgentHealthMonitor:
        """에이전트 역할에 해당하는 모니터를 반환한다 (없으면 생성)."""
        if agent_role not in self._monitors:
            self._monitors[agent_role] = AgentHealthMonitor(
                agent_role, self._thresholds
            )
        return self._monitors[agent_role]

    def all_summaries(self) -> list[dict[str, Any]]:
        return [m.get_summary() for m in self._monitors.values()]

    def unhealthy_agents(self) -> list[str]:
        return [
            role
            for role, m in self._monitors.items()
            if m.status in (AgentHealthStatus.UNHEALTHY, AgentHealthStatus.DEAD)
        ]

    def degraded_agents(self) -> list[str]:
        return [
            role
            for role, m in self._monitors.items()
            if m.status == AgentHealthStatus.DEGRADED
        ]
