"""Human Gate 판정 로직 — QA 파이프라인 결과를 종합해 gate_decision 결정."""

from __future__ import annotations

import logging

from src.orchestrator.handoff import QualityGates
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
    changed_paths: list[str] | None = None,
    task_instructions: str = "",
) -> GateDecision:
    """QA 결과와 정책을 종합해 gate_decision을 판정한다.

    Args:
        changed_paths: 변경된 파일 경로 목록 (Dynamic Guardrails 평가용).
        task_instructions: 태스크 지시사항 (위험 키워드 감지용).
    """

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

    # L2 — Dynamic Guardrails (위험 경로/키워드 감지)
    if _check_dynamic_guardrails(policy, changed_paths, task_instructions):
        return GateDecision.L2_HUMAN

    # L2 — SOP Compliance 미달
    if _check_sop_compliance(quality, policy):
        return GateDecision.L2_HUMAN

    # L1 — 에이전트 자동 재작업 조건
    if _check_l1_rework(quality, policy):
        return GateDecision.L1_REWORK

    # 자동 통과
    logger.info("Gate: AUTO_PASS — all quality checks passed")
    return GateDecision.AUTO_PASS


def _check_l3_halt(quality: QualityGates, retry_count: int) -> bool:
    """L3 긴급 중단 조건 검사.

    L3은 빌드 실패, 보안 위협 등 긴급 상황에만 발동한다.
    retry 에스컬레이션은 L2에서 처리한다.
    """
    reasons: list[str] = []

    if quality.build_result != "passed":
        reasons.append("build failed")

    scan = quality.security_scan
    if scan.critical > 0 or scan.high > 0:
        reasons.append(f"security: {scan.critical} critical, {scan.high} high")

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


def _check_dynamic_guardrails(
    policy: QualityPolicy,
    changed_paths: list[str] | None,
    task_instructions: str,
) -> bool:
    """Dynamic Guardrails — 위험 경로/키워드 감지 시 L2 강제 상향.

    결제, 인증, 인프라 등 민감한 영역의 변경을 감지하여
    자동으로 Human Gate를 활성화한다.
    """
    reasons: list[str] = []

    # 1. 변경 파일 경로 검사
    if changed_paths:
        for path in changed_paths:
            path_lower = path.lower()
            for risk_path in policy.high_risk_paths:
                if risk_path in path_lower:
                    reasons.append(f"high-risk path: {path} (matches '{risk_path}')")
                    break

    # 2. 태스크 지시사항 키워드 검사
    if task_instructions:
        instructions_lower = task_instructions.lower()
        matched_keywords = [
            kw for kw in policy.high_risk_keywords if kw in instructions_lower
        ]
        if matched_keywords:
            reasons.append(
                f"high-risk keywords in instructions: {', '.join(matched_keywords[:3])}"
            )

    if reasons:
        logger.info("Gate: L2_HUMAN (Dynamic Guardrails) — %s", "; ".join(reasons))
        return True
    return False


def _check_sop_compliance(quality: QualityGates, policy: QualityPolicy) -> bool:
    """SOP Compliance 미달 검사."""
    if quality.sop_compliance_score is None:
        return False  # SOP 미검사 시 통과

    if quality.sop_compliance_score < policy.sop_compliance_threshold:
        logger.info(
            "Gate: L2_HUMAN — SOP compliance %d < %d",
            quality.sop_compliance_score,
            policy.sop_compliance_threshold,
        )
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
