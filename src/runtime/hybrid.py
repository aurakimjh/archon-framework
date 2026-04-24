"""Cloud Hybrid 관리 — 로컬/클라우드 GPU 리소스 스케줄링."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from enum import StrEnum

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


class HybridCloudManager:
    """로컬과 클라우드 GPU 리소스를 통합 관리한다."""

    def __init__(self, config: HybridConfig) -> None:
        self._config = config
        self._resources: list[GPUResource] = []
        self._cloud_spend_today: float = 0.0
        self._cloud_spend_monthly: float = 0.0
        self._local_utilization: float = 0.0
        self._last_reset_date: str = datetime.now(UTC).strftime("%Y-%m-%d")

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
        """사용 가능한 리소스 목록을 반환한다."""
        return [r for r in self._resources if r.available]

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
            self._cloud_spend_today = 0.0
            self._last_reset_date = today
