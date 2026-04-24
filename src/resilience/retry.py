"""RetryPolicy — Exponential Backoff + Jitter 재시도 정책."""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

from src.errors import AgentError

logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass
class RetryPolicy:
    """재시도 정책 설정."""

    max_retries: int = 3
    base_delay: float = 1.0        # 초 단위 초기 대기
    max_delay: float = 60.0        # 최대 대기 상한
    exponential_base: float = 2.0  # 지수 밑 (delay = base * 2^attempt)
    jitter: bool = True            # 지터 적용 여부 (thundering herd 방지)
    # 재시도할 예외 타입 (빈 리스트면 모든 Exception)
    retryable_exceptions: list[type[Exception]] = field(default_factory=list)

    def compute_delay(self, attempt: int) -> float:
        """attempt번째 재시도의 대기 시간을 계산한다 (0-indexed)."""
        delay = min(self.base_delay * (self.exponential_base ** attempt), self.max_delay)
        if self.jitter:
            delay = random.uniform(0, delay)
        return delay

    def is_retryable(self, exc: Exception) -> bool:
        if not self.retryable_exceptions:
            return True
        return isinstance(exc, tuple(self.retryable_exceptions))


@dataclass
class RetryResult:
    """재시도 실행 결과."""

    success: bool
    value: Any = None
    last_exception: Exception | None = None
    attempts: int = 0


async def retry_async(
    fn: Callable[[], Any],
    policy: RetryPolicy | None = None,
    *,
    operation_name: str = "operation",
) -> RetryResult:
    """비동기 함수를 RetryPolicy에 따라 재시도한다."""
    policy = policy or RetryPolicy()
    last_exc: Exception | None = None

    for attempt in range(policy.max_retries + 1):
        try:
            value = await fn()
            if attempt > 0:
                logger.info(
                    "Retry [%s]: succeeded on attempt %d/%d",
                    operation_name,
                    attempt + 1,
                    policy.max_retries + 1,
                )
            return RetryResult(success=True, value=value, attempts=attempt + 1)
        except Exception as exc:
            last_exc = exc
            if not policy.is_retryable(exc):
                logger.warning(
                    "Retry [%s]: non-retryable exception %s — giving up",
                    operation_name,
                    type(exc).__name__,
                )
                break
            if attempt < policy.max_retries:
                delay = policy.compute_delay(attempt)
                logger.warning(
                    "Retry [%s]: attempt %d/%d failed (%s) — retrying in %.2fs",
                    operation_name,
                    attempt + 1,
                    policy.max_retries + 1,
                    type(exc).__name__,
                    delay,
                )
                await asyncio.sleep(delay)
            else:
                logger.error(
                    "Retry [%s]: all %d attempts exhausted — last error: %s",
                    operation_name,
                    policy.max_retries + 1,
                    exc,
                )

    return RetryResult(
        success=False,
        last_exception=last_exc,
        attempts=policy.max_retries + 1,
    )


# 에이전트용 기본 정책
AGENT_RETRY_POLICY = RetryPolicy(
    max_retries=2,
    base_delay=2.0,
    max_delay=30.0,
    retryable_exceptions=[AgentError, TimeoutError, ConnectionError],
)

# QA 파이프라인용 기본 정책
QA_RETRY_POLICY = RetryPolicy(
    max_retries=1,
    base_delay=1.0,
    max_delay=10.0,
)
