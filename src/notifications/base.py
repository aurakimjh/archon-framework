"""알림 시스템 — 추상 베이스 + GateEvent 모델."""

from __future__ import annotations

import abc
from datetime import datetime

from pydantic import BaseModel, Field

from src.gate.models import GateDecision


class GateEvent(BaseModel):
    """Gate 판정 발생 시 생성되는 알림 이벤트."""

    project_id: str
    project_name: str
    task_id: str
    gate_decision: GateDecision
    trigger_reason: str
    agent_role: str
    review_score: int = 0
    retry_count: int = 0
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    @property
    def severity(self) -> str:
        """Gate 레벨에 따른 심각도 반환."""
        severity_map = {
            GateDecision.AUTO_PASS: "info",
            GateDecision.L1_REWORK: "warning",
            GateDecision.L2_HUMAN: "error",
            GateDecision.L3_HALT: "critical",
            GateDecision.L4_DEPLOY: "warning",
        }
        return severity_map.get(self.gate_decision, "info")

    @property
    def title(self) -> str:
        """알림 제목 생성."""
        return f"[{self.gate_decision.upper()}] {self.project_name} — {self.task_id}"

    @property
    def summary(self) -> str:
        """알림 요약 생성."""
        return (
            f"Project: {self.project_name} ({self.project_id})\n"
            f"Task: {self.task_id}\n"
            f"Agent: {self.agent_role}\n"
            f"Gate: {self.gate_decision}\n"
            f"Reason: {self.trigger_reason}\n"
            f"Review Score: {self.review_score}"
        )


class Notifier(abc.ABC):
    """알림 전송 추상 베이스 클래스.

    모든 알림 채널(Slack, Terminal 등)은 이 클래스를 구현한다.
    """

    @abc.abstractmethod
    async def notify(self, event: GateEvent) -> bool:
        """알림을 전송한다.

        Returns:
            전송 성공 여부.
        """
        ...

    def should_notify(self, event: GateEvent) -> bool:
        """이 이벤트에 대해 알림을 보내야 하는지 판단.

        기본: AUTO_PASS는 알림 안 함, 나머지는 알림.
        서브클래스에서 오버라이드 가능.
        """
        return event.gate_decision != GateDecision.AUTO_PASS


class CompositeNotifier(Notifier):
    """여러 Notifier를 묶어 동시에 전송하는 복합 알리미."""

    def __init__(self, notifiers: list[Notifier] | None = None) -> None:
        self._notifiers = notifiers or []

    def add(self, notifier: Notifier) -> None:
        """알리미를 추가한다."""
        self._notifiers.append(notifier)

    async def notify(self, event: GateEvent) -> bool:
        """등록된 모든 알리미에 전송. 하나라도 성공하면 True."""
        if not self._notifiers:
            return False

        results = []
        for notifier in self._notifiers:
            if notifier.should_notify(event):
                try:
                    result = await notifier.notify(event)
                    results.append(result)
                except Exception:
                    results.append(False)

        return any(results) if results else False
