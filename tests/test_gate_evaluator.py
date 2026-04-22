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
