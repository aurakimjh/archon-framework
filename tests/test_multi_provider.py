"""Multi-Provider Orchestration 테스트 — SINGLE/SHADOW/CONSENSUS/STRICT 모드."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.gate.consensus import ConsensusGate, ConsensusResult, ConsensusStrategy, ModelReview
from src.gate.models import GateDecision
from src.orchestrator.handoff import (
    Artifacts,
    ChangedFile,
    Envelope,
    HandoffArtifact,
    HumanGatePackage,
    ProjectContext,
    QualityGates,
    SecurityScan,
    Task,
    TestResults,
)
from src.orchestrator.orchestrator import Orchestrator
from src.registry.models import (
    AgentModelConfig,
    AgentRole,
    GitConfig,
    MultiProviderMode,
    ProjectMeta,
    ProjectRegistry,
    QualityPolicy,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _registry(mode: MultiProviderMode = MultiProviderMode.SINGLE, **kw) -> ProjectRegistry:
    reviewer_config = AgentModelConfig(
        model="claude-sonnet-4-6",
        multi_provider_mode=mode,
        review_models=["gpt-4o", "gemini-2.0-flash"],
        consensus_strategy="majority",
        score_divergence_threshold=20.0,
        **kw,
    )
    return ProjectRegistry(
        project_meta=ProjectMeta(project_id="p-001", project_name="Test"),
        git_config=GitConfig(repo_url="https://github.com/test/repo.git"),
        quality_policy=QualityPolicy(),
        agent_config={AgentRole.REVIEWER: reviewer_config},
    )


def _handoff() -> HandoffArtifact:
    return HandoffArtifact(
        envelope=Envelope(handoff_id="hf-mp-001", from_agent="backend", to_agent="reviewer"),
        project_context=ProjectContext(
            project_id="p-001",
            project_name="Test",
            git_repo="https://github.com/test/repo.git",
            git_branch="develop",
            base_commit_sha="abc123",
        ),
        task=Task(
            task_id="task-mp-001",
            completed_summary="Implemented feature X",
            next_instructions="Add math operations",
        ),
        artifacts=Artifacts(
            changed_files=[
                ChangedFile(path="src/math.py", change_type="added", reason="new module"),
            ]
        ),
        quality_gates=QualityGates(
            test_results=TestResults(unit_passed=10, unit_failed=0, coverage_percent=90.0),
            lint_result="passed",
            build_result="passed",
            security_scan=SecurityScan(),
            review_score=85,
            gate_decision=GateDecision.AUTO_PASS,
        ),
    )


def _consensus_result(
    reached: bool = True,
    score: float = 88.0,
    decision: GateDecision = GateDecision.AUTO_PASS,
    variance: float = 5.0,
    dissenting: list[str] | None = None,
) -> ConsensusResult:
    return ConsensusResult(
        reviews=[
            ModelReview(model="gpt-4o", review_score=90, gate_decision=decision),
            ModelReview(model="gemini-2.0-flash", review_score=86, gate_decision=decision),
        ],
        strategy=ConsensusStrategy.MAJORITY,
        final_decision=decision,
        final_score=score,
        consensus_reached=reached,
        score_variance=variance,
        dissenting_models=dissenting or [],
    )


# ---------------------------------------------------------------------------
# _build_consensus_prompt
# ---------------------------------------------------------------------------


class TestBuildConsensusPrompt:
    def test_includes_task_and_files(self):
        h = _handoff()
        prompt = Orchestrator._build_consensus_prompt(h)
        assert "Add math operations" in prompt
        assert "src/math.py" in prompt
        assert "Coverage: 90" in prompt

    def test_empty_changed_files(self):
        h = _handoff()
        h.artifacts.changed_files = []
        prompt = Orchestrator._build_consensus_prompt(h)
        assert "Changed Files" in prompt


# ---------------------------------------------------------------------------
# _merge_consensus
# ---------------------------------------------------------------------------


class TestMergeConsensus:
    def test_merge_updates_quality_gates(self):
        h = _handoff()
        consensus = _consensus_result(score=92.0, decision=GateDecision.AUTO_PASS, variance=3.0)
        Orchestrator._merge_consensus(h, consensus)

        assert h.quality_gates.review_score == 92
        assert h.quality_gates.consensus_score == 92.0
        assert h.quality_gates.consensus_reached is True
        assert h.quality_gates.score_variance == 3.0
        assert h.quality_gates.dissenting_models == []

    def test_merge_with_dissenting(self):
        h = _handoff()
        consensus = _consensus_result(reached=False, dissenting=["gemini-2.0-flash"])
        Orchestrator._merge_consensus(h, consensus)

        assert h.quality_gates.consensus_reached is False
        assert "gemini-2.0-flash" in h.quality_gates.dissenting_models

    def test_merge_appends_review_flags(self):
        h = _handoff()
        consensus = _consensus_result()
        consensus.reviews[0].flags = [
            {"severity": "low", "category": "style", "detail": "naming issue"},
        ]
        Orchestrator._merge_consensus(h, consensus)

        flag_details = [f.detail for f in h.quality_gates.review_flags]
        assert any("naming issue" in d for d in flag_details)

    def test_merge_no_successful_reviews(self):
        h = _handoff()
        consensus = ConsensusResult(
            reviews=[ModelReview(model="gpt-4o", error="timeout")],
            strategy=ConsensusStrategy.MAJORITY,
            consensus_reached=False,
        )
        original_score = h.quality_gates.review_score
        Orchestrator._merge_consensus(h, consensus)
        assert h.quality_gates.review_score == original_score


# ---------------------------------------------------------------------------
# _run_multi_provider_review
# ---------------------------------------------------------------------------


class TestRunMultiProviderReview:
    @pytest.mark.asyncio
    async def test_single_mode_skips(self):
        o = Orchestrator()
        h = _handoff()
        reg = _registry(MultiProviderMode.SINGLE)
        result = await o._run_multi_provider_review(h, reg)
        assert result is h

    @pytest.mark.asyncio
    async def test_no_review_models_skips(self):
        o = Orchestrator()
        h = _handoff()
        reg = _registry(MultiProviderMode.CONSENSUS)
        reg.agent_config[AgentRole.REVIEWER].review_models = []
        result = await o._run_multi_provider_review(h, reg)
        assert result is h

    @pytest.mark.asyncio
    async def test_consensus_mode(self):
        o = Orchestrator()
        h = _handoff()
        consensus = _consensus_result(score=90.0, decision=GateDecision.AUTO_PASS)

        with patch.object(ConsensusGate, "run_consensus", new_callable=AsyncMock, return_value=consensus):
            result = await o._run_multi_provider_review(h, _registry(MultiProviderMode.CONSENSUS))

        assert result.quality_gates.consensus_score == 90.0
        assert result.quality_gates.review_score == 90

    @pytest.mark.asyncio
    async def test_strict_mode_consensus_reached(self):
        o = Orchestrator()
        h = _handoff()
        consensus = _consensus_result(reached=True)

        with patch.object(ConsensusGate, "run_consensus", new_callable=AsyncMock, return_value=consensus):
            result = await o._run_multi_provider_review(h, _registry(MultiProviderMode.STRICT))

        assert result.quality_gates.consensus_reached is True
        assert result.human_gate_package is None

    @pytest.mark.asyncio
    async def test_strict_mode_no_consensus_escalates(self):
        o = Orchestrator()
        h = _handoff()
        consensus = _consensus_result(
            reached=False, variance=25.0, dissenting=["gemini-2.0-flash"],
        )

        with patch.object(ConsensusGate, "run_consensus", new_callable=AsyncMock, return_value=consensus):
            result = await o._run_multi_provider_review(h, _registry(MultiProviderMode.STRICT))

        assert result.quality_gates.gate_decision == GateDecision.L2_HUMAN
        assert result.human_gate_package is not None
        assert "consensus not reached" in result.human_gate_package.trigger_reason

    @pytest.mark.asyncio
    async def test_shadow_mode_returns_original(self):
        o = Orchestrator()
        h = _handoff()
        original_score = h.quality_gates.review_score
        consensus = _consensus_result(score=50.0)

        with patch.object(ConsensusGate, "run_consensus", new_callable=AsyncMock, return_value=consensus):
            result = await o._run_multi_provider_review(h, _registry(MultiProviderMode.SHADOW))

        assert result.quality_gates.review_score == original_score
        assert result.quality_gates.consensus_score is None


# ---------------------------------------------------------------------------
# Integration: _execute_pipeline with multi-provider
# ---------------------------------------------------------------------------


class TestExecutePipelineMultiProvider:
    @pytest.mark.asyncio
    async def test_pipeline_calls_multi_provider_when_configured(self):
        o = Orchestrator()
        reg = _registry(MultiProviderMode.CONSENSUS)
        h = _handoff()
        h.envelope.to_agent = "backend"

        mock_agent = MagicMock()
        mock_agent.execute = AsyncMock(return_value=h)
        mock_reviewer = MagicMock()
        mock_reviewer.execute = AsyncMock(return_value=h)
        o._agent_pool = {AgentRole.BACKEND: mock_agent, AgentRole.REVIEWER: mock_reviewer}

        consensus = _consensus_result()
        with patch("src.runtime.qa.run_qa_pipeline", new_callable=AsyncMock, return_value=h.quality_gates), \
             patch.object(o, "_run_multi_provider_review", new_callable=AsyncMock, return_value=h) as mock_mp:
            await o._execute_pipeline(h, reg)

        mock_mp.assert_called_once()

    @pytest.mark.asyncio
    async def test_pipeline_skips_multi_provider_for_single(self):
        o = Orchestrator()
        reg = _registry(MultiProviderMode.SINGLE)
        h = _handoff()
        h.envelope.to_agent = "backend"

        mock_agent = MagicMock()
        mock_agent.execute = AsyncMock(return_value=h)
        mock_reviewer = MagicMock()
        mock_reviewer.execute = AsyncMock(return_value=h)
        o._agent_pool = {AgentRole.BACKEND: mock_agent, AgentRole.REVIEWER: mock_reviewer}

        with patch("src.runtime.qa.run_qa_pipeline", new_callable=AsyncMock, return_value=h.quality_gates), \
             patch.object(o, "_run_multi_provider_review", new_callable=AsyncMock) as mock_mp:
            await o._execute_pipeline(h, reg)

        mock_mp.assert_not_called()


# ---------------------------------------------------------------------------
# QualityGates consensus fields
# ---------------------------------------------------------------------------


class TestQualityGatesConsensusFields:
    def test_default_consensus_fields(self):
        qg = QualityGates()
        assert qg.consensus_score is None
        assert qg.consensus_reached is None
        assert qg.score_variance is None
        assert qg.dissenting_models == []

    def test_set_consensus_fields(self):
        qg = QualityGates(
            consensus_score=88.5,
            consensus_reached=True,
            score_variance=4.2,
            dissenting_models=["model-a"],
        )
        assert qg.consensus_score == 88.5
        assert qg.consensus_reached is True
        assert qg.score_variance == 4.2
        assert qg.dissenting_models == ["model-a"]
