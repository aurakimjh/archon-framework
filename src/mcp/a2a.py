"""A2A (Agent-to-Agent) 프로토콜 — 에이전트 간 직접 통신."""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class A2AMessageType(StrEnum):
    """A2A 메시지 유형."""

    REQUEST = "request"
    RESPONSE = "response"
    BROADCAST = "broadcast"
    QUERY = "query"


class A2APriority(StrEnum):
    """A2A 메시지 우선순위."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class A2AMessage(BaseModel):
    """에이전트 간 통신 메시지.

    핸드오프 외에 에이전트가 직접 다른 에이전트에게
    질의/요청/응답을 보낼 때 사용한다.
    """

    message_id: str
    from_agent: str
    to_agent: str
    message_type: A2AMessageType = A2AMessageType.REQUEST
    priority: A2APriority = A2APriority.NORMAL
    subject: str = ""
    body: str = ""
    context: dict[str, str] = Field(default_factory=dict)
    reply_to: str | None = None
    project_id: str | None = None
    task_id: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class A2ARouter:
    """A2A 메시지 라우터.

    에이전트 간 메시지를 라우팅하고, 메시지 히스토리를 관리한다.
    인메모리 구현 — 프로덕션에서는 Redis Pub/Sub 등으로 교체 가능.
    """

    def __init__(self) -> None:
        self._mailboxes: dict[str, list[A2AMessage]] = defaultdict(list)
        self._history: list[A2AMessage] = []

    def send(self, message: A2AMessage) -> None:
        """메시지를 대상 에이전트의 메일박스에 전달한다."""
        if message.message_type == A2AMessageType.BROADCAST:
            logger.info(
                "A2A broadcast from [%s]: %s",
                message.from_agent,
                message.subject,
            )
            # broadcast는 모든 기존 메일박스에 전달
            for agent_id in list(self._mailboxes.keys()):
                if agent_id != message.from_agent:
                    self._mailboxes[agent_id].append(message)
        else:
            logger.info(
                "A2A [%s] → [%s]: %s",
                message.from_agent,
                message.to_agent,
                message.subject,
            )
            self._mailboxes[message.to_agent].append(message)

        self._history.append(message)

    def receive(self, agent_id: str) -> list[A2AMessage]:
        """에이전트의 메일박스에서 모든 메시지를 가져온다 (consume)."""
        messages = self._mailboxes.pop(agent_id, [])
        return messages

    def peek(self, agent_id: str) -> list[A2AMessage]:
        """메일박스를 소비하지 않고 확인만 한다."""
        return list(self._mailboxes.get(agent_id, []))

    def pending_count(self, agent_id: str) -> int:
        """대기 중인 메시지 수를 반환한다."""
        return len(self._mailboxes.get(agent_id, []))

    def get_history(
        self,
        project_id: str | None = None,
        limit: int = 50,
    ) -> list[A2AMessage]:
        """메시지 히스토리를 반환한다."""
        if project_id:
            filtered = [m for m in self._history if m.project_id == project_id]
        else:
            filtered = self._history
        return filtered[-limit:]

    def clear(self, agent_id: str | None = None) -> None:
        """메일박스를 비운다. agent_id 없으면 전체 초기화."""
        if agent_id:
            self._mailboxes.pop(agent_id, None)
        else:
            self._mailboxes.clear()
            self._history.clear()
