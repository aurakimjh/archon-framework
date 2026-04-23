"""에이전트 풀 테스트 — 6개 에이전트 인스턴스화, 역할, 시스템 프롬프트 빌드."""

from src.agents import (
    BackendAgent,
    DevOpsAgent,
    DocsAgent,
    FrontendAgent,
    ReviewerAgent,
    TesterAgent,
)
from src.orchestrator.handoff import (
    Artifacts,
    Envelope,
    HandoffArtifact,
    ProjectContext,
    QualityGates,
    Task,
    TechStack,
)
from src.registry.models import (
    AgentRole,
    GitConfig,
    ProjectMeta,
    ProjectRegistry,
    QualityPolicy,
)


def _make_handoff() -> HandoffArtifact:
    return HandoffArtifact(
        envelope=Envelope(
            handoff_id="hf_test",
            from_agent="orchestrator",
            to_agent="backend",
        ),
        project_context=ProjectContext(
            project_id="proj_test",
            project_name="Test App",
            git_repo="/tmp/test-repo",
            git_branch="agent/backend/t001",
            base_commit_sha="abc123",
            tech_stack=TechStack(
                language="Python",
                framework="FastAPI",
                database="PostgreSQL",
                runtime="Python 3.13",
            ),
        ),
        task=Task(
            task_id="t001",
            completed_summary="",
            next_instructions="Implement user login endpoint.",
        ),
        artifacts=Artifacts(),
        quality_gates=QualityGates(),
    )


def _make_registry() -> ProjectRegistry:
    return ProjectRegistry(
        project_meta=ProjectMeta(
            project_id="proj_test",
            project_name="Test App",
        ),
        git_config=GitConfig(
            repo_url="/tmp/test-repo",
        ),
        quality_policy=QualityPolicy(),
    )


class TestAgentRoles:
    """각 에이전트의 역할이 올바르게 설정되는지 검증."""

    def test_backend_role(self) -> None:
        assert BackendAgent().role == AgentRole.BACKEND

    def test_frontend_role(self) -> None:
        assert FrontendAgent().role == AgentRole.FRONTEND

    def test_tester_role(self) -> None:
        assert TesterAgent().role == AgentRole.TESTER

    def test_devops_role(self) -> None:
        assert DevOpsAgent().role == AgentRole.DEVOPS

    def test_docs_role(self) -> None:
        assert DocsAgent().role == AgentRole.DOCS

    def test_reviewer_role(self) -> None:
        assert ReviewerAgent().role == AgentRole.REVIEWER


class TestSystemPrompts:
    """각 에이전트가 유효한 시스템 프롬프트를 빌드하는지 검증."""

    def test_backend_prompt_contains_tech_stack(self) -> None:
        agent = BackendAgent()
        prompt = agent._build_system_prompt(_make_handoff(), _make_registry())
        assert "FastAPI" in prompt
        assert "PostgreSQL" in prompt
        assert "senior backend engineer" in prompt

    def test_frontend_prompt_contains_accessibility(self) -> None:
        agent = FrontendAgent()
        prompt = agent._build_system_prompt(_make_handoff(), _make_registry())
        assert "WCAG" in prompt
        assert "responsive" in prompt
        assert "senior frontend engineer" in prompt

    def test_tester_prompt_contains_coverage(self) -> None:
        agent = TesterAgent()
        prompt = agent._build_system_prompt(_make_handoff(), _make_registry())
        assert "coverage" in prompt.lower()
        assert "edge case" in prompt.lower()
        assert "senior QA/test engineer" in prompt

    def test_devops_prompt_contains_docker(self) -> None:
        agent = DevOpsAgent()
        prompt = agent._build_system_prompt(_make_handoff(), _make_registry())
        assert "Docker" in prompt
        assert "CI/CD" in prompt
        assert "senior DevOps engineer" in prompt

    def test_docs_prompt_contains_api_docs(self) -> None:
        agent = DocsAgent()
        prompt = agent._build_system_prompt(_make_handoff(), _make_registry())
        assert "documentation" in prompt.lower()
        assert "senior technical writer" in prompt

    def test_reviewer_prompt_contains_scoring(self) -> None:
        agent = ReviewerAgent()
        prompt = agent._build_system_prompt(_make_handoff(), _make_registry())
        assert "review_score" in prompt
        assert "gate_decision" in prompt
        assert "senior code reviewer" in prompt

    def test_all_prompts_include_protected_paths(self) -> None:
        handoff = _make_handoff()
        registry = _make_registry()
        agents = [
            BackendAgent(),
            FrontendAgent(),
            TesterAgent(),
            DevOpsAgent(),
            DocsAgent(),
        ]
        for agent in agents:
            prompt = agent._build_system_prompt(handoff, registry)
            assert "protected paths" in prompt.lower() or ".env" in prompt, (
                f"{agent.role} prompt missing protected paths"
            )


class TestAgentPool:
    """오케스트레이터의 AGENT_POOL에 모든 역할이 등록되어 있는지 검증."""

    def test_all_roles_registered(self) -> None:
        from src.orchestrator.orchestrator import AGENT_POOL

        expected_roles = {
            AgentRole.BACKEND,
            AgentRole.FRONTEND,
            AgentRole.TESTER,
            AgentRole.DEVOPS,
            AgentRole.DOCS,
            AgentRole.REVIEWER,
        }
        assert set(AGENT_POOL.keys()) == expected_roles

    def test_pool_agents_are_correct_types(self) -> None:
        from src.orchestrator.orchestrator import AGENT_POOL

        assert isinstance(AGENT_POOL[AgentRole.BACKEND], BackendAgent)
        assert isinstance(AGENT_POOL[AgentRole.FRONTEND], FrontendAgent)
        assert isinstance(AGENT_POOL[AgentRole.TESTER], TesterAgent)
        assert isinstance(AGENT_POOL[AgentRole.DEVOPS], DevOpsAgent)
        assert isinstance(AGENT_POOL[AgentRole.DOCS], DocsAgent)
        assert isinstance(AGENT_POOL[AgentRole.REVIEWER], ReviewerAgent)
