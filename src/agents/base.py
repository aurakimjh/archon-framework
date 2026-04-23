"""에이전트 베이스 클래스 — 무상태, 컨텍스트 주입 패턴."""

from __future__ import annotations

import abc
import json
import logging
import re

import litellm

from src.orchestrator.handoff import (
    Artifacts,
    ChangedFile,
    Decision,
    Envelope,
    HandoffArtifact,
    QualityGates,
    Task,
)
from src.registry.models import AgentRole, ProjectRegistry

logger = logging.getLogger(__name__)

# LLM 구조화 출력 태그
_OUTPUT_TAG_PATTERN = re.compile(
    r"<archon-output>(.*?)</archon-output>",
    re.DOTALL,
)


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
        """실행 결과를 새 HandoffArtifact로 패키징.

        LLM이 <archon-output> 태그 내에 구조화된 JSON을 반환하면
        changed_files, decisions_made 등을 파싱하여 바인딩한다.
        태그가 없으면 raw text를 completed_summary로 사용한다.
        """
        parsed = self._parse_structured_output(result_text)

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
                completed_summary=parsed.get(
                    "summary", result_text[:500]
                ),
                decisions_made=parsed.get("decisions", []),
                next_instructions="Review and validate the output.",
            ),
            artifacts=Artifacts(
                changed_files=parsed.get("changed_files", []),
            ),
            quality_gates=QualityGates(),
        )

    def _parse_structured_output(
        self, result_text: str
    ) -> dict:
        """LLM 출력에서 <archon-output> JSON 블록을 추출한다.

        예상 형식:
        <archon-output>
        {
          "summary": "...",
          "changed_files": [{"path": "...", "change_type": "added", "reason": "..."}],
          "decisions": [{"decision": "...", "reason": "..."}]
        }
        </archon-output>

        파싱 실패 시 빈 dict 반환 (기존 fallback 동작).
        """
        match = _OUTPUT_TAG_PATTERN.search(result_text)
        if not match:
            return {}

        try:
            data = json.loads(match.group(1))
        except (json.JSONDecodeError, ValueError):
            logger.warning(
                "Agent [%s] returned malformed archon-output JSON",
                self.role,
            )
            return {}

        result: dict = {}

        if "summary" in data:
            result["summary"] = str(data["summary"])[:500]

        if "changed_files" in data and isinstance(data["changed_files"], list):
            result["changed_files"] = [
                ChangedFile(
                    path=f.get("path", ""),
                    change_type=f.get("change_type", "modified"),
                    reason=f.get("reason", ""),
                )
                for f in data["changed_files"]
                if isinstance(f, dict) and f.get("path")
            ]

        if "decisions" in data and isinstance(data["decisions"], list):
            result["decisions"] = [
                Decision(
                    decision=d.get("decision", ""),
                    reason=d.get("reason", ""),
                    alternatives_considered=d.get("alternatives", []),
                )
                for d in data["decisions"]
                if isinstance(d, dict) and d.get("decision")
            ]

        return result
