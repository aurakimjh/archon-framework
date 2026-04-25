"""커스텀 예외 계층 테스트."""

from __future__ import annotations

import pytest

from src.errors import (
    AgentError,
    AgentParsingError,
    AgentTimeoutError,
    ArchonError,
    BenchmarkError,
    BenchmarkTimeoutError,
    CloudBudgetExceededError,
    ClusterError,
    DashboardError,
    EvolutionError,
    ForcePushError,
    GateEvaluationError,
    GitCommandError,
    GitError,
    GuardrailError,
    HybridSchedulingError,
    InputValidationError,
    KubeRayDeployError,
    KubeRayError,
    MemoryError,
    ObservabilityError,
    OutputValidationError,
    PathGuardError,
    PipelineError,
    ProjectNotFoundError,
    ProtectedPathError,
    QAError,
    RegistryError,
    RuntimeSetupError,
    TokenBudgetExceededError,
    TracingBackendError,
    VLLMConnectionError,
    VectorStoreError,
)


# ---------------------------------------------------------------------------
# Hierarchy
# ---------------------------------------------------------------------------


class TestExceptionHierarchy:
    def test_all_inherit_from_archon_error(self):
        exceptions = [
            GitError, GitCommandError, ProtectedPathError, ForcePushError,
            AgentError, AgentTimeoutError, AgentParsingError,
            RuntimeSetupError, VLLMConnectionError, ClusterError,
            PipelineError, QAError, GateEvaluationError,
            RegistryError, ProjectNotFoundError,
            MemoryError, VectorStoreError,
            GuardrailError, InputValidationError, OutputValidationError,
            TokenBudgetExceededError, PathGuardError,
            ObservabilityError, TracingBackendError,
            BenchmarkError, BenchmarkTimeoutError,
            EvolutionError, DashboardError,
            KubeRayError, KubeRayDeployError,
            HybridSchedulingError, CloudBudgetExceededError,
        ]
        for exc_cls in exceptions:
            assert issubclass(exc_cls, ArchonError), f"{exc_cls.__name__} should inherit ArchonError"

    def test_git_subtypes(self):
        assert issubclass(GitCommandError, GitError)
        assert issubclass(ProtectedPathError, GitError)
        assert issubclass(ForcePushError, GitError)

    def test_agent_subtypes(self):
        assert issubclass(AgentTimeoutError, AgentError)
        assert issubclass(AgentParsingError, AgentError)

    def test_runtime_subtypes(self):
        assert issubclass(VLLMConnectionError, RuntimeSetupError)
        assert issubclass(ClusterError, RuntimeSetupError)
        assert issubclass(KubeRayError, RuntimeSetupError)
        assert issubclass(HybridSchedulingError, RuntimeSetupError)

    def test_pipeline_subtypes(self):
        assert issubclass(QAError, PipelineError)
        assert issubclass(GateEvaluationError, PipelineError)

    def test_guardrail_subtypes(self):
        assert issubclass(InputValidationError, GuardrailError)
        assert issubclass(OutputValidationError, GuardrailError)
        assert issubclass(TokenBudgetExceededError, GuardrailError)
        assert issubclass(PathGuardError, GuardrailError)


# ---------------------------------------------------------------------------
# Parameterized exceptions
# ---------------------------------------------------------------------------


class TestGitCommandError:
    def test_attributes(self):
        err = GitCommandError(command="git push", stderr="rejected")
        assert err.command == "git push"
        assert err.stderr == "rejected"
        assert "git push" in str(err)
        assert "rejected" in str(err)

    def test_catchable_as_git_error(self):
        with pytest.raises(GitError):
            raise GitCommandError("git commit", "nothing to commit")


class TestVLLMConnectionError:
    def test_attributes(self):
        err = VLLMConnectionError(endpoint="localhost:8000", detail="timeout")
        assert err.endpoint == "localhost:8000"
        assert err.detail == "timeout"
        assert "localhost:8000" in str(err)

    def test_empty_detail(self):
        err = VLLMConnectionError(endpoint="host:9000")
        assert err.detail == ""


class TestInputValidationError:
    def test_attributes(self):
        class FakeViolation:
            pattern_name = "ssn_pattern"
        violations = [FakeViolation()]
        err = InputValidationError(violations=violations, action="block")
        assert err.violations == violations
        assert err.action == "block"
        assert "ssn_pattern" in str(err)


class TestOutputValidationError:
    def test_attributes(self):
        class FakeViolation:
            pattern_name = "eval_usage"
        err = OutputValidationError(violations=[FakeViolation()], action="warn")
        assert err.action == "warn"
        assert "eval_usage" in str(err)


class TestTokenBudgetExceededError:
    def test_attributes(self):
        err = TokenBudgetExceededError(project_id="proj-1", used=15000, limit=10000)
        assert err.project_id == "proj-1"
        assert err.used == 15000
        assert err.limit == 10000
        assert "15000" in str(err)
        assert "10000" in str(err)


class TestPathGuardError:
    def test_attributes(self):
        err = PathGuardError(paths=[".env", "secrets/"])
        assert err.paths == [".env", "secrets/"]
        assert ".env" in str(err)


class TestCloudBudgetExceededError:
    def test_attributes(self):
        err = CloudBudgetExceededError(daily_spent=25.50, daily_limit=20.00)
        assert err.daily_spent == 25.50
        assert err.daily_limit == 20.00
        assert "$25.50" in str(err)
        assert "$20.00" in str(err)
