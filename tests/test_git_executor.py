"""GitExecutor 테스트 — protected_paths, 브랜치명/커밋, 스냅샷/롤백."""

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
from src.runtime.git_executor import (
    MAX_SNAPSHOTS,
    GitExecutor,
    ProtectedPathViolation,
    Snapshot,
)


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


# --- Snapshot 데이터클래스 ---


class TestSnapshot:
    def test_snapshot_creation(self):
        snap = Snapshot(snapshot_id="snap-001", description="before task")
        assert snap.snapshot_id == "snap-001"
        assert snap.description == "before task"
        assert snap.stash_ref == ""
        assert snap.timestamp is not None

    def test_snapshot_with_stash_ref(self):
        snap = Snapshot(snapshot_id="snap-002", stash_ref="stash@{0}")
        assert snap.stash_ref == "stash@{0}"


# --- GitExecutor 스냅샷 관리 ---


class TestGitExecutorSnapshots:
    def test_initial_no_snapshots(self):
        executor = GitExecutor(_make_git_config())
        assert executor.list_snapshots() == []

    def test_clear_snapshots(self):
        executor = GitExecutor(_make_git_config())
        # 수동으로 스냅샷 추가
        executor._snapshots.append(
            Snapshot(snapshot_id="snap-001", description="test")
        )
        assert len(executor.list_snapshots()) == 1
        count = executor.clear_snapshots()
        assert count == 1
        assert executor.list_snapshots() == []

    def test_max_snapshots_limit(self):
        executor = GitExecutor(_make_git_config())
        for i in range(MAX_SNAPSHOTS + 5):
            executor._snapshots.append(
                Snapshot(snapshot_id=f"snap-{i:03d}")
            )
        assert len(executor._snapshots) == MAX_SNAPSHOTS

    def test_list_snapshots_newest_first(self):
        executor = GitExecutor(_make_git_config())
        executor._snapshots.append(Snapshot(snapshot_id="old"))
        executor._snapshots.append(Snapshot(snapshot_id="new"))
        result = executor.list_snapshots()
        assert result[0].snapshot_id == "new"
        assert result[1].snapshot_id == "old"

    @pytest.mark.asyncio
    async def test_rollback_no_snapshots(self):
        executor = GitExecutor(_make_git_config())
        result = await executor.rollback_to_snapshot()
        assert result is None

    @pytest.mark.asyncio
    async def test_rollback_not_found(self):
        executor = GitExecutor(_make_git_config())
        executor._snapshots.append(Snapshot(snapshot_id="snap-001"))
        result = await executor.rollback_to_snapshot("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_rollback_empty_snapshot(self):
        executor = GitExecutor(_make_git_config())
        snap = Snapshot(snapshot_id="empty-snap", stash_ref="")
        executor._snapshots.append(snap)
        result = await executor.rollback_to_snapshot("empty-snap")
        assert result is not None
        assert result.snapshot_id == "empty-snap"
