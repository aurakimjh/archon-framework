"""Cloud Hybrid 관리 — 로컬/클라우드 GPU 리소스 스케줄링."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from src.log import get_logger

logger = logging.getLogger(__name__)
_slog = get_logger(__name__)


class CloudProvider(StrEnum):
    """클라우드 프로바이더."""

    LOCAL = "local"
    AWS = "aws"
    GCP = "gcp"
    AZURE = "azure"


class SchedulingStrategy(StrEnum):
    """스케줄링 전략."""

    LOCAL_FIRST = "local_first"
    COST_OPTIMAL = "cost_optimal"
    PERFORMANCE = "performance"
    BALANCED = "balanced"


class PreemptionStrategy(StrEnum):
    """Spot preemption 발생 시 대응 전략."""

    MIGRATE = "migrate"       # 다른 리소스로 태스크 이전
    LOCAL_FALLBACK = "local_fallback"  # 로컬 리소스로 폴백
    REQUEUE = "requeue"       # 태스크를 큐에 다시 추가


class GPUResource(BaseModel):
    """GPU 리소스."""

    provider: CloudProvider
    worker_id: str
    gpu_model: str = ""
    gpu_count: int = 1
    cost_per_hour_usd: float = 0.0
    is_spot: bool = False
    region: str = ""
    available: bool = True
    latency_score: float = Field(default=1.0, ge=0.0, le=1.0)
    preempted: bool = False


class HybridConfig(BaseModel):
    """하이브리드 클라우드 설정."""

    strategy: SchedulingStrategy = SchedulingStrategy.LOCAL_FIRST
    local_gpu_capacity: int = 1
    cloud_budget_daily_usd: float = 50.0
    cloud_budget_monthly_usd: float = 1000.0
    prefer_spot: bool = True
    providers: list[CloudProvider] = Field(
        default_factory=lambda: [CloudProvider.LOCAL]
    )
    overflow_threshold: float = Field(default=0.8, ge=0.0, le=1.0)
    preemption_strategy: PreemptionStrategy = PreemptionStrategy.LOCAL_FALLBACK


class PreemptionEvent(BaseModel):
    """Spot preemption 이벤트."""

    worker_id: str
    task_id: str = ""
    reason: str = "spot_reclaimed"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PreemptionResult(BaseModel):
    """Preemption 처리 결과."""

    original_worker_id: str
    task_id: str
    strategy_used: PreemptionStrategy
    fallback_worker_id: str | None = None
    success: bool = False
    detail: str = ""


class HybridCloudManager:
    """로컬과 클라우드 GPU 리소스를 통합 관리한다."""

    def __init__(self, config: HybridConfig) -> None:
        self._config = config
        self._resources: list[GPUResource] = []
        self._cloud_spend_today: float = 0.0
        self._cloud_spend_monthly: float = 0.0
        self._local_utilization: float = 0.0
        self._last_reset_date: str = datetime.now(UTC).strftime("%Y-%m-%d")
        self._active_tasks: dict[str, str] = {}  # task_id → worker_id
        self._preemption_history: list[PreemptionResult] = []
        self._on_preemption_callbacks: list[Any] = []

    @property
    def config(self) -> HybridConfig:
        return self._config

    def register_resource(self, resource: GPUResource) -> None:
        """GPU 리소스를 등록한다."""
        self._resources.append(resource)
        _slog.debug("resource_registered", worker_id=resource.worker_id, provider=resource.provider)

    def unregister_resource(self, worker_id: str) -> bool:
        """GPU 리소스를 해제한다."""
        before = len(self._resources)
        self._resources = [r for r in self._resources if r.worker_id != worker_id]
        return len(self._resources) < before

    def get_available_resources(self) -> list[GPUResource]:
        """사용 가능한 리소스 목록을 반환한다 (preempted 제외)."""
        return [r for r in self._resources if r.available and not r.preempted]

    def get_local_utilization(self) -> float:
        """로컬 GPU 사용률을 반환한다."""
        return self._local_utilization

    def set_local_utilization(self, value: float) -> None:
        """로컬 GPU 사용률을 설정한다."""
        self._local_utilization = max(0.0, min(1.0, value))

    def get_cloud_spend_today(self) -> float:
        """오늘 클라우드 지출을 반환한다."""
        self._check_date_reset()
        return self._cloud_spend_today

    def check_budget(self) -> bool:
        """예산 내인지 확인한다."""
        self._check_date_reset()
        return (
            self._cloud_spend_today < self._config.cloud_budget_daily_usd
            and self._cloud_spend_monthly < self._config.cloud_budget_monthly_usd
        )

    def record_cloud_usage(self, resource: GPUResource, duration_hours: float) -> float:
        """클라우드 사용량을 기록한다.

        Returns:
            기록된 비용.
        """
        cost = resource.cost_per_hour_usd * duration_hours
        self._cloud_spend_today += cost
        self._cloud_spend_monthly += cost
        _slog.info(
            "cloud_usage_recorded",
            worker_id=resource.worker_id,
            cost_usd=round(cost, 4),
            daily_total=round(self._cloud_spend_today, 2),
        )
        return cost

    async def schedule_task(
        self,
        task_id: str,
        role: str,
        estimated_gpu_hours: float = 0.1,
    ) -> GPUResource | None:
        """태스크에 최적 리소스를 할당한다."""
        available = self.get_available_resources()
        if not available:
            _slog.warning("no_resources_available", task_id=task_id)
            return None

        scored = [
            (r, self._score_resource(r, estimated_gpu_hours))
            for r in available
        ]
        scored.sort(key=lambda x: x[1], reverse=True)

        best_resource, best_score = scored[0]

        # 클라우드 리소스인 경우 예산 확인
        if best_resource.provider != CloudProvider.LOCAL and not self.check_budget():
            # 예산 초과 시 로컬만 사용 시도
            local = [r for r, _ in scored if r.provider == CloudProvider.LOCAL]
            if local:
                best_resource = local[0]
            else:
                _slog.warning("cloud_budget_exceeded", task_id=task_id)
                return None

        self._active_tasks[task_id] = best_resource.worker_id
        _slog.info(
            "task_scheduled",
            task_id=task_id,
            worker_id=best_resource.worker_id,
            provider=best_resource.provider,
            score=round(best_score, 4),
        )
        return best_resource

    def _score_resource(self, resource: GPUResource, estimated_hours: float) -> float:
        """리소스 점수를 계산한다 (높을수록 좋음)."""
        strategy = self._config.strategy

        if strategy == SchedulingStrategy.LOCAL_FIRST:
            local_bonus = 0.5 if resource.provider == CloudProvider.LOCAL else 0.0
            cost_penalty = resource.cost_per_hour_usd * estimated_hours / 10
            return 1.0 + local_bonus - cost_penalty

        if strategy == SchedulingStrategy.COST_OPTIMAL:
            cost = resource.cost_per_hour_usd * estimated_hours
            spot_bonus = 0.1 if resource.is_spot else 0.0
            return 1.0 - (cost / 10) + spot_bonus

        if strategy == SchedulingStrategy.PERFORMANCE:
            return resource.latency_score + (resource.gpu_count * 0.1)

        # BALANCED
        cost_score = 1.0 - (resource.cost_per_hour_usd * estimated_hours / 10)
        local_bonus = 0.2 if resource.provider == CloudProvider.LOCAL else 0.0
        return (cost_score + resource.latency_score + local_bonus) / 2

    def get_summary(self) -> dict[str, object]:
        """리소스 요약을 반환한다."""
        return {
            "total_resources": len(self._resources),
            "available_resources": len(self.get_available_resources()),
            "local_utilization": self._local_utilization,
            "cloud_spend_today": round(self._cloud_spend_today, 2),
            "cloud_spend_monthly": round(self._cloud_spend_monthly, 2),
            "budget_ok": self.check_budget(),
            "strategy": str(self._config.strategy),
        }

    def _check_date_reset(self) -> None:
        """날짜가 바뀌면 일일 지출을 리셋한다."""
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        if today != self._last_reset_date:
            _slog.info(
                "daily_budget_reset",
                prev_date=self._last_reset_date,
                new_date=today,
                prev_spend=round(self._cloud_spend_today, 2),
            )
            self._cloud_spend_today = 0.0
            self._last_reset_date = today

    # --- 백그라운드 예산 리셋 스케줄러 ---

    async def start_budget_scheduler(self, interval_seconds: int = 3600) -> None:
        """백그라운드에서 주기적으로 일일 예산을 리셋한다.

        장기간 schedule_task() 호출이 없어도 날짜가 바뀌면
        일일 지출이 자동으로 초기화된다.

        Args:
            interval_seconds: 체크 주기 (초). 기본 1시간.
        """
        self._scheduler_running = True
        _slog.info("budget_scheduler_started", interval_seconds=interval_seconds)
        while self._scheduler_running:
            self._check_date_reset()
            await asyncio.sleep(interval_seconds)

    def stop_budget_scheduler(self) -> None:
        """백그라운드 예산 스케줄러를 중지한다."""
        self._scheduler_running = False
        _slog.info("budget_scheduler_stopped")

    # --- 태스크 트래킹 ---

    def register_task(self, task_id: str, worker_id: str) -> None:
        """실행 중인 태스크를 등록한다."""
        self._active_tasks[task_id] = worker_id

    def unregister_task(self, task_id: str) -> bool:
        """완료된 태스크를 해제한다."""
        return self._active_tasks.pop(task_id, None) is not None

    def get_active_tasks(self) -> dict[str, str]:
        """활성 태스크 맵을 반환한다 (task_id → worker_id)."""
        return dict(self._active_tasks)

    # --- Spot Preemption 대응 ---

    def on_preemption(self, callback: Callable[[PreemptionResult], Any]) -> None:
        """Preemption 이벤트 콜백을 등록한다."""
        self._on_preemption_callbacks.append(callback)

    async def handle_preemption(self, event: PreemptionEvent) -> PreemptionResult:
        """Spot preemption 이벤트를 처리한다.

        1. 해당 worker를 preempted로 마킹
        2. 설정된 전략에 따라 대응 (MIGRATE / LOCAL_FALLBACK / REQUEUE)
        3. 결과를 히스토리에 기록하고 콜백 호출

        Args:
            event: Preemption 이벤트 정보.

        Returns:
            처리 결과.
        """
        strategy = self._config.preemption_strategy

        # 워커를 preempted로 마킹
        for r in self._resources:
            if r.worker_id == event.worker_id:
                r.preempted = True
                r.available = False
                break

        # 해당 워커에서 실행 중인 태스크 식별
        affected_tasks = [
            tid for tid, wid in self._active_tasks.items()
            if wid == event.worker_id
        ]
        task_id = event.task_id or (affected_tasks[0] if affected_tasks else "")

        _slog.warning(
            "preemption_detected",
            worker_id=event.worker_id,
            task_id=task_id,
            strategy=strategy,
            reason=event.reason,
        )

        result: PreemptionResult

        if strategy == PreemptionStrategy.MIGRATE:
            result = await self._handle_migrate(event.worker_id, task_id)
        elif strategy == PreemptionStrategy.LOCAL_FALLBACK:
            result = await self._handle_local_fallback(event.worker_id, task_id)
        else:  # REQUEUE
            result = self._handle_requeue(event.worker_id, task_id)

        self._preemption_history.append(result)

        # 콜백 호출
        for cb in self._on_preemption_callbacks:
            try:
                ret = cb(result)
                if asyncio.iscoroutine(ret):
                    await ret
            except Exception:
                _slog.exception("preemption_callback_error")

        return result

    async def _handle_migrate(self, worker_id: str, task_id: str) -> PreemptionResult:
        """다른 사용 가능한 리소스(클라우드 포함)로 태스크를 이전한다."""
        fallback = self._find_fallback_resource(worker_id, local_only=False)
        if fallback:
            if task_id:
                self._active_tasks[task_id] = fallback.worker_id
            return PreemptionResult(
                original_worker_id=worker_id,
                task_id=task_id,
                strategy_used=PreemptionStrategy.MIGRATE,
                fallback_worker_id=fallback.worker_id,
                success=True,
                detail=f"Migrated to {fallback.worker_id} ({fallback.provider})",
            )
        return PreemptionResult(
            original_worker_id=worker_id,
            task_id=task_id,
            strategy_used=PreemptionStrategy.MIGRATE,
            success=False,
            detail="No available resource for migration",
        )

    async def _handle_local_fallback(self, worker_id: str, task_id: str) -> PreemptionResult:
        """로컬 리소스로 폴백한다."""
        fallback = self._find_fallback_resource(worker_id, local_only=True)
        if fallback:
            if task_id:
                self._active_tasks[task_id] = fallback.worker_id
            return PreemptionResult(
                original_worker_id=worker_id,
                task_id=task_id,
                strategy_used=PreemptionStrategy.LOCAL_FALLBACK,
                fallback_worker_id=fallback.worker_id,
                success=True,
                detail=f"Fell back to local {fallback.worker_id}",
            )
        return PreemptionResult(
            original_worker_id=worker_id,
            task_id=task_id,
            strategy_used=PreemptionStrategy.LOCAL_FALLBACK,
            success=False,
            detail="No local resource available for fallback",
        )

    def _handle_requeue(self, worker_id: str, task_id: str) -> PreemptionResult:
        """태스크를 큐에 다시 추가한다 (active_tasks에서 제거)."""
        if task_id:
            self._active_tasks.pop(task_id, None)
        return PreemptionResult(
            original_worker_id=worker_id,
            task_id=task_id,
            strategy_used=PreemptionStrategy.REQUEUE,
            success=True,
            detail="Task requeued for rescheduling",
        )

    def _find_fallback_resource(
        self, exclude_worker_id: str, *, local_only: bool = False
    ) -> GPUResource | None:
        """폴백 가능한 리소스를 찾는다."""
        candidates = [
            r for r in self._resources
            if r.worker_id != exclude_worker_id
            and r.available
            and not r.preempted
        ]
        if local_only:
            candidates = [r for r in candidates if r.provider == CloudProvider.LOCAL]

        if not candidates:
            return None

        # latency_score 기준 최적 리소스 선택
        return max(candidates, key=lambda r: r.latency_score)

    def get_preemption_history(self) -> list[PreemptionResult]:
        """Preemption 처리 히스토리를 반환한다."""
        return list(self._preemption_history)

    def recover_worker(self, worker_id: str) -> bool:
        """Preempted 워커를 다시 사용 가능하게 복구한다."""
        for r in self._resources:
            if r.worker_id == worker_id:
                r.preempted = False
                r.available = True
                _slog.info("worker_recovered", worker_id=worker_id)
                return True
        return False
