"""MemoryPolicy — 크로스 프로젝트 메모리 접근 정책."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class MemorySharingMode(StrEnum):
    ISOLATED = "isolated"         # 완전 격리: 이 프로젝트 메모리만 접근
    SHARED_READ = "shared_read"   # 다른 프로젝트 읽기 허용, 쓰기는 자기 프로젝트만
    FULL_SHARED = "full_shared"   # 완전 공유: 모든 프로젝트 읽기·쓰기


class MemoryPolicy(BaseModel):
    """프로젝트별 메모리 공유 정책."""

    sharing_mode: MemorySharingMode = MemorySharingMode.ISOLATED

    # 민감 프로젝트 태그: 이 태그가 붙은 프로젝트는 FULL_SHARED여도 자동 격리
    sensitive_tags: list[str] = Field(
        default_factory=lambda: ["confidential", "hipaa", "pci", "secret"]
    )

    # 읽기 허용 프로젝트 ID 화이트리스트 (SHARED_READ/FULL_SHARED에서만 유효)
    # 빈 리스트 = 전체 허용
    allowed_read_projects: list[str] = Field(default_factory=list)

    # 쓰기 허용 프로젝트 ID 화이트리스트 (FULL_SHARED에서만 유효)
    # 빈 리스트 = 전체 허용
    allowed_write_projects: list[str] = Field(default_factory=list)

    # L1 Redis TTL override (초, 0이면 MemoryConfig.redis_ttl 사용)
    redis_ttl_override: int = 0

    # L2 ChromaDB 검색 결과 TTL (초, 0이면 만료 없음)
    vector_result_ttl: int = 0

    # 크로스 프로젝트 L2 검색 시 유사도 임계값 (격리 모드보다 높게 설정 권장)
    cross_project_similarity_threshold: float = 0.90

    # L3 Mem0 크로스 프로젝트 학습 허용 여부
    allow_cross_project_learning: bool = False


@dataclass
class AccessDecision:
    """메모리 접근 허용/거부 결정."""

    allowed: bool
    reason: str
    source_project: str
    target_project: str
    operation: str   # "read" | "write"


class MemoryAccessController:
    """프로젝트 메모리 접근 시 정책을 체크한다.

    MemoryStore.inject_memory_context() 호출 전후에 삽입하거나,
    크로스 프로젝트 검색 직전에 호출한다.
    """

    def __init__(
        self,
        project_id: str,
        policy: MemoryPolicy,
        project_tags: list[str] | None = None,
    ) -> None:
        self._project_id = project_id
        self._policy = policy
        self._tags = project_tags or []

    def check_read(self, target_project_id: str) -> AccessDecision:
        """target_project_id의 메모리를 읽을 수 있는지 확인한다."""
        return self._check(target_project_id, "read")

    def check_write(self, target_project_id: str) -> AccessDecision:
        """target_project_id의 메모리에 쓸 수 있는지 확인한다."""
        return self._check(target_project_id, "write")

    def filter_projects(
        self, candidate_projects: list[str], operation: str = "read"
    ) -> list[str]:
        """접근 가능한 프로젝트 ID만 필터링해서 반환한다."""
        return [
            p for p in candidate_projects
            if self._check(p, operation).allowed
        ]

    def is_self_sensitive(self) -> bool:
        """현재 프로젝트가 민감 태그를 가지면 True."""
        sensitive = set(self._policy.sensitive_tags)
        return bool(sensitive & set(self._tags))

    def _check(self, target_project_id: str, operation: str) -> AccessDecision:
        policy = self._policy
        source = self._project_id

        # 자기 자신은 항상 허용
        if target_project_id == source:
            return AccessDecision(
                allowed=True,
                reason="same project",
                source_project=source,
                target_project=target_project_id,
                operation=operation,
            )

        # 민감 프로젝트는 ISOLATED 강제
        if self.is_self_sensitive():
            return AccessDecision(
                allowed=False,
                reason=f"source project [{source}] has sensitive tags {self._tags}",
                source_project=source,
                target_project=target_project_id,
                operation=operation,
            )

        mode = policy.sharing_mode

        if mode == MemorySharingMode.ISOLATED:
            return AccessDecision(
                allowed=False,
                reason="sharing_mode=ISOLATED",
                source_project=source,
                target_project=target_project_id,
                operation=operation,
            )

        if mode == MemorySharingMode.SHARED_READ:
            if operation == "write":
                return AccessDecision(
                    allowed=False,
                    reason="sharing_mode=SHARED_READ — write to other project denied",
                    source_project=source,
                    target_project=target_project_id,
                    operation=operation,
                )
            # 읽기: 화이트리스트 체크
            allowed = self._in_whitelist(target_project_id, policy.allowed_read_projects)
            return AccessDecision(
                allowed=allowed,
                reason=(
                    "whitelist check" if allowed
                    else f"[{target_project_id}] not in allowed_read_projects"
                ),
                source_project=source,
                target_project=target_project_id,
                operation=operation,
            )

        if mode == MemorySharingMode.FULL_SHARED:
            whitelist = (
                policy.allowed_read_projects if operation == "read"
                else policy.allowed_write_projects
            )
            allowed = self._in_whitelist(target_project_id, whitelist)
            return AccessDecision(
                allowed=allowed,
                reason=(
                    "whitelist check" if allowed
                    else f"[{target_project_id}] not in allowed_{operation}_projects"
                ),
                source_project=source,
                target_project=target_project_id,
                operation=operation,
            )

        return AccessDecision(
            allowed=False,
            reason=f"unknown sharing_mode={mode}",
            source_project=source,
            target_project=target_project_id,
            operation=operation,
        )

    @staticmethod
    def _in_whitelist(project_id: str, whitelist: list[str]) -> bool:
        """화이트리스트가 비어있으면 모두 허용, 아니면 목록 체크."""
        return not whitelist or project_id in whitelist
