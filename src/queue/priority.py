"""멀티 프로젝트 우선순위 랭킹 — 프로젝트 간 태스크 정렬 및 슬롯 할당."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from src.queue.scheduler import TaskSpec

logger = logging.getLogger(__name__)


@dataclass
class ProjectWeight:
    """프로젝트별 우선순위 가중치 정보.

    Attributes:
        project_id: 프로젝트 ID.
        priority: 프로젝트 우선순위 (1~10, 높을수록 중요).
        deadline: 마감일 (가까울수록 우선).
        pending_count: 대기 중인 태스크 수.
    """

    project_id: str
    priority: int = 5
    deadline: datetime | None = None
    pending_count: int = 0


@dataclass
class RankedTask:
    """우선순위 점수가 부여된 태스크.

    Attributes:
        task: 원본 TaskSpec.
        score: 종합 우선순위 점수 (높을수록 먼저 실행).
    """

    task: TaskSpec
    score: float = 0.0


class PriorityRanker:
    """멀티 프로젝트 환경에서 태스크 우선순위를 종합 랭킹.

    점수 계산:
      score = (project_priority * 10) + task_priority + deadline_bonus

    deadline_bonus:
      - 마감 24시간 이내: +30
      - 마감 72시간 이내: +15
      - 마감 7일 이내: +5
      - 그 외: 0
    """

    def __init__(
        self,
        project_weights: list[ProjectWeight] | None = None,
        max_slots: int = 5,
    ) -> None:
        """
        Args:
            project_weights: 프로젝트별 가중치 목록.
            max_slots: 동시 실행 가능한 최대 슬롯 수.
        """
        self._weights: dict[str, ProjectWeight] = {}
        if project_weights:
            for pw in project_weights:
                self._weights[pw.project_id] = pw
        self._max_slots = max_slots

    def set_project_weight(self, weight: ProjectWeight) -> None:
        """프로젝트 가중치를 설정/업데이트."""
        self._weights[weight.project_id] = weight

    def _deadline_bonus(self, deadline: datetime | None, now: datetime | None = None) -> float:
        """마감일까지 남은 시간에 따른 가산점."""
        if deadline is None:
            return 0.0
        current = now or datetime.utcnow()
        remaining = (deadline - current).total_seconds()
        if remaining <= 0:
            return 50.0  # 이미 지남 — 최우선
        hours = remaining / 3600
        if hours <= 24:
            return 30.0
        if hours <= 72:
            return 15.0
        if hours <= 168:  # 7일
            return 5.0
        return 0.0

    def rank(
        self,
        tasks: list[TaskSpec],
        now: datetime | None = None,
    ) -> list[RankedTask]:
        """태스크 목록을 종합 우선순위로 정렬.

        Args:
            tasks: 랭킹할 태스크 목록.
            now: 현재 시각 (테스트용). None이면 utcnow().

        Returns:
            score 내림차순 정렬된 RankedTask 목록.
        """
        ranked: list[RankedTask] = []

        for task in tasks:
            pw = self._weights.get(task.project_id)
            project_priority = pw.priority if pw else 5
            deadline = pw.deadline if pw else None

            score = (
                project_priority * 10.0
                + task.priority
                + self._deadline_bonus(deadline, now)
            )

            ranked.append(RankedTask(task=task, score=score))

        ranked.sort(key=lambda r: r.score, reverse=True)
        return ranked

    def allocate_slots(
        self,
        tasks: list[TaskSpec],
        now: datetime | None = None,
    ) -> list[TaskSpec]:
        """우선순위 랭킹 후 max_slots만큼 할당.

        Returns:
            실행 가능한 상위 N개 태스크.
        """
        ranked = self.rank(tasks, now)
        return [r.task for r in ranked[: self._max_slots]]
