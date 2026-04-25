"""CircuitBreaker 테스트 — 상태 전환, 레지스트리, health_monitor."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from src.resilience.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerRegistry,
    CircuitOpenError,
    CircuitState,
)


# ---------------------------------------------------------------------------
# CircuitOpenError
# ---------------------------------------------------------------------------


class TestCircuitOpenError:
    def test_attributes(self):
        err = CircuitOpenError("test-cb", 12.5)
        assert err.name == "test-cb"
        assert err.reset_in == 12.5
        assert "test-cb" in str(err)
        assert "OPEN" in str(err)


# ---------------------------------------------------------------------------
# CircuitBreakerConfig
# ---------------------------------------------------------------------------


class TestCircuitBreakerConfig:
    def test_defaults(self):
        cfg = CircuitBreakerConfig()
        assert cfg.failure_threshold == 5
        assert cfg.success_threshold == 2
        assert cfg.timeout == 30.0
        assert cfg.half_open_max_calls == 1


# ---------------------------------------------------------------------------
# CircuitBreaker — 기본 상태 전환
# ---------------------------------------------------------------------------


class TestCircuitBreakerBasic:
    def test_initial_state(self):
        cb = CircuitBreaker("test")
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0

    @pytest.mark.asyncio
    async def test_successful_call(self):
        cb = CircuitBreaker("test")

        async def ok():
            return 42

        result = await cb.call(ok)
        assert result == 42
        assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_failure_increments_count(self):
        cb = CircuitBreaker("test", CircuitBreakerConfig(failure_threshold=3))

        async def fail():
            raise ValueError("boom")

        with pytest.raises(ValueError):
            await cb.call(fail)

        assert cb.failure_count == 1
        assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_closed_to_open_transition(self):
        cfg = CircuitBreakerConfig(failure_threshold=3)
        cb = CircuitBreaker("test", cfg)

        async def fail():
            raise ValueError("boom")

        for _ in range(3):
            with pytest.raises(ValueError):
                await cb.call(fail)

        assert cb.state == CircuitState.OPEN
        assert cb.failure_count == 3

    @pytest.mark.asyncio
    async def test_open_state_raises_circuit_open_error(self):
        cfg = CircuitBreakerConfig(failure_threshold=1, timeout=100.0)
        cb = CircuitBreaker("test", cfg)

        async def fail():
            raise ValueError("boom")

        with pytest.raises(ValueError):
            await cb.call(fail)

        assert cb.state == CircuitState.OPEN

        async def ok():
            return 42

        with pytest.raises(CircuitOpenError) as exc_info:
            await cb.call(ok)

        assert exc_info.value.name == "test"

    @pytest.mark.asyncio
    async def test_open_state_uses_fallback(self):
        cfg = CircuitBreakerConfig(failure_threshold=1, timeout=100.0)
        cb = CircuitBreaker("test", cfg)

        async def fail():
            raise ValueError("boom")

        with pytest.raises(ValueError):
            await cb.call(fail)

        async def fallback():
            return "fallback_value"

        result = await cb.call(fail, fallback=fallback)
        assert result == "fallback_value"

    def test_reset(self):
        cb = CircuitBreaker("test")
        cb._state = CircuitState.OPEN
        cb._failure_count = 5
        cb._opened_at = time.monotonic()
        cb.reset()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0

    @pytest.mark.asyncio
    async def test_success_resets_failure_count_in_closed(self):
        cfg = CircuitBreakerConfig(failure_threshold=3)
        cb = CircuitBreaker("test", cfg)

        async def fail():
            raise ValueError("boom")

        async def ok():
            return 1

        # 2 failures
        for _ in range(2):
            with pytest.raises(ValueError):
                await cb.call(fail)
        assert cb.failure_count == 2

        # 1 success resets
        await cb.call(ok)
        assert cb.failure_count == 0
        assert cb.state == CircuitState.CLOSED


# ---------------------------------------------------------------------------
# HALF_OPEN 전환 및 복구
# ---------------------------------------------------------------------------


class TestHalfOpenTransition:
    @pytest.mark.asyncio
    async def test_open_to_half_open_after_timeout(self):
        cfg = CircuitBreakerConfig(failure_threshold=1, timeout=0.0)
        cb = CircuitBreaker("test", cfg)

        async def fail():
            raise ValueError("boom")

        with pytest.raises(ValueError):
            await cb.call(fail)
        assert cb.state == CircuitState.OPEN

        # timeout=0 → 즉시 HALF_OPEN 전환
        async def ok():
            return "recovered"

        result = await cb.call(ok)
        assert result == "recovered"

    @pytest.mark.asyncio
    async def test_half_open_to_closed_on_success_threshold(self):
        cfg = CircuitBreakerConfig(
            failure_threshold=1, success_threshold=2, timeout=0.0,
            half_open_max_calls=5,
        )
        cb = CircuitBreaker("test", cfg)

        async def fail():
            raise ValueError("boom")

        async def ok():
            return "ok"

        # CLOSED → OPEN
        with pytest.raises(ValueError):
            await cb.call(fail)
        assert cb.state == CircuitState.OPEN

        # OPEN → HALF_OPEN → 1st success
        await cb.call(ok)
        # After timeout=0, state transitions to HALF_OPEN, then success
        # Need another success to reach threshold=2
        # Force state to test properly
        cb._state = CircuitState.HALF_OPEN
        cb._success_count = 1
        cb._half_open_calls = 0

        await cb.call(ok)
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0

    @pytest.mark.asyncio
    async def test_half_open_failure_reopens(self):
        cfg = CircuitBreakerConfig(
            failure_threshold=1, timeout=0.0, half_open_max_calls=5,
        )
        cb = CircuitBreaker("test", cfg)

        async def fail():
            raise ValueError("boom")

        # CLOSED → OPEN
        with pytest.raises(ValueError):
            await cb.call(fail)

        # OPEN → HALF_OPEN (timeout=0), then fail → back to OPEN
        with pytest.raises(ValueError):
            await cb.call(fail)

        assert cb.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_half_open_max_calls_exceeded(self):
        cfg = CircuitBreakerConfig(
            failure_threshold=1, timeout=0.0, half_open_max_calls=1,
        )
        cb = CircuitBreaker("test", cfg)

        async def fail():
            raise ValueError("boom")

        # CLOSED → OPEN
        with pytest.raises(ValueError):
            await cb.call(fail)

        # First call in HALF_OPEN
        cb._state = CircuitState.HALF_OPEN
        cb._half_open_calls = 1

        async def ok():
            return 1

        with pytest.raises(CircuitOpenError):
            await cb.call(ok)


# ---------------------------------------------------------------------------
# health_monitor callback
# ---------------------------------------------------------------------------


class TestHealthMonitor:
    @pytest.mark.asyncio
    async def test_record_circuit_open_called(self):
        monitor = MagicMock()
        cfg = CircuitBreakerConfig(failure_threshold=2)
        cb = CircuitBreaker("test", cfg, health_monitor=monitor)

        async def fail():
            raise ValueError("boom")

        for _ in range(2):
            with pytest.raises(ValueError):
                await cb.call(fail)

        assert cb.state == CircuitState.OPEN
        monitor.record_circuit_open.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_monitor_no_error(self):
        cfg = CircuitBreakerConfig(failure_threshold=1)
        cb = CircuitBreaker("test", cfg, health_monitor=None)

        async def fail():
            raise ValueError("boom")

        with pytest.raises(ValueError):
            await cb.call(fail)

        assert cb.state == CircuitState.OPEN


# ---------------------------------------------------------------------------
# get_status
# ---------------------------------------------------------------------------


class TestGetStatus:
    def test_initial_status(self):
        cb = CircuitBreaker("my-cb")
        status = cb.get_status()
        assert status["name"] == "my-cb"
        assert status["state"] == CircuitState.CLOSED
        assert status["failure_count"] == 0
        assert status["success_count"] == 0
        assert status["opened_at"] is None

    @pytest.mark.asyncio
    async def test_status_after_open(self):
        cfg = CircuitBreakerConfig(failure_threshold=1)
        cb = CircuitBreaker("my-cb", cfg)

        async def fail():
            raise ValueError("boom")

        with pytest.raises(ValueError):
            await cb.call(fail)

        status = cb.get_status()
        assert status["state"] == CircuitState.OPEN
        assert status["failure_count"] == 1
        assert status["opened_at"] is not None


# ---------------------------------------------------------------------------
# CircuitBreakerRegistry
# ---------------------------------------------------------------------------


class TestCircuitBreakerRegistry:
    def test_get_creates_new(self):
        registry = CircuitBreakerRegistry()
        cb = registry.get("agent-a")
        assert cb.name == "agent-a"
        assert cb.state == CircuitState.CLOSED

    def test_get_returns_same(self):
        registry = CircuitBreakerRegistry()
        cb1 = registry.get("agent-a")
        cb2 = registry.get("agent-a")
        assert cb1 is cb2

    def test_all_statuses(self):
        registry = CircuitBreakerRegistry()
        registry.get("a")
        registry.get("b")
        statuses = registry.all_statuses()
        assert len(statuses) == 2
        names = {s["name"] for s in statuses}
        assert names == {"a", "b"}

    def test_all_statuses_empty(self):
        registry = CircuitBreakerRegistry()
        assert registry.all_statuses() == []

    def test_custom_config(self):
        cfg = CircuitBreakerConfig(failure_threshold=10)
        registry = CircuitBreakerRegistry(config=cfg)
        cb = registry.get("agent-a")
        assert cb._cfg.failure_threshold == 10
