"""마스터 오케스트레이터 — 작업 분배, 리뷰 조율, Human Gate 관리."""

from __future__ import annotations

import logging

from src.agents.backend import BackendAgent
from src.agents.base import BaseAgent
from src.agents.devops import DevOpsAgent
from src.agents.docs import DocsAgent
from src.agents.frontend import FrontendAgent
from src.agents.reviewer import ReviewerAgent
from src.agents.tester import TesterAgent
from src.gate.evaluator import evaluate_gate
from src.gate.models import GateDecision
from src.guardrails.policy import GuardrailPolicy
from src.guardrails.token_budget import TokenBudgetTracker
from src.healing.health_monitor import AgentHealthMonitor
from src.log import get_logger
from src.memory.context_injector import MemoryStore
from src.notifications.base import GateEvent, Notifier
from src.orchestrator.handoff import (
    Envelope,
    HandoffArtifact,
    HumanGatePackage,
)
from src.gate.consensus import ConsensusGate, ConsensusResult, ConsensusStrategy
from src.registry.models import AgentRole, MultiProviderMode, ProjectRegistry

logger = logging.getLogger(__name__)
slog = get_logger(__name__)

# 레거시 호환: 정책 없는 기본 풀
AGENT_POOL: dict[str, BaseAgent] = {
    AgentRole.BACKEND: BackendAgent(),
    AgentRole.FRONTEND: FrontendAgent(),
    AgentRole.TESTER: TesterAgent(),
    AgentRole.DEVOPS: DevOpsAgent(),
    AgentRole.DOCS: DocsAgent(),
    AgentRole.REVIEWER: ReviewerAgent(),
}


def create_agent_pool(
    guardrail_policy: GuardrailPolicy | None = None,
    token_budget: TokenBudgetTracker | None = None,
    health_monitor: AgentHealthMonitor | None = None,
    tracing_middleware: object | None = None,
) -> dict[str, BaseAgent]:
    """의존성을 주입한 에이전트 풀을 생성한다."""
    kwargs: dict = {
        "guardrail_policy": guardrail_policy,
        "token_budget": token_budget,
        "health_monitor": health_monitor,
        "tracing_middleware": tracing_middleware,
    }
    return {
        AgentRole.BACKEND: BackendAgent(**kwargs),
        AgentRole.FRONTEND: FrontendAgent(**kwargs),
        AgentRole.TESTER: TesterAgent(**kwargs),
        AgentRole.DEVOPS: DevOpsAgent(**kwargs),
        AgentRole.DOCS: DocsAgent(**kwargs),
        AgentRole.REVIEWER: ReviewerAgent(**kwargs),
    }

# 기본 태스크 체인 정의 (역할별 후속 에이전트)
DEFAULT_TASK_CHAINS: dict[str, list[str]] = {
    AgentRole.BACKEND: [AgentRole.TESTER, AgentRole.DOCS],
    AgentRole.FRONTEND: [AgentRole.TESTER, AgentRole.DOCS],
    AgentRole.TESTER: [],
    AgentRole.DEVOPS: [AgentRole.TESTER],
    AgentRole.DOCS: [],
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

    def __init__(
        self,
        memory: MemoryStore | None = None,
        task_chains: dict[str, list[str]] | None = None,
        notifier: Notifier | None = None,
        tracing_middleware: object | None = None,
        agent_pool: dict[str, BaseAgent] | None = None,
    ) -> None:
        self.memory = memory or MemoryStore()
        self._task_chains = task_chains or DEFAULT_TASK_CHAINS
        self._notifier = notifier
        self._tracing = tracing_middleware
        self._agent_pool = agent_pool or AGENT_POOL

    async def process_handoff(
        self,
        handoff: HandoffArtifact,
        registry: ProjectRegistry,
        on_step: Callable[[str, Any], None] | None = None,
    ) -> HandoffArtifact:
        """핸드오프를 받아 에이전트 실행 → QA → 리뷰 → Gate 판정 루프 수행.

        L1_REWORK 발생 시 자동 재작업 루프를 돌며,
        max_retry_before_escalation 초과 시 L2로 에스컬레이션한다.
        """
        max_retries = registry.quality_policy.max_retry_before_escalation
        current_handoff = handoff

        # --- 트레이싱: 파이프라인 스팬 시작 ---
        _pipeline_span = None
        if self._tracing and hasattr(self._tracing, "start_pipeline_trace"):
            _pipeline_span = self._tracing.start_pipeline_trace(
                project_id=handoff.project_context.project_id,
                task_id=handoff.task.task_id,
            )
            self._tracing._current_pipeline_span = _pipeline_span

        for attempt in range(max_retries + 1):
            current_handoff.envelope.retry_count = attempt

            logger.info(
                "Orchestrator loop — attempt %d/%d for task [%s]",
                attempt + 1,
                max_retries + 1,
                current_handoff.task.task_id,
            )
            slog.info(
                "orchestrator_loop",
                attempt=attempt + 1,
                max_attempts=max_retries + 1,
                task_id=current_handoff.task.task_id,
                project_id=current_handoff.project_context.project_id,
            )
            if on_step:
                on_step("loop", f"Attempt {attempt + 1}/{max_retries + 1}")

            # 1. 에이전트 실행 + 리뷰 + Gate 판정
            try:
                result = await self._execute_pipeline(current_handoff, registry, on_step)
            except Exception as exc:
                logger.error(
                    "Pipeline exception on attempt %d for [%s]: %s",
                    attempt + 1,
                    current_handoff.task.task_id,
                    exc,
                )
                result = current_handoff.model_copy(deep=True)
                result.quality_gates.gate_decision = GateDecision.L2_HUMAN
                result.human_gate_package = HumanGatePackage(
                    gate_level=GateDecision.L2_HUMAN,
                    trigger_reason=f"Pipeline error: {type(exc).__name__}: {exc}",
                    required_decision="Investigate pipeline failure and decide how to proceed.",
                    estimated_review_time="10분",
                )
                if on_step:
                    on_step("error", f"Pipeline error: {exc}")
                self._end_pipeline_span(_pipeline_span, result)
                return result
            gate = result.quality_gates.gate_decision

            # 2. Gate에 따른 분기
            if gate == GateDecision.AUTO_PASS:
                await self._handle_auto_pass(result, registry)
                if on_step:
                    on_step("commit", f"Auto commit completed for {result.task.task_id}")
                self._end_pipeline_span(_pipeline_span, result)
                return result

            if gate == GateDecision.L1_REWORK:
                if attempt < max_retries:
                    logger.info(
                        "L1_REWORK — retrying (%d/%d) for task [%s]",
                        attempt + 1,
                        max_retries,
                        result.task.task_id,
                    )
                    if on_step:
                        on_step("l1_rework", f"재작업 지시 ({attempt + 1}/{max_retries}회 시도)")
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
                    if on_step:
                        on_step("l2_escalated", f"L1 {max_retries}회 소진 → L2_HUMAN 에스컬레이션")
                    await self._handle_human_gate(result, registry, escalated=True)
                    self._end_pipeline_span(_pipeline_span, result)
                    return result

            # L2, L3, L4는 루프 중단
            if gate == GateDecision.L2_HUMAN:
                if on_step:
                    on_step("l2_human", "프로젝트 일시정지 — 개발자 판단 필요")
                await self._handle_human_gate(result, registry)
                self._end_pipeline_span(_pipeline_span, result)
                return result

            if gate == GateDecision.L3_HALT:
                if on_step:
                    on_step("l3_halt", "긴급 중단 — 심각한 품질 문제")
                await self._handle_halt(result, registry)
                self._end_pipeline_span(_pipeline_span, result)
                return result

            if gate == GateDecision.L4_DEPLOY:
                if on_step:
                    on_step("l4_deploy", "배포 승인 대기 — 개발자 최종 확인 필요")
                await self._handle_deploy_gate(result, registry)
                self._end_pipeline_span(_pipeline_span, result)
                return result

        self._end_pipeline_span(_pipeline_span, result)  # type: ignore[possibly-undefined]
        return result  # type: ignore[possibly-undefined]

    def _end_pipeline_span(
        self,
        span: object | None,
        result: HandoffArtifact,
    ) -> None:
        """파이프라인 트레이싱 스팬을 종료한다."""
        if span and self._tracing and hasattr(self._tracing, "end_span"):
            gate = str(result.quality_gates.gate_decision)
            self._tracing.end_span(
                span, output={"gate_decision": gate},
            )

    async def _execute_pipeline(
        self,
        handoff: HandoffArtifact,
        registry: ProjectRegistry,
        on_step: Callable[[str, Any], None] | None = None,
    ) -> HandoffArtifact:
        """단일 실행 파이프라인: 에이전트 → QA → 리뷰 → Gate 판정."""
        target_role = handoff.envelope.to_agent

        # 에이전트 선택
        agent = self._agent_pool.get(target_role)
        if not agent:
            raise ValueError(f"Unknown agent role: {target_role}")

        # 메모리 컨텍스트 주입
        memory_ctx = await self.memory.inject_memory_context(
            task_instructions=handoff.task.next_instructions,
            project_id=handoff.project_context.project_id,
        )
        handoff.memory_context = memory_ctx

        # 에이전트 실행
        if on_step:
            on_step("agent_exec", f"{target_role.capitalize()} Agent 실행 중...")
        result = await agent.execute(handoff, registry)
        if on_step:
            on_step("agent_done", {
                "role": target_role,
                "summary": result.task.completed_summary,
                "files": [f.path for f in result.artifacts.changed_files]
            })

        # QA 파이프라인 실행 (Phase 1: 실제 subprocess 연동)
        if on_step:
            on_step("qa", "QA Pipeline 실행 중...")
        from src.runtime.qa import run_qa_pipeline

        qa_result = await run_qa_pipeline(
            project_root=handoff.project_context.git_repo,
            registry=registry,
        )
        result.quality_gates = qa_result
        if on_step:
            on_step("qa_done", {
                "lint": qa_result.lint_result,
                "build": qa_result.build_result,
                "unit_passed": qa_result.test_results.unit_passed,
                "unit_failed": qa_result.test_results.unit_failed,
                "coverage": qa_result.test_results.coverage_percent,
                "security": qa_result.security_scan.model_dump(),
            })

        # 리뷰 (target이 reviewer가 아닌 경우)
        # ReviewerAgent._build_handoff_result()가 QA 결과를 보존하므로
        # reviewer 실행 전에 QA 결과를 input_handoff에 넣어두면 된다.
        if target_role != AgentRole.REVIEWER:
            reviewer = self._agent_pool.get(AgentRole.REVIEWER)
            if reviewer:
                if on_step:
                    on_step("reviewer", "Reviewer Agent 실행 중...")
                result = await reviewer.execute(result, registry)
                if on_step:
                    on_step("reviewer_done", {
                        "review_score": result.quality_gates.review_score,
                        "flags": [f.model_dump() for f in result.quality_gates.review_flags]
                    })

            # Multi-Provider 리뷰 (SINGLE이 아닌 경우)
            reviewer_config = registry.agent_config.get(AgentRole.REVIEWER)
            if reviewer_config and reviewer_config.multi_provider_mode != MultiProviderMode.SINGLE:
                if on_step:
                    on_step("consensus", "Multi-Provider 리뷰 실행 중...")
                result = await self._run_multi_provider_review(result, registry)
                if on_step:
                    on_step("consensus_done", {
                        "consensus_score": result.quality_gates.consensus_score,
                        "consensus_reached": result.quality_gates.consensus_reached,
                        "variance": result.quality_gates.score_variance,
                        "dissenting": result.quality_gates.dissenting_models,
                    })

        # Dynamic Guardrails 인자 준비
        changed_paths = [cf.path for cf in result.artifacts.changed_files]
        has_schema = any(
            "migration" in p or "schema" in p for p in changed_paths
        )
        has_external = any(
            "integration" in p or "external" in p for p in changed_paths
        )

        # Gate 판정
        gate = evaluate_gate(
            quality=result.quality_gates,
            policy=registry.quality_policy,
            retry_count=handoff.envelope.retry_count,
            changed_paths=changed_paths,
            task_instructions=handoff.task.next_instructions,
            has_schema_change=has_schema,
            has_external_integration=has_external,
        )
        result.quality_gates.gate_decision = gate
        if on_step:
            on_step("gate", {"decision": gate})


        # 알림 전송
        await self._send_notification(handoff, result, registry)

        # 핸드오프 기록 저장
        self.memory.store_handoff(
            project_id=handoff.project_context.project_id,
            handoff_id=result.envelope.handoff_id,
            summary=result.task.completed_summary,
            metadata={
                "agent": result.envelope.from_agent,
                "gate": str(result.quality_gates.gate_decision),
            },
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
        if not handoff.artifacts.changed_files:
            logger.info("AUTO_PASS — no changed files, skipping commit for [%s]", handoff.task.task_id)
            return

        logger.info("AUTO_PASS — proceeding to auto commit for [%s]", handoff.task.task_id)
        slog.info("state_transition", state="AUTO_PASS", task_id=handoff.task.task_id)

        from src.runtime.git_executor import GitExecutor

        repo_root = handoff.project_context.git_repo
        git = GitExecutor(registry.git_config)
        await git.auto_commit(
            handoff=handoff,
            message_template=registry.git_config.auto_commit_message_template,
            repo_root=repo_root,
        )

    def get_next_agents(self, current_role: str) -> list[str]:
        """현재 역할의 태스크 체인에서 다음 에이전트 목록을 반환."""
        return list(self._task_chains.get(current_role, []))

    def _route_to_next_agent(
        self,
        completed_handoff: HandoffArtifact,
        next_role: str,
    ) -> HandoffArtifact:
        """완료된 핸드오프를 기반으로 다음 에이전트용 핸드오프를 생성."""
        return HandoffArtifact(
            envelope=Envelope(
                handoff_id=f"hf_{completed_handoff.task.task_id}_{next_role}",
                from_agent=completed_handoff.envelope.to_agent,
                to_agent=next_role,
                parent_handoff_id=completed_handoff.envelope.handoff_id,
            ),
            project_context=completed_handoff.project_context,
            task=completed_handoff.task.model_copy(
                update={
                    "next_instructions": (
                        f"Review and process the output from "
                        f"{completed_handoff.envelope.to_agent} agent. "
                        f"Summary: {completed_handoff.task.completed_summary}"
                    ),
                },
            ),
            artifacts=completed_handoff.artifacts,
        )

    async def process_chain(
        self,
        handoff: HandoffArtifact,
        registry: ProjectRegistry,
    ) -> list[HandoffArtifact]:
        """태스크 체인을 따라 순차 실행.

        첫 에이전트를 실행하고, AUTO_PASS되면 체인에 정의된
        후속 에이전트들을 순서대로 실행한다.

        Returns:
            각 단계의 결과 HandoffArtifact 목록.
        """
        results: list[HandoffArtifact] = []

        # 첫 에이전트 실행
        result = await self.process_handoff(handoff, registry)
        results.append(result)

        # AUTO_PASS가 아니면 체인 중단
        if result.quality_gates.gate_decision != GateDecision.AUTO_PASS:
            return results

        # 후속 에이전트 체인 실행
        current_role = handoff.envelope.to_agent
        next_roles = self.get_next_agents(current_role)

        for next_role in next_roles:
            next_handoff = self._route_to_next_agent(result, next_role)
            chain_result = await self.process_handoff(next_handoff, registry)
            results.append(chain_result)

            if chain_result.quality_gates.gate_decision != GateDecision.AUTO_PASS:
                logger.warning(
                    "Chain interrupted at [%s] — gate: %s",
                    next_role,
                    chain_result.quality_gates.gate_decision,
                )
                break

            result = chain_result

        return results

    async def _send_notification(
        self,
        handoff: HandoffArtifact,
        result: HandoffArtifact,
        registry: ProjectRegistry,
    ) -> None:
        """Gate 판정 결과를 알림으로 전송한다."""
        if not self._notifier:
            return

        event = GateEvent(
            project_id=handoff.project_context.project_id,
            project_name=handoff.project_context.project_name,
            task_id=handoff.task.task_id,
            gate_decision=result.quality_gates.gate_decision,
            trigger_reason=result.task.completed_summary[:200],
            agent_role=result.envelope.from_agent,
            review_score=result.quality_gates.review_score,
            retry_count=handoff.envelope.retry_count,
        )

        if self._notifier.should_notify(event):
            try:
                await self._notifier.notify(event)
            except Exception as e:
                logger.warning("Notification failed: %s", e)

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

    # ------------------------------------------------------------------
    # Multi-Provider Review
    # ------------------------------------------------------------------

    async def _run_multi_provider_review(
        self,
        result: HandoffArtifact,
        registry: ProjectRegistry,
    ) -> HandoffArtifact:
        """Multi-Provider 모드에 따라 다중 모델 리뷰를 실행한다.

        SHADOW:    primary 결과 유지 + 다른 모델 비차단 비교 로깅.
        CONSENSUS: 다중 모델 합의로 gate_decision 교체.
        STRICT:    합의 실패 시 L2_HUMAN 강제 상향.
        """
        reviewer_config = registry.agent_config.get(AgentRole.REVIEWER)
        if not reviewer_config or not reviewer_config.review_models:
            return result

        mode = reviewer_config.multi_provider_mode
        models = reviewer_config.review_models

        review_prompt = self._build_consensus_prompt(result)
        strategy = ConsensusStrategy(reviewer_config.consensus_strategy)
        gate = ConsensusGate(
            strategy=strategy,
            score_divergence_threshold=reviewer_config.score_divergence_threshold,
            timeout=reviewer_config.timeout_seconds,
        )

        slog.info(
            "multi_provider_review_start",
            mode=mode,
            models=models,
            strategy=strategy,
            task_id=result.task.task_id,
        )

        if mode == MultiProviderMode.SHADOW:
            return await self._run_shadow_review(result, gate, review_prompt, models)

        if mode == MultiProviderMode.CONSENSUS:
            return await self._run_consensus_review(result, gate, review_prompt, models)

        if mode == MultiProviderMode.STRICT:
            return await self._run_strict_review(result, gate, review_prompt, models)

        return result

    async def _run_shadow_review(
        self,
        result: HandoffArtifact,
        gate: ConsensusGate,
        prompt: str,
        models: list[str],
    ) -> HandoffArtifact:
        """SHADOW — primary 결과를 유지하고, 다른 모델 결과는 비교 로깅만."""
        import asyncio

        async def _shadow_task() -> None:
            consensus = await gate.run_consensus(prompt, models)
            slog.info(
                "shadow_review_complete",
                primary_score=result.quality_gates.review_score,
                primary_gate=str(result.quality_gates.gate_decision),
                consensus_score=consensus.final_score,
                consensus_gate=str(consensus.final_decision),
                consensus_reached=consensus.consensus_reached,
                variance=consensus.score_variance,
                task_id=result.task.task_id,
            )

        asyncio.create_task(_shadow_task())
        return result

    async def _run_consensus_review(
        self,
        result: HandoffArtifact,
        gate: ConsensusGate,
        prompt: str,
        models: list[str],
    ) -> HandoffArtifact:
        """CONSENSUS — 다중 모델 합의로 review_score와 gate_decision을 교체."""
        consensus = await gate.run_consensus(prompt, models)
        self._merge_consensus(result, consensus)
        return result

    async def _run_strict_review(
        self,
        result: HandoffArtifact,
        gate: ConsensusGate,
        prompt: str,
        models: list[str],
    ) -> HandoffArtifact:
        """STRICT — 합의 실패 시 L2_HUMAN으로 강제 상향."""
        consensus = await gate.run_consensus(prompt, models)
        self._merge_consensus(result, consensus)

        if not consensus.consensus_reached:
            logger.warning(
                "STRICT mode — consensus not reached (variance=%.2f), escalating to L2_HUMAN",
                consensus.score_variance,
            )
            result.quality_gates.gate_decision = GateDecision.L2_HUMAN
            result.human_gate_package = HumanGatePackage(
                gate_level=GateDecision.L2_HUMAN,
                trigger_reason=(
                    f"Multi-provider strict mode: consensus not reached. "
                    f"Score variance={consensus.score_variance:.1f}, "
                    f"dissenting={consensus.dissenting_models}"
                ),
                required_decision="Review model disagreements and decide how to proceed.",
                estimated_review_time="10분",
            )
        return result

    @staticmethod
    def _merge_consensus(result: HandoffArtifact, consensus: ConsensusResult) -> None:
        """ConsensusResult를 QualityGates에 병합한다."""
        qg = result.quality_gates
        qg.consensus_score = consensus.final_score
        qg.consensus_reached = consensus.consensus_reached
        qg.score_variance = consensus.score_variance
        qg.dissenting_models = list(consensus.dissenting_models)

        if consensus.success_count > 0:
            qg.review_score = round(consensus.final_score)
            qg.gate_decision = consensus.final_decision

            for review in consensus.reviews:
                if review.is_success:
                    for flag in review.flags:
                        from src.orchestrator.handoff import ReviewFlag
                        try:
                            qg.review_flags.append(ReviewFlag(
                                severity=flag.get("severity", "low"),
                                category=flag.get("category", "consensus"),
                                detail=f"[{review.model}] {flag.get('detail', '')}",
                            ))
                        except Exception:
                            pass

    @staticmethod
    def _build_consensus_prompt(result: HandoffArtifact) -> str:
        """ConsensusGate에 전달할 리뷰 프롬프트를 빌드한다."""
        changed = "\n".join(
            f"- {f.path} ({f.change_type}): {f.reason}"
            for f in result.artifacts.changed_files
        )
        return (
            f"## Task\n{result.task.next_instructions}\n\n"
            f"## Completed Summary\n{result.task.completed_summary}\n\n"
            f"## Changed Files\n{changed}\n\n"
            f"## Current QA Results\n"
            f"- Lint: {result.quality_gates.lint_result}\n"
            f"- Build: {result.quality_gates.build_result}\n"
            f"- Tests: {result.quality_gates.test_results.unit_passed} passed, "
            f"{result.quality_gates.test_results.unit_failed} failed\n"
            f"- Coverage: {result.quality_gates.test_results.coverage_percent}%\n"
            f"- Primary Review Score: {result.quality_gates.review_score}\n"
        )
