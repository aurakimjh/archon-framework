"""Orchestrator 코어 ���스트 — process_handoff 상태 머신, 체인 실행, 알림."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.gate.models import GateDecision
from src.memory.context_injector import MemoryStore
from src.notifications.base import GateEvent, Notifier
from src.orchestrator.handoff import (
    Artifacts,
    ChangedFile,
    Envelope,
    HandoffArtifact,
    HumanGatePackage,
    ProjectContext,
    QualityGates,
    ReviewFlag,
    SecurityScan,
    Task,
    TestResults,
)
from src.orchestrator.orchestrator import DEFAULT_TASK_CHAINS, Orchestrator
from src.registry.models import (
    AgentRole,
    GitConfig,
    ProjectMeta,
    ProjectRegistry,
    QualityPolicy,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_registry(**overrides) -> ProjectRegistry:
    defaults = dict(
        project_meta=ProjectMeta(project_id="proj-001", project_name="Test"),
        git_config=GitConfig(repo_url="https://github.com/test/repo.git"),
        quality_policy=QualityPolicy(
            coverage_threshold=80,
            review_score_threshold=70,
            max_retry_before_escalation=2,
        ),
    )
    defaults.update(overrides)
    return ProjectRegistry(**defaults)


def _make_handoff(**overrides) -> HandoffArtifact:
    defaults = dict(
        envelope=Envelope(
            handoff_id="hf-001",
            from_agent="orchestrator",
            to_agent="backend",
        ),
        project_context=ProjectContext(
            project_id="proj-001",
            project_name="Test",
            git_repo="https://github.com/test/repo.git",
            git_branch="develop",
            base_commit_sha="abc123",
        ),
        task=Task(
            task_id="task-001",
            completed_summary="",
            next_instructions="Implement feature X",
        ),
    )
    defaults.update(overrides)
    return HandoffArtifact(**defaults)


def _make_quality(gate: GateDecision = GateDecision.AUTO_PASS, **kw) -> QualityGates:
    defaults = dict(
        test_results=TestResults(unit_passed=10, unit_failed=0, coverage_percent=90.0),
        lint_result="passed",
        build_result="passed",
        security_scan=SecurityScan(),
        review_score=85,
        gate_decision=gate,
    )
    defaults.update(kw)
    return QualityGates(**defaults)


def _make_result_handoff(gate: GateDecision, **kw) -> HandoffArtifact:
    h = _make_handoff()
    h.envelope.from_agent = "backend"
    h.envelope.to_agent = "reviewer"
    h.task.completed_summary = "Done"
    h.quality_gates = _make_quality(gate, **kw)
    return h


# ---------------------------------------------------------------------------
# Orchestrator 초기화
# ---------------------------------------------------------------------------


class TestOrchestratorInit:
    def test_default_init(self):
        o = Orchestrator()
        assert isinstance(o.memory, MemoryStore)
        assert o._task_chains == DEFAULT_TASK_CHAINS
        assert o._notifier is None

    def test_custom_chains(self):
        chains = {"backend": ["docs"]}
        o = Orchestrator(task_chains=chains)
        assert o._task_chains == chains

    def test_get_next_agents(self):
        o = Orchestrator()
        assert AgentRole.TESTER in o.get_next_agents(AgentRole.BACKEND)
        assert o.get_next_agents(AgentRole.DOCS) == []
        assert o.get_next_agents("unknown_role") == []


# ---------------------------------------------------------------------------
# _prepare_rework_handoff
# ---------------------------------------------------------------------------


class TestPrepareReworkHandoff:
    def test_rework_handoff_has_flags(self):
        o = Orchestrator()
        original = _make_handoff()
        review_result = _make_result_handoff(GateDecision.L1_REWORK)
        review_result.quality_gates.review_flags = [
            ReviewFlag(severity="warning", category="naming", detail="bad variable name"),
        ]
        rework = o._prepare_rework_handoff(original, review_result, retry_count=1)
        assert "Rework Required" in rework.task.next_instructions
        assert "bad variable name" in rework.task.next_instructions
        assert rework.envelope.retry_count == 1
        assert rework.envelope.parent_handoff_id == review_result.envelope.handoff_id

    def test_rework_includes_lint_failure(self):
        o = Orchestrator()
        original = _make_handoff()
        review_result = _make_result_handoff(GateDecision.L1_REWORK)
        review_result.quality_gates.lint_result = "failed"
        rework = o._prepare_rework_handoff(original, review_result, retry_count=1)
        assert "lint" in rework.task.next_instructions.lower()

    def test_rework_includes_test_failures(self):
        o = Orchestrator()
        original = _make_handoff()
        review_result = _make_result_handoff(GateDecision.L1_REWORK)
        review_result.quality_gates.test_results.unit_failed = 3
        rework = o._prepare_rework_handoff(original, review_result, retry_count=2)
        assert "3 failing unit tests" in rework.task.next_instructions


# ---------------------------------------------------------------------------
# _route_to_next_agent
# ---------------------------------------------------------------------------


class TestRouteToNextAgent:
    def test_route_creates_new_handoff(self):
        o = Orchestrator()
        completed = _make_result_handoff(GateDecision.AUTO_PASS)
        next_hf = o._route_to_next_agent(completed, AgentRole.TESTER)
        assert next_hf.envelope.to_agent == AgentRole.TESTER
        assert next_hf.envelope.from_agent == completed.envelope.to_agent
        assert next_hf.envelope.parent_handoff_id == completed.envelope.handoff_id
        assert "backend" in next_hf.task.next_instructions.lower() or \
               "Review" in next_hf.task.next_instructions


# ---------------------------------------------------------------------------
# _send_notification
# ---------------------------------------------------------------------------


class TestSendNotification:
    @pytest.mark.asyncio
    async def test_no_notifier(self):
        o = Orchestrator(notifier=None)
        # should not raise
        await o._send_notification(_make_handoff(), _make_result_handoff(GateDecision.AUTO_PASS), _make_registry())

    @pytest.mark.asyncio
    async def test_notifier_called(self):
        mock_notifier = MagicMock(spec=Notifier)
        mock_notifier.should_notify.return_value = True
        mock_notifier.notify = AsyncMock()

        o = Orchestrator(notifier=mock_notifier)
        await o._send_notification(
            _make_handoff(),
            _make_result_handoff(GateDecision.L2_HUMAN),
            _make_registry(),
        )
        mock_notifier.notify.assert_called_once()
        event = mock_notifier.notify.call_args[0][0]
        assert isinstance(event, GateEvent)
        assert event.gate_decision == GateDecision.L2_HUMAN

    @pytest.mark.asyncio
    async def test_notifier_skipped_when_should_not(self):
        mock_notifier = MagicMock(spec=Notifier)
        mock_notifier.should_notify.return_value = False
        mock_notifier.notify = AsyncMock()

        o = Orchestrator(notifier=mock_notifier)
        await o._send_notification(
            _make_handoff(),
            _make_result_handoff(GateDecision.AUTO_PASS),
            _make_registry(),
        )
        mock_notifier.notify.assert_not_called()

    @pytest.mark.asyncio
    async def test_notifier_exception_logged(self):
        mock_notifier = MagicMock(spec=Notifier)
        mock_notifier.should_notify.return_value = True
        mock_notifier.notify = AsyncMock(side_effect=RuntimeError("send failed"))

        o = Orchestrator(notifier=mock_notifier)
        # should not raise — exception is logged
        await o._send_notification(
            _make_handoff(),
            _make_result_handoff(GateDecision.L2_HUMAN),
            _make_registry(),
        )


# ---------------------------------------------------------------------------
# _handle_human_gate / _handle_halt / _handle_deploy_gate
# ---------------------------------------------------------------------------


class TestGateHandlers:
    @pytest.mark.asyncio
    async def test_handle_human_gate(self):
        o = Orchestrator()
        handoff = _make_result_handoff(GateDecision.L2_HUMAN)
        await o._handle_human_gate(handoff, _make_registry())
        assert handoff.human_gate_package is not None
        assert handoff.human_gate_package.gate_level == GateDecision.L2_HUMAN
        assert "Quality policy" in handoff.human_gate_package.trigger_reason

    @pytest.mark.asyncio
    async def test_handle_human_gate_escalated(self):
        o = Orchestrator()
        handoff = _make_result_handoff(GateDecision.L2_HUMAN)
        await o._handle_human_gate(handoff, _make_registry(), escalated=True)
        assert "rework exhausted" in handoff.human_gate_package.trigger_reason.lower()

    @pytest.mark.asyncio
    async def test_handle_halt(self):
        o = Orchestrator()
        handoff = _make_result_handoff(GateDecision.L3_HALT)
        await o._handle_halt(handoff, _make_registry())
        # L3 doesn't set human_gate_package — just logs

    @pytest.mark.asyncio
    async def test_handle_deploy_gate(self):
        o = Orchestrator()
        handoff = _make_result_handoff(GateDecision.L4_DEPLOY)
        await o._handle_deploy_gate(handoff, _make_registry())
        assert handoff.human_gate_package is not None
        assert handoff.human_gate_package.gate_level == GateDecision.L4_DEPLOY


# ---------------------------------------------------------------------------
# _end_pipeline_span
# ---------------------------------------------------------------------------


class TestEndPipelineSpan:
    def test_no_tracing(self):
        o = Orchestrator()
        o._end_pipeline_span(None, _make_result_handoff(GateDecision.AUTO_PASS))

    def test_with_tracing(self):
        mock_tracing = MagicMock()
        mock_tracing.end_span = MagicMock()
        o = Orchestrator(tracing_middleware=mock_tracing)
        span = MagicMock()
        o._end_pipeline_span(span, _make_result_handoff(GateDecision.L1_REWORK))
        mock_tracing.end_span.assert_called_once()


# ---------------------------------------------------------------------------
# process_handoff (full loop — mocking _execute_pipeline)
# ---------------------------------------------------------------------------


class TestProcessHandoff:
    @pytest.mark.asyncio
    async def test_auto_pass_first_attempt(self):
        o = Orchestrator()
        result = _make_result_handoff(GateDecision.AUTO_PASS)

        with patch.object(o, "_execute_pipeline", new_callable=AsyncMock, return_value=result), \
             patch.object(o, "_handle_auto_pass", new_callable=AsyncMock) as mock_auto:
            out = await o.process_handoff(_make_handoff(), _make_registry())

        assert out.quality_gates.gate_decision == GateDecision.AUTO_PASS
        mock_auto.assert_called_once()

    @pytest.mark.asyncio
    async def test_l1_rework_then_pass(self):
        o = Orchestrator()
        l1_result = _make_result_handoff(GateDecision.L1_REWORK)
        pass_result = _make_result_handoff(GateDecision.AUTO_PASS)

        with patch.object(
            o, "_execute_pipeline",
            new_callable=AsyncMock,
            side_effect=[l1_result, pass_result],
        ), patch.object(o, "_handle_auto_pass", new_callable=AsyncMock):
            out = await o.process_handoff(_make_handoff(), _make_registry())

        assert out.quality_gates.gate_decision == GateDecision.AUTO_PASS

    @pytest.mark.asyncio
    async def test_l1_exhausted_escalates_to_l2(self):
        o = Orchestrator()
        registry = _make_registry()
        max_r = registry.quality_policy.max_retry_before_escalation  # 2
        l1_results = [_make_result_handoff(GateDecision.L1_REWORK) for _ in range(max_r + 1)]

        with patch.object(
            o, "_execute_pipeline",
            new_callable=AsyncMock,
            side_effect=l1_results,
        ), patch.object(o, "_handle_human_gate", new_callable=AsyncMock) as mock_human:
            out = await o.process_handoff(_make_handoff(), registry)

        assert out.quality_gates.gate_decision == GateDecision.L2_HUMAN
        mock_human.assert_called_once()
        # escalated=True
        assert mock_human.call_args.kwargs.get("escalated") is True

    @pytest.mark.asyncio
    async def test_l2_human_stops_loop(self):
        o = Orchestrator()
        result = _make_result_handoff(GateDecision.L2_HUMAN)

        with patch.object(o, "_execute_pipeline", new_callable=AsyncMock, return_value=result), \
             patch.object(o, "_handle_human_gate", new_callable=AsyncMock):
            out = await o.process_handoff(_make_handoff(), _make_registry())

        assert out.quality_gates.gate_decision == GateDecision.L2_HUMAN

    @pytest.mark.asyncio
    async def test_l3_halt_stops_loop(self):
        o = Orchestrator()
        result = _make_result_handoff(GateDecision.L3_HALT)

        with patch.object(o, "_execute_pipeline", new_callable=AsyncMock, return_value=result), \
             patch.object(o, "_handle_halt", new_callable=AsyncMock):
            out = await o.process_handoff(_make_handoff(), _make_registry())

        assert out.quality_gates.gate_decision == GateDecision.L3_HALT

    @pytest.mark.asyncio
    async def test_l4_deploy_stops_loop(self):
        o = Orchestrator()
        result = _make_result_handoff(GateDecision.L4_DEPLOY)

        with patch.object(o, "_execute_pipeline", new_callable=AsyncMock, return_value=result), \
             patch.object(o, "_handle_deploy_gate", new_callable=AsyncMock):
            out = await o.process_handoff(_make_handoff(), _make_registry())

        assert out.quality_gates.gate_decision == GateDecision.L4_DEPLOY

    @pytest.mark.asyncio
    async def test_tracing_starts_and_ends(self):
        mock_tracing = MagicMock()
        mock_tracing.start_pipeline_trace.return_value = MagicMock()
        o = Orchestrator(tracing_middleware=mock_tracing)
        result = _make_result_handoff(GateDecision.AUTO_PASS)

        with patch.object(o, "_execute_pipeline", new_callable=AsyncMock, return_value=result), \
             patch.object(o, "_handle_auto_pass", new_callable=AsyncMock):
            await o.process_handoff(_make_handoff(), _make_registry())

        mock_tracing.start_pipeline_trace.assert_called_once()


# ---------------------------------------------------------------------------
# _execute_pipeline
# ---------------------------------------------------------------------------


class TestExecutePipeline:
    @pytest.mark.asyncio
    async def test_unknown_agent_raises(self):
        o = Orchestrator()
        handoff = _make_handoff()
        handoff.envelope.to_agent = "nonexistent_role"
        with pytest.raises(ValueError, match="Unknown agent role"):
            await o._execute_pipeline(handoff, _make_registry())


# ---------------------------------------------------------------------------
# process_chain
# ---------------------------------------------------------------------------


class TestProcessChain:
    @pytest.mark.asyncio
    async def test_chain_stops_on_non_auto_pass(self):
        o = Orchestrator()
        l2_result = _make_result_handoff(GateDecision.L2_HUMAN)

        with patch.object(o, "process_handoff", new_callable=AsyncMock, return_value=l2_result):
            results = await o.process_chain(_make_handoff(), _make_registry())

        assert len(results) == 1
        assert results[0].quality_gates.gate_decision == GateDecision.L2_HUMAN

    @pytest.mark.asyncio
    async def test_chain_continues_on_auto_pass(self):
        o = Orchestrator()
        pass_result = _make_result_handoff(GateDecision.AUTO_PASS)

        with patch.object(o, "process_handoff", new_callable=AsyncMock, return_value=pass_result):
            results = await o.process_chain(_make_handoff(), _make_registry())

        # backend -> tester, docs = 3 total
        assert len(results) == 3
