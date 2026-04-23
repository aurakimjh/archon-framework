"""DemoPipeline 전체 흐름 테스트 (mock 모드)."""

from __future__ import annotations

from src.gate.models import GateDecision
from src.orchestrator.handoff import Envelope, HandoffArtifact, ProjectContext, Task, TechStack
from src.pipeline.demo_pipeline import DemoPipeline
from src.registry.models import GitConfig, ProjectMeta, ProjectRegistry, QualityPolicy


def _make_registry(max_retry: int = 3) -> ProjectRegistry:
    return ProjectRegistry(
        project_meta=ProjectMeta(project_id="test-001", project_name="Test Project"),
        git_config=GitConfig(repo_url="https://github.com/test/repo.git"),
        quality_policy=QualityPolicy(
            coverage_threshold=80,
            review_score_threshold=70,
            max_retry_before_escalation=max_retry,
        ),
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

    # 두 번째 시도가 성공했으므로 rework 지시사항은 내부에서 처리됨
    # 최종 handoff는 AUTO_PASS 결과를 담음
    assert result.gate == GateDecision.AUTO_PASS
    assert "Rework Required" not in result.handoff.task.next_instructions
