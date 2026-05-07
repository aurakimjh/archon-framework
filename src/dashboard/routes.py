"""Dashboard REST API 라우트."""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Awaitable, Callable

from src.dashboard.models import (
    AgentStatusResponse,
    CostSummary,
    GateQueueItem,
    ProjectSummary,
    TaskRequest,
)
from src.dashboard.notifications import fire_and_forget
from src.dashboard.persistence import (
    BudgetStatus,
    BudgetThreshold,
    DashboardStore,
    GateRecord,
    GateStatus,
    NotificationEvent,
    TaskRecord,
    TaskStatus,
    TimeseriesPoint,
    UsageEvent,
    UsageSummary,
)
from src.dashboard.pricing import calc_cost
from src.log import get_logger

logger = logging.getLogger(__name__)
_slog = get_logger(__name__)

EventCallback = Callable[[str, dict[str, Any]], Awaitable[None]]


class DashboardRoutes:
    """Dashboard API 핸들러.

    FastAPI 없이도 동작하며, FastAPI router에 마운트할 수 있다.
    영속화: store 인자가 있으면 SQLite로 task/gate를 저장. 없으면 in-memory(레거시).
    """

    def __init__(
        self,
        registry_store: Any = None,
        health_registry: Any = None,
        token_budgets: dict[str, Any] | None = None,
        metrics_collector: Any = None,
        gate_queue: list[GateQueueItem] | None = None,
        store: DashboardStore | None = None,
        on_event: EventCallback | None = None,
    ) -> None:
        self._registry_store = registry_store
        self._health_registry = health_registry
        self._token_budgets = token_budgets or {}
        self._metrics_collector = metrics_collector
        self._gate_queue: list[GateQueueItem] = gate_queue or []
        self._store = store
        self._on_event = on_event
        self._running_tasks: dict[str, asyncio.Task[Any]] = {}
        # 예산 초과 알림 중복 방지 — (threshold_id, period_key) 키.
        self._notified_budgets: set[tuple[int, str]] = set()

    # ---------------- Tasks ----------------

    async def run_task(
        self,
        request: TaskRequest,
        on_step: Callable[[str, Any], None] | None = None,
    ) -> dict[str, Any]:
        """새 작업을 등록·시작한다. 영속화 store가 있으면 라이프사이클을 추적한다."""
        from src.orchestrator.handoff import (
            Envelope,
            HandoffArtifact,
            ProjectContext,
            Task,
        )
        from src.registry.models import GitConfig, ProjectMeta, ProjectRegistry

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

        handoff_id = f"hf_ui_{request.project_id}_{uuid.uuid4().hex[:8]}"
        task_id = f"task_{request.project_id}_{uuid.uuid4().hex[:8]}"
        initial_handoff = HandoffArtifact(
            envelope=Envelope(
                handoff_id=handoff_id,
                from_agent="user",
                to_agent=request.agent_role,
            ),
            project_context=ProjectContext(
                project_id=request.project_id,
                project_name=getattr(
                    registry.project_meta, "project_name", request.project_id
                ),
                git_repo=registry.git_config.repo_url,
                git_branch=registry.git_config.main_branch,
                base_commit_sha="0000000",
            ),
            task=Task(
                task_id=task_id,
                completed_summary="New task from UI",
                next_instructions=request.instructions,
            ),
        )

        if self._store:
            self._store.tasks.create(
                task_id=task_id,
                project_id=request.project_id,
                agent_role=request.agent_role,
                instructions=request.instructions,
                handoff_id=handoff_id,
                metadata={"mock": request.mock, "scenario": request.scenario},
            )
            await self._emit("task_created", {"task_id": task_id})

        async def run_and_persist() -> None:
            try:
                if self._store:
                    self._store.tasks.transition(task_id, status=TaskStatus.RUNNING)
                    await self._emit(
                        "task_status_changed",
                        {"task_id": task_id, "status": "running"},
                    )

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
                    final_handoff = await orchestrator.process_handoff(
                        initial_handoff, registry, on_step=on_step
                    )
                    gate = final_handoff.quality_gates.gate_decision

                gate_str = str(gate)
                review_score = final_handoff.quality_gates.review_score

                if gate_str in {"L2_HUMAN", "L3_HALT", "L4_DEPLOY"}:
                    self._enqueue_gate(
                        handoff_id=final_handoff.envelope.handoff_id,
                        project_id=request.project_id,
                        gate_level=gate_str,
                        trigger_reason=(
                            final_handoff.human_gate_package.trigger_reason
                            if final_handoff.human_gate_package
                            else "N/A"
                        ),
                        agent_role=final_handoff.envelope.from_agent,
                        review_score=review_score,
                    )
                    await self._emit(
                        "gate_enqueued",
                        {
                            "handoff_id": final_handoff.envelope.handoff_id,
                            "gate_level": gate_str,
                            "project_id": request.project_id,
                        },
                    )

                if self._store:
                    final_status = (
                        TaskStatus.SUCCEEDED
                        if gate_str in {"AUTO_PASS", "L4_DEPLOY"}
                        else TaskStatus.FAILED
                        if gate_str == "L3_HALT"
                        else TaskStatus.SUCCEEDED  # L1/L2은 Human 처리 후 종료, 일단 succeeded
                    )
                    self._store.tasks.transition(
                        task_id,
                        status=final_status,
                        gate_decision=gate_str,
                        review_score=review_score,
                    )
                    await self._emit(
                        "task_status_changed",
                        {
                            "task_id": task_id,
                            "status": final_status.value,
                            "gate": gate_str,
                        },
                    )

            except asyncio.CancelledError:
                if self._store:
                    self._store.tasks.transition(
                        task_id, status=TaskStatus.CANCELLED, cancelled_by="user"
                    )
                    await self._emit(
                        "task_status_changed",
                        {"task_id": task_id, "status": "cancelled"},
                    )
                raise
            except Exception as exc:
                _slog.exception("task_failed", task_id=task_id)
                if self._store:
                    self._store.tasks.transition(
                        task_id, status=TaskStatus.FAILED, error=str(exc)[:500]
                    )
                    await self._emit(
                        "task_status_changed",
                        {"task_id": task_id, "status": "failed", "error": str(exc)[:200]},
                    )
            finally:
                self._running_tasks.pop(task_id, None)

        loop_task = asyncio.create_task(run_and_persist())
        self._running_tasks[task_id] = loop_task

        return {
            "status": "started",
            "project_id": request.project_id,
            "task_id": task_id,
            "handoff_id": handoff_id,
        }

    async def list_tasks(
        self,
        *,
        status: str | None = None,
        project_id: str | None = None,
        active_only: bool = False,
        limit: int = 100,
    ) -> list[TaskRecord]:
        if not self._store:
            return []
        return self._store.tasks.list(
            status=status,
            project_id=project_id,
            active_only=active_only,
            limit=limit,
        )

    async def get_task(self, task_id: str) -> TaskRecord | None:
        if not self._store:
            return None
        return self._store.tasks.get(task_id)

    async def cancel_task(self, task_id: str, reason: str | None = None) -> dict[str, Any]:
        running = self._running_tasks.pop(task_id, None)
        if running and not running.done():
            running.cancel()
            try:
                await running
            except (asyncio.CancelledError, Exception):
                pass

        if self._store:
            updated = self._store.tasks.transition(
                task_id,
                status=TaskStatus.CANCELLED,
                cancelled_by=reason or "user",
            )
            if updated is None:
                return {"status": "not_found", "task_id": task_id}
            return {"status": "cancelled", "task_id": task_id}

        return {"status": "cancelled", "task_id": task_id}

    # ---------------- Projects ----------------

    async def list_projects(self) -> list[ProjectSummary]:
        if not self._registry_store:
            return []
        projects: list[ProjectSummary] = []
        if hasattr(self._registry_store, "list_projects"):
            for pid in self._registry_store.list_projects():
                try:
                    reg = self._registry_store.load(pid)
                    projects.append(
                        ProjectSummary(
                            project_id=pid,
                            project_name=getattr(reg, "project_name", pid),
                            status=getattr(reg, "status", "active"),
                            priority=getattr(reg, "priority", 0),
                        )
                    )
                except Exception:
                    projects.append(ProjectSummary(project_id=pid))
        return projects

    async def get_project(self, project_id: str) -> ProjectSummary | None:
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

    async def project_timeline(
        self, project_id: str, *, limit: int = 50
    ) -> list[dict[str, Any]]:
        """tasks + gates를 시간순으로 결합한 프로젝트 타임라인."""
        if not self._store:
            return []

        items: list[dict[str, Any]] = []
        for t in self._store.tasks.list(project_id=project_id, limit=limit):
            items.append(
                {
                    "kind": "task",
                    "timestamp": t.created_at,
                    "id": t.id,
                    "status": t.status.value,
                    "agent_role": t.agent_role,
                    "instructions": t.instructions[:200],
                    "gate_decision": t.gate_decision,
                    "review_score": t.review_score,
                    "started_at": t.started_at,
                    "completed_at": t.completed_at,
                }
            )
        for g in self._store.gates.list(status=None, project_id=project_id, limit=limit):
            items.append(
                {
                    "kind": "gate",
                    "timestamp": g.created_at,
                    "id": g.handoff_id,
                    "status": g.status.value,
                    "agent_role": g.agent_role,
                    "gate_level": g.gate_level,
                    "review_score": g.review_score,
                    "decided_at": g.decided_at,
                    "decided_by": g.decided_by,
                }
            )
        items.sort(key=lambda x: x["timestamp"], reverse=True)
        return items[:limit]

    async def project_memory_search(
        self, project_id: str, *, q: str, limit: int = 20
    ) -> dict[str, Any]:
        """선택적 — 메모리 모듈이 가용하면 검색하고, 아니면 빈 결과 반환."""
        try:
            from src.memory.mem0_store import Mem0Store  # type: ignore[import-not-found]
        except Exception:
            return {"available": False, "results": []}

        try:
            store = Mem0Store(user_id=project_id)
            results = store.search(query=q, limit=limit) or []
        except Exception as exc:  # noqa: BLE001
            return {"available": False, "error": str(exc)[:200], "results": []}

        # mem0 결과 형태가 다양하므로 일관된 dict로 변환.
        normalized: list[dict[str, Any]] = []
        for r in results:
            if isinstance(r, dict):
                normalized.append(
                    {
                        "memory": str(r.get("memory") or r.get("text") or ""),
                        "score": float(r.get("score") or 0.0),
                        "metadata": r.get("metadata") or {},
                    }
                )
            else:
                normalized.append({"memory": str(r), "score": 0.0, "metadata": {}})
        return {"available": True, "results": normalized}

    # ---------------- Agents ----------------

    async def list_agents(self) -> list[AgentStatusResponse]:
        agents: list[AgentStatusResponse] = []
        if not self._health_registry:
            return agents
        if hasattr(self._health_registry, "_monitors"):
            for role, monitor in self._health_registry._monitors.items():
                summary = monitor.get_summary()
                agents.append(
                    AgentStatusResponse(
                        role=role,
                        health_status=summary.get("status", "unknown"),
                        consecutive_failures=summary.get("consecutive_failures", 0),
                        avg_latency_ms=summary.get("avg_latency_ms", 0.0),
                        total_executions=summary.get("total_checks", 0),
                    )
                )
        return agents

    async def get_agent(self, role: str) -> AgentStatusResponse | None:
        for a in await self.list_agents():
            if a.role == role:
                return a
        return None

    # ---------------- Cost ----------------

    async def list_costs(self) -> list[CostSummary]:
        costs: list[CostSummary] = []
        for project_id, tracker in self._token_budgets.items():
            if hasattr(tracker, "get_status"):
                status = tracker.get_status(project_id)
                costs.append(
                    CostSummary(
                        project_id=project_id,
                        date=getattr(status, "date", ""),
                        daily_tokens_used=getattr(status, "daily_tokens_used", 0),
                        daily_token_limit=getattr(status, "daily_token_limit", 0),
                        total_cost_usd=getattr(status, "total_cost_usd", 0.0),
                        agent_breakdown=getattr(status, "agent_breakdown", {}),
                        usage_ratio=getattr(status, "usage_ratio", 0.0),
                    )
                )
        return costs

    async def get_cost(self, project_id: str) -> CostSummary | None:
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

    # ---------------- Gates ----------------

    async def list_gate_queue(self) -> list[GateQueueItem]:
        if self._store:
            return [
                _gate_record_to_item(g)
                for g in self._store.gates.list(status=GateStatus.PENDING)
            ]
        return list(self._gate_queue)

    async def get_gate(self, handoff_id: str) -> GateRecord | None:
        if self._store:
            return self._store.gates.get(handoff_id)
        for g in self._gate_queue:
            if g.handoff_id == handoff_id:
                return GateRecord(
                    handoff_id=g.handoff_id,
                    project_id=g.project_id,
                    gate_level=g.gate_level,
                    trigger_reason=g.trigger_reason,
                    agent_role=g.agent_role,
                    review_score=g.review_score,
                    payload={},
                    created_at=g.created_at.isoformat(),
                )
        return None

    async def approve_gate(
        self,
        handoff_id: str,
        comment: str | None = None,
        reviewer: str | None = None,
    ) -> dict[str, Any]:
        if self._store:
            record = self._store.gates.decide(
                handoff_id,
                status=GateStatus.APPROVED,
                comment=comment,
                decided_by=reviewer,
            )
            if record is None:
                return {"status": "not_found", "handoff_id": handoff_id}
            _slog.info("gate_approved", handoff_id=handoff_id)
            return {
                "status": "approved",
                "handoff_id": handoff_id,
                "comment": comment,
                "decided_by": reviewer,
            }
        # 레거시 in-memory 경로
        self._gate_queue = [g for g in self._gate_queue if g.handoff_id != handoff_id]
        _slog.info("gate_approved", handoff_id=handoff_id)
        return {"status": "approved", "handoff_id": handoff_id}

    async def reject_gate(
        self,
        handoff_id: str,
        comment: str | None = None,
        reviewer: str | None = None,
    ) -> dict[str, Any]:
        if self._store:
            record = self._store.gates.decide(
                handoff_id,
                status=GateStatus.REJECTED,
                comment=comment,
                decided_by=reviewer,
            )
            if record is None:
                return {"status": "not_found", "handoff_id": handoff_id}
            _slog.info("gate_rejected", handoff_id=handoff_id)
            return {
                "status": "rejected",
                "handoff_id": handoff_id,
                "comment": comment,
                "decided_by": reviewer,
            }
        self._gate_queue = [g for g in self._gate_queue if g.handoff_id != handoff_id]
        _slog.info("gate_rejected", handoff_id=handoff_id)
        return {"status": "rejected", "handoff_id": handoff_id}

    # ---------------- Usage / Cost ----------------

    async def record_usage(
        self,
        *,
        project_id: str | None,
        agent_role: str | None,
        model: str | None,
        tokens_in: int,
        tokens_out: int,
        task_id: str | None = None,
        cost_usd: float | None = None,
        timestamp: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> UsageEvent | None:
        if not self._store:
            return None
        cost = (
            cost_usd
            if cost_usd is not None
            else calc_cost(model, tokens_in, tokens_out)
        )
        event = self._store.usage.record_event(
            timestamp=timestamp,
            project_id=project_id,
            agent_role=agent_role,
            model=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost,
            task_id=task_id,
            metadata=metadata,
        )
        await self._check_budget_alerts()
        return event

    async def _check_budget_alerts(self) -> None:
        """현재 예산 상태를 점검하여 처음 exceeded 진입한 임계치에 알림 발송."""
        if not self._store:
            return
        from datetime import UTC, datetime as _dt

        statuses = self._store.budgets.status()
        now = _dt.now(UTC)
        for s in statuses:
            if not s.exceeded or s.threshold.id is None:
                continue
            period_key = (
                now.strftime("%Y-%m-%d")
                if s.threshold.period.value == "daily"
                else now.strftime("%Y-%m")
            )
            key = (s.threshold.id, period_key)
            if key in self._notified_budgets:
                continue
            self._notified_budgets.add(key)
            fire_and_forget(
                event=NotificationEvent.BUDGET_EXCEEDED,
                payload={
                    "scope": s.threshold.scope,
                    "period": s.threshold.period.value,
                    "limit_usd": s.threshold.limit_usd,
                    "used_usd": round(s.used_usd, 2),
                    "ratio": round(s.usage_ratio, 3),
                },
                store=self._store.notifications,
            )

    async def query_timeseries(
        self,
        *,
        period: str = "daily",
        start: str | None = None,
        end: str | None = None,
        group_by: str = "none",
        project_id: str | None = None,
    ) -> list[TimeseriesPoint]:
        if not self._store:
            return []
        return self._store.usage.query_timeseries(
            period=period,
            start=start,
            end=end,
            group_by=group_by,
            project_id=project_id,
        )

    async def get_usage_summary(self) -> UsageSummary:
        if not self._store:
            return UsageSummary()
        return self._store.usage.get_summary()

    async def list_budgets(self) -> list[BudgetThreshold]:
        if not self._store:
            return []
        return self._store.budgets.list()

    async def upsert_budget(self, t: BudgetThreshold) -> BudgetThreshold:
        if not self._store:
            raise RuntimeError("store is not configured")
        return self._store.budgets.upsert(t)

    async def delete_budget(self, threshold_id: int) -> bool:
        if not self._store:
            return False
        return self._store.budgets.delete(threshold_id)

    async def budget_status(self) -> list[BudgetStatus]:
        if not self._store:
            return []
        return self._store.budgets.status()

    async def seed_usage(
        self, *, days: int = 14, events_per_day: int = 24
    ) -> int:
        """dev/demo용 — 무작위 시드 이벤트를 채운다."""
        if not self._store:
            return 0
        import random
        from datetime import UTC, datetime, timedelta

        roles = ["backend", "frontend", "tester", "devops", "docs", "reviewer"]
        models = [
            "claude-opus-4-7",
            "claude-sonnet-4-6",
            "claude-haiku-4-5-20251001",
            "gpt-4o",
            "gpt-4o-mini",
        ]
        projects = ["demo-shop", "demo-blog", "demo-infra"]

        end = datetime.now(UTC)
        rng = random.Random(42)  # 재현 가능한 시드.
        count = 0
        for d in range(days):
            day = end - timedelta(days=d)
            for _ in range(events_per_day):
                ts = day.replace(
                    hour=rng.randint(0, 23),
                    minute=rng.randint(0, 59),
                    second=rng.randint(0, 59),
                ).isoformat()
                model = rng.choice(models)
                tokens_in = rng.randint(500, 8000)
                tokens_out = rng.randint(100, 4000)
                self._store.usage.record_event(
                    timestamp=ts,
                    project_id=rng.choice(projects),
                    agent_role=rng.choice(roles),
                    model=model,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    cost_usd=calc_cost(model, tokens_in, tokens_out),
                )
                count += 1
        return count

    # ---------------- Metrics ----------------

    async def get_metrics(self) -> dict[str, Any]:
        if self._metrics_collector and hasattr(self._metrics_collector, "get_metrics"):
            metrics = self._metrics_collector.get_metrics()
            return metrics.model_dump()
        return {}

    def add_gate_item(self, item: GateQueueItem) -> None:
        """레거시 in-memory 경로에서 사용하는 헬퍼."""
        self._gate_queue.append(item)

    # ---------------- internal helpers ----------------

    def _enqueue_gate(
        self,
        *,
        handoff_id: str,
        project_id: str,
        gate_level: str,
        trigger_reason: str,
        agent_role: str,
        review_score: int | None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        if self._store:
            self._store.gates.enqueue(
                handoff_id=handoff_id,
                project_id=project_id,
                gate_level=gate_level,
                trigger_reason=trigger_reason,
                agent_role=agent_role,
                review_score=review_score,
                payload=payload or {},
            )
            fire_and_forget(
                event=NotificationEvent.GATE_ENQUEUED,
                payload={
                    "handoff_id": handoff_id,
                    "project_id": project_id,
                    "gate_level": gate_level,
                    "agent_role": agent_role,
                    "review_score": review_score,
                    "trigger_reason": trigger_reason,
                },
                store=self._store.notifications,
            )
            return
        self._gate_queue.append(
            GateQueueItem(
                handoff_id=handoff_id,
                project_id=project_id,
                gate_level=gate_level,
                trigger_reason=trigger_reason,
                agent_role=agent_role,
                review_score=review_score,
            )
        )

    async def _emit(self, event_type: str, payload: dict[str, Any]) -> None:
        if self._on_event is None:
            return
        try:
            await self._on_event(event_type, payload)
        except Exception:
            logger.exception("on_event callback failed")


def _gate_record_to_item(g: GateRecord) -> GateQueueItem:
    """저장 모델 → API 응답 모델."""
    from datetime import datetime

    return GateQueueItem(
        handoff_id=g.handoff_id,
        project_id=g.project_id,
        gate_level=g.gate_level,
        trigger_reason=g.trigger_reason,
        created_at=datetime.fromisoformat(g.created_at),
        agent_role=g.agent_role,
        review_score=g.review_score,
    )
