"""에이전트 베이스 클래스 — 무상태, 컨텍스트 주입 패턴."""

from __future__ import annotations

import abc
import logging
from typing import Any

import litellm

from src.orchestrator.handoff import (
    Artifacts,
    Envelope,
    HandoffArtifact,
    ProjectContext,
    QualityGates,
    Task,
)
from src.registry.models import AgentRole, ProjectRegistry

logger = logging.getLogger(__name__)


class BaseAgent(abc.ABC):
    """무상태 에이전트 베이스 클래스.

    모든 에이전트는 이 클래스를 상속하며, 프로젝트 컨텍스트를 주입받아 실행한다.
    에이전트는 아무것도 기억하지 않는다 — 매 태스크마다 context가 주입된다.
    """

    role: AgentRole

    def __init__(self, role: AgentRole) -> None:
        self.role = role

    async def execute(
        self,
        handoff: HandoffArtifact,
        registry: ProjectRegistry,
    ) -> HandoffArtifact:
        """태스크를 실행하고 다음 핸드오프를 생성한다."""
        model = registry.get_model_for_role(self.role)
        logger.info(
            "Agent [%s] executing task [%s] with model [%s]",
            self.role,
            handoff.task.task_id,
            model,
        )

        system_prompt = self._build_system_prompt(handoff, registry)
        user_prompt = self._build_user_prompt(handoff)

        response = await litellm.acompletion(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=registry.agent_config.get(self.role, None)
            and registry.agent_config[self.role].max_tokens
            or 4096,
            temperature=registry.agent_config.get(self.role, None)
            and registry.agent_config[self.role].temperature
            or 0.2,
        )

        result_text = response.choices[0].message.content or ""
        return self._build_handoff_result(handoff, result_text)

    @abc.abstractmethod
    def _build_system_prompt(
        self,
        handoff: HandoffArtifact,
        registry: ProjectRegistry,
    ) -> str:
        """역할별 시스템 프롬프트 생성."""
        ...

    def _build_user_prompt(self, handoff: HandoffArtifact) -> str:
        """태스크 지시사항을 유저 프롬프트로 변환."""
        parts = [
            f"## Task: {handoff.task.task_id}",
            f"\n### Instructions\n{handoff.task.next_instructions}",
        ]
        if handoff.task.decisions_made:
            parts.append("\n### Prior Decisions")
            for d in handoff.task.decisions_made:
                parts.append(f"- {d.decision} (reason: {d.reason})")
        if handoff.memory_context:
            if handoff.memory_context.known_patterns:
                parts.append("\n### Known Patterns")
                for p in handoff.memory_context.known_patterns:
                    parts.append(f"- {p.pattern}: {p.reason}")
        return "\n".join(parts)

    def _build_handoff_result(
        self,
        input_handoff: HandoffArtifact,
        result_text: str,
    ) -> HandoffArtifact:
        """실행 결과를 새 HandoffArtifact로 패키징."""
        return HandoffArtifact(
            envelope=Envelope(
                handoff_id=f"hf_{input_handoff.envelope.handoff_id}_out",
                from_agent=self.role,
                to_agent="reviewer",
                parent_handoff_id=input_handoff.envelope.handoff_id,
            ),
            project_context=input_handoff.project_context,
            task=Task(
                task_id=input_handoff.task.task_id,
                completed_summary=result_text[:500],
                next_instructions="Review and validate the output.",
            ),
            artifacts=Artifacts(),
            quality_gates=QualityGates(),
        )
