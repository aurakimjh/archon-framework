"""Archon 프레임워크 커스텀 예외 계층 구조.

모든 예외는 ArchonError를 상속하며, 도메인별로 세분화한다.
"""

from __future__ import annotations


class ArchonError(Exception):
    """Archon 프레임워크 최상위 예외."""


# --- Git ---


class GitError(ArchonError):
    """Git 작업 관련 예외."""


class GitCommandError(GitError):
    """Git 명령 실행 실패."""

    def __init__(self, command: str, stderr: str) -> None:
        self.command = command
        self.stderr = stderr
        super().__init__(f"git command failed: {command} — {stderr}")


class ProtectedPathError(GitError):
    """protected_paths에 포함된 파일 수정 시도."""


class ForcePushError(GitError):
    """force push 시도 감지."""


# --- Agent ---


class AgentError(ArchonError):
    """에이전트 실행 관련 예외."""


class AgentTimeoutError(AgentError):
    """에이전트 실행 타임아웃."""


class AgentParsingError(AgentError):
    """에이전트 출력 파싱 실패."""


# --- Runtime ---


class RuntimeSetupError(ArchonError):
    """런타임 초기화/설정 예외."""


class VLLMConnectionError(RuntimeSetupError):
    """vLLM 서버 연결 실패."""

    def __init__(self, endpoint: str, detail: str = "") -> None:
        self.endpoint = endpoint
        self.detail = detail
        super().__init__(f"vLLM connection failed: {endpoint} — {detail}")


class ClusterError(RuntimeSetupError):
    """클러스터 관련 예외."""


# --- Pipeline ---


class PipelineError(ArchonError):
    """파이프라인 실행 예외."""


class QAError(PipelineError):
    """QA 파이프라인 실행 실패."""


class GateEvaluationError(PipelineError):
    """Gate 판정 오류."""


# --- Registry ---


class RegistryError(ArchonError):
    """레지스트리 관련 예외."""


class ProjectNotFoundError(RegistryError):
    """프로젝트를 찾을 수 없음."""


# --- Memory ---


class MemoryError(ArchonError):
    """메모리 시스템 예외."""


class VectorStoreError(MemoryError):
    """벡터 스토어 관련 예외."""
