"""GitExecutor 확장 테스트 — auto_commit 흐름, _run_git, save_snapshot/rollback."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.errors import GitCommandError, ProtectedPathError
from src.orchestrator.handoff import (
    Artifacts,
    ChangedFile,
    Envelope,
    HandoffArtifact,
    ProjectContext,
    Task,
)
from src.registry.models import GitConfig
from src.runtime.git_executor import GitExecutor, Snapshot


def _make_config(**overrides) -> GitConfig:
    defaults = dict(
        repo_url="https://github.com/test/repo.git",
        main_branch="develop",
        agent_branch_prefix="agent/",
        auto_commit_message_template="feat({agent}): {summary} [task:{task_id}]",
        protected_paths=[".env", "secrets/"],
    )
    defaults.update(overrides)
    return GitConfig(**defaults)


def _make_handoff(files: list[dict] | None = None) -> HandoffArtifact:
    return HandoffArtifact(
        envelope=Envelope(handoff_id="hf-1", from_agent="backend", to_agent="reviewer"),
        project_context=ProjectContext(
            project_id="proj-1", project_name="Test",
            git_repo="https://github.com/test/repo.git",
            git_branch="develop", base_commit_sha="abc123",
        ),
        task=Task(task_id="task-42", completed_summary="Added payment API"),
        artifacts=Artifacts(
            changed_files=[ChangedFile(**f) for f in (files or [])],
        ),
    )


# ---------------------------------------------------------------------------
# _run_git
# ---------------------------------------------------------------------------


class TestRunGit:
    @pytest.mark.asyncio
    async def test_success(self):
        executor = GitExecutor(_make_config())
        executor._repo_root = "/tmp"
        # echo should work
        result = await executor._run_git("version")
        assert "git version" in result

    @pytest.mark.asyncio
    async def test_failure_raises_git_command_error(self, tmp_path):
        """유효한 디렉토리이지만 git repo가 아닌 곳에서 git log → GitCommandError."""
        executor = GitExecutor(_make_config())
        executor._repo_root = str(tmp_path)
        with pytest.raises(GitCommandError):
            await executor._run_git("log", "--oneline")


# ---------------------------------------------------------------------------
# auto_commit
# ---------------------------------------------------------------------------


class TestAutoCommit:
    @pytest.mark.asyncio
    async def test_protected_path_blocks(self):
        executor = GitExecutor(_make_config())
        handoff = _make_handoff([
            {"path": ".env", "change_type": "modified", "reason": "added key"},
        ])
        with pytest.raises(ProtectedPathError):
            await executor.auto_commit(handoff, "feat({agent}): {summary} [task:{task_id}]")

    @pytest.mark.asyncio
    async def test_no_changed_files_returns_none(self):
        executor = GitExecutor(_make_config())
        handoff = _make_handoff([])  # no files

        with patch.object(executor, "_run_git", new_callable=AsyncMock) as mock_git:
            result = await executor.auto_commit(
                handoff,
                "feat({agent}): {summary} [task:{task_id}]",
                repo_root="/tmp",
            )

        assert result is None

    @pytest.mark.asyncio
    async def test_full_commit_flow(self):
        executor = GitExecutor(_make_config())
        handoff = _make_handoff([
            {"path": "src/api/pay.py", "change_type": "added"},
            {"path": "src/old.py", "change_type": "deleted"},
        ])

        call_log = []

        async def mock_run_git(*args, cwd=None):
            call_log.append(args)
            if args == ("rev-parse", "HEAD"):
                return "abc123def456"
            return ""

        with patch.object(executor, "_run_git", side_effect=mock_run_git):
            sha = await executor.auto_commit(
                handoff,
                "feat({agent}): {summary} [task:{task_id}]",
                repo_root="/tmp",
            )

        assert sha == "abc123def456"
        # Verify flow: checkout -b, add, rm, commit, rev-parse, push
        commands = [c[0] for c in call_log]
        assert "checkout" in commands
        assert "add" in commands
        assert "rm" in commands
        assert "commit" in commands
        assert "push" in commands

    @pytest.mark.asyncio
    async def test_existing_branch_checkout(self):
        executor = GitExecutor(_make_config())
        handoff = _make_handoff([
            {"path": "src/main.py", "change_type": "modified"},
        ])

        call_count = 0

        async def mock_run_git(*args, cwd=None):
            nonlocal call_count
            call_count += 1
            if args[:2] == ("checkout", "-b"):
                raise GitCommandError("git checkout -b", "already exists")
            if args == ("rev-parse", "HEAD"):
                return "sha123"
            return ""

        with patch.object(executor, "_run_git", side_effect=mock_run_git):
            sha = await executor.auto_commit(handoff, "{agent}: {summary} [{task_id}]", "/tmp")

        assert sha == "sha123"

    @pytest.mark.asyncio
    async def test_push_failure_not_fatal(self):
        executor = GitExecutor(_make_config())
        handoff = _make_handoff([{"path": "src/main.py", "change_type": "added"}])

        async def mock_run_git(*args, cwd=None):
            if args[0] == "push":
                raise GitCommandError("git push", "no remote")
            if args == ("rev-parse", "HEAD"):
                return "sha456"
            return ""

        with patch.object(executor, "_run_git", side_effect=mock_run_git):
            sha = await executor.auto_commit(handoff, "{agent}: {summary} [{task_id}]", "/tmp")

        assert sha == "sha456"  # commit succeeded despite push failure


# ---------------------------------------------------------------------------
# save_snapshot / rollback
# ---------------------------------------------------------------------------


class TestSnapshotFlow:
    @pytest.mark.asyncio
    async def test_save_snapshot(self):
        executor = GitExecutor(_make_config())
        stash_calls = []

        async def mock_run_git(*args, cwd=None):
            stash_calls.append(args)
            if args[:2] == ("stash", "list"):
                return "stash@{0}: On branch: archon-snap-xxx"
            return ""

        with patch.object(executor, "_run_git", side_effect=mock_run_git):
            snap = await executor.save_snapshot("before task", repo_root="/tmp")

        assert snap.snapshot_id.startswith("archon-snap-")
        assert snap.description == "before task"
        assert snap.stash_ref == "stash@{0}"
        assert len(executor.list_snapshots()) == 1

    @pytest.mark.asyncio
    async def test_save_snapshot_no_changes(self):
        executor = GitExecutor(_make_config())

        async def mock_run_git(*args, cwd=None):
            if args[:2] == ("stash", "push"):
                raise GitCommandError("git stash push", "No local changes")
            return ""

        with patch.object(executor, "_run_git", side_effect=mock_run_git):
            snap = await executor.save_snapshot(repo_root="/tmp")

        assert snap.stash_ref == ""
        assert len(executor.list_snapshots()) == 1

    @pytest.mark.asyncio
    async def test_rollback_latest(self):
        executor = GitExecutor(_make_config())
        snap = Snapshot(snapshot_id="snap-1", stash_ref="stash@{0}")
        executor._snapshots.append(snap)

        async def mock_run_git(*args, cwd=None):
            return ""

        with patch.object(executor, "_run_git", side_effect=mock_run_git):
            result = await executor.rollback_to_snapshot()

        assert result is not None
        assert result.snapshot_id == "snap-1"

    @pytest.mark.asyncio
    async def test_rollback_by_id(self):
        executor = GitExecutor(_make_config())
        snap1 = Snapshot(snapshot_id="snap-old", stash_ref="stash@{1}")
        snap2 = Snapshot(snapshot_id="snap-new", stash_ref="stash@{0}")
        executor._snapshots.append(snap1)
        executor._snapshots.append(snap2)

        async def mock_run_git(*args, cwd=None):
            return ""

        with patch.object(executor, "_run_git", side_effect=mock_run_git):
            result = await executor.rollback_to_snapshot("snap-old")

        assert result.snapshot_id == "snap-old"

    @pytest.mark.asyncio
    async def test_rollback_stash_apply_failure(self):
        executor = GitExecutor(_make_config())
        snap = Snapshot(snapshot_id="snap-fail", stash_ref="stash@{0}")
        executor._snapshots.append(snap)

        async def mock_run_git(*args, cwd=None):
            if args[:2] == ("stash", "apply"):
                raise GitCommandError("git stash apply", "conflict")
            return ""

        with patch.object(executor, "_run_git", side_effect=mock_run_git):
            with pytest.raises(GitCommandError):
                await executor.rollback_to_snapshot("snap-fail")


# ---------------------------------------------------------------------------
# check_force_push_attempt
# ---------------------------------------------------------------------------


class TestForcePushDetection:
    @pytest.mark.asyncio
    async def test_force_with_lease(self):
        executor = GitExecutor(_make_config())
        assert await executor.check_force_push_attempt(["push", "--force-with-lease"]) is True

    @pytest.mark.asyncio
    async def test_no_force(self):
        executor = GitExecutor(_make_config())
        assert await executor.check_force_push_attempt(["push", "origin", "main"]) is False
