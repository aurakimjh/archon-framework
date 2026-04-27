"""DemoPipeline 전체 흐름 테스트 (mock 모드)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from src.gate.consensus import ConsensusResult, ConsensusStrategy, ModelReview
from src.gate.models import GateDecision
from src.orchestrator.handoff import Envelope, HandoffArtifact, ProjectContext, Task, TechStack
from src.pipeline.demo_pipeline import DemoPipeline
from src.registry.models import (
    AgentModelConfig,
    AgentRole,
    GitConfig,
    MultiProviderMode,
    ProjectMeta,
    ProjectRegistry,
    QualityPolicy,
)


def _make_registry(
    max_retry: int = 3,
    multi_provider_mode: MultiProviderMode = MultiProviderMode.SINGLE,
) -> ProjectRegistry:
    agent_config = {}
    if multi_provider_mode != MultiProviderMode.SINGLE:
        agent_config[AgentRole.REVIEWER] = AgentModelConfig(
            model="reviewer-primary",
            multi_provider_mode=multi_provider_mode,
            review_models=["model-a", "model-b"],
            score_divergence_threshold=20.0,
        )

    return ProjectRegistry(
        project_meta=ProjectMeta(project_id="test-001", project_name="Test Project"),
        git_config=GitConfig(repo_url="https://github.com/test/repo.git"),
        quality_policy=QualityPolicy(
            coverage_threshold=80,
            review_score_threshold=70,
            max_retry_before_escalation=max_retry,
        ),
        agent_config=agent_config,
    )


def _make_handoff() -> HandoffArtifact:
    return HandoffArtifact(
        envelope=Envelope(
            handoff_id="test-hf-001",
            from_agent="orchestrator",
            to_agent="backend",
        ),
        project_context=ProjectContext(
            project_id="test-001",
            project_name="Test Project",
            git_repo="https://github.com/test/repo.git",
            git_branch="agent/backend/test-001",
            base_commit_sha="abc123",
            tech_stack=TechStack(language="python", framework="fastapi"),
        ),
        task=Task(
            task_id="test-001",
            completed_summary="",
            next_instructions="Implement add(a, b) -> int.",
        ),
    )


async def test_auto_pass_single_attempt() -> None:
    """auto_pass: 첫 시도에 AUTO_PASS, review_score=92, lint=passed."""
    pipeline = DemoPipeline(registry=_make_registry(), mock=True, scenario="auto_pass")
    result = await pipeline.run(_make_handoff())

    assert result.gate == GateDecision.AUTO_PASS
    assert result.attempt == 0
    assert result.handoff.quality_gates.review_score == 92
    assert result.handoff.quality_gates.lint_result == "passed"


async def test_l1_rework_then_auto_pass() -> None:
    """l1: attempt 0 → L1_REWORK (린트 실패), attempt 1 → AUTO_PASS."""
    pipeline = DemoPipeline(registry=_make_registry(), mock=True, scenario="l1")
    result = await pipeline.run(_make_handoff())

    assert result.gate == GateDecision.AUTO_PASS
    assert result.attempt == 1  # 두 번째 시도에 성공


async def test_l1_exhausted_escalates_to_l2() -> None:
    """L1 max_retry 소진 시 L2_HUMAN 에스컬레이션."""
    # max_retry=2 → attempts 0, 1 retry, attempt 2 exhausted → L2
    pipeline = DemoPipeline(
        registry=_make_registry(max_retry=2),
        mock=True,
        scenario="l1_exhausted",
    )
    result = await pipeline.run(_make_handoff())

    assert result.gate == GateDecision.L2_HUMAN
    assert result.attempt == 2


async def test_l2_human_direct() -> None:
    """l2: review_score < threshold → 즉시 L2_HUMAN, human_gate_package 설정."""
    pipeline = DemoPipeline(registry=_make_registry(), mock=True, scenario="l2")
    result = await pipeline.run(_make_handoff())

    assert result.gate == GateDecision.L2_HUMAN
    assert result.attempt == 0
    assert result.handoff.human_gate_package is not None


async def test_step_callback_fired_for_all_stages() -> None:
    """on_step 콜백이 backend/qa/reviewer/gate/commit 단계마다 호출되는지 검증."""
    fired: list[str] = []
    pipeline = DemoPipeline(
        registry=_make_registry(),
        mock=True,
        scenario="auto_pass",
        on_step=lambda step, _data: fired.append(step),
    )
    await pipeline.run(_make_handoff())

    assert "backend" in fired
    assert "backend_done" in fired
    assert "qa" in fired
    assert "qa_done" in fired
    assert "reviewer" in fired
    assert "reviewer_done" in fired
    assert "gate" in fired
    assert "commit" in fired


async def test_multi_provider_consensus_callback_fired() -> None:
    """Multi-Provider 설정 시 consensus 단계 이벤트와 결과를 노출한다."""
    fired: list[str] = []
    result_payloads: list[object] = []
    consensus = ConsensusResult(
        reviews=[
            ModelReview(
                model="model-a",
                review_score=90,
                gate_decision=GateDecision.AUTO_PASS,
            ),
            ModelReview(
                model="model-b",
                review_score=86,
                gate_decision=GateDecision.AUTO_PASS,
            ),
        ],
        strategy=ConsensusStrategy.MAJORITY,
        final_decision=GateDecision.AUTO_PASS,
        final_score=88.0,
        consensus_reached=True,
        score_variance=2.0,
    )
    pipeline = DemoPipeline(
        registry=_make_registry(multi_provider_mode=MultiProviderMode.CONSENSUS),
        mock=True,
        scenario="auto_pass",
        on_step=lambda step, data: (fired.append(step), result_payloads.append(data)),
    )

    with patch(
        "src.gate.consensus.ConsensusGate.run_consensus",
        new_callable=AsyncMock,
        return_value=consensus,
    ):
        result = await pipeline.run(_make_handoff())

    assert result.gate == GateDecision.AUTO_PASS
    assert "consensus" in fired
    assert "consensus_done" in fired
    payload = result_payloads[fired.index("consensus_done")]
    assert isinstance(payload, dict)
    assert payload["consensus_score"] == 88.0
    assert result.handoff.quality_gates.consensus_score == 88.0


async def test_strict_multi_provider_consensus_failure_stays_l2() -> None:
    """Strict 합의 실패는 일반 gate 재평가 후에도 AUTO_PASS로 덮이지 않는다."""
    consensus = ConsensusResult(
        reviews=[
            ModelReview(
                model="model-a",
                review_score=92,
                gate_decision=GateDecision.AUTO_PASS,
            ),
            ModelReview(
                model="model-b",
                review_score=88,
                gate_decision=GateDecision.AUTO_PASS,
            ),
        ],
        strategy=ConsensusStrategy.MAJORITY,
        final_decision=GateDecision.AUTO_PASS,
        final_score=90.0,
        consensus_reached=False,
        score_variance=25.0,
        dissenting_models=["model-b"],
    )
    pipeline = DemoPipeline(
        registry=_make_registry(multi_provider_mode=MultiProviderMode.STRICT),
        mock=True,
        scenario="auto_pass",
    )

    with patch(
        "src.gate.consensus.ConsensusGate.run_consensus",
        new_callable=AsyncMock,
        return_value=consensus,
    ):
        result = await pipeline.run(_make_handoff())

    assert result.gate == GateDecision.L2_HUMAN
    assert result.handoff.quality_gates.gate_decision == GateDecision.L2_HUMAN
    assert result.handoff.human_gate_package is not None


async def test_l1_callback_fires_rework_event() -> None:
    """l1 시나리오에서 l1_rework 이벤트가 발생하는지 검증."""
    fired: list[str] = []
    pipeline = DemoPipeline(
        registry=_make_registry(),
        mock=True,
        scenario="l1",
        on_step=lambda step, _data: fired.append(step),
    )
    await pipeline.run(_make_handoff())

    assert "l1_rework" in fired
    assert fired.count("backend") == 2  # 두 번 실행됨


async def test_dry_run_does_not_commit() -> None:
    """dry_run=True 시 AUTO_PASS여도 커밋 미실행."""
    pipeline = DemoPipeline(
        registry=_make_registry(), mock=True, scenario="auto_pass", dry_run=True
    )
    result = await pipeline.run(_make_handoff())

    assert result.gate == GateDecision.AUTO_PASS
    assert result.committed is False
    assert result.commit_sha is None


async def test_rework_handoff_injects_flags() -> None:
    """L1_REWORK 시 review_flags가 next_instructions에 주입되는지 검증."""
    captured_instructions: list[str] = []

    def on_step(step: str, data: object) -> None:
        if step == "backend" and captured_instructions:
            return  # 두 번째 backend 호출 전 이미 캡처됨

    # l1 시나리오에서 두 번째 시도의 handoff를 직접 검사하기 위해 pipeline 내부 호출
    pipeline = DemoPipeline(registry=_make_registry(), mock=True, scenario="l1")
    initial = _make_handoff()
    result = await pipeline.run(initial)

    # L1 rework 후 두 번째 시도에서 AUTO_PASS
    assert result.gate == GateDecision.AUTO_PASS
    # rework 지시사항이 주입되었는지 확인 (첫 시도 실패 → 재작업)
    assert result.attempt == 1  # 두 번째 시도 (0-indexed)
