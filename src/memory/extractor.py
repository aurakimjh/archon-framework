"""Semantic Memory Extractor — 핸드오프 완료 후 지식을 자동 분류/저장한다.

에이전트 파이프라인 종료 시 비동기로 실행되어,
HandoffArtifact에서 재사용 가능한 지식을 추출하고
MemoryStore(L2/L3)에 구조화하여 저장한다.
"""

from __future__ import annotations

import logging
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from src.log import get_logger
from src.orchestrator.handoff import HandoffArtifact

logger = logging.getLogger(__name__)
_slog = get_logger(__name__)


class MemoryCategory(StrEnum):
    """추출된 메모리의 분류."""

    DECISION_PATTERN = "decision_pattern"      # 아키텍처/기술 결정
    ERROR_RESOLUTION = "error_resolution"      # 에러 → 해결책 매핑
    QUALITY_INSIGHT = "quality_insight"         # 리뷰/QA에서 발견된 인사이트
    HUMAN_FEEDBACK = "human_feedback"           # 사람의 판단/피드백
    TECH_PATTERN = "tech_pattern"              # 기술 스택/코딩 패턴


class ExtractedMemory(BaseModel):
    """추출된 단일 지식 단위."""

    category: MemoryCategory
    content: str
    reason: str = ""
    source_handoff_id: str = ""
    source_agent: str = ""
    project_id: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExtractionResult(BaseModel):
    """추출 결과 요약."""

    handoff_id: str
    project_id: str
    extracted_count: int = 0
    stored_count: int = 0
    memories: list[ExtractedMemory] = Field(default_factory=list)


class MemoryExtractor:
    """HandoffArtifact에서 재사용 가능한 지식을 추출한다.

    추출 대상:
    - task.decisions_made → DECISION_PATTERN
    - quality_gates.review_flags → QUALITY_INSIGHT
    - memory_context.error_history → ERROR_RESOLUTION
    - memory_context.human_feedback → HUMAN_FEEDBACK
    - artifacts.dependency_changes → TECH_PATTERN
    - 고득점 핸드오프의 완료 요약 → DECISION_PATTERN
    """

    def __init__(
        self,
        min_review_score: int = 70,
        extract_from_low_score: bool = True,
    ) -> None:
        """
        Args:
            min_review_score: 이 점수 이상이면 성공 패턴으로 저장.
            extract_from_low_score: 낮은 점수에서도 인사이트 추출 여부.
        """
        self._min_review_score = min_review_score
        self._extract_from_low_score = extract_from_low_score

    def extract(self, handoff: HandoffArtifact) -> list[ExtractedMemory]:
        """HandoffArtifact에서 지식을 추출한다."""
        memories: list[ExtractedMemory] = []
        hid = handoff.envelope.handoff_id
        pid = handoff.project_context.project_id
        agent = handoff.envelope.from_agent

        memories.extend(self._extract_decisions(handoff, hid, pid, agent))
        memories.extend(self._extract_review_flags(handoff, hid, pid, agent))
        memories.extend(self._extract_error_resolutions(handoff, hid, pid, agent))
        memories.extend(self._extract_human_feedback(handoff, hid, pid, agent))
        memories.extend(self._extract_tech_patterns(handoff, hid, pid, agent))
        memories.extend(self._extract_success_pattern(handoff, hid, pid, agent))

        _slog.info(
            "memory_extracted",
            handoff_id=hid,
            count=len(memories),
            categories=[m.category.value for m in memories],
        )
        return memories

    async def extract_and_store(
        self,
        handoff: HandoffArtifact,
        memory_store: Any,
    ) -> ExtractionResult:
        """추출 + MemoryStore 저장을 한번에 수행한다.

        Args:
            handoff: 완료된 핸드오프.
            memory_store: MemoryStore 인스턴스.

        Returns:
            추출 및 저장 결과.
        """
        memories = self.extract(handoff)
        pid = handoff.project_context.project_id
        hid = handoff.envelope.handoff_id
        stored = 0

        for mem in memories:
            try:
                memory_store.store_pattern(
                    project_id=pid,
                    pattern=mem.content,
                    reason=mem.reason,
                )
                stored += 1
            except Exception:
                _slog.exception(
                    "memory_store_failed",
                    category=mem.category,
                    handoff_id=hid,
                )

        _slog.info(
            "memory_stored",
            handoff_id=hid,
            extracted=len(memories),
            stored=stored,
        )

        return ExtractionResult(
            handoff_id=hid,
            project_id=pid,
            extracted_count=len(memories),
            stored_count=stored,
            memories=memories,
        )

    # --- 추출 로직 ---

    def _extract_decisions(
        self, h: HandoffArtifact, hid: str, pid: str, agent: str,
    ) -> list[ExtractedMemory]:
        """task.decisions_made에서 아키텍처/기술 결정을 추출."""
        results = []
        for d in h.task.decisions_made:
            content = d.decision
            if d.alternatives_considered:
                content += f" (대안: {', '.join(d.alternatives_considered)})"
            results.append(ExtractedMemory(
                category=MemoryCategory.DECISION_PATTERN,
                content=content,
                reason=d.reason,
                source_handoff_id=hid,
                source_agent=agent,
                project_id=pid,
                metadata={"alternatives": d.alternatives_considered},
            ))
        return results

    def _extract_review_flags(
        self, h: HandoffArtifact, hid: str, pid: str, agent: str,
    ) -> list[ExtractedMemory]:
        """quality_gates.review_flags에서 품질 인사이트를 추출."""
        score = h.quality_gates.review_score
        if not self._extract_from_low_score and score < self._min_review_score:
            return []

        results = []
        for flag in h.quality_gates.review_flags:
            results.append(ExtractedMemory(
                category=MemoryCategory.QUALITY_INSIGHT,
                content=f"[{flag.severity}/{flag.category}] {flag.detail}",
                reason=f"review_score={score}, gate={h.quality_gates.gate_decision}",
                source_handoff_id=hid,
                source_agent=agent,
                project_id=pid,
                metadata={
                    "severity": flag.severity,
                    "flag_category": flag.category,
                    "review_score": score,
                },
            ))
        return results

    def _extract_error_resolutions(
        self, h: HandoffArtifact, hid: str, pid: str, agent: str,
    ) -> list[ExtractedMemory]:
        """memory_context.error_history에서 에러→해결책 매핑을 추출."""
        if not h.memory_context:
            return []
        results = []
        for err in h.memory_context.error_history:
            if not err.resolution:
                continue
            results.append(ExtractedMemory(
                category=MemoryCategory.ERROR_RESOLUTION,
                content=f"Error: {err.error} → Resolution: {err.resolution}",
                reason=f"retry #{err.retry_num}",
                source_handoff_id=hid,
                source_agent=agent,
                project_id=pid,
                metadata={"retry_num": err.retry_num},
            ))
        return results

    def _extract_human_feedback(
        self, h: HandoffArtifact, hid: str, pid: str, agent: str,
    ) -> list[ExtractedMemory]:
        """memory_context.human_feedback에서 사람의 판단을 추출."""
        if not h.memory_context:
            return []
        results = []
        for fb in h.memory_context.human_feedback:
            results.append(ExtractedMemory(
                category=MemoryCategory.HUMAN_FEEDBACK,
                content=f"{fb.decision} (applies to: {fb.applies_to})",
                reason=f"feedback date: {fb.date}",
                source_handoff_id=hid,
                source_agent=agent,
                project_id=pid,
                metadata={"date": fb.date, "applies_to": fb.applies_to},
            ))
        return results

    def _extract_tech_patterns(
        self, h: HandoffArtifact, hid: str, pid: str, agent: str,
    ) -> list[ExtractedMemory]:
        """artifacts.dependency_changes에서 기술 패턴을 추출."""
        results = []
        for dep in h.artifacts.dependency_changes:
            content = f"{dep.action} {dep.name}@{dep.version}"
            reason_parts = []
            if dep.license:
                reason_parts.append(f"license={dep.license}")
            if dep.security_scan:
                reason_parts.append(f"security={dep.security_scan}")
            results.append(ExtractedMemory(
                category=MemoryCategory.TECH_PATTERN,
                content=content,
                reason=", ".join(reason_parts) if reason_parts else "",
                source_handoff_id=hid,
                source_agent=agent,
                project_id=pid,
                metadata={
                    "dependency": dep.name,
                    "version": dep.version,
                    "action": dep.action,
                },
            ))
        return results

    def _extract_success_pattern(
        self, h: HandoffArtifact, hid: str, pid: str, agent: str,
    ) -> list[ExtractedMemory]:
        """고득점 핸드오프의 완료 요약을 성공 패턴으로 저장."""
        score = h.quality_gates.review_score
        if score < self._min_review_score:
            return []
        summary = h.task.completed_summary.strip()
        if not summary:
            return []
        return [ExtractedMemory(
            category=MemoryCategory.DECISION_PATTERN,
            content=summary,
            reason=f"high-quality completion (score={score})",
            source_handoff_id=hid,
            source_agent=agent,
            project_id=pid,
            metadata={"review_score": score, "type": "success_pattern"},
        )]
