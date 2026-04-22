"""Human Gate 판정 로직 — QA 파이프라인 결과를 종합해 gate_decision 결정."""

from __future__ import annotations

import logging

from src.orchestrator.handoff import QualityGates, SecurityScan
from src.registry.models import QualityPolicy

from .models import GateDecision

logger = logging.getLogger(__name__)


def evaluate_gate(
    quality: QualityGates,
    policy: QualityPolicy,
    has_schema_change: bool = False,
    has_external_integration: bool = False,
    is_deploy_request: bool = False,
    retry_count: int = 0,
) -> GateDecision:
    """QA 결과와 정책을 종합해 gate_decision을 판정한다."""

    # L4 — 배포 요청은 항상 Human 최종 승인
    if is_deploy_request:
        logger.info("Gate: L4_DEPLOY — deploy request requires human approval")
        return GateDecision.L4_DEPLOY

    # L3 — 긴급 전체 중단 조건
    if _check_l3_halt(quality, retry_count):
        return GateDecision.L3_HALT

    # L2 — Human Gate 조건
    if _check_l2_human(quality, policy, has_schema_change, has_external_integration, retry_count):
        return GateDecision.L2_HUMAN

    # L1 — 에이전트 자동 재작업 조건
    if _check_l1_rework(quality, policy):
        return GateDecision.L1_REWORK

    # 자동 통과
    logger.info("Gate: AUTO_PASS — all quality checks passed")
    return GateDecision.AUTO_PASS


def _check_l3_halt(quality: QualityGates, retry_count: int) -> bool:
    """L3 긴급 중단 조건 검사."""
    reasons: list[str] = []

    if quality.build_result != "passed":
        reasons.append("build failed")

    scan = quality.security_scan
    if scan.critical > 0 or scan.high > 0:
        reasons.append(f"security: {scan.critical} critical, {scan.high} high")

    if retry_count >= 3:
        reasons.append(f"agent loop detected: {retry_count} retries")

    if reasons:
        logger.warning("Gate: L3_HALT — %s", "; ".join(reasons))
        return True
    return False


def _check_l2_human(
    quality: QualityGates,
    policy: QualityPolicy,
    has_schema_change: bool,
    has_external_integration: bool,
    retry_count: int,
) -> bool:
    """L2 Human Gate 조건 검사."""
    reasons: list[str] = []

    if quality.review_score < policy.review_score_threshold:
        reasons.append(f"review_score {quality.review_score} < {policy.review_score_threshold}")

    if quality.test_results.coverage_percent < policy.coverage_threshold - 10:
        reasons.append(
            f"coverage {quality.test_results.coverage_percent}% < "
            f"{policy.coverage_threshold - 10}%"
        )

    if has_schema_change and policy.require_human_on_schema_change:
        reasons.append("schema change detected")

    if has_external_integration and policy.require_human_on_external_integration:
        reasons.append("external integration detected")

    if quality.security_scan.medium > 0:
        reasons.append(f"security medium: {quality.security_scan.medium}")

    if retry_count >= policy.max_retry_before_escalation:
        reasons.append(f"L1 rework exhausted: {retry_count} retries")

    if reasons:
        logger.info("Gate: L2_HUMAN — %s", "; ".join(reasons))
        return True
    return False


def _check_l1_rework(quality: QualityGates, policy: QualityPolicy) -> bool:
    """L1 에이전트 자동 재작업 조건 검사."""
    reasons: list[str] = []

    if quality.lint_result != "passed":
        reasons.append("lint issues")

    coverage = quality.test_results.coverage_percent
    threshold = policy.coverage_threshold
    if threshold - 10 <= coverage < threshold:
        reasons.append(f"coverage {coverage}% slightly below {threshold}%")

    if quality.test_results.unit_failed > 0:
        reasons.append(f"{quality.test_results.unit_failed} unit tests failed")

    if reasons:
        logger.info("Gate: L1_REWORK — %s", "; ".join(reasons))
        return True
    return False
