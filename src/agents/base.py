"""에이전트 베이스 클래스 — 무상태, 컨텍스트 주입 패턴."""

from __future__ import annotations

import abc
import json
import logging
import re
from collections.abc import AsyncIterator
from typing import Any

import litellm

from src.errors import (
    InputValidationError,
    OutputValidationError,
    PathGuardError,
    TokenBudgetExceededError,
)
from src.guardrails.input_validator import InputValidator
from src.guardrails.output_validator import OutputValidator
from src.guardrails.path_guard import PathGuard
from src.guardrails.policy import GuardrailPolicy
from src.guardrails.token_budget import TokenBudgetTracker
from src.healing.diagnostics import AgentDiagnostician
from src.healing.health_monitor import AgentHealthMonitor
from src.log import get_logger
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
_slog = get_logger(__name__)

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

    def __init__(
        self,
        role: AgentRole,
        a2a_router: A2ARouter | None = None,
        guardrail_policy: GuardrailPolicy | None = None,
        token_budget: TokenBudgetTracker | None = None,
        health_monitor: AgentHealthMonitor | None = None,
        diagnostician: AgentDiagnostician | None = None,
        tracing_middleware: Any | None = None,
    ) -> None:
        self.role = role
        self._a2a_router = a2a_router
        self._guardrail_policy = guardrail_policy
        self._token_budget = token_budget
        self._health_monitor = health_monitor
        self._diagnostician = diagnostician
        self._tracing = tracing_middleware
        # 구조화 로거 (역할 컨텍스트 고정)
        self.slog = get_logger(__name__, agent_role=str(role))

    async def execute(
        self,
        handoff: HandoffArtifact,
        registry: ProjectRegistry,
    ) -> HandoffArtifact:
        """태스크를 실행하고 다음 핸드오프를 생성한다."""
        import time

        from src.memory.compressor import compress_handoff

        model = registry.get_model_for_role(self.role)
        agent_cfg = registry.agent_config.get(self.role)
        max_ctx = (agent_cfg.max_tokens * 3) if agent_cfg else 12000

        # 토큰 초과 시 자동 압축
        handoff = compress_handoff(handoff, max_context_tokens=max_ctx)

        self.slog.info(
            "agent_execute_start",
            task_id=handoff.task.task_id,
            model=model,
            project_id=handoff.project_context.project_id,
        )

        system_prompt = self._build_system_prompt(handoff, registry)
        user_prompt = self._build_user_prompt(handoff)

        # --- 가드레일: 입력 검증 ---
        self._run_input_validation(system_prompt, user_prompt, handoff)

        # --- 가드레일: 토큰 예산 사전 확인 ---
        self._check_token_budget(handoff.task.task_id)

        # --- 트레이싱: 에이전트 스팬 시작 ---
        _span = None
        if self._tracing and hasattr(self._tracing, "start_agent_span"):
            _parent = getattr(self._tracing, "_current_pipeline_span", None)
            if _parent:
                _span = self._tracing.start_agent_span(
                    parent=_parent, agent_role=str(self.role), model=model,
                )

        _start = time.perf_counter()
        try:
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
        except Exception as exc:
            _latency = (time.perf_counter() - _start) * 1000
            if self._health_monitor:
                self._health_monitor.record_failure(
                    error=str(exc), latency_ms=_latency
                )
            if self._diagnostician:
                self._diagnostician.record_error(str(exc))
            if _span and self._tracing:
                self._tracing.end_span(_span, error=str(exc))
            raise

        _latency_ms = (time.perf_counter() - _start) * 1000
        result_text = response.choices[0].message.content or ""

        # --- 가드레일: 출력 검증 ---
        self._run_output_validation(result_text)

        # --- 가드레일: 토큰 사용량 기록 ---
        usage = getattr(response, "usage", None)
        inp_tokens = getattr(usage, "prompt_tokens", 0) if usage else 0
        out_tokens = getattr(usage, "completion_tokens", 0) if usage else 0
        if usage and self._token_budget:
            self._token_budget.record(
                agent_role=self.role,
                model=model,
                task_id=handoff.task.task_id,
                input_tokens=inp_tokens,
                output_tokens=out_tokens,
            )

        # --- 트레이싱: LLM 호출 기록 + 스팬 종료 ---
        if _span and self._tracing:
            self._tracing.record_llm_call(
                span=_span,
                model=model,
                input_tokens=inp_tokens,
                output_tokens=out_tokens,
                latency_ms=_latency_ms,
            )
            self._tracing.end_span(
                _span, output={"output_tokens": out_tokens},
            )

        result = self._build_handoff_result(handoff, result_text)

        # --- 스키마 자가 교정: 구조화 출력 실패 시 1회 재시도 ---
        if (
            "<archon-output>" in result_text
            and not result.task.completed_summary.strip()
        ):
            corrected = await self._self_correct_output(
                result_text, model, registry,
            )
            if corrected:
                result = self._build_handoff_from_parsed(
                    handoff, corrected, result_text,
                )

        # --- 가드레일: 경로 보호 확인 ---
        self._run_path_guard(result, registry)

        # --- 헬스 기록: 성공 ---
        if self._health_monitor:
            self._health_monitor.record_success(latency_ms=_latency_ms)

        self.slog.info(
            "agent_execute_done",
            task_id=handoff.task.task_id,
            input_tokens=inp_tokens,
            output_tokens=out_tokens,
            latency_ms=round(_latency_ms, 1),
        )

        return result

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

    def _build_handoff_from_parsed(
        self,
        input_handoff: HandoffArtifact,
        parsed: dict,
        fallback_text: str,
    ) -> HandoffArtifact:
        """파싱된 구조화 데이터로 HandoffArtifact를 생성한다."""
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
                    "summary", fallback_text[:500]
                ),
                decisions_made=parsed.get("decisions", []),
                next_instructions="Review and validate the output.",
            ),
            artifacts=Artifacts(
                changed_files=parsed.get("changed_files", []),
            ),
            quality_gates=QualityGates(),
        )

    # --- 가드레일 헬퍼 ---

    def _run_input_validation(
        self, system_prompt: str, user_prompt: str, handoff: HandoffArtifact
    ) -> None:
        if not self._guardrail_policy:
            return
        validator = InputValidator(self._guardrail_policy)
        result = validator.validate(system_prompt, user_prompt)
        if not result.passed:
            raise InputValidationError(
                result.violations,
                self._guardrail_policy.input_violation_action,
            )

    def _check_token_budget(self, task_id: str) -> None:
        if not self._token_budget or not self._guardrail_policy:
            return
        status = self._token_budget.check_before_call(self.role, estimated_tokens=0)
        if status.limit_exceeded and self._guardrail_policy.budget_exceeded_action == "block":
            raise TokenBudgetExceededError(
                status.project_id,
                status.daily_tokens_used,
                status.daily_token_limit,
            )

    def _run_output_validation(self, result_text: str) -> None:
        if not self._guardrail_policy:
            return
        validator = OutputValidator(self._guardrail_policy)
        result = validator.validate(result_text)
        if not result.passed:
            raise OutputValidationError(
                result.violations,
                self._guardrail_policy.output_violation_action,
            )

    def _run_path_guard(
        self, result: HandoffArtifact, registry: ProjectRegistry
    ) -> None:
        if not self._guardrail_policy:
            return
        protected = registry.git_config.protected_paths
        guard = PathGuard(protected_paths=protected, policy=self._guardrail_policy)
        guard_result = guard.check_handoff(result)
        if not guard_result.passed:
            raise PathGuardError(guard_result.blocked_paths)
        if guard_result.requires_human_gate:
            logger.warning(
                "PathGuard [%s]: config/sensitive file change detected"
                " — Human Gate recommended: %s",
                self.role,
                guard_result.config_changes,
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

        raw_json = match.group(1)
        data = self._try_parse_json(raw_json)
        if data is None:
            return {}

        return self._extract_structured_fields(data)

    def _try_parse_json(self, raw: str) -> dict | None:
        """JSON 파싱을 시도한다. 실패 시 None 반환."""
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            logger.warning(
                "Agent [%s] returned malformed archon-output JSON",
                self.role,
            )
            return None

    async def _self_correct_output(
        self,
        malformed_text: str,
        model: str,
        registry: ProjectRegistry,
    ) -> dict:
        """스키마 위반 시 교정 메시지를 투입하여 1회 재시도한다.

        LLM에 원래 출력과 기대 스키마를 보여주고 올바른 JSON을 재생성하도록 요청한다.
        재시도도 실패하면 빈 dict를 반환한다.
        """
        correction_prompt = (
            "Your previous output was malformed. "
            "Please re-output ONLY the corrected JSON inside "
            "<archon-output></archon-output> tags.\n\n"
            "Expected schema:\n"
            '{"summary": "string", '
            '"changed_files": [{"path": "string", '
            '"change_type": "added|modified|deleted", "reason": "string"}], '
            '"decisions": [{"decision": "string", "reason": "string"}]}\n\n'
            f"Your previous output:\n{malformed_text[:2000]}"
        )

        _slog.info("self_correction_attempt", agent_role=str(self.role))

        try:
            response = await litellm.acompletion(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a JSON correction assistant. "
                            "Output ONLY valid JSON inside "
                            "<archon-output></archon-output> tags."
                        ),
                    },
                    {"role": "user", "content": correction_prompt},
                ],
                max_tokens=2048,
                temperature=0.0,
            )
            corrected = response.choices[0].message.content or ""
            match = _OUTPUT_TAG_PATTERN.search(corrected)
            if match:
                data = self._try_parse_json(match.group(1))
                if data is not None:
                    _slog.info(
                        "self_correction_success",
                        agent_role=str(self.role),
                    )
                    return self._extract_structured_fields(data)
        except Exception:
            _slog.warning(
                "self_correction_failed",
                agent_role=str(self.role),
            )

        return {}

    @staticmethod
    def _extract_structured_fields(data: dict) -> dict:
        """파싱된 JSON에서 구조화 필드를 추출한다."""
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
