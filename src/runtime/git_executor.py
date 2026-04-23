"""GitExecutor — AUTO_PASS 시 자동 브랜치 생성, 커밋, 푸시. protected_paths 검증 포함."""

from __future__ import annotations

import asyncio
import logging

from src.errors import GitCommandError, ProtectedPathError
from src.orchestrator.handoff import HandoffArtifact
from src.registry.models import GitConfig

logger = logging.getLogger(__name__)


# 하위 호환 별칭
ProtectedPathViolation = ProtectedPathError


class GitExecutor:
    """Git 자동화 — 브랜치 생성, 커밋, 푸시를 수행한다.

    protected_paths에 포함된 파일이 변경 목록에 있으면 즉시 차단한다.
    """

    def __init__(self, git_config: GitConfig) -> None:
        self.config = git_config
        self._repo_root: str | None = None

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

    async def check_force_push_attempt(self, args: list[str]) -> bool:
        """force push 시도를 감지한다. L3_HALT 트리거용."""
        force_flags = {"--force", "-f", "--force-with-lease"}
        return bool(force_flags & set(args))
