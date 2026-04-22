"""Human Gate 판정 모델."""

from enum import StrEnum


class GateDecision(StrEnum):
    """QA 결과를 종합한 최종 판정값."""

    AUTO_PASS = "auto_pass"
    L1_REWORK = "l1_rework"
    L2_HUMAN = "l2_human"
    L3_HALT = "l3_halt"
    L4_DEPLOY = "l4_deploy"


class SecuritySeverity(StrEnum):
    """보안 취약점 심각도."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
