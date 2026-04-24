"""GitExecutor — AUTO_PASS 시 자동 브랜치 생성, 커밋, 푸시. protected_paths 검증 포함.

트랜잭션 스냅샷: 에이전트 실행 전 save_snapshot()으로 워킹 트리를 저장하고,
할루시에이션 감지 시 rollback_to_snapshot()으로 즉시 복원한다.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime

from src.errors import GitCommandError, ProtectedPathError
from src.log import get_logger
from src.orchestrator.handoff import HandoffArtifact
from src.registry.models import GitConfig

logger = logging.getLogger(__name__)
_slog = get_logger(__name__)

MAX_SNAPSHOTS = 20


# 하위 호환 별칭
ProtectedPathViolation = ProtectedPathError


@dataclass
class Snapshot:
    """트랜잭션 스냅샷 — 워킹 트리 상태를 git stash로 보존한다."""

    snapshot_id: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    description: str = ""
    stash_ref: str = ""


class GitExecutor:
    """Git 자동화 — 브랜치 생성, 커밋, 푸시를 수행한다.

    protected_paths에 포함된 파일이 변경 목록에 있으면 즉시 차단한다.
    트랜잭션 스냅샷으로 에이전트 작업 전후 워킹 트리를 보존/복원한다.
    """

    def __init__(self, git_config: GitConfig) -> None:
        self.config = git_config
        self._repo_root: str | None = None
        self._snapshots: deque[Snapshot] = deque(maxlen=MAX_SNAPSHOTS)

    async def _run_git(self, *args: str, cwd: str | None = None) -> str:
        """git 명령 실행."""
        cmd = ["git", *args]
        logger.debug("git: %s", " ".join(cmd))
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd or self._repo_root,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            error_msg = stderr.decode(errors="replace").strip()
            logger.error("git command failed: %s — %s", " ".join(cmd), error_msg)
            raise GitCommandError(command=" ".join(cmd), stderr=error_msg)
        return stdout.decode(errors="replace").strip()

    def validate_protected_paths(self, handoff: HandoffArtifact) -> None:
        """변경 파일이 protected_paths에 해당하지 않는지 검증한다.

        위반 시 ProtectedPathViolation을 발생시킨다.
        """
        protected = self.config.protected_paths
        for changed_file in handoff.artifacts.changed_files:
            file_path = changed_file.path
            for protected_path in protected:
                if file_path.startswith(protected_path) or file_path == protected_path:
                    raise ProtectedPathError(
                        f"Agent attempted to modify protected path: {file_path} "
                        f"(protected: {protected_path})"
                    )

    def _build_branch_name(self, handoff: HandoffArtifact) -> str:
        """에이전트 작업 브랜치명 생성. 형식: agent/{role}/{task_id}"""
        return (
            f"{self.config.agent_branch_prefix}"
            f"{handoff.envelope.from_agent}/"
            f"{handoff.task.task_id}"
        )

    def _build_commit_message(
        self,
        handoff: HandoffArtifact,
        message_template: str,
    ) -> str:
        """커밋 메시지 생성. 템플릿의 {agent}, {summary}, {task_id} 치환."""
        return message_template.format(
            agent=handoff.envelope.from_agent,
            summary=handoff.task.completed_summary[:80],
            task_id=handoff.task.task_id,
        )

    async def auto_commit(
        self,
        handoff: HandoffArtifact,
        message_template: str,
        repo_root: str | None = None,
    ) -> str | None:
        """AUTO_PASS 시 자동 커밋을 수행한다.

        1. protected_paths 검증
        2. 브랜치 생성/체크아웃
        3. 변경 파일 스테이징
        4. 커밋
        5. 푸시 (remote 설정 시)

        Returns:
            커밋 SHA 또는 None (변경사항 없을 때)
        """
        self._repo_root = repo_root

        # 1. protected_paths 검증
        self.validate_protected_paths(handoff)
        logger.info("Protected paths validation passed")

        # 2. 브랜치 생성/체크아웃
        branch_name = self._build_branch_name(handoff)
        try:
            await self._run_git("checkout", "-b", branch_name)
            logger.info("Created and checked out branch: %s", branch_name)
        except GitCommandError:
            # 브랜치가 이미 존재하면 체크아웃만
            await self._run_git("checkout", branch_name)
            logger.info("Checked out existing branch: %s", branch_name)

        # 3. 변경 파일 스테이징
        if not handoff.artifacts.changed_files:
            logger.info("No changed files to commit")
            return None

        for changed_file in handoff.artifacts.changed_files:
            if changed_file.change_type == "deleted":
                await self._run_git("rm", changed_file.path)
            else:
                await self._run_git("add", changed_file.path)

        # 4. 커밋
        commit_message = self._build_commit_message(handoff, message_template)
        await self._run_git("commit", "-m", commit_message)
        commit_sha = await self._run_git("rev-parse", "HEAD")
        logger.info("Committed: %s (%s)", commit_message, commit_sha[:8])

        # 5. 푸시 (remote가 설정되어 있을 때만)
        try:
            await self._run_git("push", "-u", "origin", branch_name)
            logger.info("Pushed branch: %s", branch_name)
        except GitCommandError as e:
            logger.warning("Push skipped (no remote?): %s", e)

        return commit_sha

    # ── 트랜잭션 스냅샷 ──────────────────────────────────────

    async def save_snapshot(
        self,
        description: str = "",
        repo_root: str | None = None,
    ) -> Snapshot:
        """워킹 트리 스냅샷을 저장한다 (git stash 기반).

        에이전트 실행 전 호출하여 현재 상태를 보존한다.
        변경사항이 없어도 빈 스냅샷을 기록하여 이력을 유지한다.
        """
        if repo_root:
            self._repo_root = repo_root

        ts = datetime.now(UTC)
        snapshot_id = f"archon-snap-{ts.strftime('%Y%m%d%H%M%S%f')}"

        # untracked 포함 전체 stash
        try:
            await self._run_git(
                "stash", "push",
                "--include-untracked",
                "-m", snapshot_id,
            )
            stash_ref = await self._run_git(
                "stash", "list", "--grep", snapshot_id,
            )
            # stash_ref 형식: "stash@{0}: On branch: archon-snap-..."
            ref = stash_ref.split(":")[0] if stash_ref else ""
            _slog.info(
                "snapshot_saved",
                snapshot_id=snapshot_id,
                stash_ref=ref,
            )
        except GitCommandError:
            # 변경사항 없으면 stash 실패 — 빈 스냅샷 기록
            ref = ""
            _slog.info(
                "snapshot_saved_empty",
                snapshot_id=snapshot_id,
            )

        snap = Snapshot(
            snapshot_id=snapshot_id,
            timestamp=ts,
            description=description,
            stash_ref=ref,
        )
        self._snapshots.append(snap)
        return snap

    async def rollback_to_snapshot(
        self,
        snapshot_id: str | None = None,
    ) -> Snapshot | None:
        """스냅샷으로 워킹 트리를 복원한다.

        snapshot_id 미지정 시 가장 최근 스냅샷으로 복원한다.
        할루시에이션 감지 시 즉시 호출하여 안전한 상태로 되돌린다.

        Returns:
            복원된 Snapshot 또는 None (스냅샷 없을 때)
        """
        if not self._snapshots:
            _slog.warning("rollback_no_snapshots")
            return None

        if snapshot_id:
            target = next(
                (s for s in self._snapshots if s.snapshot_id == snapshot_id),
                None,
            )
            if not target:
                _slog.warning(
                    "rollback_snapshot_not_found",
                    snapshot_id=snapshot_id,
                )
                return None
        else:
            target = self._snapshots[-1]

        if not target.stash_ref:
            _slog.info(
                "rollback_empty_snapshot",
                snapshot_id=target.snapshot_id,
            )
            return target

        # 현재 변경사항 버리고 stash 적용
        try:
            await self._run_git("checkout", ".")
            await self._run_git("clean", "-fd")
        except GitCommandError:
            pass  # 이미 클린 상태

        try:
            stash_index = target.stash_ref  # e.g. "stash@{0}"
            await self._run_git("stash", "apply", stash_index)
            _slog.info(
                "rollback_applied",
                snapshot_id=target.snapshot_id,
                stash_ref=stash_index,
            )
        except GitCommandError as e:
            _slog.error(
                "rollback_failed",
                snapshot_id=target.snapshot_id,
                error=str(e),
            )
            raise

        return target

    def list_snapshots(self) -> list[Snapshot]:
        """저장된 스냅샷 목록을 반환한다 (최신순)."""
        return list(reversed(self._snapshots))

    def clear_snapshots(self) -> int:
        """모든 스냅샷 이력을 제거한다. 삭제 건수를 반환한다."""
        count = len(self._snapshots)
        self._snapshots.clear()
        _slog.info("snapshots_cleared", count=count)
        return count

    # ── force push 감지 ──────────────────────────────────────

    async def check_force_push_attempt(self, args: list[str]) -> bool:
        """force push 시도를 감지한다. L3_HALT 트리거용."""
        force_flags = {"--force", "-f", "--force-with-lease"}
        return bool(force_flags & set(args))
