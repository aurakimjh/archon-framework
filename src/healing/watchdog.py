"""HealthWatchdog — 백그라운드 헬스 모니터링 및 자동 복구 트리거."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from src.healing.diagnostics import DiagnosticRegistry
from src.healing.health_monitor import AgentHealthStatus, HealthMonitorRegistry
from src.healing.self_healer import HealingConfig, RecoveryAction, SelfHealerRegistry
from src.log import get_logger

slog = get_logger(__name__)


@dataclass
class WatchdogConfig:
    """Watchdog 동작 설정."""

    check_interval_seconds: float = 30.0   # 주기적 체크 간격
    alert_on_degraded: bool = True          # DEGRADED 시 알림
    alert_on_unhealthy: bool = True         # UNHEALTHY 시 알림
    alert_on_dead: bool = True              # DEAD 시 알림
    auto_heal: bool = True                  # 자동 복구 실행 여부
    max_alerts_per_agent: int = 5           # 동일 에이전트 알림 최대 횟수 (스팸 방지)


@dataclass
class WatchdogAlert:
    """Watchdog이 탐지한 이상 이벤트."""

    agent_role: str
    status: AgentHealthStatus
    message: str
    timestamp: float = field(default_factory=time.monotonic)
    extra: dict[str, Any] = field(default_factory=dict)


class HealthWatchdog:
    """백그라운드에서 주기적으로 에이전트 헬스를 점검하고 복구를 트리거한다.

    start() / stop()으로 asyncio 태스크를 관리한다.
    alerter 콜백을 등록하면 이상 탐지 시 호출된다.
    """

    def __init__(
        self,
        monitor_registry: HealthMonitorRegistry,
        diagnostic_registry: DiagnosticRegistry,
        healer_registry: SelfHealerRegistry | None = None,
        config: WatchdogConfig | None = None,
    ) -> None:
        self._monitors = monitor_registry
        self._diagnostics = diagnostic_registry
        self._healers = healer_registry or SelfHealerRegistry()
        self._config = config or WatchdogConfig()
        self._task: asyncio.Task[None] | None = None
        self._running = False
        self._alert_counts: dict[str, int] = {}
        self._alert_history: list[WatchdogAlert] = []
        self._alerters: list[Any] = []  # callable[(WatchdogAlert) -> Awaitable[None]]

    def add_alerter(self, alerter: Any) -> None:
        """이상 탐지 시 호출될 비동기 콜백을 등록한다.

        콜백 시그니처: async def alerter(alert: WatchdogAlert) -> None
        """
        self._alerters.append(alerter)

    async def start(self) -> None:
        """백그라운드 모니터링 루프를 시작한다."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="health_watchdog")
        slog.info(
            "watchdog_started",
            interval=self._config.check_interval_seconds,
            auto_heal=self._config.auto_heal,
        )

    async def stop(self) -> None:
        """백그라운드 모니터링 루프를 중단한다."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        slog.info("watchdog_stopped")

    async def check_once(self) -> list[WatchdogAlert]:
        """단일 헬스 체크를 수행하고 발생한 알림 목록을 반환한다."""
        alerts: list[WatchdogAlert] = []

        for summary in self._monitors.all_summaries():
            role: str = summary["agent_role"]
            status = AgentHealthStatus(summary["status"])

            alert = self._evaluate_agent(role, status, summary)
            if alert:
                alerts.append(alert)
                self._alert_history.append(alert)
                await self._dispatch_alert(alert)

                if self._config.auto_heal:
                    await self._trigger_heal(role, status)

        return alerts

    @property
    def alert_history(self) -> list[WatchdogAlert]:
        return list(self._alert_history)

    @property
    def is_running(self) -> bool:
        return self._running

    # ------------------------------------------------------------------

    async def _loop(self) -> None:
        """주기적 체크 루프."""
        while self._running:
            try:
                alerts = await self.check_once()
                if alerts:
                    slog.info(
                        "watchdog_cycle_alerts",
                        alert_count=len(alerts),
                        roles=[a.agent_role for a in alerts],
                    )
            except asyncio.CancelledError:
                break
            except Exception as exc:
                slog.warning("watchdog_cycle_error", error=str(exc))

            try:
                await asyncio.sleep(self._config.check_interval_seconds)
            except asyncio.CancelledError:
                break

    def _evaluate_agent(
        self,
        role: str,
        status: AgentHealthStatus,
        summary: dict[str, Any],
    ) -> WatchdogAlert | None:
        """에이전트 상태를 평가하여 알림이 필요하면 WatchdogAlert를 반환한다."""
        if status == AgentHealthStatus.HEALTHY:
            # 회복 시 카운터 리셋
            if role in self._alert_counts:
                del self._alert_counts[role]
            return None

        should_alert = (
            (status == AgentHealthStatus.DEGRADED and self._config.alert_on_degraded)
            or (status == AgentHealthStatus.UNHEALTHY and self._config.alert_on_unhealthy)
            or (status == AgentHealthStatus.DEAD and self._config.alert_on_dead)
        )
        if not should_alert:
            return None

        count = self._alert_counts.get(role, 0)
        if count >= self._config.max_alerts_per_agent:
            return None

        self._alert_counts[role] = count + 1

        consec = summary.get("consecutive_failures", 0)
        err_rate = summary.get("recent_failure_rate", 0.0)
        msg = (
            f"Agent '{role}' is {status}: "
            f"{consec} consecutive failures, "
            f"{err_rate:.0%} recent error rate."
        )
        return WatchdogAlert(
            agent_role=role,
            status=status,
            message=msg,
            extra={
                "consecutive_failures": consec,
                "recent_failure_rate": round(err_rate, 3),
                "avg_latency_ms": summary.get("avg_latency_ms", 0.0),
            },
        )

    async def _dispatch_alert(self, alert: WatchdogAlert) -> None:
        """등록된 알림 콜백들에게 이벤트를 전달한다."""
        slog.warning(
            "watchdog_alert",
            agent_role=alert.agent_role,
            status=alert.status,
            message=alert.message,
        )
        for alerter in self._alerters:
            try:
                await alerter(alert)
            except Exception as exc:
                slog.warning("watchdog_alerter_error", error=str(exc))

    async def _trigger_heal(self, role: str, status: AgentHealthStatus) -> None:
        """SelfHealer를 통해 복구 액션을 실행한다."""
        monitor = self._monitors.get(role)
        diagnostician = self._diagnostics.get(role)
        healer = self._healers.get(role, monitor, diagnostician)

        result = healer.heal(override_status=status)
        if result.action != RecoveryAction.NONE:
            slog.info(
                "watchdog_heal_triggered",
                agent_role=role,
                action=result.action,
                success=result.success,
            )
