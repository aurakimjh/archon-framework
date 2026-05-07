"""Dashboard REST API 라우트."""

from __future__ import annotations

import logging
from typing import Any

from src.dashboard.models import (
    AgentStatusResponse,
    CostSummary,
    GateQueueItem,
    ProjectSummary,
    TaskRequest,
)
from src.log import get_logger

logger = logging.getLogger(__name__)
_slog = get_logger(__name__)


class DashboardRoutes:
    """Dashboard API 핸들러.

    FastAPI 없이도 동작하며, FastAPI router에 마운트할 수 있다.
    """

    def __init__(
        self,
        registry_store: Any = None,
        health_registry: Any = None,
        token_budgets: dict[str, Any] | None = None,
        metrics_collector: Any = None,
        gate_queue: list[GateQueueItem] | None = None,
    ) -> None:
        self._registry_store = registry_store
        self._health_registry = health_registry
        self._token_budgets = token_budgets or {}
        self._metrics_collector = metrics_collector
        self._gate_queue: list[GateQueueItem] = gate_queue or []

    # --- Tasks ---

    async def run_task(
        self, 
        request: TaskRequest, 
        on_step: callable | None = None
    ) -> dict[str, Any]:
        """새 작업을 실행한다."""
        from src.orchestrator.handoff import HandoffArtifact, Envelope, ProjectContext, Task
        from src.registry.models import ProjectRegistry, ProjectMeta, GitConfig

        # Registry 로드 (실패 시 기본값 생성)
        registry = None
        if self._registry_store:
            try:
                registry = self._registry_store.load(request.project_id)
            except Exception:
                pass
        
        if registry is None:
            registry = ProjectRegistry(
                project_meta=ProjectMeta(
                    project_id=request.project_id,
                    project_name=request.project_id,
                ),
                git_config=GitConfig(repo_url="mem://mock"),
            )

        # 초기 핸드오프 생성
        initial_handoff = HandoffArtifact(
            envelope=Envelope(
                handoff_id=f"hf_ui_{request.project_id}",
                from_agent="user",
                to_agent=request.agent_role,
            ),
            project_context=ProjectContext(
                project_id=request.project_id,
                project_name=getattr(registry.project_meta, "project_name", request.project_id),
                git_repo=registry.git_config.repo_url,
                git_branch=registry.git_config.main_branch,
                base_commit_sha="0000000",
            ),
            task=Task(
                task_id=f"task_{request.project_id}",
                completed_summary="New task from UI",
                next_instructions=request.instructions,
            ),
        )

        import asyncio

        async def run_and_queue():
            if request.mock:
                from src.pipeline.demo_pipeline import DemoPipeline
                pipeline = DemoPipeline(
                    registry=registry,
                    mock=True,
                    scenario=request.scenario,
                    on_step=on_step,
                )
                result = await pipeline.run(initial_handoff)
                gate = result.gate
                final_handoff = result.handoff
            else:
                from src.orchestrator.orchestrator import Orchestrator
                orchestrator = Orchestrator()
                final_handoff = await orchestrator.process_handoff(initial_handoff, registry, on_step=on_step)
                gate = final_handoff.quality_gates.gate_decision

            # Human Gate 대상이면 Queue에 추가
            if gate in ["L2_HUMAN", "L3_HALT", "L4_DEPLOY"]:
                from src.dashboard.models import GateQueueItem
                self.add_gate_item(GateQueueItem(
                    handoff_id=final_handoff.envelope.handoff_id,
                    project_id=request.project_id,
                    gate_level=str(gate),
                    trigger_reason=final_handoff.human_gate_package.trigger_reason if final_handoff.human_gate_package else "N/A",
                    agent_role=final_handoff.envelope.from_agent,
                    review_score=final_handoff.quality_gates.review_score,
                ))

        asyncio.create_task(run_and_queue())

        return {
            "status": "started",
            "project_id": request.project_id,
            "task_id": initial_handoff.task.task_id,
        }

    # --- Projects ---

    async def list_projects(self) -> list[ProjectSummary]:
        """프로젝트 목록을 반환한다."""
        if not self._registry_store:
            return []

        projects: list[ProjectSummary] = []
        if hasattr(self._registry_store, "list_projects"):
            for pid in self._registry_store.list_projects():
                try:
                    reg = self._registry_store.load(pid)
                    projects.append(ProjectSummary(
                        project_id=pid,
                        project_name=getattr(reg, "project_name", pid),
                        status=getattr(reg, "status", "active"),
                        priority=getattr(reg, "priority", 0),
                    ))
                except Exception:
                    projects.append(ProjectSummary(project_id=pid))
        return projects

    async def get_project(self, project_id: str) -> ProjectSummary | None:
        """프로젝트 상세를 반환한다."""
        if not self._registry_store or not hasattr(self._registry_store, "load"):
            return None
        try:
            reg = self._registry_store.load(project_id)
            return ProjectSummary(
                project_id=project_id,
                project_name=getattr(reg, "project_name", project_id),
                status=getattr(reg, "status", "active"),
                priority=getattr(reg, "priority", 0),
            )
        except Exception:
            return None

    # --- Agents ---

    async def list_agents(self) -> list[AgentStatusResponse]:
        """에이전트 상태 목록을 반환한다."""
        agents: list[AgentStatusResponse] = []
        if not self._health_registry:
            return agents

        if hasattr(self._health_registry, "_monitors"):
            for role, monitor in self._health_registry._monitors.items():
                summary = monitor.get_summary()
                agents.append(AgentStatusResponse(
                    role=role,
                    health_status=summary.get("status", "unknown"),
                    consecutive_failures=summary.get("consecutive_failures", 0),
                    avg_latency_ms=summary.get("avg_latency_ms", 0.0),
                    total_executions=summary.get("total_checks", 0),
                ))
        return agents

    async def get_agent(self, role: str) -> AgentStatusResponse | None:
        """특정 에이전트 상태를 반환한다."""
        agents = await self.list_agents()
        for a in agents:
            if a.role == role:
                return a
        return None

    # --- Cost ---

    async def list_costs(self) -> list[CostSummary]:
        """프로젝트별 비용 요약을 반환한다."""
        costs: list[CostSummary] = []
        for project_id, tracker in self._token_budgets.items():
            if hasattr(tracker, "get_status"):
                status = tracker.get_status(project_id)
                costs.append(CostSummary(
                    project_id=project_id,
                    date=getattr(status, "date", ""),
                    daily_tokens_used=getattr(status, "daily_tokens_used", 0),
                    daily_token_limit=getattr(status, "daily_token_limit", 0),
                    total_cost_usd=getattr(status, "total_cost_usd", 0.0),
                    agent_breakdown=getattr(status, "agent_breakdown", {}),
                    usage_ratio=getattr(status, "usage_ratio", 0.0),
                ))
        return costs

    async def get_cost(self, project_id: str) -> CostSummary | None:
        """특정 프로젝트 비용을 반환한다."""
        if project_id in self._token_budgets:
            tracker = self._token_budgets[project_id]
            if hasattr(tracker, "get_status"):
                status = tracker.get_status(project_id)
                return CostSummary(
                    project_id=project_id,
                    date=getattr(status, "date", ""),
                    daily_tokens_used=getattr(status, "daily_tokens_used", 0),
                    daily_token_limit=getattr(status, "daily_token_limit", 0),
                    total_cost_usd=getattr(status, "total_cost_usd", 0.0),
                    usage_ratio=getattr(status, "usage_ratio", 0.0),
                )
        return None

    # --- Gates ---

    async def list_gate_queue(self) -> list[GateQueueItem]:
        """Human Gate 대기열을 반환한다."""
        return list(self._gate_queue)

    async def approve_gate(self, handoff_id: str) -> dict[str, str]:
        """Gate를 승인한다."""
        self._gate_queue = [g for g in self._gate_queue if g.handoff_id != handoff_id]
        _slog.info("gate_approved", handoff_id=handoff_id)
        return {"status": "approved", "handoff_id": handoff_id}

    async def reject_gate(self, handoff_id: str) -> dict[str, str]:
        """Gate를 거부한다."""
        self._gate_queue = [g for g in self._gate_queue if g.handoff_id != handoff_id]
        _slog.info("gate_rejected", handoff_id=handoff_id)
        return {"status": "rejected", "handoff_id": handoff_id}

    # --- Metrics ---

    async def get_metrics(self) -> dict[str, Any]:
        """파이프라인 메트릭을 반환한다."""
        if self._metrics_collector and hasattr(self._metrics_collector, "get_metrics"):
            metrics = self._metrics_collector.get_metrics()
            return metrics.model_dump()
        return {}

    def add_gate_item(self, item: GateQueueItem) -> None:
        """Gate 대기열에 항목을 추가한다."""
        self._gate_queue.append(item)
