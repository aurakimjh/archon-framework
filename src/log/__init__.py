"""Archon Structured Logging — structlog 기반 구조화 로깅."""

from __future__ import annotations

from typing import Any

import structlog

from src.log.config import setup_logging
from src.log.context import (
    agent_context,
    bind_context,
    clear_context,
    get_context,
    pipeline_context,
    unbind_context,
    with_context,
)
from src.log.processors import (
    TimingProcessor,
    agent_context_injector,
    sensitive_data_masker,
    token_usage_normalizer,
)


def get_logger(
    name: str | None = None,
    **initial_context: Any,
) -> structlog.stdlib.BoundLogger:
    """structlog BoundLogger를 반환한다.

    기존 logging.getLogger(__name__)의 드롭인 대체재로 사용 가능하다.
    initial_context를 넘기면 이 로거의 모든 이벤트에 자동 포함된다.

    Example::

        logger = get_logger(__name__, agent_role="backend")
        logger.info("agent started", task_id="task-001")
    """
    logger = structlog.get_logger(name)
    if initial_context:
        logger = logger.bind(**initial_context)
    return logger  # type: ignore[return-value]


__all__ = [
    "get_logger",
    "setup_logging",
    "bind_context",
    "unbind_context",
    "clear_context",
    "get_context",
    "with_context",
    "agent_context",
    "pipeline_context",
    "TimingProcessor",
    "agent_context_injector",
    "sensitive_data_masker",
    "token_usage_normalizer",
]
