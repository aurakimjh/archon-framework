"""RecoveryManager — 파이프라인 부분 실패 시 복구 로직."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from src.resilience.circuit_breaker import CircuitBreaker, CircuitBreakerRegistry, CircuitOpenError
from src.resilience.fallback import FallbackConfig, FallbackMode, FallbackStrategy
from src.resilience.retry import RetryPolicy, RetryResult, retry_async

logger = logging.getLogger(__name__)


class StepStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    RECOVERED = "recovered"   # 폴백으로 복구됨


@dataclass
class PipelineStep:
    """파이프라인 단계 메타데이터."""

    name: str
    agent_role: str
    status: StepStatus = StepStatus.PENDING
    result: Any = None
    error: Exception | None = None
    attempts: int = 0
    fallback_used: FallbackMode | None = None


@dataclass
class RecoveryConfig:
    """복구 전략 설정."""

    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    fallback_config: FallbackConfig = field(default_factory=FallbackConfig)
    # True면 실패 단계를 건너뛰고 이후 단계를 계속 실행
    continue_on_failure: bool = False
    # 전체 파이프라인 실패로 처리할 최대 실패 단계 수 (0 = 허용 안 함)
    max_failed_steps: int = 0


class RecoveryManager:
    """파이프라인 부분 실패 시 복구를 조율한다.

    - 성공한 단계의 결과를 보존한다.
    - 실패한 단계에 RetryPolicy → Fallback 순으로 복구를 시도한다.
    - continue_on_failure=True면 복구 불가 단계를 SKIPPED 처리하고 계속 진행한다.
    """

    def __init__(
        self,
        config: RecoveryConfig | None = None,
        circuit_registry: CircuitBreakerRegistry | None = None,
    ) -> None:
        self._cfg = config or RecoveryConfig()
        self._circuit_registry = circuit_registry or CircuitBreakerRegistry()
        self._fallback = FallbackStrategy(self._cfg.fallback_config)
        self._steps: list[PipelineStep] = []

    def register_step(self, name: str, agent_role: str) -> PipelineStep:
        """파이프라인 단계를 등록하고 추적 객체를 반환한다."""
        step = PipelineStep(name=name, agent_role=agent_role)
        self._steps.append(step)
        return step

    async def run_step(
        self,
        step: PipelineStep,
        fn: Any,  # Callable[[], Awaitable[Any]]
        *,
        fallback_fn: Any | None = None,
    ) -> Any:
        """단일 파이프라인 단계를 실행하고 실패 시 복구를 시도한다.

        복구 순서: Retry → Fallback → (continue_on_failure이면 SKIPPED)
        """
        step.status = StepStatus.RUNNING
        circuit = self._circuit_registry.get(step.agent_role)

        async def _guarded():
            return await circuit.call(fn, fallback=None)

        retry_result: RetryResult = await retry_async(
            _guarded,
            policy=self._cfg.retry_policy,
            operation_name=step.name,
        )

        if retry_result.success:
            step.status = StepStatus.SUCCESS
            step.result = retry_result.value
            step.attempts = retry_result.attempts
            self._fallback.cache_result(step.agent_role, retry_result.value)
            return step.result

        # Retry 실패 → Fallback
        step.error = retry_result.last_exception
        step.attempts = retry_result.attempts

        exc = retry_result.last_exception or Exception("unknown")
        fb_mode, fb_params = self._fallback.decide(step.agent_role, exc)

        if fb_mode == FallbackMode.CACHED:
            step.status = StepStatus.RECOVERED
            step.result = fb_params["result"]
            step.fallback_used = FallbackMode.CACHED
            logger.info("RecoveryManager [%s]: recovered via CACHED result", step.name)
            return step.result

        if fb_mode == FallbackMode.ALTERNATIVE_MODEL and fallback_fn:
            try:
                step.result = await fallback_fn(model=fb_params.get("model"))
                step.status = StepStatus.RECOVERED
                step.fallback_used = FallbackMode.ALTERNATIVE_MODEL
                return step.result
            except Exception as alt_exc:
                logger.error(
                    "RecoveryManager [%s]: alternative model also failed: %s",
                    step.name,
                    alt_exc,
                )

        if fb_mode == FallbackMode.DEGRADED or self._cfg.continue_on_failure:
            step.status = StepStatus.SKIPPED
            step.fallback_used = FallbackMode.DEGRADED
            logger.warning(
                "RecoveryManager [%s]: step SKIPPED (continue_on_failure=%s)",
                step.name,
                self._cfg.continue_on_failure,
            )
            return None

        step.status = StepStatus.FAILED
        raise exc

    def get_summary(self) -> dict:
        """파이프라인 전체 복구 요약을 반환한다."""
        counts = {s: 0 for s in StepStatus}
        for step in self._steps:
            counts[step.status] += 1
        failed_steps = [s.name for s in self._steps if s.status == StepStatus.FAILED]
        recovered_steps = [s.name for s in self._steps if s.status == StepStatus.RECOVERED]
        return {
            "total": len(self._steps),
            "success": counts[StepStatus.SUCCESS],
            "failed": counts[StepStatus.FAILED],
            "recovered": counts[StepStatus.RECOVERED],
            "skipped": counts[StepStatus.SKIPPED],
            "failed_steps": failed_steps,
            "recovered_steps": recovered_steps,
            "circuit_statuses": self._circuit_registry.all_statuses(),
        }

    def is_pipeline_healthy(self) -> bool:
        """파이프라인이 허용 가능한 상태인지 반환한다."""
        failed = sum(1 for s in self._steps if s.status == StepStatus.FAILED)
        limit = self._cfg.max_failed_steps
        if limit == 0:
            return failed == 0
        return failed <= limit
