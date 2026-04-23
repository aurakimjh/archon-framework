"""공유 메모리 — 3계층 메모리 파사드 + 컨텍스트 주입."""

from __future__ import annotations

import logging
from typing import Any

from src.orchestrator.handoff import (
    ErrorRecord,
    HumanFeedback,
    KnownPattern,
    MemoryContext,
    PastDecision,
)

from .mem0_store import Mem0Store
from .redis_scratchpad import RedisScratchpad
from .vector_store import VectorStore

logger = logging.getLogger(__name__)


class MemoryStore:
    """3계층 메모리 파사드.

    L1 (Redis)  — 단기 메모리: 태스크별 스크래치패드, TTL 24시간.
    L2 (ChromaDB) — 중기 메모리: 프로젝트별 핸드오프 벡터 검색.
    L3 (Mem0)   — 장기 메모리: 크로스 프로젝트 패턴 학습.

    각 백엔드는 선택적으로 주입된다. None이면 인메모리 dict 폴백.
    """

    def __init__(
        self,
        redis_scratchpad: RedisScratchpad | None = None,
        vector_store: VectorStore | None = None,
        mem0_store: Mem0Store | None = None,
    ) -> None:
        self._redis = redis_scratchpad
        self._vector = vector_store
        self._mem0 = mem0_store

        # 인메모리 폴백 (백엔드 미연결 시)
        self._fallback_scratch: dict[str, Any] = {}
        self._fallback_history: dict[str, list[dict[str, Any]]] = {}
        self._fallback_patterns: dict[str, list[dict[str, Any]]] = {}

    @property
    def has_redis(self) -> bool:
        return self._redis is not None

    @property
    def has_vector(self) -> bool:
        return self._vector is not None

    @property
    def has_mem0(self) -> bool:
        return self._mem0 is not None

    # --- L1: Scratchpad ---

    async def set_scratch(
        self,
        project_id: str,
        task_id: str,
        key: str,
        value: Any,
    ) -> None:
        """스크래치 값 저장 (L1)."""
        if self._redis:
            await self._redis.set(project_id, task_id, key, value)
        else:
            full_key = f"scratch:{project_id}:{task_id}:{key}"
            self._fallback_scratch[full_key] = value

    async def get_scratch(
        self,
        project_id: str,
        task_id: str,
        key: str,
    ) -> Any | None:
        """스크래치 값 조회 (L1)."""
        if self._redis:
            return await self._redis.get(project_id, task_id, key)
        full_key = f"scratch:{project_id}:{task_id}:{key}"
        return self._fallback_scratch.get(full_key)

    # --- L2: Handoff History (Vector) ---

    def store_handoff(
        self,
        project_id: str,
        handoff_id: str,
        summary: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """핸드오프 기록 저장 (L2)."""
        if self._vector:
            self._vector.store_handoff(project_id, handoff_id, summary, metadata)
        else:
            if project_id not in self._fallback_history:
                self._fallback_history[project_id] = []
            self._fallback_history[project_id].append({
                "handoff_id": handoff_id,
                "summary": summary,
                **(metadata or {}),
            })

    def search_handoffs(
        self,
        project_id: str,
        query: str,
        n_results: int = 5,
        threshold: float = 0.85,
    ) -> list[dict[str, Any]]:
        """유사 핸드오프 검색 (L2)."""
        if self._vector:
            return self._vector.search(project_id, query, n_results, threshold)
        # 폴백: 단순 문자열 매칭 (벡터 검색 없음)
        results = []
        for record in self._fallback_history.get(project_id, []):
            summary = record.get("summary", "")
            if query.lower() in summary.lower():
                results.append({
                    "id": record.get("handoff_id", ""),
                    "document": summary,
                    "metadata": {},
                    "similarity": 0.9,
                })
        return results[:n_results]

    # --- L3: Pattern Memory (Mem0) ---

    def store_pattern(
        self,
        project_id: str,
        pattern: str,
        reason: str = "",
        user_id: str = "archon",
    ) -> None:
        """패턴 저장 (L3)."""
        if self._mem0:
            content = f"[{project_id}] {pattern}"
            if reason:
                content += f" — {reason}"
            self._mem0.add_memory(
                content,
                user_id=user_id,
                metadata={"project_id": project_id, "type": "pattern"},
            )
        else:
            if project_id not in self._fallback_patterns:
                self._fallback_patterns[project_id] = []
            self._fallback_patterns[project_id].append({
                "pattern": pattern,
                "reason": reason,
            })

    def search_patterns(
        self,
        query: str,
        user_id: str = "archon",
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """유사 패턴 검색 (L3, 크로스 프로젝트)."""
        if self._mem0:
            return self._mem0.search_memories(query, user_id=user_id, limit=limit)
        # 폴백: 전체 프로젝트에서 단순 매칭
        results = []
        for patterns in self._fallback_patterns.values():
            for p in patterns:
                if query.lower() in p.get("pattern", "").lower():
                    results.append({
                        "id": "",
                        "memory": p.get("pattern", ""),
                        "metadata": {"reason": p.get("reason", "")},
                    })
        return results[:limit]

    # --- Context Injection ---

    async def inject_memory_context(
        self,
        task_instructions: str,
        project_id: str,
    ) -> MemoryContext:
        """에이전트에 주입할 메모리 컨텍스트를 생성한다.

        L2(ChromaDB)에서 유사 핸드오프를 검색하고,
        L3(Mem0)에서 크로스 프로젝트 패턴을 검색하여
        MemoryContext로 조합한다.
        """
        past_decisions: list[PastDecision] = []
        known_patterns: list[KnownPattern] = []
        error_history: list[ErrorRecord] = []
        human_feedback: list[HumanFeedback] = []

        # L2: 유사 핸드오프 검색 → past_decisions
        similar_handoffs = self.search_handoffs(project_id, task_instructions, n_results=5)
        for h in similar_handoffs:
            past_decisions.append(
                PastDecision(
                    similarity=h.get("similarity", 0.0),
                    project=project_id,
                    decision=h.get("document", ""),
                    outcome=h.get("metadata", {}).get("outcome", ""),
                )
            )

        # L3: 패턴 검색 → known_patterns
        patterns = self.search_patterns(task_instructions, limit=5)
        for p in patterns:
            known_patterns.append(
                KnownPattern(
                    pattern=p.get("memory", ""),
                    reason=p.get("metadata", {}).get("reason", ""),
                )
            )

        # 폴백: 인메모리 패턴도 추가
        if not self._mem0:
            for pattern_data in self._fallback_patterns.get(project_id, []):
                known_patterns.append(
                    KnownPattern(
                        pattern=pattern_data.get("pattern", ""),
                        reason=pattern_data.get("reason", ""),
                        example_file=pattern_data.get("example_file"),
                    )
                )

        logger.debug(
            "Injected memory context for project [%s]: "
            "%d patterns, %d past decisions (redis=%s, vector=%s, mem0=%s)",
            project_id,
            len(known_patterns),
            len(past_decisions),
            self.has_redis,
            self.has_vector,
            self.has_mem0,
        )

        return MemoryContext(
            relevant_past_decisions=past_decisions,
            known_patterns=known_patterns,
            error_history=error_history,
            human_feedback=human_feedback,
        )
