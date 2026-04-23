"""마스터 오케스트레이터 — 작업 분배, 리뷰 조율, Human Gate 관리."""

from __future__ import annotations

import copy
import logging
from typing import Any

from src.agents.base import BaseAgent
from src.agents.backend import BackendAgent
from src.agents.devops import DevOpsAgent
from src.agents.docs import DocsAgent
from src.agents.frontend import FrontendAgent
from src.agents.reviewer import ReviewerAgent
from src.agents.tester import TesterAgent
from src.gate.evaluator import evaluate_gate
from src.gate.models import GateDecision
from src.memory.context_injector import MemoryStore
from src.orchestrator.handoff import (
    Envelope,
    HandoffArtifact,
    HumanGatePackage,
    QualityGates,
)
from src.registry.models import AgentRole, ProjectRegistry

logger = logging.getLogger(__name__)

# 에이전트 풀 (무상태 — 인스턴스 재사용 가능)
AGENT_POOL: dict[str, BaseAgent] = {
    AgentRole.BACKEND: BackendAgent(),
    AgentRole.FRONTEND: FrontendAgent(),
    AgentRole.TESTER: TesterAgent(),
    AgentRole.DEVOPS: DevOpsAgent(),
    AgentRole.DOCS: DocsAgent(),
    AgentRole.REVIEWER: ReviewerAgent(),
}


class Orchestrator:
    """전체 아키텍처 설계, 작업 분배, 코드 리뷰, Human Gate 판단.

    상태 머신:
      에이전트 실행 → QA → 리뷰 → Gate 판정
        ├─ AUTO_PASS  → GitExecutor.auto_commit()
        ├─ L1_REWORK  → retry_count++ → 재실행 (최대 max_retry회)
        ├─ L2_HUMAN   → 프로젝트 일시정지, 개발자 알림
        ├─ L3_HALT    → 긴급 중단
        └─ L4_DEPLOY  → 배포 승인 대기
    """

    def __init__(self, memory: MemoryStore | None = None) -> None:
        self.memory = memory or MemoryStore()

    async def process_handoff(
        self,
        handoff: HandoffArtifact,
        registry: ProjectRegistry,
    ) -> HandoffArtifact:
        """핸드오프를 받아 에이전트 실행 → QA → 리뷰 → Gate 판정 루프 수행.

        L1_REWORK 발생 시 자동 재작업 루프를 돌며,
        max_retry_before_escalation 초과 시 L2로 에스컬레이션한다.
        """
        max_retries = registry.quality_policy.max_retry_before_escalation
        current_handoff = handoff

        for attempt in range(max_retries + 1):
            current_handoff.envelope.retry_count = attempt

            logger.info(
                "Orchestrator loop — attempt %d/%d for task [%s]",
                attempt + 1,
                max_retries + 1,
                current_handoff.task.task_id,
            )

            # 1. 에이전트 실행 + 리뷰 + Gate 판정
            result = await self._execute_pipeline(current_handoff, registry)
            gate = result.quality_gates.gate_decision

            # 2. Gate에 따른 분기
            if gate == GateDecision.AUTO_PASS:
                await self._handle_auto_pass(result, registry)
                return result

            if gate == GateDecision.L1_REWORK:
                if attempt < max_retries:
                    logger.info(
                        "L1_REWORK — retrying (%d/%d) for task [%s]",
                        attempt + 1,
                        max_retries,
                        result.task.task_id,
                    )
                    # 리뷰 피드백을 다음 시도의 지시사항에 반영
                    current_handoff = self._prepare_rework_handoff(
                        original=handoff,
                        review_result=result,
                        retry_count=attempt + 1,
                    )
                    continue
                else:
                    # 최대 재시도 초과 → L2 에스컬레이션
                    logger.warning(
                        "L1_REWORK exhausted (%d retries) — escalating to L2_HUMAN",
                        max_retries,
                    )
                    result.quality_gates.gate_decision = GateDecision.L2_HUMAN
                    await self._handle_human_gate(result, registry, escalated=True)
                    return result

            # L2, L3, L4는 루프 중단
            if gate == GateDecision.L2_HUMAN:
                await self._handle_human_gate(result, registry)
                return result

            if gate == GateDecision.L3_HALT:
                await self._handle_halt(result, registry)
                return result

            if gate == GateDecision.L4_DEPLOY:
                await self._handle_deploy_gate(result, registry)
                return result

        return result  # type: ignore[possibly-undefined]

    async def _execute_pipeline(
        self,
        handoff: HandoffArtifact,
        registry: ProjectRegistry,
    ) -> HandoffArtifact:
        """단일 실행 파이프라인: 에이전트 → QA → 리뷰 → Gate 판정."""
        target_role = handoff.envelope.to_agent

        # 에이전트 선택
        agent = AGENT_POOL.get(target_role)
        if not agent:
            raise ValueError(f"Unknown agent role: {target_role}")

        # 메모리 컨텍스트 주입
        memory_ctx = await self.memory.inject_memory_context(
            task_instructions=handoff.task.next_instructions,
            project_id=handoff.project_context.project_id,
        )
        handoff.memory_context = memory_ctx

        # 에이전트 실행
        result = await agent.execute(handoff, registry)

        # QA 파이프라인 실행 (Phase 1: 실제 subprocess 연동)
        from src.runtime.qa import run_qa_pipeline

        qa_result = await run_qa_pipeline(
            project_root=handoff.project_context.git_repo,
            registry=registry,
        )
        result.quality_gates = qa_result

        # 리뷰 (target이 reviewer가 아닌 경우)
        if target_role != AgentRole.REVIEWER:
            reviewer = AGENT_POOL.get(AgentRole.REVIEWER)
            if reviewer:
                result = await reviewer.execute(result, registry)

        # Gate 판정
        gate = evaluate_gate(
            quality=result.quality_gates,
            policy=registry.quality_policy,
            retry_count=handoff.envelope.retry_count,
        )
        result.quality_gates.gate_decision = gate

        # 핸드오프 기록 저장
        self.memory.store_handoff(
            project_id=handoff.project_context.project_id,
            handoff_data=result.model_dump(),
        )

        return result

    def _prepare_rework_handoff(
        self,
        original: HandoffArtifact,
        review_result: HandoffArtifact,
        retry_count: int,
    ) -> HandoffArtifact:
        """L1_REWORK 재작업용 핸드오프를 생성한다.

        리뷰에서 발견된 문제를 다음 시도의 지시사항에 포함시킨다.
        """
        # 리뷰 플래그를 재작업 지시사항으로 변환
        rework_instructions = [original.task.next_instructions, "", "## Rework Required"]
        for flag in review_result.quality_gates.review_flags:
            rework_instructions.append(f"- [{flag.severity}] {flag.category}: {flag.detail}")

        if review_result.quality_gates.lint_result != "passed":
            rework_instructions.append("- Fix all lint issues")
        if review_result.quality_gates.test_results.unit_failed > 0:
            rework_instructions.append(
                f"- Fix {review_result.quality_gates.test_results.unit_failed} failing unit tests"
            )

        rework_handoff = original.model_copy(deep=True)
        rework_handoff.task.next_instructions = "\n".join(rework_instructions)
        rework_handoff.envelope.retry_count = retry_count
        rework_handoff.envelope.parent_handoff_id = review_result.envelope.handoff_id

        return rework_handoff

    async def _handle_auto_pass(
        self,
        handoff: HandoffArtifact,
        registry: ProjectRegistry,
    ) -> None:
        """AUTO_PASS — 자동 커밋/푸시."""
        logger.info("AUTO_PASS — proceeding to auto commit for [%s]", handoff.task.task_id)

        from src.runtime.git_executor import GitExecutor

        git = GitExecutor(registry.git_config)
        await git.auto_commit(
            handoff=handoff,
            message_template=registry.git_config.auto_commit_message_template,
        )

    async def _handle_human_gate(
        self,
        handoff: HandoffArtifact,
        registry: ProjectRegistry,
        escalated: bool = False,
    ) -> None:
        """L2_HUMAN — 프로젝트 일시정지, 개발자 알림."""
        trigger = "L1 rework exhausted" if escalated else "Quality policy triggered"
        logger.warning(
            "L2_HUMAN — project [%s] paused: %s",
            handoff.project_context.project_id,
            trigger,
        )
        handoff.human_gate_package = HumanGatePackage(
            gate_level=GateDecision.L2_HUMAN,
            trigger_reason=trigger,
            required_decision="Review the flagged issues and decide how to proceed.",
            estimated_review_time="5분",
        )

    async def _handle_halt(
        self,
        handoff: HandoffArtifact,
        registry: ProjectRegistry,
    ) -> None:
        """L3_HALT — 긴급 중단."""
        logger.critical(
            "L3_HALT — emergency stop for project [%s]",
            handoff.project_context.project_id,
        )

    async def _handle_deploy_gate(
        self,
        handoff: HandoffArtifact,
        registry: ProjectRegistry,
    ) -> None:
        """L4_DEPLOY — 배포 승인 대기."""
        logger.warning(
            "L4_DEPLOY — deployment requires human approval for [%s]",
            handoff.project_context.project_id,
        )
        handoff.human_gate_package = HumanGatePackage(
            gate_level=GateDecision.L4_DEPLOY,
            trigger_reason="Production deployment requested",
            required_decision="Approve production deployment?",
            estimated_review_time="10분",
        )
