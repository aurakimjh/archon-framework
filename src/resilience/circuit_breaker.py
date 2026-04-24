"""CircuitBreaker — Closed / Open / Half-Open 상태 머신."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


class CircuitState(StrEnum):
    CLOSED = "closed"        # 정상 동작
    OPEN = "open"            # 차단 중 (fast-fail)
    HALF_OPEN = "half_open"  # 복구 탐색 중


class CircuitOpenError(Exception):
    """Circuit Breaker가 OPEN 상태일 때 호출 차단."""

    def __init__(self, name: str, reset_in: float) -> None:
        self.name = name
        self.reset_in = reset_in
        super().__init__(f"Circuit [{name}] is OPEN — retry after {reset_in:.1f}s")


@dataclass
class CircuitBreakerConfig:
    failure_threshold: int = 5       # 연속 실패 횟수 → OPEN 전환
    success_threshold: int = 2       # HALF_OPEN에서 연속 성공 → CLOSED 복귀
    timeout: float = 30.0            # OPEN 상태 유지 시간 (초)
    half_open_max_calls: int = 1     # HALF_OPEN에서 동시 탐색 허용 수


class CircuitBreaker:
    """에이전트/서비스 호출을 보호하는 Circuit Breaker.

    CLOSED → (failure_threshold 도달) → OPEN → (timeout 경과) → HALF_OPEN
    HALF_OPEN → (success_threshold 성공) → CLOSED
    HALF_OPEN → (실패) → OPEN (재설정)
    """

    def __init__(
        self,
        name: str,
        config: CircuitBreakerConfig | None = None,
        health_monitor: Any | None = None,
    ) -> None:
        self.name = name
        self._cfg = config or CircuitBreakerConfig()
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._opened_at: float | None = None
        self._half_open_calls = 0
        self._lock = asyncio.Lock()
        self._health_monitor = health_monitor  # AgentHealthMonitor (optional)

    @property
    def state(self) -> CircuitState:
        return self._state

    @property
    def failure_count(self) -> int:
        return self._failure_count

    async def call(
        self, fn: Callable[[], Any], *, fallback: Callable[[], Any] | None = None,
    ) -> Any:
        """보호된 호출을 실행한다.

        OPEN이면 CircuitOpenError를 발생시키거나 fallback을 호출한다.
        """
        async with self._lock:
            state = self._evaluate_state()

        if state == CircuitState.OPEN:
            reset_in = max(0.0, (self._opened_at or 0) + self._cfg.timeout - time.monotonic())
            logger.warning("CircuitBreaker [%s]: OPEN — fast-failing", self.name)
            if fallback:
                return await fallback()
            raise CircuitOpenError(self.name, reset_in)

        if state == CircuitState.HALF_OPEN:
            async with self._lock:
                if self._half_open_calls >= self._cfg.half_open_max_calls:
                    raise CircuitOpenError(self.name, 0.0)
                self._half_open_calls += 1

        try:
            result = await fn()
            await self._on_success()
            return result
        except Exception:
            await self._on_failure()
            raise

    def reset(self) -> None:
        """수동으로 Circuit을 CLOSED로 리셋한다."""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._opened_at = None
        self._half_open_calls = 0
        logger.info("CircuitBreaker [%s]: manually reset to CLOSED", self.name)

    def get_status(self) -> dict:
        return {
            "name": self.name,
            "state": self._state,
            "failure_count": self._failure_count,
            "success_count": self._success_count,
            "opened_at": self._opened_at,
        }

    # --- 내부 전환 ---

    def _evaluate_state(self) -> CircuitState:
        if self._state == CircuitState.OPEN:
            elapsed = time.monotonic() - (self._opened_at or 0)
            if elapsed >= self._cfg.timeout:
                self._state = CircuitState.HALF_OPEN
                self._half_open_calls = 0
                self._success_count = 0
                logger.info(
                    "CircuitBreaker [%s]: OPEN → HALF_OPEN (elapsed %.1fs)",
                    self.name,
                    elapsed,
                )
        return self._state

    async def _on_success(self) -> None:
        async with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self._cfg.success_threshold:
                    self._state = CircuitState.CLOSED
                    self._failure_count = 0
                    self._half_open_calls = 0
                    logger.info("CircuitBreaker [%s]: HALF_OPEN → CLOSED", self.name)
            elif self._state == CircuitState.CLOSED:
                self._failure_count = 0  # 성공 시 실패 카운터 리셋

    async def _on_failure(self) -> None:
        async with self._lock:
            self._failure_count += 1
            if self._state == CircuitState.HALF_OPEN:
                # 탐색 중 실패 → 다시 OPEN
                self._state = CircuitState.OPEN
                self._opened_at = time.monotonic()
                self._half_open_calls = 0
                logger.warning("CircuitBreaker [%s]: HALF_OPEN → OPEN (probe failed)", self.name)
            elif (
                self._state == CircuitState.CLOSED
                and self._failure_count >= self._cfg.failure_threshold
            ):
                self._state = CircuitState.OPEN
                self._opened_at = time.monotonic()
                logger.error(
                    "CircuitBreaker [%s]: CLOSED → OPEN (failures=%d)",
                    self.name,
                    self._failure_count,
                )
                if self._health_monitor is not None:
                    self._health_monitor.record_circuit_open()


class CircuitBreakerRegistry:
    """에이전트 역할별 CircuitBreaker 풀."""

    def __init__(self, config: CircuitBreakerConfig | None = None) -> None:
        self._default_config = config or CircuitBreakerConfig()
        self._breakers: dict[str, CircuitBreaker] = {}

    def get(self, name: str) -> CircuitBreaker:
        if name not in self._breakers:
            self._breakers[name] = CircuitBreaker(name, self._default_config)
        return self._breakers[name]

    def all_statuses(self) -> list[dict]:
        return [cb.get_status() for cb in self._breakers.values()]
