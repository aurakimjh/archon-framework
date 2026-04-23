"""Mem0 L3 장기 메모리 — 크로스 프로젝트 패턴 학습."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_SIMILARITY_THRESHOLD = 0.85


class Mem0Store:
    """Mem0 SDK 래핑 — L3 장기 메모리.

    크로스 프로젝트 패턴을 학습하고, 유사 결정/패턴을 검색한다.
    Mem0 Memory 인스턴스를 주입받는다.
    """

    def __init__(self, mem0_client: Any) -> None:
        """
        Args:
            mem0_client: mem0.Memory 인스턴스.
        """
        self._mem0 = mem0_client

    def add_memory(
        self,
        content: str,
        user_id: str = "archon",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """패턴/결정을 장기 메모리에 저장.

        Args:
            content: 기억할 내용 (예: "Python FastAPI 프로젝트에서 Pydantic v2 사용").
            user_id: 사용자/에이전트 식별자. 기본 "archon".
            metadata: 추가 메타데이터 (project_id, agent_role 등).

        Returns:
            Mem0 add 결과.
        """
        result = self._mem0.add(
            content,
            user_id=user_id,
            metadata=metadata or {},
        )
        logger.debug("Mem0 add result: %s", result)
        return result if isinstance(result, dict) else {"result": result}

    def search_memories(
        self,
        query: str,
        user_id: str = "archon",
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """유사 메모리 검색.

        Args:
            query: 검색 쿼리.
            user_id: 사용자/에이전트 식별자.
            limit: 최대 결과 수.

        Returns:
            각 결과: {"id": str, "memory": str, "metadata": dict}
        """
        try:
            results = self._mem0.search(query, user_id=user_id, limit=limit)
        except Exception:
            logger.warning("Mem0 search failed", exc_info=True)
            return []

        if isinstance(results, dict):
            results = results.get("results", [])

        memories: list[dict[str, Any]] = []
        for item in results:
            if not isinstance(item, dict):
                continue
            memories.append({
                "id": item.get("id", ""),
                "memory": item.get("memory", ""),
                "metadata": item.get("metadata", {}),
            })

        return memories[:limit]

    def get_all(self, user_id: str = "archon") -> list[dict[str, Any]]:
        """사용자의 모든 메모리 조회."""
        try:
            results = self._mem0.get_all(user_id=user_id)
        except Exception:
            logger.warning("Mem0 get_all failed", exc_info=True)
            return []

        if isinstance(results, dict):
            results = results.get("results", [])

        return [
            {
                "id": item.get("id", ""),
                "memory": item.get("memory", ""),
                "metadata": item.get("metadata", {}),
            }
            for item in results
            if isinstance(item, dict)
        ]

    def delete_memory(self, memory_id: str) -> None:
        """특정 메모리 삭제."""
        try:
            self._mem0.delete(memory_id)
        except Exception:
            logger.warning("Mem0 delete failed for %s", memory_id, exc_info=True)
