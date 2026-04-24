"""로깅 컨텍스트 관리 — async-safe contextvars 기반."""

from __future__ import annotations

import contextlib
from contextvars import ContextVar
from typing import Any, Iterator

import structlog

# structlog contextvars는 structlog.contextvars 모듈이 직접 관리한다.
# 여기서는 편의 래퍼만 제공한다.

_CONTEXT_VAR: ContextVar[dict[str, Any]] = ContextVar("archon_log_context", default={})


def bind_context(**kwargs: Any) -> None:
    """현재 코루틴/스레드의 로깅 컨텍스트에 키-값을 바인딩한다.

    structlog.contextvars에 반영되어 이후 모든 로그에 자동 포함된다.

    Example::

        bind_context(project_id="proj-ecomm", pipeline_id="pl-001")
        logger.info("pipeline started")  # → {"project_id": ..., "pipeline_id": ..., ...}
    """
    structlog.contextvars.bind_contextvars(**kwargs)


def unbind_context(*keys: str) -> None:
    """특정 키를 현재 컨텍스트에서 제거한다."""
    structlog.contextvars.unbind_contextvars(*keys)


def clear_context() -> None:
    """현재 컨텍스트를 모두 초기화한다."""
    structlog.contextvars.clear_contextvars()


def get_context() -> dict[str, Any]:
    """현재 컨텍스트 딕셔너리를 반환한다 (읽기 전용 스냅샷)."""
    return dict(structlog.contextvars.get_contextvars())


@contextlib.contextmanager
def with_context(**kwargs: Any) -> Iterator[None]:
    """컨텍스트 매니저: 블록 내에서만 컨텍스트를 바인딩하고 자동 복원한다.

    Example::

        with with_context(agent_role="backend", task_id="task-001"):
            logger.info("agent started")
        # 블록 종료 후 agent_role, task_id 자동 제거
    """
    bind_context(**kwargs)
    try:
        yield
    finally:
        unbind_context(*kwargs.keys())


@contextlib.contextmanager
def pipeline_context(
    pipeline_id: str,
    project_id: str,
    step: str = "",
    attempt: int = 0,
) -> Iterator[None]:
    """파이프라인 단계별 컨텍스트를 자동으로 관리한다.

    Example::

        async with pipeline_context("pl-001", "proj-ecomm", step="backend"):
            await agent.execute(handoff, registry)
    """
    with with_context(
        pipeline_id=pipeline_id,
        project_id=project_id,
        step=step,
        attempt=attempt,
    ):
        yield


@contextlib.contextmanager
def agent_context(
    agent_name: str,
    agent_role: str,
    task_id: str = "",
) -> Iterator[None]:
    """에이전트 실행 컨텍스트를 자동으로 관리한다."""
    with with_context(
        agent_name=agent_name,
        agent_role=agent_role,
        task_id=task_id,
    ):
        yield
