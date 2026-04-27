"""Complexity Router 테스트 — 복잡도 측정 + 동적 모델 선택."""

from __future__ import annotations

from src.orchestrator.handoff import (
    Artifacts,
    Blocker,
    ChangedFile,
    Decision,
    DependencyChange,
    Envelope,
    HandoffArtifact,
    ProjectContext,
    Task,
)
from src.registry.models import (
    AgentModelConfig,
    AgentRole,
    GitConfig,
    MultiProviderMode,
    ProjectMeta,
    ProjectRegistry,
)
from src.router.complexity import (
    ComplexityLevel,
    ComplexityScore,
    measure_complexity,
    select_model_by_complexity,
)
from src.router.role_router import get_model_for_handoff, get_review_models


# --- 헬퍼 ---


def _make_handoff(
    instructions: str = "Simple task",
    changed_files: int = 0,
    decisions: int = 0,
    blockers: int = 0,
    dep_changes: int = 0,
) -> HandoffArtifact:
    return HandoffArtifact(
        envelope=Envelope(
            handoff_id="hf_cx",
            from_agent="orchestrator",
            to_agent="backend",
        ),
        project_context=ProjectContext(
            project_id="proj_test",
            project_name="Test",
            git_repo="/tmp/test",
            git_branch="develop",
            base_commit_sha="abc123",
        ),
        task=Task(
            task_id="task_cx",
            completed_summary="",
            next_instructions=instructions,
            decisions_made=[
                Decision(decision=f"d{i}", reason=f"r{i}") for i in range(decisions)
            ],
            blockers=[
                Blocker(issue=f"b{i}") for i in range(blockers)
            ],
        ),
        artifacts=Artifacts(
            changed_files=[
                ChangedFile(path=f"file{i}.py", change_type="modified")
                for i in range(changed_files)
            ],
            dependency_changes=[
                DependencyChange(name=f"pkg{i}", version="1.0", action="added")
                for i in range(dep_changes)
            ],
        ),
    )


def _make_registry(
    high_model: str | None = None,
) -> ProjectRegistry:
    return ProjectRegistry(
        project_meta=ProjectMeta(project_id="proj_test", project_name="Test"),
        git_config=GitConfig(repo_url="https://example.com/repo.git"),
        agent_config={
            AgentRole.BACKEND: AgentModelConfig(
                model="qwen-27b",
                high_complexity_model=high_model,
            ),
        },
    )


# --- measure_complexity ---


class TestMeasureComplexity:
    def test_simple_task_is_low(self):
        handoff = _make_handoff(instructions="Add a simple print statement")
        result = measure_complexity(handoff)
        assert result.level == ComplexityLevel.LOW
        assert result.score < 30

    def test_long_instructions_add_score(self):
        handoff = _make_handoff(instructions="x" * 3500)
        result = measure_complexity(handoff)
        assert result.score >= 20
        assert any("long instructions" in f for f in result.factors)

    def test_high_keywords_increase_score(self):
        handoff = _make_handoff(
            instructions="Implement database schema migration with encryption and authentication"
        )
        result = measure_complexity(handoff)
        assert result.level in (ComplexityLevel.MEDIUM, ComplexityLevel.HIGH)
        assert any("high-complexity" in f for f in result.factors)

    def test_medium_keywords(self):
        handoff = _make_handoff(
            instructions="Create api endpoint with validation and error handling"
        )
        result = measure_complexity(handoff)
        assert any("medium-complexity" in f for f in result.factors)

    def test_many_changed_files(self):
        handoff = _make_handoff(changed_files=15)
        result = measure_complexity(handoff)
        assert any("many changed files" in f for f in result.factors)

    def test_dependency_changes(self):
        handoff = _make_handoff(dep_changes=3)
        result = measure_complexity(handoff)
        assert any("dependency" in f for f in result.factors)

    def test_blockers_add_score(self):
        handoff = _make_handoff(blockers=2)
        result = measure_complexity(handoff)
        assert any("blocker" in f for f in result.factors)

    def test_many_decisions(self):
        handoff = _make_handoff(decisions=5)
        result = measure_complexity(handoff)
        assert any("prior decisions" in f for f in result.factors)

    def test_cross_agent_keywords(self):
        handoff = _make_handoff(
            instructions="Coordinate frontend, backend, and devops for deployment"
        )
        result = measure_complexity(handoff)
        assert any("cross-agent" in f for f in result.factors)

    def test_combined_high_complexity(self):
        """여러 요소가 합산되어 HIGH가 된다."""
        handoff = _make_handoff(
            instructions=(
                "Refactor the database schema migration with authentication "
                "and security. Handle backward compatibility and race condition."
            ),
            changed_files=12,
            dep_changes=2,
            blockers=1,
        )
        result = measure_complexity(handoff)
        assert result.level == ComplexityLevel.HIGH
        assert result.score >= 60

    def test_score_capped_at_100(self):
        handoff = _make_handoff(
            instructions=(
                "migration refactor architecture security authentication "
                "encryption database schema breaking change backward compatibility "
                "distributed concurrency race condition performance optimization scalability " * 5
            ),
            changed_files=20,
            dep_changes=5,
            blockers=3,
            decisions=10,
        )
        result = measure_complexity(handoff)
        assert result.score <= 100


# --- select_model_by_complexity ---


class TestSelectModel:
    def test_low_complexity_uses_default(self):
        registry = _make_registry(high_model="claude-opus")
        complexity = ComplexityScore(level=ComplexityLevel.LOW, score=10, factors=[])
        model = select_model_by_complexity("backend", complexity, registry)
        assert model == "qwen-27b"

    def test_high_complexity_uses_high_model(self):
        registry = _make_registry(high_model="claude-opus")
        complexity = ComplexityScore(level=ComplexityLevel.HIGH, score=80, factors=[])
        model = select_model_by_complexity("backend", complexity, registry)
        assert model == "claude-opus"

    def test_high_complexity_no_high_model_fallback(self):
        registry = _make_registry(high_model=None)
        complexity = ComplexityScore(level=ComplexityLevel.HIGH, score=80, factors=[])
        model = select_model_by_complexity("backend", complexity, registry)
        assert model == "qwen-27b"

    def test_unknown_role_fallback(self):
        registry = _make_registry()
        complexity = ComplexityScore(level=ComplexityLevel.HIGH, score=80, factors=[])
        model = select_model_by_complexity("unknown_role", complexity, registry)
        assert model == "unknown_role-agent"


# --- get_model_for_handoff (role_router 통합) ---


class TestGetModelForHandoff:
    def test_simple_task_uses_default(self):
        registry = _make_registry(high_model="claude-opus")
        handoff = _make_handoff(instructions="Simple add function")
        model = get_model_for_handoff("backend", handoff, registry)
        assert model == "qwen-27b"

    def test_complex_task_uses_high_model(self):
        registry = _make_registry(high_model="claude-opus")
        handoff = _make_handoff(
            instructions=(
                "Refactor the database schema migration with authentication "
                "and security. Handle backward compatibility and race condition."
            ),
            changed_files=15,
            dep_changes=3,
            blockers=1,
        )
        model = get_model_for_handoff("backend", handoff, registry)
        assert model == "claude-opus"

    def test_no_high_model_config(self):
        registry = _make_registry(high_model=None)
        handoff = _make_handoff(instructions="Complex migration refactor")
        model = get_model_for_handoff("backend", handoff, registry)
        assert model == "qwen-27b"


class TestGetReviewModels:
    def test_returns_configured_review_models(self):
        registry = ProjectRegistry(
            project_meta=ProjectMeta(project_id="proj_test", project_name="Test"),
            git_config=GitConfig(repo_url="https://example.com/repo.git"),
            agent_config={
                AgentRole.REVIEWER: AgentModelConfig(
                    model="reviewer-primary",
                    multi_provider_mode=MultiProviderMode.CONSENSUS,
                    review_models=["model-a", "model-b"],
                )
            },
        )

        assert get_review_models(registry) == ["model-a", "model-b"]

    def test_returns_empty_list_without_reviewer_config(self):
        assert get_review_models(_make_registry()) == []

    def test_returns_copy_of_review_models(self):
        registry = ProjectRegistry(
            project_meta=ProjectMeta(project_id="proj_test", project_name="Test"),
            git_config=GitConfig(repo_url="https://example.com/repo.git"),
            agent_config={
                AgentRole.REVIEWER: AgentModelConfig(
                    model="reviewer-primary",
                    multi_provider_mode=MultiProviderMode.CONSENSUS,
                    review_models=["model-a"],
                )
            },
        )

        models = get_review_models(registry)
        models.append("mutated")

        assert registry.agent_config[AgentRole.REVIEWER].review_models == ["model-a"]
