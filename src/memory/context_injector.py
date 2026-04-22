"""공유 메모리 — 3계층 메모리 구조 컨텍스트 주입."""

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

logger = logging.getLogger(__name__)


class MemoryStore:
    """3계층 메모리 스토어 추상 레이어.

    Phase 1에서는 인메모리 딕셔너리로 동작.
    Phase 2에서 Redis(L1), ChromaDB(L2), Mem0(L3) 연동.
    """

    def __init__(self) -> None:
        # L1 — 단기 메모리 (세션 내 스크래치패드)
        self._scratchpad: dict[str, Any] = {}
        # L2 — 중기 메모리 (프로젝트 내 핸드오프 기록)
        self._handoff_history: dict[str, list[dict[str, Any]]] = {}
        # L3 — 장기 메모리 (크로스 프로젝트 패턴)
        self._patterns: dict[str, list[dict[str, Any]]] = {}

    # --- L1: Scratchpad ---

    def set_scratch(self, project_id: str, task_id: str, key: str, value: Any) -> None:
        full_key = f"scratch:{project_id}:{task_id}:{key}"
        self._scratchpad[full_key] = value

    def get_scratch(self, project_id: str, task_id: str, key: str) -> Any:
        full_key = f"scratch:{project_id}:{task_id}:{key}"
        return self._scratchpad.get(full_key)

    # --- L2: Handoff History ---

    def store_handoff(self, project_id: str, handoff_data: dict[str, Any]) -> None:
        if project_id not in self._handoff_history:
            self._handoff_history[project_id] = []
        self._handoff_history[project_id].append(handoff_data)

    def get_handoff_history(
        self, project_id: str, limit: int = 10
    ) -> list[dict[str, Any]]:
        return self._handoff_history.get(project_id, [])[-limit:]

    # --- L3: Pattern Memory ---

    def store_pattern(self, project_id: str, pattern: dict[str, Any]) -> None:
        if project_id not in self._patterns:
            self._patterns[project_id] = []
        self._patterns[project_id].append(pattern)

    # --- Context Injection ---

    async def inject_memory_context(
        self,
        task_instructions: str,
        project_id: str,
    ) -> MemoryContext:
        """에이전트에 주입할 메모리 컨텍스트를 생성한다.

        Phase 1: 로컬 히스토리 기반 단순 매칭.
        Phase 2: Mem0 벡터 검색 (cosine similarity > 0.85).
        """
        past_decisions: list[PastDecision] = []
        known_patterns: list[KnownPattern] = []
        error_history: list[ErrorRecord] = []
        human_feedback: list[HumanFeedback] = []

        # Phase 1: 프로젝트 내 패턴 조회
        for pattern_data in self._patterns.get(project_id, []):
            known_patterns.append(
                KnownPattern(
                    pattern=pattern_data.get("pattern", ""),
                    reason=pattern_data.get("reason", ""),
                    example_file=pattern_data.get("example_file"),
                )
            )

        logger.debug(
            "Injected memory context for project [%s]: %d patterns, %d past decisions",
            project_id,
            len(known_patterns),
            len(past_decisions),
        )

        return MemoryContext(
            relevant_past_decisions=past_decisions,
            known_patterns=known_patterns,
            error_history=error_history,
            human_feedback=human_feedback,
        )
