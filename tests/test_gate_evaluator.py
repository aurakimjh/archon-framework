"""Human Gate 판정 로직 테스트."""

from src.gate.evaluator import evaluate_gate
from src.gate.models import GateDecision
from src.orchestrator.handoff import QualityGates, SecurityScan, TestResults
from src.registry.models import QualityPolicy


def _make_quality(**overrides) -> QualityGates:
    defaults = {
        "test_results": TestResults(
            unit_passed=42, unit_failed=0, integration_passed=8, coverage_percent=87.0
        ),
        "lint_result": "passed",
        "build_result": "passed",
        "security_scan": SecurityScan(critical=0, high=0, medium=0, low=0),
        "review_score": 85,
    }
    defaults.update(overrides)
    return QualityGates(**defaults)


def _make_policy(**overrides) -> QualityPolicy:
    defaults = {
        "coverage_threshold": 80,
        "review_score_threshold": 70,
        "max_retry_before_escalation": 3,
    }
    defaults.update(overrides)
    return QualityPolicy(**defaults)


# --- 기본 Gate 판정 ---


def test_auto_pass():
    result = evaluate_gate(_make_quality(), _make_policy())
    assert result == GateDecision.AUTO_PASS


def test_l1_rework_lint_failure():
    q = _make_quality(lint_result="failed")
    result = evaluate_gate(q, _make_policy())
    assert result == GateDecision.L1_REWORK


def test_l1_rework_low_coverage():
    q = _make_quality(
        test_results=TestResults(unit_passed=30, unit_failed=0, coverage_percent=75.0)
    )
    result = evaluate_gate(q, _make_policy())
    assert result == GateDecision.L1_REWORK


def test_l2_human_low_review_score():
    q = _make_quality(review_score=60)
    result = evaluate_gate(q, _make_policy())
    assert result == GateDecision.L2_HUMAN


def test_l2_human_schema_change():
    result = evaluate_gate(_make_quality(), _make_policy(), has_schema_change=True)
    assert result == GateDecision.L2_HUMAN


def test_l2_human_external_integration():
    result = evaluate_gate(_make_quality(), _make_policy(), has_external_integration=True)
    assert result == GateDecision.L2_HUMAN


def test_l2_human_retry_exhausted():
    result = evaluate_gate(_make_quality(), _make_policy(), retry_count=3)
    assert result == GateDecision.L2_HUMAN


def test_l3_halt_build_failure():
    q = _make_quality(build_result="failed")
    result = evaluate_gate(q, _make_policy())
    assert result == GateDecision.L3_HALT


def test_l3_halt_critical_security():
    q = _make_quality(security_scan=SecurityScan(critical=1, high=0, medium=0, low=0))
    result = evaluate_gate(q, _make_policy())
    assert result == GateDecision.L3_HALT


def test_l3_halt_agent_loop():
    """에이전트 루프 감지: retry_count >= 3이면서 빌드 실패."""
    q = _make_quality(build_result="failed")
    result = evaluate_gate(q, _make_policy(), retry_count=3)
    assert result == GateDecision.L3_HALT


def test_l4_deploy():
    result = evaluate_gate(_make_quality(), _make_policy(), is_deploy_request=True)
    assert result == GateDecision.L4_DEPLOY


# --- Multi-Provider Consensus ---


def test_consensus_l2_is_not_overwritten_by_clean_quality():
    """Consensus가 L2를 요구하면 일반 품질 지표가 깨끗해도 L2를 유지한다."""
    q = _make_quality(
        consensus_score=91.0,
        consensus_reached=False,
        gate_decision=GateDecision.L2_HUMAN,
    )
    result = evaluate_gate(q, _make_policy())
    assert result == GateDecision.L2_HUMAN


def test_consensus_l1_is_not_overwritten_by_auto_pass():
    """Consensus가 L1을 요구하면 AUTO_PASS로 다운그레이드하지 않는다."""
    q = _make_quality(
        consensus_score=84.0,
        consensus_reached=True,
        gate_decision=GateDecision.L1_REWORK,
    )
    result = evaluate_gate(q, _make_policy())
    assert result == GateDecision.L1_REWORK


def test_policy_l2_is_not_downgraded_by_consensus_auto_pass():
    """품질 정책이 더 엄격하면 consensus AUTO_PASS가 이를 덮지 못한다."""
    q = _make_quality(
        review_score=60,
        consensus_score=92.0,
        consensus_reached=True,
        gate_decision=GateDecision.AUTO_PASS,
    )
    result = evaluate_gate(q, _make_policy())
    assert result == GateDecision.L2_HUMAN


# --- Dynamic Guardrails ---


def test_dynamic_guardrail_payment_path():
    """결제 관련 파일 변경 시 L2 강제 상향."""
    result = evaluate_gate(
        _make_quality(),
        _make_policy(),
        changed_paths=["src/services/payment_processor.py"],
    )
    assert result == GateDecision.L2_HUMAN


def test_dynamic_guardrail_auth_path():
    """인증 관련 파일 변경 시 L2 강제 상향."""
    result = evaluate_gate(
        _make_quality(),
        _make_policy(),
        changed_paths=["src/auth/login.py"],
    )
    assert result == GateDecision.L2_HUMAN


def test_dynamic_guardrail_infrastructure_path():
    """인프라 경로 변경 시 L2 강제 상향."""
    result = evaluate_gate(
        _make_quality(),
        _make_policy(),
        changed_paths=["infrastructure/terraform/main.tf"],
    )
    assert result == GateDecision.L2_HUMAN


def test_dynamic_guardrail_risk_keywords():
    """위험 키워드가 지시사항에 포함되면 L2 강제 상향."""
    result = evaluate_gate(
        _make_quality(),
        _make_policy(),
        task_instructions="Implement payment processing with Stripe API for refund handling",
    )
    assert result == GateDecision.L2_HUMAN


def test_dynamic_guardrail_delete_keyword():
    """delete_all 키워드 → L2."""
    result = evaluate_gate(
        _make_quality(),
        _make_policy(),
        task_instructions="Run delete_all on user records older than 3 years",
    )
    assert result == GateDecision.L2_HUMAN


def test_dynamic_guardrail_safe_path():
    """일반 경로 변경은 guardrail에 걸리지 않음."""
    result = evaluate_gate(
        _make_quality(),
        _make_policy(),
        changed_paths=["src/utils/helpers.py", "tests/test_utils.py"],
    )
    assert result == GateDecision.AUTO_PASS


def test_dynamic_guardrail_safe_instructions():
    """일반 지시사항은 guardrail에 걸리지 않음."""
    result = evaluate_gate(
        _make_quality(),
        _make_policy(),
        task_instructions="Add logging to the user registration endpoint",
    )
    assert result == GateDecision.AUTO_PASS


def test_dynamic_guardrail_custom_risk_paths():
    """커스텀 위험 경로 설정."""
    policy = _make_policy(high_risk_paths=["custom_module/"])
    result = evaluate_gate(
        _make_quality(),
        policy,
        changed_paths=["custom_module/sensitive.py"],
    )
    assert result == GateDecision.L2_HUMAN


# --- SOP Compliance ---


def test_sop_compliance_pass():
    """SOP 점수 충족 시 통과."""
    q = _make_quality(sop_compliance_score=85)
    result = evaluate_gate(q, _make_policy())
    assert result == GateDecision.AUTO_PASS


def test_sop_compliance_fail():
    """SOP 점수 미달 시 L2."""
    q = _make_quality(sop_compliance_score=50)
    result = evaluate_gate(q, _make_policy())
    assert result == GateDecision.L2_HUMAN


def test_sop_compliance_none_passes():
    """SOP 미검사(None)면 통과."""
    q = _make_quality(sop_compliance_score=None)
    result = evaluate_gate(q, _make_policy())
    assert result == GateDecision.AUTO_PASS


def test_sop_compliance_custom_threshold():
    """커스텀 SOP 임계값."""
    q = _make_quality(sop_compliance_score=85)
    policy = _make_policy(sop_compliance_threshold=90)
    result = evaluate_gate(q, policy)
    assert result == GateDecision.L2_HUMAN
