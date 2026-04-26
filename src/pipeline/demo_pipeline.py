"""PoC 데모 파이프라인 — Backend→QA→Reviewer→Gate→Commit 전체 흐름."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from src.gate.evaluator import evaluate_gate
from src.gate.models import GateDecision
from src.log import get_logger
from src.orchestrator.handoff import (
    Artifacts,
    ChangedFile,
    HandoffArtifact,
    HumanGatePackage,
    QualityGates,
    ReviewFlag,
    SecurityScan,
    TestResults,
)
from src.registry.models import ProjectRegistry

_log = logging.getLogger(__name__)
slog = get_logger(__name__)

# ---------------------------------------------------------------------------
# Per-attempt mock data
# ---------------------------------------------------------------------------

@dataclass
class _AttemptData:
    backend_summary: str
    lint: str
    build: str
    coverage: float
    unit_passed: int
    unit_failed: int
    security: SecurityScan
    review_score: int
    review_flags: list[ReviewFlag]


# Preset data bundles
_CLEAN = _AttemptData(
    backend_summary="Implemented add(a, b) -> int in src/math/operations.py. Added 14 unit tests.",
    lint="passed", build="passed", coverage=88.5,
    unit_passed=14, unit_failed=0,
    security=SecurityScan(),
    review_score=92, review_flags=[],
)

_LINT_FAIL = _AttemptData(
    backend_summary="Implemented add function. Style issues remain.",
    lint="failed", build="passed", coverage=82.0,
    unit_passed=12, unit_failed=0,
    security=SecurityScan(),
    review_score=78,
    review_flags=[ReviewFlag(severity="low", category="style", detail="E501 line too long")],
)

_LINT_FIXED = _AttemptData(
    backend_summary="Fixed lint issues. Reimplemented add(a, b) -> int with proper style.",
    lint="passed", build="passed", coverage=85.0,
    unit_passed=14, unit_failed=0,
    security=SecurityScan(),
    review_score=89, review_flags=[],
)

_POOR_REVIEW = _AttemptData(
    backend_summary="Implemented add function. Missing error handling.",
    lint="passed", build="passed", coverage=76.0,
    unit_passed=10, unit_failed=0,
    security=SecurityScan(),
    review_score=58,
    review_flags=[
        ReviewFlag(severity="high", category="design", detail="Missing error handling"),
        ReviewFlag(severity="high", category="security", detail="Input not validated"),
    ],
)


# scenario → per-attempt data list (last entry reused when attempt index exceeds length)
MOCK_SCENARIOS: dict[str, list[_AttemptData]] = {
    "auto_pass":    [_CLEAN],
    "l1":           [_LINT_FAIL, _LINT_FIXED],          # attempt 0 → L1, attempt 1 → AUTO_PASS
    "l2":           [_POOR_REVIEW],                     # review_score < threshold → L2_HUMAN
    "l1_exhausted": [_LINT_FAIL, _LINT_FAIL, _LINT_FAIL, _LINT_FAIL],  # all attempts → L1
}

SCENARIO_LABELS: dict[str, str] = {
    "auto_pass":    "AUTO_PASS — 완벽한 코드, 자동 커밋",
    "l1":           "L1_REWORK — 린트 실패 → 재작업 → AUTO_PASS",
    "l2":           "L2_HUMAN — 낮은 리뷰 점수, 개발자 판단 요청",
    "l1_exhausted": "L1_REWORK 소진 → L2_HUMAN 에스컬레이션",
}

# (step_name, data) — data는 str 또는 dict
StepCallback = Callable[[str, Any], None]


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------

@dataclass
class PipelineResult:
    """파이프라인 최종 실행 결과."""

    handoff: HandoffArtifact
    gate: GateDecision
    attempt: int               # 0-indexed 최종 시도 번호
    committed: bool = False
    commit_sha: str | None = None


# ---------------------------------------------------------------------------
# DemoPipeline
# ---------------------------------------------------------------------------

class DemoPipeline:
    """Backend→QA→Reviewer→Gate→Commit PoC 파이프라인.

    mock=True : LLM/subprocess 없이 시나리오 데이터로 전체 흐름 시연.
    mock=False: 실제 BackendAgent, QA Pipeline, ReviewerAgent 실행.
    dry_run=True: AUTO_PASS 시 커밋 미실행 (데모/테스트용).
    on_step: 각 단계 이벤트를 받는 콜백 (step_name, data).
    """

    def __init__(
        self,
        registry: ProjectRegistry,
        *,
        mock: bool = True,
        scenario: str = "auto_pass",
        dry_run: bool = True,
        on_step: StepCallback | None = None,
    ) -> None:
        if scenario not in MOCK_SCENARIOS:
            raise ValueError(
                f"Unknown scenario: {scenario!r}. Choose from {list(MOCK_SCENARIOS)}"
            )
        self.registry = registry
        self.mock = mock
        self.scenario = scenario
        self.dry_run = dry_run
        self._emit: StepCallback = on_step or (lambda _s, _d: None)

    def _attempt_data(self, attempt: int) -> _AttemptData:
        pool = MOCK_SCENARIOS[self.scenario]
        return pool[min(attempt, len(pool) - 1)]

    # ------------------------------------------------------------------
    # Mock steps
    # ------------------------------------------------------------------

    async def _mock_backend(self, handoff: HandoffArtifact, attempt: int) -> HandoffArtifact:
        data = self._attempt_data(attempt)
        result = handoff.model_copy(deep=True)
        result.envelope.from_agent = "backend"
        result.envelope.to_agent = "reviewer"
        result.task.completed_summary = data.backend_summary
        result.artifacts = Artifacts(
            changed_files=[
                ChangedFile(
                    path="src/math/operations.py",
                    change_type="added",
                    reason="new function",
                ),
                ChangedFile(
                    path="tests/test_math.py",
                    change_type="added",
                    reason="unit tests",
                ),
            ]
        )
        return result

    async def _mock_qa(self, attempt: int) -> QualityGates:
        data = self._attempt_data(attempt)
        return QualityGates(
            test_results=TestResults(
                unit_passed=data.unit_passed,
                unit_failed=data.unit_failed,
                coverage_percent=data.coverage,
            ),
            lint_result=data.lint,
            build_result=data.build,
            security_scan=data.security,
        )

    async def _mock_reviewer(
        self, handoff: HandoffArtifact, attempt: int
    ) -> HandoffArtifact:
        data = self._attempt_data(attempt)
        result = handoff.model_copy(deep=True)
        result.envelope.from_agent = "reviewer"
        result.quality_gates.review_score = data.review_score
        result.quality_gates.review_flags = list(data.review_flags)
        return result

    # ------------------------------------------------------------------
    # Real steps
    # ------------------------------------------------------------------

    async def _real_backend(self, handoff: HandoffArtifact) -> HandoffArtifact:
        from src.agents.backend import BackendAgent

        return await BackendAgent().execute(handoff, self.registry)

    async def _real_qa(self, handoff: HandoffArtifact) -> QualityGates:
        from src.runtime.qa import run_qa_pipeline

        return await run_qa_pipeline(
            project_root=handoff.project_context.git_repo,
            registry=self.registry,
        )

    async def _real_reviewer(self, handoff: HandoffArtifact) -> HandoffArtifact:
        from src.agents.reviewer import ReviewerAgent

        return await ReviewerAgent().execute(handoff, self.registry)

    # ------------------------------------------------------------------
    # L1 rework handoff preparation
    # ------------------------------------------------------------------

    def _prepare_rework(
        self,
        original: HandoffArtifact,
        review_result: HandoffArtifact,
        retry_count: int,
    ) -> HandoffArtifact:
        """리뷰 플래그를 next_instructions에 주입해 재작업 핸드오프 생성."""
        lines = [original.task.next_instructions, "", "## Rework Required"]
        for flag in review_result.quality_gates.review_flags:
            lines.append(f"- [{flag.severity}] {flag.category}: {flag.detail}")
        if review_result.quality_gates.lint_result != "passed":
            lines.append("- Fix all lint issues (ruff)")
        n_failed = review_result.quality_gates.test_results.unit_failed
        if n_failed > 0:
            lines.append(f"- Fix {n_failed} failing unit test{'s' if n_failed > 1 else ''}")

        rework = original.model_copy(deep=True)
        rework.task.next_instructions = "\n".join(lines)
        rework.envelope.retry_count = retry_count
        rework.envelope.parent_handoff_id = review_result.envelope.handoff_id
        return rework

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def run(self, initial_handoff: HandoffArtifact) -> PipelineResult:
        """파이프라인 실행.

        AUTO_PASS : dry_run=False 시 GitExecutor.auto_commit() 수행.
        L1_REWORK : max_retry_before_escalation 이내 자동 재시도.
        L1 소진    : L2_HUMAN 에스컬레이션.
        L2/L3/L4  : 즉시 중단 및 반환.
        """
        max_retries = self.registry.quality_policy.max_retry_before_escalation
        policy = self.registry.quality_policy
        current = initial_handoff.model_copy(deep=True)
        tag = "[Mock] " if self.mock else ""

        project_id = initial_handoff.project_context.project_id
        task_id = initial_handoff.task.task_id
        slog.info(
            "pipeline_start",
            project_id=project_id,
            task_id=task_id,
            scenario=self.scenario,
            mock=self.mock,
        )

        for attempt in range(max_retries + 1):
            current.envelope.retry_count = attempt
            self._emit("loop", f"Attempt {attempt + 1}/{max_retries + 1}")
            slog.info("pipeline_attempt", attempt=attempt + 1, task_id=task_id)

            # 1. Backend
            self._emit("backend", f"{tag}BackendAgent 실행 중...")
            backend_result = (
                await self._mock_backend(current, attempt)
                if self.mock
                else await self._real_backend(current)
            )
            self._emit("backend_done", {
                "summary": backend_result.task.completed_summary,
                "files": [f.path for f in backend_result.artifacts.changed_files],
            })

            # 2. QA
            self._emit("qa", f"{tag}QA Pipeline 실행 중...")
            qa_gates = (
                await self._mock_qa(attempt)
                if self.mock
                else await self._real_qa(backend_result)
            )
            backend_result.quality_gates = qa_gates
            self._emit("qa_done", {
                "lint": qa_gates.lint_result,
                "build": qa_gates.build_result,
                "unit_passed": qa_gates.test_results.unit_passed,
                "unit_failed": qa_gates.test_results.unit_failed,
                "coverage": qa_gates.test_results.coverage_percent,
                "security": qa_gates.security_scan,
            })

            # 3. Reviewer
            self._emit("reviewer", f"{tag}ReviewerAgent 실행 중...")
            review_result = (
                await self._mock_reviewer(backend_result, attempt)
                if self.mock
                else await self._real_reviewer(backend_result)
            )
            self._emit("reviewer_done", {
                "review_score": review_result.quality_gates.review_score,
                "flags": review_result.quality_gates.review_flags,
            })

            # 4. Gate
            gate = evaluate_gate(
                quality=review_result.quality_gates,
                policy=policy,
                retry_count=attempt,
            )
            review_result.quality_gates.gate_decision = gate
            self._emit("gate", {"decision": gate})

            # 5. Dispatch
            if gate == GateDecision.AUTO_PASS:
                commit_sha: str | None = None
                if not self.dry_run:
                    commit_sha = await self._do_commit(review_result)
                self._emit(
                    "commit",
                    f"커밋 완료: {commit_sha[:8]}" if commit_sha else "dry-run — 커밋 미실행",
                )
                return PipelineResult(
                    handoff=review_result,
                    gate=gate,
                    attempt=attempt,
                    committed=commit_sha is not None,
                    commit_sha=commit_sha,
                )

            if gate == GateDecision.L1_REWORK:
                if attempt < max_retries:
                    self._emit("l1_rework", f"재작업 지시 ({attempt + 1}/{max_retries}회 시도)")
                    current = self._prepare_rework(
                        original=initial_handoff,
                        review_result=review_result,
                        retry_count=attempt + 1,
                    )
                    continue
                # max_retries 소진 → L2 에스컬레이션
                review_result.quality_gates.gate_decision = GateDecision.L2_HUMAN
                self._emit("l2_escalated", f"L1 {max_retries}회 소진 → L2_HUMAN 에스컬레이션")
                return PipelineResult(
                    handoff=review_result,
                    gate=GateDecision.L2_HUMAN,
                    attempt=attempt,
                )

            # L2 / L3 / L4 — 즉시 반환
            if gate == GateDecision.L2_HUMAN:
                review_result.human_gate_package = HumanGatePackage(
                    gate_level=GateDecision.L2_HUMAN,
                    trigger_reason="Quality policy triggered",
                    required_decision="Review flagged issues and decide how to proceed.",
                )
                self._emit("l2_human", "프로젝트 일시정지 — 개발자 판단 필요")
            elif gate == GateDecision.L3_HALT:
                self._emit("l3_halt", "긴급 중단 — 심각한 품질 문제")
            elif gate == GateDecision.L4_DEPLOY:
                self._emit("l4_deploy", "배포 승인 대기 — 개발자 최종 확인 필요")

            return PipelineResult(handoff=review_result, gate=gate, attempt=attempt)

        # unreachable — every branch inside the loop returns or continues
        return PipelineResult(  # type: ignore[return-value]
            handoff=current, gate=GateDecision.L3_HALT, attempt=max_retries
        )

    async def _do_commit(self, handoff: HandoffArtifact) -> str | None:
        from src.runtime.git_executor import GitExecutor

        git = GitExecutor(self.registry.git_config)
        return await git.auto_commit(
            handoff=handoff,
            message_template=self.registry.git_config.auto_commit_message_template,
        )
