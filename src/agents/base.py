"""에이전트 베이스 클래스 — 무상태, 컨텍스트 주입 패턴."""

from __future__ import annotations

import abc
import json
import logging
import re
from collections.abc import AsyncIterator

import litellm

from src.mcp.a2a import A2AMessage, A2AMessageType, A2APriority, A2ARouter
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

    def __init__(self, role: AgentRole, a2a_router: A2ARouter | None = None) -> None:
        self.role = role
        self._a2a_router = a2a_router

    async def execute(
        self,
        handoff: HandoffArtifact,
        registry: ProjectRegistry,
    ) -> HandoffArtifact:
        """태스크를 실행하고 다음 핸드오프를 생성한다."""
        from src.memory.compressor import compress_handoff

        model = registry.get_model_for_role(self.role)
        agent_cfg = registry.agent_config.get(self.role)
        max_ctx = (agent_cfg.max_tokens * 3) if agent_cfg else 12000

        # 토큰 초과 시 자동 압축
        handoff = compress_handoff(handoff, max_context_tokens=max_ctx)

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

    async def execute_streaming(
        self,
        handoff: HandoffArtifact,
        registry: ProjectRegistry,
    ) -> AsyncIterator[str]:
        """스트리밍 모드로 태스크를 실행한다.

        청크 단위로 텍스트를 yield하며, 완료 시 handoff를 반환하지 않고
        호출자가 collect해서 _build_handoff_result()를 호출해야 한다.
        타임아웃은 AgentModelConfig.timeout_seconds를 따른다.
        """
        model = registry.get_model_for_role(self.role)
        agent_cfg = registry.agent_config.get(self.role)
        timeout = agent_cfg.timeout_seconds if agent_cfg else 300

        logger.info(
            "Agent [%s] streaming task [%s] with model [%s] (timeout=%ds)",
            self.role,
            handoff.task.task_id,
            model,
            timeout,
        )

        system_prompt = self._build_system_prompt(handoff, registry)
        user_prompt = self._build_user_prompt(handoff)

        response = await litellm.acompletion(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=agent_cfg.max_tokens if agent_cfg else 4096,
            temperature=agent_cfg.temperature if agent_cfg else 0.2,
            stream=True,
            timeout=timeout,
        )

        async for chunk in response:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta

    async def execute_with_streaming(
        self,
        handoff: HandoffArtifact,
        registry: ProjectRegistry,
        on_chunk: None | (type[None]) = None,
    ) -> HandoffArtifact:
        """스트리밍 실행 후 결과를 HandoffArtifact로 조립.

        streaming이 활성화된 경우 execute_streaming()으로 실행하고,
        비활성화 상태면 기존 execute()로 폴백한다.
        """
        agent_cfg = registry.agent_config.get(self.role)
        use_streaming = agent_cfg.streaming if agent_cfg else False

        if not use_streaming:
            return await self.execute(handoff, registry)

        chunks: list[str] = []
        async for chunk in self.execute_streaming(handoff, registry):
            chunks.append(chunk)

        result_text = "".join(chunks)
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

    def send_a2a(
        self,
        to_agent: str,
        subject: str,
        body: str,
        *,
        message_type: A2AMessageType = A2AMessageType.REQUEST,
        priority: A2APriority = A2APriority.NORMAL,
        project_id: str | None = None,
        task_id: str | None = None,
    ) -> bool:
        """다른 에이전트에게 A2A 메시지를 전송한다.

        A2ARouter가 설정되지 않은 경우 False를 반환한다.
        """
        if not self._a2a_router:
            logger.debug("A2A router not configured, skipping message to [%s]", to_agent)
            return False

        import uuid

        message = A2AMessage(
            message_id=f"a2a_{uuid.uuid4().hex[:12]}",
            from_agent=self.role,
            to_agent=to_agent,
            message_type=message_type,
            priority=priority,
            subject=subject,
            body=body,
            project_id=project_id,
            task_id=task_id,
        )
        self._a2a_router.send(message)
        return True

    def receive_a2a(self) -> list[A2AMessage]:
        """이 에이전트의 A2A 메시지를 수신한다."""
        if not self._a2a_router:
            return []
        return self._a2a_router.receive(self.role)

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
