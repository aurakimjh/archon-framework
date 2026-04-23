"""오케스트레이터 멀티 에이전트 라우팅 테스트."""

from __future__ import annotations

import pytest

from src.orchestrator.orchestrator import DEFAULT_TASK_CHAINS, AGENT_POOL, Orchestrator
from src.orchestrator.handoff import (
    Envelope,
    HandoffArtifact,
    ProjectContext,
    Task,
)
from src.registry.models import AgentRole


# --- 헬퍼 ---


def _make_handoff(to_agent: str = "backend", task_id: str = "task_001") -> HandoffArtifact:
    return HandoffArtifact(
        envelope=Envelope(
            handoff_id=f"hf_{task_id}",
            from_agent="orchestrator",
            to_agent=to_agent,
        ),
        project_context=ProjectContext(
            project_id="proj_test",
            project_name="Test Project",
            git_repo="/tmp/test-repo",
            git_branch="develop",
            base_commit_sha="abc123",
        ),
        task=Task(
            task_id=task_id,
            completed_summary="",
            next_instructions="Implement the feature.",
        ),
    )


# --- AGENT_POOL ---


class TestAgentPool:
    def test_all_roles_in_pool(self):
        """6개 에이전트가 풀에 등록되어 있다."""
        expected = {
            AgentRole.BACKEND,
            AgentRole.FRONTEND,
            AgentRole.TESTER,
            AgentRole.DEVOPS,
            AgentRole.DOCS,
            AgentRole.REVIEWER,
        }
        assert set(AGENT_POOL.keys()) == expected

    def test_pool_agents_match_roles(self):
        for role, agent in AGENT_POOL.items():
            assert agent.role == role


# --- DEFAULT_TASK_CHAINS ---


class TestTaskChains:
    def test_backend_chain(self):
        assert DEFAULT_TASK_CHAINS[AgentRole.BACKEND] == [
            AgentRole.TESTER,
            AgentRole.DOCS,
        ]

    def test_frontend_chain(self):
        assert DEFAULT_TASK_CHAINS[AgentRole.FRONTEND] == [
            AgentRole.TESTER,
            AgentRole.DOCS,
        ]

    def test_tester_no_chain(self):
        assert DEFAULT_TASK_CHAINS[AgentRole.TESTER] == []

    def test_devops_chain(self):
        assert DEFAULT_TASK_CHAINS[AgentRole.DEVOPS] == [AgentRole.TESTER]

    def test_docs_no_chain(self):
        assert DEFAULT_TASK_CHAINS[AgentRole.DOCS] == []


# --- Orchestrator 초기화 ---


class TestOrchestratorInit:
    def test_default_chains(self):
        orch = Orchestrator()
        assert orch._task_chains == DEFAULT_TASK_CHAINS

    def test_custom_chains(self):
        custom = {"backend": ["docs"]}
        orch = Orchestrator(task_chains=custom)
        assert orch._task_chains == custom

    def test_get_next_agents(self):
        orch = Orchestrator()
        assert orch.get_next_agents("backend") == ["tester", "docs"]
        assert orch.get_next_agents("tester") == []
        assert orch.get_next_agents("unknown") == []


# --- _route_to_next_agent ---


class TestRouteToNextAgent:
    def test_route_creates_handoff(self):
        orch = Orchestrator()
        completed = _make_handoff(to_agent="backend")
        completed.task.completed_summary = "Backend API implemented"

        next_handoff = orch._route_to_next_agent(completed, "tester")

        assert next_handoff.envelope.to_agent == "tester"
        assert next_handoff.envelope.from_agent == "backend"
        assert next_handoff.envelope.parent_handoff_id == "hf_task_001"
        assert "backend" in next_handoff.task.next_instructions
        assert "Backend API implemented" in next_handoff.task.next_instructions

    def test_route_preserves_project_context(self):
        orch = Orchestrator()
        completed = _make_handoff(to_agent="backend")
        completed.task.completed_summary = "done"

        next_handoff = orch._route_to_next_agent(completed, "docs")
        assert next_handoff.project_context.project_id == "proj_test"
        assert next_handoff.project_context.git_branch == "develop"

    def test_route_preserves_artifacts(self):
        orch = Orchestrator()
        completed = _make_handoff(to_agent="backend")
        completed.task.completed_summary = "done"

        next_handoff = orch._route_to_next_agent(completed, "tester")
        assert next_handoff.artifacts == completed.artifacts

    def test_route_chain_ids_unique(self):
        """체인의 각 단계에서 handoff_id가 고유하다."""
        orch = Orchestrator()
        h1 = _make_handoff(to_agent="backend")
        h1.task.completed_summary = "step1"

        h2 = orch._route_to_next_agent(h1, "tester")
        h3 = orch._route_to_next_agent(h1, "docs")

        assert h2.envelope.handoff_id != h3.envelope.handoff_id
        assert "tester" in h2.envelope.handoff_id
        assert "docs" in h3.envelope.handoff_id
