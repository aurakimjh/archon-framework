"""마스터 오케스트레이터 — 작업 분배, 리뷰 조율, Human Gate 관리."""

from __future__ import annotations

import logging
from typing import Any

from src.agents.base import BaseAgent
from src.agents.backend import BackendAgent
from src.agents.reviewer import ReviewerAgent
from src.gate.evaluator import evaluate_gate
from src.gate.models import GateDecision
from src.memory.context_injector import MemoryStore
from src.orchestrator.handoff import HandoffArtifact, QualityGates
from src.registry.models import AgentRole, ProjectRegistry

logger = logging.getLogger(__name__)

# 에이전트 풀 (무상태 — 인스턴스 재사용 가능)
AGENT_POOL: dict[str, BaseAgent] = {
    AgentRole.BACKEND: BackendAgent(),
    AgentRole.REVIEWER: ReviewerAgent(),
}


class Orchestrator:
    """전체 아키텍처 설계, 작업 분배, 코드 리뷰, Human Gate 판단."""

    def __init__(self, memory: MemoryStore | None = None) -> None:
        self.memory = memory or MemoryStore()

    async def process_handoff(
        self,
        handoff: HandoffArtifact,
        registry: ProjectRegistry,
    ) -> HandoffArtifact:
        """핸드오프를 받아 에이전트 실행 → 리뷰 → Gate 판정 파이프라인 수행."""
        target_role = handoff.envelope.to_agent

        # 1. 에이전트 선택
        agent = AGENT_POOL.get(target_role)
        if not agent:
            logger.error("No agent registered for role: %s", target_role)
            raise ValueError(f"Unknown agent role: {target_role}")

        # 2. 메모리 컨텍스트 주입
        memory_ctx = await self.memory.inject_memory_context(
            task_instructions=handoff.task.next_instructions,
            project_id=handoff.project_context.project_id,
        )
        handoff.memory_context = memory_ctx

        # 3. 에이전트 실행
        result = await agent.execute(handoff, registry)

        # 4. 리뷰 (target이 reviewer가 아닌 경우)
        if target_role != AgentRole.REVIEWER:
            reviewer = AGENT_POOL.get(AgentRole.REVIEWER)
            if reviewer:
                result = await reviewer.execute(result, registry)

        # 5. Gate 판정
        gate = evaluate_gate(
            quality=result.quality_gates,
            policy=registry.quality_policy,
            retry_count=handoff.envelope.retry_count,
        )
        result.quality_gates.gate_decision = gate

        # 6. Gate에 따른 후속 처리
        await self._handle_gate_decision(gate, result, registry)

        # 7. 핸드오프 기록 저장
        self.memory.store_handoff(
            project_id=handoff.project_context.project_id,
            handoff_data=result.model_dump(),
        )

        return result

    async def _handle_gate_decision(
        self,
        gate: GateDecision,
        handoff: HandoffArtifact,
        registry: ProjectRegistry,
    ) -> None:
        """Gate 결과에 따른 후속 처리."""
        match gate:
            case GateDecision.AUTO_PASS:
                logger.info("AUTO_PASS — proceeding to auto commit")
            case GateDecision.L1_REWORK:
                logger.info("L1_REWORK — scheduling agent rework")
            case GateDecision.L2_HUMAN:
                logger.warning(
                    "L2_HUMAN — project [%s] paused, awaiting developer input",
                    handoff.project_context.project_id,
                )
            case GateDecision.L3_HALT:
                logger.critical(
                    "L3_HALT — emergency stop for project [%s]",
                    handoff.project_context.project_id,
                )
            case GateDecision.L4_DEPLOY:
                logger.warning(
                    "L4_DEPLOY — deployment requires human approval for [%s]",
                    handoff.project_context.project_id,
                )
