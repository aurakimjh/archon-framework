"""GitExecutor 테스트 — protected_paths 검증, 브랜치명/커밋 메시지 생성."""

import pytest

from src.orchestrator.handoff import (
    Artifacts,
    ChangedFile,
    Envelope,
    HandoffArtifact,
    ProjectContext,
    Task,
)
from src.registry.models import GitConfig
from src.runtime.git_executor import GitExecutor, ProtectedPathViolation


def _make_git_config(**overrides) -> GitConfig:
    defaults = {
        "repo_url": "https://github.com/test/repo.git",
        "main_branch": "develop",
        "agent_branch_prefix": "agent/",
        "auto_commit_message_template": "feat({agent}): {summary} [task:{task_id}]",
        "protected_paths": [".env", "infrastructure/", "secrets/"],
    }
    defaults.update(overrides)
    return GitConfig(**defaults)


def _make_handoff(changed_files: list[dict] | None = None) -> HandoffArtifact:
    files = changed_files or []
    return HandoffArtifact(
        envelope=Envelope(
            handoff_id="hf_test",
            from_agent="backend",
            to_agent="reviewer",
        ),
        project_context=ProjectContext(
            project_id="proj_test",
            project_name="Test",
            git_repo="https://github.com/test/repo.git",
            git_branch="develop",
            base_commit_sha="abc123",
        ),
        task=Task(
            task_id="task_api_v2",
            completed_summary="Implemented payment API endpoints",
        ),
        artifacts=Artifacts(
            changed_files=[ChangedFile(**f) for f in files],
        ),
    )


def test_protected_path_violation():
    executor = GitExecutor(_make_git_config())
    handoff = _make_handoff([
        {"path": ".env", "change_type": "modified", "reason": "added key"},
    ])
    with pytest.raises(ProtectedPathViolation):
        executor.validate_protected_paths(handoff)


def test_protected_path_subdirectory():
    executor = GitExecutor(_make_git_config())
    handoff = _make_handoff([
        {"path": "infrastructure/k8s/deploy.yaml", "change_type": "added"},
    ])
    with pytest.raises(ProtectedPathViolation):
        executor.validate_protected_paths(handoff)


def test_safe_path_passes():
    executor = GitExecutor(_make_git_config())
    handoff = _make_handoff([
        {"path": "src/api/payments.py", "change_type": "added"},
    ])
    executor.validate_protected_paths(handoff)  # should not raise


def test_branch_name():
    executor = GitExecutor(_make_git_config())
    handoff = _make_handoff()
    assert executor._build_branch_name(handoff) == "agent/backend/task_api_v2"


def test_commit_message():
    executor = GitExecutor(_make_git_config())
    handoff = _make_handoff()
    msg = executor._build_commit_message(
        handoff, "feat({agent}): {summary} [task:{task_id}]"
    )
    assert msg == "feat(backend): Implemented payment API endpoints [task:task_api_v2]"


def test_force_push_detection():
    import asyncio

    executor = GitExecutor(_make_git_config())
    assert asyncio.run(executor.check_force_push_attempt(["push", "--force"])) is True
    assert asyncio.run(executor.check_force_push_attempt(["push", "-f"])) is True
    assert asyncio.run(executor.check_force_push_attempt(["push", "origin", "main"])) is False
