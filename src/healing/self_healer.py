"""SelfHealer — 에이전트 상태에 따른 자동 복구 전략 실행."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from src.healing.diagnostics import AgentDiagnostician, DiagnosticReport
from src.healing.health_monitor import AgentHealthMonitor, AgentHealthStatus
from src.log import get_logger

slog = get_logger(__name__)


class RecoveryAction(StrEnum):
    NONE = "none"
    MODEL_DOWNGRADE = "model_downgrade"         # DEGRADED: 더 빠른/저렴한 모델로 전환
    AGENT_REINIT = "agent_reinit"               # UNHEALTHY: 에이전트 재초기화
    SUBSTITUTE_AGENT = "substitute_agent"        # DEAD: 대체 에이전트 투입
    CIRCUIT_BREAK = "circuit_break"             # 수동 Circuit Breaker 트리거
    ESCALATE = "escalate"                       # 복구 불가 → 인간 에스컬레이션


@dataclass
class RecoveryResult:
    """복구 시도 결과."""

    agent_role: str
    action: RecoveryAction
    success: bool
    details: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.monotonic)
    error: str = ""


@dataclass
class HealingConfig:
    """자가 치유 동작 설정."""

    # DEGRADED 시 전환할 fallback 모델 (None이면 model_downgrade 스킵)
    fallback_model: str | None = None
    # DEAD 시 투입할 대체 역할 (None이면 escalate)
    substitute_role: str | None = None
    # 최대 복구 시도 횟수 (초과 시 ESCALATE)
    max_recovery_attempts: int = 3
    # 복구 쿨다운 (초) — 연속 복구 루프 방지
    recovery_cooldown_seconds: float = 30.0


class SelfHealer:
    """에이전트 건강 상태에 따라 복구 전략을 선택하고 실행한다.

    - DEGRADED  → model_downgrade (fallback_model 설정 시)
    - UNHEALTHY → agent_reinit
    - DEAD      → substitute_agent (substitute_role 설정 시) or escalate
    """

    def __init__(
        self,
        agent_role: str,
        monitor: AgentHealthMonitor,
        diagnostician: AgentDiagnostician,
        config: HealingConfig | None = None,
    ) -> None:
        self.agent_role = agent_role
        self._monitor = monitor
        self._diagnostician = diagnostician
        self._config = config or HealingConfig()
        self._history: list[RecoveryResult] = []
        self._last_recovery_at: float = 0.0
        self._recovery_attempt_count: int = 0

    @property
    def recovery_history(self) -> list[RecoveryResult]:
        return list(self._history)

    def should_attempt_recovery(self) -> bool:
        """복구 시도가 가능한 시점인지 확인한다 (쿨다운 + 최대 횟수)."""
        if self._recovery_attempt_count >= self._config.max_recovery_attempts:
            return False
        elapsed = time.monotonic() - self._last_recovery_at
        return elapsed >= self._config.recovery_cooldown_seconds

    def select_action(self, status: AgentHealthStatus) -> RecoveryAction:
        """현재 상태에 맞는 복구 액션을 선택한다."""
        if status == AgentHealthStatus.HEALTHY:
            return RecoveryAction.NONE

        if status == AgentHealthStatus.DEGRADED:
            if self._config.fallback_model:
                return RecoveryAction.MODEL_DOWNGRADE
            return RecoveryAction.NONE

        if status == AgentHealthStatus.UNHEALTHY:
            return RecoveryAction.AGENT_REINIT

        if status == AgentHealthStatus.DEAD:
            if self._config.substitute_role:
                return RecoveryAction.SUBSTITUTE_AGENT
            return RecoveryAction.ESCALATE

        return RecoveryAction.NONE

    def heal(self, override_status: AgentHealthStatus | None = None) -> RecoveryResult:
        """현재 상태를 진단하고 적절한 복구 액션을 실행한다."""
        status = override_status or self._monitor.status

        if not self.should_attempt_recovery():
            result = RecoveryResult(
                agent_role=self.agent_role,
                action=RecoveryAction.NONE,
                success=False,
                details={"reason": "cooldown_or_max_attempts"},
            )
            return result

        action = self.select_action(status)
        report = self._diagnostician.generate_report()

        result = self._execute_action(action, status, report)
        self._history.append(result)
        self._last_recovery_at = time.monotonic()
        if action != RecoveryAction.NONE:
            self._recovery_attempt_count += 1

        level = "info" if result.success else "warning"
        getattr(slog, level)(
            "healing_action",
            agent_role=self.agent_role,
            status=status,
            action=action,
            success=result.success,
            root_cause=report.root_cause if report.error_count > 0 else "n/a",
            details=result.details,
        )
        return result

    def reset_recovery_count(self) -> None:
        """복구 시도 카운터를 초기화한다 (에이전트 정상 복구 확인 후 호출)."""
        self._recovery_attempt_count = 0
        self._monitor.reset()
        self._diagnostician.clear()
        slog.info("healing_reset", agent_role=self.agent_role)

    # ------------------------------------------------------------------
    # Action implementations
    # ------------------------------------------------------------------

    def _execute_action(
        self,
        action: RecoveryAction,
        status: AgentHealthStatus,
        report: DiagnosticReport,
    ) -> RecoveryResult:
        if action == RecoveryAction.NONE:
            return RecoveryResult(
                agent_role=self.agent_role,
                action=action,
                success=True,
                details={"status": status, "reason": "no_action_required"},
            )

        if action == RecoveryAction.MODEL_DOWNGRADE:
            return self._do_model_downgrade(report)

        if action == RecoveryAction.AGENT_REINIT:
            return self._do_agent_reinit(report)

        if action == RecoveryAction.SUBSTITUTE_AGENT:
            return self._do_substitute(report)

        if action == RecoveryAction.ESCALATE:
            return self._do_escalate(report)

        return RecoveryResult(
            agent_role=self.agent_role,
            action=action,
            success=False,
            details={"reason": "unknown_action"},
        )

    def _do_model_downgrade(self, report: DiagnosticReport) -> RecoveryResult:
        """DEGRADED 복구: fallback 모델로 전환 신호를 기록한다.

        실제 모델 전환은 호출자(Orchestrator/BaseAgent)가 이 결과를 보고 처리한다.
        """
        return RecoveryResult(
            agent_role=self.agent_role,
            action=RecoveryAction.MODEL_DOWNGRADE,
            success=True,
            details={
                "fallback_model": self._config.fallback_model,
                "dominant_error": report.dominant_category,
                "recommendations": report.recommendations[:2],
            },
        )

    def _do_agent_reinit(self, report: DiagnosticReport) -> RecoveryResult:
        """UNHEALTHY 복구: 에이전트 재초기화 신호를 기록한다.

        에러 히스토리를 초기화하여 다음 execute()가 깨끗한 상태로 시작하도록 한다.
        """
        self._diagnostician.clear()
        return RecoveryResult(
            agent_role=self.agent_role,
            action=RecoveryAction.AGENT_REINIT,
            success=True,
            details={
                "cleared_error_history": True,
                "dominant_error": report.dominant_category,
                "root_cause": report.root_cause,
                "recommendations": report.recommendations[:2],
            },
        )

    def _do_substitute(self, report: DiagnosticReport) -> RecoveryResult:
        """DEAD 복구: 대체 에이전트 역할을 지정한다."""
        return RecoveryResult(
            agent_role=self.agent_role,
            action=RecoveryAction.SUBSTITUTE_AGENT,
            success=True,
            details={
                "substitute_role": self._config.substitute_role,
                "root_cause": report.root_cause,
                "error_count": report.error_count,
            },
        )

    def _do_escalate(self, report: DiagnosticReport) -> RecoveryResult:
        """복구 불가 → 인간 에스컬레이션 요청."""
        return RecoveryResult(
            agent_role=self.agent_role,
            action=RecoveryAction.ESCALATE,
            success=False,
            details={
                "reason": "no_substitute_configured",
                "root_cause": report.root_cause,
                "dominant_error": report.dominant_category,
                "pattern_summary": report.pattern_summary,
                "recommendations": report.recommendations,
            },
        )


class SelfHealerRegistry:
    """전체 에이전트의 SelfHealer를 한 곳에서 관리한다."""

    def __init__(self, default_config: HealingConfig | None = None) -> None:
        self._config = default_config or HealingConfig()
        self._healers: dict[str, SelfHealer] = {}

    def get(
        self,
        agent_role: str,
        monitor: AgentHealthMonitor,
        diagnostician: AgentDiagnostician,
    ) -> SelfHealer:
        if agent_role not in self._healers:
            self._healers[agent_role] = SelfHealer(
                agent_role=agent_role,
                monitor=monitor,
                diagnostician=diagnostician,
                config=self._config,
            )
        return self._healers[agent_role]

    def all_histories(self) -> dict[str, list[RecoveryResult]]:
        return {role: h.recovery_history for role, h in self._healers.items()}
