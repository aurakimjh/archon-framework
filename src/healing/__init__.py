"""Self-Healing Agent 모듈 — 헬스 모니터링, 진단, 자동 복구."""

from src.healing.diagnostics import (
    AgentDiagnostician,
    DiagnosticRegistry,
    DiagnosticReport,
    ErrorCategory,
    ErrorRecord,
    RootCause,
    classify_error,
)
from src.healing.health_monitor import (
    AgentHealthMonitor,
    AgentHealthStatus,
    AgentHealthThresholds,
    HealthCheckResult,
    HealthMonitorRegistry,
)
from src.healing.self_healer import (
    HealingConfig,
    RecoveryAction,
    RecoveryResult,
    SelfHealer,
    SelfHealerRegistry,
)
from src.healing.watchdog import (
    HealthWatchdog,
    WatchdogAlert,
    WatchdogConfig,
)

__all__ = [
    # health_monitor
    "AgentHealthMonitor",
    "AgentHealthStatus",
    "AgentHealthThresholds",
    "HealthCheckResult",
    "HealthMonitorRegistry",
    # diagnostics
    "AgentDiagnostician",
    "DiagnosticRegistry",
    "DiagnosticReport",
    "ErrorCategory",
    "ErrorRecord",
    "RootCause",
    "classify_error",
    # self_healer
    "HealingConfig",
    "RecoveryAction",
    "RecoveryResult",
    "SelfHealer",
    "SelfHealerRegistry",
    # watchdog
    "HealthWatchdog",
    "WatchdogAlert",
    "WatchdogConfig",
]
