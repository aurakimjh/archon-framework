"""Self-Healing Agent 모듈 테스트."""

from __future__ import annotations

import asyncio
import pytest

from src.healing.diagnostics import (
    AgentDiagnostician,
    DiagnosticRegistry,
    ErrorCategory,
    RootCause,
    classify_error,
)
from src.healing.health_monitor import (
    AgentHealthMonitor,
    AgentHealthStatus,
    AgentHealthThresholds,
    HealthMonitorRegistry,
)
from src.healing.self_healer import (
    HealingConfig,
    RecoveryAction,
    SelfHealer,
    SelfHealerRegistry,
)
from src.healing.watchdog import HealthWatchdog, WatchdogAlert, WatchdogConfig
from src.healing.diagnostics import DiagnosticRegistry


# ---------------------------------------------------------------------------
# AgentHealthMonitor
# ---------------------------------------------------------------------------

class TestAgentHealthMonitor:
    def _make(self, **kwargs) -> AgentHealthMonitor:
        thresholds = AgentHealthThresholds(**kwargs)
        return AgentHealthMonitor("backend", thresholds)

    def test_initial_status_healthy(self):
        m = AgentHealthMonitor("backend")
        assert m.status == AgentHealthStatus.HEALTHY

    def test_success_stays_healthy(self):
        m = AgentHealthMonitor("backend")
        status = m.record_success(latency_ms=100.0)
        assert status == AgentHealthStatus.HEALTHY

    def test_consecutive_failures_degrade(self):
        # unhealthy_error_rate=1.1 → 에러율 체크 비활성화, consecutive만 테스트
        m = self._make(degraded_consecutive_failures=3, unhealthy_error_rate=1.1)
        for _ in range(3):
            m.record_failure("timeout")
        assert m.status == AgentHealthStatus.DEGRADED

    def test_consecutive_failures_unhealthy(self):
        m = self._make(unhealthy_consecutive_failures=5, unhealthy_error_rate=1.1)
        for _ in range(5):
            m.record_failure("server error")
        assert m.status == AgentHealthStatus.UNHEALTHY

    def test_consecutive_failures_dead(self):
        m = self._make(dead_consecutive_failures=8, unhealthy_error_rate=1.1)
        for _ in range(8):
            m.record_failure("fatal")
        assert m.status == AgentHealthStatus.DEAD

    def test_success_resets_consecutive_failures(self):
        m = self._make(degraded_consecutive_failures=3)
        for _ in range(2):
            m.record_failure("error")
        m.record_success()
        assert m.consecutive_failures == 0
        assert m.status == AgentHealthStatus.HEALTHY

    def test_high_error_rate_triggers_unhealthy(self):
        # 10개 중 8개 실패 → error_rate=0.8 > 0.7
        m = self._make(
            history_window=10,
            unhealthy_error_rate=0.7,
            degraded_consecutive_failures=99,
            unhealthy_consecutive_failures=99,
            dead_consecutive_failures=99,
        )
        for _ in range(8):
            m.record_failure("err")
        for _ in range(2):
            m.record_success()
        assert m.status == AgentHealthStatus.UNHEALTHY

    def test_high_latency_triggers_degraded(self):
        m = self._make(
            degraded_latency_ms=1000.0,
            degraded_consecutive_failures=99,
            unhealthy_consecutive_failures=99,
            dead_consecutive_failures=99,
        )
        for _ in range(3):
            m.record_success(latency_ms=2000.0)
        assert m.status == AgentHealthStatus.DEGRADED

    def test_record_circuit_open_upgrades_to_unhealthy(self):
        m = AgentHealthMonitor("backend")
        assert m.status == AgentHealthStatus.HEALTHY
        m.record_circuit_open()
        assert m.status == AgentHealthStatus.UNHEALTHY

    def test_record_circuit_open_does_not_downgrade_dead(self):
        m = self._make(dead_consecutive_failures=2)
        for _ in range(2):
            m.record_failure("fatal")
        assert m.status == AgentHealthStatus.DEAD
        m.record_circuit_open()
        assert m.status == AgentHealthStatus.DEAD  # DEAD 유지

    def test_reset_clears_to_healthy(self):
        m = self._make(dead_consecutive_failures=3)
        for _ in range(3):
            m.record_failure("err")
        m.reset()
        assert m.status == AgentHealthStatus.HEALTHY
        assert m.consecutive_failures == 0

    def test_get_summary_keys(self):
        m = AgentHealthMonitor("qa")
        m.record_success(latency_ms=200.0)
        summary = m.get_summary()
        assert summary["agent_role"] == "qa"
        assert "status" in summary
        assert "consecutive_failures" in summary
        assert "recent_failure_rate" in summary
        assert "avg_latency_ms" in summary


class TestHealthMonitorRegistry:
    def test_get_creates_monitor(self):
        reg = HealthMonitorRegistry()
        m = reg.get("backend")
        assert isinstance(m, AgentHealthMonitor)
        assert m.agent_role == "backend"

    def test_get_same_role_returns_same_instance(self):
        reg = HealthMonitorRegistry()
        m1 = reg.get("qa")
        m2 = reg.get("qa")
        assert m1 is m2

    def test_unhealthy_agents_filter(self):
        reg = HealthMonitorRegistry(AgentHealthThresholds(unhealthy_consecutive_failures=2))
        m = reg.get("backend")
        for _ in range(2):
            m.record_failure("err")
        assert "backend" in reg.unhealthy_agents()

    def test_degraded_agents_filter(self):
        reg = HealthMonitorRegistry(
            AgentHealthThresholds(
                degraded_consecutive_failures=2,
                unhealthy_consecutive_failures=99,
                dead_consecutive_failures=99,
            )
        )
        m = reg.get("reviewer")
        for _ in range(2):
            m.record_failure("slow")
        assert "reviewer" in reg.degraded_agents()

    def test_all_summaries(self):
        reg = HealthMonitorRegistry()
        reg.get("backend").record_success()
        reg.get("qa").record_success()
        summaries = reg.all_summaries()
        assert len(summaries) == 2


# ---------------------------------------------------------------------------
# classify_error & AgentDiagnostician
# ---------------------------------------------------------------------------

class TestClassifyError:
    def test_timeout(self):
        assert classify_error("Read timeout after 30s") == ErrorCategory.LLM_TIMEOUT

    def test_rate_limit(self):
        assert classify_error("429 Too Many Requests") == ErrorCategory.RATE_LIMIT

    def test_auth(self):
        assert classify_error("401 Unauthorized: invalid api_key") == ErrorCategory.AUTH_FAILURE

    def test_oom(self):
        assert classify_error("Out of memory error") == ErrorCategory.OOM

    def test_context_length(self):
        assert classify_error("Context length exceeded max_token limit") == ErrorCategory.CONTEXT_LENGTH

    def test_network(self):
        assert classify_error("Connection refused by host") == ErrorCategory.NETWORK

    def test_validation(self):
        assert classify_error("ValidationError: invalid input schema") == ErrorCategory.VALIDATION

    def test_unknown(self):
        assert classify_error("some random unexpected error") == ErrorCategory.UNKNOWN


class TestAgentDiagnostician:
    def test_record_error_classifies(self):
        d = AgentDiagnostician("backend")
        rec = d.record_error("Read timeout occurred")
        assert rec.category == ErrorCategory.LLM_TIMEOUT

    def test_analyze_patterns_empty(self):
        d = AgentDiagnostician("backend")
        result = d.analyze_patterns()
        assert result["error_count"] == 0

    def test_repeated_error_detection(self):
        d = AgentDiagnostician("backend")
        msg = "Read timeout after 30s"
        for _ in range(3):
            d.record_error(msg)
        analysis = d.analyze_patterns()
        assert analysis["error_count"] == 3
        assert len(analysis["repeated"]) >= 1
        assert analysis["repeated"][0][1] == 3

    def test_generate_report_empty(self):
        d = AgentDiagnostician("backend")
        report = d.generate_report()
        assert report.error_count == 0
        assert report.confidence == 0.0

    def test_generate_report_timeout(self):
        d = AgentDiagnostician("backend")
        for _ in range(5):
            d.record_error("Connection timed out")
        report = d.generate_report()
        assert report.dominant_category in (ErrorCategory.LLM_TIMEOUT, ErrorCategory.NETWORK)
        assert report.root_cause != RootCause.UNKNOWN
        assert report.confidence > 0.0
        assert len(report.recommendations) > 0

    def test_generate_report_rate_limit_root_cause(self):
        d = AgentDiagnostician("backend")
        for _ in range(3):
            d.record_error("429 rate limit exceeded")
        report = d.generate_report()
        assert report.root_cause == RootCause.RATE_LIMIT_QUOTA

    def test_clear_resets_history(self):
        d = AgentDiagnostician("backend")
        d.record_error("error")
        d.clear()
        assert d.analyze_patterns()["error_count"] == 0

    def test_report_as_dict(self):
        d = AgentDiagnostician("backend")
        d.record_error("timeout")
        report = d.generate_report()
        data = report.as_dict()
        assert "agent_role" in data
        assert "root_cause" in data
        assert "recommendations" in data


class TestDiagnosticRegistry:
    def test_get_creates_diagnostician(self):
        reg = DiagnosticRegistry()
        d = reg.get("qa")
        assert isinstance(d, AgentDiagnostician)

    def test_all_reports(self):
        reg = DiagnosticRegistry()
        reg.get("backend").record_error("timeout")
        reg.get("qa").record_error("validation error")
        reports = reg.all_reports()
        assert len(reports) == 2


# ---------------------------------------------------------------------------
# SelfHealer
# ---------------------------------------------------------------------------

class TestSelfHealer:
    def _make(self, status: AgentHealthStatus, **cfg_kwargs) -> SelfHealer:
        thresholds = AgentHealthThresholds(
            dead_consecutive_failures=2,
            unhealthy_consecutive_failures=2,
            degraded_consecutive_failures=1,
        )
        monitor = AgentHealthMonitor("backend", thresholds)
        # Force status by recording failures
        if status == AgentHealthStatus.DEGRADED:
            monitor.record_failure("degraded")
        elif status == AgentHealthStatus.UNHEALTHY:
            for _ in range(2):
                monitor.record_failure("unhealthy")
        elif status == AgentHealthStatus.DEAD:
            for _ in range(2):
                monitor.record_failure("dead")

        diagnostician = AgentDiagnostician("backend")
        config = HealingConfig(recovery_cooldown_seconds=0.0, **cfg_kwargs)
        return SelfHealer("backend", monitor, diagnostician, config)

    def test_heal_healthy_returns_none_action(self):
        monitor = AgentHealthMonitor("backend")
        diagnostician = AgentDiagnostician("backend")
        config = HealingConfig(recovery_cooldown_seconds=0.0)
        healer = SelfHealer("backend", monitor, diagnostician, config)
        result = healer.heal()
        assert result.action == RecoveryAction.NONE
        assert result.success is True

    def test_degraded_with_fallback_model_downgrades(self):
        healer = self._make(
            AgentHealthStatus.DEGRADED,
            fallback_model="gpt-3.5-turbo",
        )
        result = healer.heal(override_status=AgentHealthStatus.DEGRADED)
        assert result.action == RecoveryAction.MODEL_DOWNGRADE
        assert result.success is True
        assert result.details["fallback_model"] == "gpt-3.5-turbo"

    def test_degraded_without_fallback_no_action(self):
        healer = self._make(AgentHealthStatus.DEGRADED, fallback_model=None)
        result = healer.heal(override_status=AgentHealthStatus.DEGRADED)
        assert result.action == RecoveryAction.NONE

    def test_unhealthy_reinit(self):
        healer = self._make(AgentHealthStatus.UNHEALTHY)
        result = healer.heal(override_status=AgentHealthStatus.UNHEALTHY)
        assert result.action == RecoveryAction.AGENT_REINIT
        assert result.success is True
        assert result.details["cleared_error_history"] is True

    def test_dead_with_substitute(self):
        healer = self._make(
            AgentHealthStatus.DEAD,
            substitute_role="fallback_backend",
        )
        result = healer.heal(override_status=AgentHealthStatus.DEAD)
        assert result.action == RecoveryAction.SUBSTITUTE_AGENT
        assert result.success is True
        assert result.details["substitute_role"] == "fallback_backend"

    def test_dead_without_substitute_escalates(self):
        healer = self._make(AgentHealthStatus.DEAD, substitute_role=None)
        result = healer.heal(override_status=AgentHealthStatus.DEAD)
        assert result.action == RecoveryAction.ESCALATE
        assert result.success is False

    def test_max_recovery_attempts_blocks_healing(self):
        healer = self._make(
            AgentHealthStatus.UNHEALTHY,
            max_recovery_attempts=2,
        )
        healer.heal(override_status=AgentHealthStatus.UNHEALTHY)
        healer.heal(override_status=AgentHealthStatus.UNHEALTHY)
        result = healer.heal(override_status=AgentHealthStatus.UNHEALTHY)
        assert result.action == RecoveryAction.NONE
        assert "cooldown_or_max_attempts" in result.details["reason"]

    def test_reset_clears_recovery_count(self):
        healer = self._make(AgentHealthStatus.UNHEALTHY, max_recovery_attempts=1)
        healer.heal(override_status=AgentHealthStatus.UNHEALTHY)
        healer.reset_recovery_count()
        result = healer.heal(override_status=AgentHealthStatus.UNHEALTHY)
        assert result.action == RecoveryAction.AGENT_REINIT

    def test_recovery_history_recorded(self):
        healer = self._make(AgentHealthStatus.UNHEALTHY)
        healer.heal(override_status=AgentHealthStatus.UNHEALTHY)
        assert len(healer.recovery_history) == 1


# ---------------------------------------------------------------------------
# HealthWatchdog
# ---------------------------------------------------------------------------

class TestHealthWatchdog:
    def _make_registries(self):
        monitor_reg = HealthMonitorRegistry(
            AgentHealthThresholds(
                degraded_consecutive_failures=2,
                unhealthy_consecutive_failures=4,
                dead_consecutive_failures=6,
            )
        )
        diagnostic_reg = DiagnosticRegistry()
        healer_reg = SelfHealerRegistry(HealingConfig(recovery_cooldown_seconds=0.0))
        return monitor_reg, diagnostic_reg, healer_reg

    @pytest.mark.asyncio
    async def test_check_once_no_alerts_when_healthy(self):
        mon_reg, diag_reg, heal_reg = self._make_registries()
        mon_reg.get("backend").record_success()
        watchdog = HealthWatchdog(mon_reg, diag_reg, heal_reg)
        alerts = await watchdog.check_once()
        assert alerts == []

    @pytest.mark.asyncio
    async def test_check_once_detects_degraded(self):
        mon_reg, diag_reg, heal_reg = self._make_registries()
        m = mon_reg.get("backend")
        for _ in range(2):
            m.record_failure("slow")
        watchdog = HealthWatchdog(mon_reg, diag_reg, heal_reg, WatchdogConfig(auto_heal=False))
        alerts = await watchdog.check_once()
        assert len(alerts) == 1
        assert alerts[0].agent_role == "backend"
        assert alerts[0].status == AgentHealthStatus.DEGRADED

    @pytest.mark.asyncio
    async def test_alerter_called_on_issue(self):
        mon_reg, diag_reg, heal_reg = self._make_registries()
        m = mon_reg.get("qa")
        for _ in range(4):
            m.record_failure("fatal")

        received: list[WatchdogAlert] = []

        async def my_alerter(alert: WatchdogAlert) -> None:
            received.append(alert)

        watchdog = HealthWatchdog(mon_reg, diag_reg, heal_reg, WatchdogConfig(auto_heal=False))
        watchdog.add_alerter(my_alerter)
        await watchdog.check_once()
        assert len(received) == 1
        assert received[0].agent_role == "qa"

    @pytest.mark.asyncio
    async def test_max_alerts_per_agent_spam_prevention(self):
        mon_reg, diag_reg, heal_reg = self._make_registries()
        m = mon_reg.get("backend")
        for _ in range(2):
            m.record_failure("err")

        watchdog = HealthWatchdog(
            mon_reg, diag_reg, heal_reg,
            WatchdogConfig(auto_heal=False, max_alerts_per_agent=2),
        )
        for _ in range(5):
            await watchdog.check_once()
        # 최대 2번까지만 알림
        assert len(watchdog.alert_history) <= 2

    @pytest.mark.asyncio
    async def test_start_stop(self):
        mon_reg, diag_reg, heal_reg = self._make_registries()
        watchdog = HealthWatchdog(
            mon_reg, diag_reg, heal_reg,
            WatchdogConfig(check_interval_seconds=60.0),
        )
        await watchdog.start()
        assert watchdog.is_running
        await watchdog.stop()
        assert not watchdog.is_running

    @pytest.mark.asyncio
    async def test_auto_heal_triggers_on_unhealthy(self):
        mon_reg, diag_reg, heal_reg = self._make_registries()
        m = mon_reg.get("backend")
        for _ in range(4):
            m.record_failure("server down")

        watchdog = HealthWatchdog(mon_reg, diag_reg, heal_reg, WatchdogConfig(auto_heal=True))
        alerts = await watchdog.check_once()
        assert len(alerts) >= 1
        # 복구 히스토리 확인
        healer = heal_reg.get(
            "backend",
            mon_reg.get("backend"),
            diag_reg.get("backend"),
        )
        assert len(healer.recovery_history) >= 1


# ---------------------------------------------------------------------------
# CircuitBreaker + HealthMonitor 통합
# ---------------------------------------------------------------------------

class TestCircuitBreakerHealthIntegration:
    @pytest.mark.asyncio
    async def test_circuit_open_records_circuit_open(self):
        from src.resilience.circuit_breaker import CircuitBreaker, CircuitBreakerConfig

        monitor = AgentHealthMonitor("backend")
        config = CircuitBreakerConfig(failure_threshold=2)
        cb = CircuitBreaker("backend", config, health_monitor=monitor)

        async def failing():
            raise RuntimeError("fail")

        for _ in range(2):
            try:
                await cb.call(failing)
            except RuntimeError:
                pass

        assert monitor.status == AgentHealthStatus.UNHEALTHY
