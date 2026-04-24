"""Resilience 모듈 테스트 — retry, circuit_breaker, fallback, recovery."""

from __future__ import annotations

import asyncio

import pytest

from src.resilience.circuit_breaker import (
    CircuitBreakerConfig,
    CircuitBreaker,
    CircuitOpenError,
    CircuitState,
    CircuitBreakerRegistry,
)
from src.resilience.fallback import FallbackConfig, FallbackMode, FallbackStrategy
from src.resilience.recovery import RecoveryConfig, RecoveryManager, StepStatus
from src.resilience.retry import RetryPolicy, retry_async


# ---------------------------------------------------------------------------
# RetryPolicy
# ---------------------------------------------------------------------------

class TestRetryPolicy:
    def test_delay_increases_exponentially(self):
        policy = RetryPolicy(base_delay=1.0, exponential_base=2.0, jitter=False)
        assert policy.compute_delay(0) == pytest.approx(1.0)
        assert policy.compute_delay(1) == pytest.approx(2.0)
        assert policy.compute_delay(2) == pytest.approx(4.0)

    def test_delay_capped_by_max(self):
        policy = RetryPolicy(base_delay=1.0, max_delay=5.0, exponential_base=2.0, jitter=False)
        assert policy.compute_delay(10) == pytest.approx(5.0)

    def test_retryable_all_by_default(self):
        policy = RetryPolicy()
        assert policy.is_retryable(ValueError("x"))

    def test_retryable_specific_types(self):
        policy = RetryPolicy(retryable_exceptions=[ConnectionError])
        assert policy.is_retryable(ConnectionError())
        assert not policy.is_retryable(ValueError("x"))


class TestRetryAsync:
    @pytest.mark.asyncio
    async def test_succeeds_on_first_try(self):
        calls = []
        async def fn():
            calls.append(1)
            return "ok"
        result = await retry_async(fn, RetryPolicy(max_retries=3))
        assert result.success
        assert result.value == "ok"
        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_retries_and_succeeds(self):
        calls = []
        async def fn():
            calls.append(1)
            if len(calls) < 3:
                raise ConnectionError("not yet")
            return "ok"
        policy = RetryPolicy(max_retries=5, base_delay=0.0, jitter=False)
        result = await retry_async(fn, policy)
        assert result.success
        assert len(calls) == 3

    @pytest.mark.asyncio
    async def test_exhausts_retries(self):
        async def fn():
            raise ValueError("always fails")
        policy = RetryPolicy(max_retries=2, base_delay=0.0, jitter=False)
        result = await retry_async(fn, policy)
        assert not result.success
        assert isinstance(result.last_exception, ValueError)
        assert result.attempts == 3

    @pytest.mark.asyncio
    async def test_non_retryable_stops_immediately(self):
        calls = []
        async def fn():
            calls.append(1)
            raise RuntimeError("not retryable")
        policy = RetryPolicy(
            max_retries=5, base_delay=0.0, jitter=False,
            retryable_exceptions=[ConnectionError],
        )
        result = await retry_async(fn, policy)
        assert not result.success
        assert len(calls) == 1  # 재시도 없이 즉시 중단


# ---------------------------------------------------------------------------
# CircuitBreaker
# ---------------------------------------------------------------------------

class TestCircuitBreaker:
    @pytest.mark.asyncio
    async def test_starts_closed(self):
        cb = CircuitBreaker("test")
        assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_opens_after_failures(self):
        cfg = CircuitBreakerConfig(failure_threshold=3, timeout=60.0)
        cb = CircuitBreaker("test", cfg)
        for _ in range(3):
            try:
                await cb.call(lambda: (_ for _ in ()).throw(RuntimeError("err")))
            except RuntimeError:
                pass
        assert cb.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_fast_fails_when_open(self):
        cfg = CircuitBreakerConfig(failure_threshold=1, timeout=60.0)
        cb = CircuitBreaker("test", cfg)
        try:
            await cb.call(lambda: (_ for _ in ()).throw(RuntimeError("err")))
        except RuntimeError:
            pass
        with pytest.raises(CircuitOpenError):
            await cb.call(lambda: asyncio.sleep(0))

    @pytest.mark.asyncio
    async def test_uses_fallback_when_open(self):
        cfg = CircuitBreakerConfig(failure_threshold=1, timeout=60.0)
        cb = CircuitBreaker("test", cfg)
        try:
            await cb.call(lambda: (_ for _ in ()).throw(RuntimeError("err")))
        except RuntimeError:
            pass

        async def fallback():
            return "fallback_result"

        result = await cb.call(lambda: asyncio.sleep(0), fallback=fallback)
        assert result == "fallback_result"

    @pytest.mark.asyncio
    async def test_resets_manually(self):
        cfg = CircuitBreakerConfig(failure_threshold=1, timeout=60.0)
        cb = CircuitBreaker("test", cfg)
        try:
            await cb.call(lambda: (_ for _ in ()).throw(RuntimeError("err")))
        except RuntimeError:
            pass
        assert cb.state == CircuitState.OPEN
        cb.reset()
        assert cb.state == CircuitState.CLOSED

    def test_registry_creates_separate_breakers(self):
        reg = CircuitBreakerRegistry()
        cb1 = reg.get("agent_a")
        cb2 = reg.get("agent_b")
        cb1_again = reg.get("agent_a")
        assert cb1 is not cb2
        assert cb1 is cb1_again


# ---------------------------------------------------------------------------
# FallbackStrategy
# ---------------------------------------------------------------------------

class TestFallbackStrategy:
    def test_cached_mode_returns_cached(self):
        cfg = FallbackConfig(mode=FallbackMode.CACHED)
        fs = FallbackStrategy(cfg)
        fs.cache_result("backend", "cached_value")
        mode, params = fs.decide("backend", RuntimeError("err"))
        assert mode == FallbackMode.CACHED
        assert params["result"] == "cached_value"

    def test_cached_mode_degrades_when_no_cache(self):
        cfg = FallbackConfig(mode=FallbackMode.CACHED)
        fs = FallbackStrategy(cfg)
        mode, _ = fs.decide("backend", RuntimeError("err"))
        assert mode == FallbackMode.DEGRADED

    def test_alternative_model_mode(self):
        cfg = FallbackConfig(mode=FallbackMode.ALTERNATIVE_MODEL, fallback_model="gpt-4o")
        fs = FallbackStrategy(cfg)
        mode, params = fs.decide("backend", RuntimeError("err"))
        assert mode == FallbackMode.ALTERNATIVE_MODEL
        assert params["model"] == "gpt-4o"

    def test_alternative_model_degrades_when_no_model(self):
        cfg = FallbackConfig(mode=FallbackMode.ALTERNATIVE_MODEL, fallback_model=None)
        fs = FallbackStrategy(cfg)
        mode, _ = fs.decide("backend", RuntimeError("err"))
        assert mode == FallbackMode.DEGRADED

    def test_degraded_mode(self):
        cfg = FallbackConfig(mode=FallbackMode.DEGRADED)
        fs = FallbackStrategy(cfg)
        mode, params = fs.decide("backend", RuntimeError("err"))
        assert mode == FallbackMode.DEGRADED
        assert params == {}


# ---------------------------------------------------------------------------
# RecoveryManager
# ---------------------------------------------------------------------------

class TestRecoveryManager:
    @pytest.mark.asyncio
    async def test_successful_step(self):
        rm = RecoveryManager(RecoveryConfig(retry_policy=RetryPolicy(max_retries=0, base_delay=0)))
        step = rm.register_step("step1", "backend")

        async def fn():
            return "result"

        result = await rm.run_step(step, fn)
        assert result == "result"
        assert step.status == StepStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_failed_step_continue_on_failure(self):
        cfg = RecoveryConfig(
            retry_policy=RetryPolicy(max_retries=0, base_delay=0.0, jitter=False),
            fallback_config=FallbackConfig(mode=FallbackMode.DEGRADED),
            continue_on_failure=True,
        )
        rm = RecoveryManager(cfg)
        step = rm.register_step("step1", "backend")

        async def fn():
            raise RuntimeError("fail")

        result = await rm.run_step(step, fn)
        assert result is None
        assert step.status == StepStatus.SKIPPED

    @pytest.mark.asyncio
    async def test_failed_step_raises_without_continue(self):
        cfg = RecoveryConfig(
            retry_policy=RetryPolicy(max_retries=0, base_delay=0.0, jitter=False),
            fallback_config=FallbackConfig(mode=FallbackMode.NONE),
            continue_on_failure=False,
        )
        rm = RecoveryManager(cfg)
        step = rm.register_step("step1", "backend")

        async def fn():
            raise RuntimeError("fail")

        with pytest.raises(RuntimeError):
            await rm.run_step(step, fn)
        assert step.status == StepStatus.FAILED

    @pytest.mark.asyncio
    async def test_recovered_via_cache(self):
        cfg = RecoveryConfig(
            retry_policy=RetryPolicy(max_retries=0, base_delay=0.0, jitter=False),
            fallback_config=FallbackConfig(mode=FallbackMode.CACHED),
        )
        rm = RecoveryManager(cfg)
        # 성공 단계로 캐시 채우기
        step_ok = rm.register_step("step_ok", "backend")
        async def fn_ok():
            return "cached_value"
        await rm.run_step(step_ok, fn_ok)

        # 실패 단계 → CACHED 폴백
        step_fail = rm.register_step("step_fail", "backend")
        async def fn_fail():
            raise RuntimeError("fail")
        result = await rm.run_step(step_fail, fn_fail)
        assert result == "cached_value"
        assert step_fail.status == StepStatus.RECOVERED

    def test_summary(self):
        rm = RecoveryManager()
        rm.register_step("s1", "backend")
        rm.register_step("s2", "tester")
        summary = rm.get_summary()
        assert summary["total"] == 2
        assert "failed_steps" in summary

    def test_pipeline_healthy_no_failures(self):
        rm = RecoveryManager(RecoveryConfig(max_failed_steps=0))
        assert rm.is_pipeline_healthy()
