"""Cloud Hybrid 모듈 테스트 — 리소스 관리, 스케줄링, 예산."""

from __future__ import annotations

import pytest

from src.runtime.hybrid import (
    CloudProvider,
    GPUResource,
    HybridCloudManager,
    HybridConfig,
    PreemptionEvent,
    PreemptionResult,
    PreemptionStrategy,
    SchedulingStrategy,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _local_gpu(**kwargs) -> GPUResource:
    defaults = {
        "provider": CloudProvider.LOCAL,
        "worker_id": "local-0",
        "gpu_model": "RTX 4090",
        "cost_per_hour_usd": 0.0,
        "latency_score": 1.0,
    }
    defaults.update(kwargs)
    return GPUResource(**defaults)


def _cloud_gpu(**kwargs) -> GPUResource:
    defaults = {
        "provider": CloudProvider.AWS,
        "worker_id": "aws-0",
        "gpu_model": "A100",
        "cost_per_hour_usd": 3.0,
        "is_spot": False,
        "latency_score": 0.7,
    }
    defaults.update(kwargs)
    return GPUResource(**defaults)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class TestHybridConfig:
    def test_defaults(self):
        cfg = HybridConfig()
        assert cfg.strategy == SchedulingStrategy.LOCAL_FIRST
        assert cfg.local_gpu_capacity == 1
        assert cfg.cloud_budget_daily_usd == 50.0
        assert cfg.overflow_threshold == 0.8

    def test_custom_strategy(self):
        cfg = HybridConfig(strategy=SchedulingStrategy.COST_OPTIMAL)
        assert cfg.strategy == SchedulingStrategy.COST_OPTIMAL

    def test_providers(self):
        cfg = HybridConfig(providers=[CloudProvider.LOCAL, CloudProvider.AWS])
        assert len(cfg.providers) == 2


class TestGPUResource:
    def test_local(self):
        r = _local_gpu()
        assert r.provider == CloudProvider.LOCAL
        assert r.cost_per_hour_usd == 0.0

    def test_cloud(self):
        r = _cloud_gpu()
        assert r.provider == CloudProvider.AWS
        assert r.cost_per_hour_usd == 3.0


# ---------------------------------------------------------------------------
# HybridCloudManager
# ---------------------------------------------------------------------------


class TestHybridCloudManager:
    def test_register_and_list(self):
        mgr = HybridCloudManager(HybridConfig())
        mgr.register_resource(_local_gpu())
        mgr.register_resource(_cloud_gpu())
        assert len(mgr.get_available_resources()) == 2

    def test_unregister(self):
        mgr = HybridCloudManager(HybridConfig())
        mgr.register_resource(_local_gpu(worker_id="l1"))
        assert mgr.unregister_resource("l1") is True
        assert mgr.unregister_resource("unknown") is False
        assert len(mgr.get_available_resources()) == 0

    def test_unavailable_filtered(self):
        mgr = HybridCloudManager(HybridConfig())
        mgr.register_resource(_local_gpu(available=True))
        mgr.register_resource(_cloud_gpu(available=False))
        assert len(mgr.get_available_resources()) == 1


class TestScheduling:
    @pytest.mark.asyncio
    async def test_local_first_prefers_local(self):
        mgr = HybridCloudManager(HybridConfig(strategy=SchedulingStrategy.LOCAL_FIRST))
        mgr.register_resource(_local_gpu())
        mgr.register_resource(_cloud_gpu())
        result = await mgr.schedule_task("t1", "backend")
        assert result is not None
        assert result.provider == CloudProvider.LOCAL

    @pytest.mark.asyncio
    async def test_cost_optimal_prefers_cheapest(self):
        mgr = HybridCloudManager(HybridConfig(strategy=SchedulingStrategy.COST_OPTIMAL))
        mgr.register_resource(_local_gpu(cost_per_hour_usd=0.0))
        mgr.register_resource(_cloud_gpu(cost_per_hour_usd=0.5))
        result = await mgr.schedule_task("t1", "backend")
        assert result is not None
        assert result.cost_per_hour_usd == 0.0

    @pytest.mark.asyncio
    async def test_performance_prefers_fast(self):
        mgr = HybridCloudManager(HybridConfig(strategy=SchedulingStrategy.PERFORMANCE))
        mgr.register_resource(_local_gpu(latency_score=0.5))
        mgr.register_resource(_cloud_gpu(latency_score=0.9, gpu_count=4))
        result = await mgr.schedule_task("t1", "backend")
        assert result is not None
        assert result.latency_score >= 0.9

    @pytest.mark.asyncio
    async def test_balanced_strategy(self):
        mgr = HybridCloudManager(HybridConfig(strategy=SchedulingStrategy.BALANCED))
        mgr.register_resource(_local_gpu())
        mgr.register_resource(_cloud_gpu())
        result = await mgr.schedule_task("t1", "backend")
        assert result is not None

    @pytest.mark.asyncio
    async def test_no_resources_returns_none(self):
        mgr = HybridCloudManager(HybridConfig())
        result = await mgr.schedule_task("t1", "backend")
        assert result is None

    @pytest.mark.asyncio
    async def test_budget_exceeded_falls_back_to_local(self):
        cfg = HybridConfig(cloud_budget_daily_usd=1.0)
        mgr = HybridCloudManager(cfg)
        mgr.register_resource(_local_gpu())
        mgr.register_resource(_cloud_gpu(cost_per_hour_usd=5.0))
        # Exhaust budget
        mgr.record_cloud_usage(_cloud_gpu(), 1.0)
        result = await mgr.schedule_task("t1", "backend")
        assert result is not None
        assert result.provider == CloudProvider.LOCAL

    @pytest.mark.asyncio
    async def test_budget_exceeded_no_local_returns_none(self):
        cfg = HybridConfig(cloud_budget_daily_usd=1.0)
        mgr = HybridCloudManager(cfg)
        mgr.register_resource(_cloud_gpu(cost_per_hour_usd=5.0))
        mgr.record_cloud_usage(_cloud_gpu(), 1.0)
        result = await mgr.schedule_task("t1", "backend")
        assert result is None


class TestBudgetTracking:
    def test_record_cloud_usage(self):
        mgr = HybridCloudManager(HybridConfig())
        resource = _cloud_gpu(cost_per_hour_usd=2.0)
        cost = mgr.record_cloud_usage(resource, 0.5)
        assert cost == pytest.approx(1.0)
        assert mgr.get_cloud_spend_today() == pytest.approx(1.0)

    def test_check_budget_ok(self):
        mgr = HybridCloudManager(HybridConfig(cloud_budget_daily_usd=100.0))
        assert mgr.check_budget() is True

    def test_check_budget_exceeded(self):
        cfg = HybridConfig(cloud_budget_daily_usd=5.0)
        mgr = HybridCloudManager(cfg)
        mgr.record_cloud_usage(_cloud_gpu(cost_per_hour_usd=10.0), 1.0)
        assert mgr.check_budget() is False

    def test_local_utilization(self):
        mgr = HybridCloudManager(HybridConfig())
        mgr.set_local_utilization(0.75)
        assert mgr.get_local_utilization() == pytest.approx(0.75)
        mgr.set_local_utilization(1.5)
        assert mgr.get_local_utilization() == pytest.approx(1.0)
        mgr.set_local_utilization(-0.1)
        assert mgr.get_local_utilization() == pytest.approx(0.0)


class TestSummary:
    def test_get_summary(self):
        mgr = HybridCloudManager(HybridConfig())
        mgr.register_resource(_local_gpu())
        mgr.register_resource(_cloud_gpu(available=False))
        summary = mgr.get_summary()
        assert summary["total_resources"] == 2
        assert summary["available_resources"] == 1
        assert summary["budget_ok"] is True
        assert summary["strategy"] == "local_first"


# ---------------------------------------------------------------------------
# Task Tracking
# ---------------------------------------------------------------------------


class TestTaskTracking:
    def test_register_and_unregister_task(self):
        mgr = HybridCloudManager(HybridConfig())
        mgr.register_task("t1", "local-0")
        assert mgr.get_active_tasks() == {"t1": "local-0"}
        assert mgr.unregister_task("t1") is True
        assert mgr.get_active_tasks() == {}

    def test_unregister_unknown_task(self):
        mgr = HybridCloudManager(HybridConfig())
        assert mgr.unregister_task("nope") is False

    @pytest.mark.asyncio
    async def test_schedule_task_records_active(self):
        mgr = HybridCloudManager(HybridConfig())
        mgr.register_resource(_local_gpu(worker_id="l1"))
        result = await mgr.schedule_task("t1", "backend")
        assert result is not None
        assert mgr.get_active_tasks()["t1"] == "l1"


# ---------------------------------------------------------------------------
# Preemption Handling
# ---------------------------------------------------------------------------


class TestPreemption:
    @pytest.mark.asyncio
    async def test_local_fallback_success(self):
        cfg = HybridConfig(preemption_strategy=PreemptionStrategy.LOCAL_FALLBACK)
        mgr = HybridCloudManager(cfg)
        mgr.register_resource(_local_gpu(worker_id="local-0"))
        mgr.register_resource(_cloud_gpu(worker_id="aws-0", is_spot=True))
        mgr.register_task("t1", "aws-0")

        event = PreemptionEvent(worker_id="aws-0", task_id="t1")
        result = await mgr.handle_preemption(event)

        assert result.success is True
        assert result.strategy_used == PreemptionStrategy.LOCAL_FALLBACK
        assert result.fallback_worker_id == "local-0"
        assert mgr.get_active_tasks()["t1"] == "local-0"

    @pytest.mark.asyncio
    async def test_local_fallback_no_local(self):
        cfg = HybridConfig(preemption_strategy=PreemptionStrategy.LOCAL_FALLBACK)
        mgr = HybridCloudManager(cfg)
        mgr.register_resource(_cloud_gpu(worker_id="aws-0", is_spot=True))
        mgr.register_task("t1", "aws-0")

        event = PreemptionEvent(worker_id="aws-0", task_id="t1")
        result = await mgr.handle_preemption(event)

        assert result.success is False
        assert "No local resource" in result.detail

    @pytest.mark.asyncio
    async def test_migrate_to_another_cloud(self):
        cfg = HybridConfig(preemption_strategy=PreemptionStrategy.MIGRATE)
        mgr = HybridCloudManager(cfg)
        mgr.register_resource(_cloud_gpu(worker_id="aws-0", is_spot=True))
        mgr.register_resource(_cloud_gpu(worker_id="aws-1", is_spot=False))
        mgr.register_task("t1", "aws-0")

        event = PreemptionEvent(worker_id="aws-0", task_id="t1")
        result = await mgr.handle_preemption(event)

        assert result.success is True
        assert result.strategy_used == PreemptionStrategy.MIGRATE
        assert result.fallback_worker_id == "aws-1"

    @pytest.mark.asyncio
    async def test_migrate_no_fallback(self):
        cfg = HybridConfig(preemption_strategy=PreemptionStrategy.MIGRATE)
        mgr = HybridCloudManager(cfg)
        mgr.register_resource(_cloud_gpu(worker_id="aws-0", is_spot=True))
        mgr.register_task("t1", "aws-0")

        event = PreemptionEvent(worker_id="aws-0", task_id="t1")
        result = await mgr.handle_preemption(event)

        assert result.success is False

    @pytest.mark.asyncio
    async def test_requeue(self):
        cfg = HybridConfig(preemption_strategy=PreemptionStrategy.REQUEUE)
        mgr = HybridCloudManager(cfg)
        mgr.register_resource(_cloud_gpu(worker_id="aws-0", is_spot=True))
        mgr.register_task("t1", "aws-0")

        event = PreemptionEvent(worker_id="aws-0", task_id="t1")
        result = await mgr.handle_preemption(event)

        assert result.success is True
        assert result.strategy_used == PreemptionStrategy.REQUEUE
        assert "t1" not in mgr.get_active_tasks()

    @pytest.mark.asyncio
    async def test_preempted_worker_excluded_from_available(self):
        mgr = HybridCloudManager(HybridConfig())
        spot = _cloud_gpu(worker_id="aws-0", is_spot=True)
        mgr.register_resource(spot)
        mgr.register_resource(_local_gpu(worker_id="local-0"))
        assert len(mgr.get_available_resources()) == 2

        event = PreemptionEvent(worker_id="aws-0")
        await mgr.handle_preemption(event)

        available = mgr.get_available_resources()
        assert len(available) == 1
        assert available[0].worker_id == "local-0"

    @pytest.mark.asyncio
    async def test_preemption_history_recorded(self):
        mgr = HybridCloudManager(HybridConfig())
        mgr.register_resource(_cloud_gpu(worker_id="aws-0"))
        mgr.register_resource(_local_gpu(worker_id="local-0"))

        event = PreemptionEvent(worker_id="aws-0", task_id="t1")
        await mgr.handle_preemption(event)

        history = mgr.get_preemption_history()
        assert len(history) == 1
        assert history[0].original_worker_id == "aws-0"

    @pytest.mark.asyncio
    async def test_preemption_callback_called(self):
        mgr = HybridCloudManager(HybridConfig())
        mgr.register_resource(_cloud_gpu(worker_id="aws-0"))
        mgr.register_resource(_local_gpu(worker_id="local-0"))

        captured: list[PreemptionResult] = []
        mgr.on_preemption(lambda r: captured.append(r))

        event = PreemptionEvent(worker_id="aws-0", task_id="t1")
        await mgr.handle_preemption(event)

        assert len(captured) == 1
        assert captured[0].task_id == "t1"

    @pytest.mark.asyncio
    async def test_async_callback(self):
        mgr = HybridCloudManager(HybridConfig())
        mgr.register_resource(_cloud_gpu(worker_id="aws-0"))
        mgr.register_resource(_local_gpu(worker_id="local-0"))

        captured: list[str] = []

        async def async_cb(result: PreemptionResult) -> None:
            captured.append(result.task_id)

        mgr.on_preemption(async_cb)

        event = PreemptionEvent(worker_id="aws-0", task_id="t1")
        await mgr.handle_preemption(event)

        assert captured == ["t1"]

    @pytest.mark.asyncio
    async def test_auto_detect_task_from_active(self):
        """task_id가 없는 이벤트에서 active_tasks로 자동 식별."""
        cfg = HybridConfig(preemption_strategy=PreemptionStrategy.REQUEUE)
        mgr = HybridCloudManager(cfg)
        mgr.register_resource(_cloud_gpu(worker_id="aws-0"))
        mgr.register_task("t1", "aws-0")

        event = PreemptionEvent(worker_id="aws-0")  # task_id 미지정
        result = await mgr.handle_preemption(event)

        assert result.task_id == "t1"
        assert result.success is True

    def test_recover_worker(self):
        mgr = HybridCloudManager(HybridConfig())
        gpu = _cloud_gpu(worker_id="aws-0")
        mgr.register_resource(gpu)

        # preempt manually
        gpu.preempted = True
        gpu.available = False
        assert len(mgr.get_available_resources()) == 0

        assert mgr.recover_worker("aws-0") is True
        assert len(mgr.get_available_resources()) == 1

    def test_recover_unknown_worker(self):
        mgr = HybridCloudManager(HybridConfig())
        assert mgr.recover_worker("nope") is False

    def test_preemption_event_defaults(self):
        e = PreemptionEvent(worker_id="w1")
        assert e.reason == "spot_reclaimed"
        assert e.task_id == ""
        assert e.timestamp is not None

    def test_preemption_result_defaults(self):
        r = PreemptionResult(
            original_worker_id="w1",
            task_id="t1",
            strategy_used=PreemptionStrategy.MIGRATE,
        )
        assert r.success is False
        assert r.fallback_worker_id is None
