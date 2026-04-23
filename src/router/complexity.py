"""Complexity Router — 태스크 복잡도 측정 및 동적 모델 선택."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import StrEnum

from src.orchestrator.handoff import HandoffArtifact
from src.registry.models import ProjectRegistry

logger = logging.getLogger(__name__)


class ComplexityLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class ComplexityScore:
    """복잡도 분석 결과.

    Attributes:
        level: 복잡도 수준 (LOW/MEDIUM/HIGH).
        score: 0~100 점수.
        factors: 복잡도에 기여한 요인들.
    """

    level: ComplexityLevel
    score: int
    factors: list[str]


# --- 복잡도 측정 키워드 ---

_HIGH_COMPLEXITY_KEYWORDS = [
    "migration", "refactor", "architecture", "security",
    "authentication", "authorization", "encryption",
    "database schema", "breaking change", "backward compatibility",
    "distributed", "concurrency", "race condition",
    "performance optimization", "scalability",
]

_MEDIUM_COMPLEXITY_KEYWORDS = [
    "api endpoint", "crud", "integration", "middleware",
    "validation", "error handling", "logging",
    "testing", "configuration", "deployment",
    "webhook", "notification", "caching",
]


def measure_complexity(handoff: HandoffArtifact) -> ComplexityScore:
    """Handoff Artifact를 분석하여 태스크 복잡도를 측정한다.

    측정 기준:
    1. 지시사항 길이 (토큰 수 추정)
    2. 고복잡도 키워드 포함 여부
    3. 변경 파일 수
    4. 의존성 변경 포함 여부
    5. 기존 결정/블로커 수
    """
    score = 0
    factors: list[str] = []

    instructions = handoff.task.next_instructions.lower()
    summary = handoff.task.completed_summary.lower()
    combined = f"{instructions} {summary}"

    # 1. 지시사항 길이
    instruction_len = len(handoff.task.next_instructions)
    if instruction_len > 3000:
        score += 20
        factors.append(f"long instructions ({instruction_len} chars)")
    elif instruction_len > 1000:
        score += 10
        factors.append(f"moderate instructions ({instruction_len} chars)")

    # 2. 고복잡도 키워드
    high_matches = [kw for kw in _HIGH_COMPLEXITY_KEYWORDS if kw in combined]
    if high_matches:
        score += min(len(high_matches) * 10, 30)
        factors.append(f"high-complexity keywords: {', '.join(high_matches[:3])}")

    # 3. 중복잡도 키워드
    medium_matches = [kw for kw in _MEDIUM_COMPLEXITY_KEYWORDS if kw in combined]
    if medium_matches:
        score += min(len(medium_matches) * 5, 15)
        factors.append(f"medium-complexity keywords: {', '.join(medium_matches[:3])}")

    # 4. 변경 파일 수
    file_count = len(handoff.artifacts.changed_files)
    if file_count > 10:
        score += 15
        factors.append(f"many changed files ({file_count})")
    elif file_count > 5:
        score += 8
        factors.append(f"moderate changed files ({file_count})")

    # 5. 의존성 변경
    if handoff.artifacts.dependency_changes:
        score += 10
        factors.append(f"{len(handoff.artifacts.dependency_changes)} dependency changes")

    # 6. 블로커 존재
    if handoff.task.blockers:
        score += 10
        factors.append(f"{len(handoff.task.blockers)} blockers")

    # 7. 기존 결정 수
    if len(handoff.task.decisions_made) > 3:
        score += 5
        factors.append(f"{len(handoff.task.decisions_made)} prior decisions")

    # 8. 멀티 에이전트 관련 키워드 (cross-agent 작업)
    multi_agent_patterns = re.findall(
        r"\b(frontend|backend|devops|tester|docs)\b", combined
    )
    unique_roles = set(multi_agent_patterns)
    if len(unique_roles) >= 3:
        score += 10
        factors.append(f"cross-agent task ({len(unique_roles)} roles)")

    # 점수 → 레벨 변환
    score = min(score, 100)
    if score >= 60:
        level = ComplexityLevel.HIGH
    elif score >= 30:
        level = ComplexityLevel.MEDIUM
    else:
        level = ComplexityLevel.LOW

    return ComplexityScore(level=level, score=score, factors=factors)


def select_model_by_complexity(
    role: str,
    complexity: ComplexityScore,
    registry: ProjectRegistry,
) -> str:
    """복잡도에 따라 적절한 모델을 선택한다.

    HIGH 복잡도일 때 high_complexity_model이 설정되어 있으면 해당 모델을 반환.
    그 외에는 기본 모델을 반환.
    """
    config = registry.agent_config.get(role)
    if not config:
        return registry.get_model_for_role(role)

    if complexity.level == ComplexityLevel.HIGH and config.high_complexity_model:
        logger.info(
            "Complexity router: [%s] → high-complexity model [%s] (score=%d)",
            role,
            config.high_complexity_model,
            complexity.score,
        )
        return config.high_complexity_model

    return config.model_override or config.model
