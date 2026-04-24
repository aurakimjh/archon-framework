"""structlog 설정 — 개발/프로덕션 모드 프로세서 체인 구성."""

from __future__ import annotations

import logging
import logging.config
import os
import sys
from typing import Any

import structlog

from src.log.processors import (
    TimingProcessor,
    agent_context_injector,
    sensitive_data_masker,
    token_usage_normalizer,
)

# 공유 프로세서 체인 (stdlib logging 브리지 포함)
_SHARED_PROCESSORS: list[Any] = [
    structlog.contextvars.merge_contextvars,
    structlog.stdlib.add_log_level,
    structlog.stdlib.add_logger_name,
    structlog.processors.TimeStamper(fmt="iso"),
    agent_context_injector,
    token_usage_normalizer,
    TimingProcessor(),
    sensitive_data_masker,
]


def setup_logging(
    *,
    level: str | None = None,
    mode: str | None = None,
    log_file: str | None = None,
) -> None:
    """structlog + stdlib logging을 함께 설정한다.

    Args:
        level: 로그 레벨 (DEBUG/INFO/WARNING/ERROR). 없으면 ARCHON_LOG_LEVEL 환경변수 → INFO.
        mode: "dev" | "prod". 없으면 ARCHON_ENV 환경변수 → "dev".
        log_file: 파일 출력 경로. None이면 콘솔만.
    """
    resolved_level = (level or os.environ.get("ARCHON_LOG_LEVEL", "INFO")).upper()
    resolved_mode = mode or os.environ.get("ARCHON_ENV", "dev")
    is_dev = resolved_mode == "dev"

    # --- structlog 렌더러 선택 ---
    if is_dev:
        renderer: Any = structlog.dev.ConsoleRenderer(colors=True)
    else:
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[
            *_SHARED_PROCESSORS,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # --- stdlib logging 설정 ---
    formatter = structlog.stdlib.ProcessorFormatter(
        processor=renderer,
        foreign_pre_chain=_SHARED_PROCESSORS,
    )

    handlers: list[logging.Handler] = []

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    handlers.append(console_handler)

    if log_file:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(formatter)
        handlers.append(file_handler)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    for h in handlers:
        root_logger.addHandler(h)
    root_logger.setLevel(resolved_level)

    # archon 네임스페이스 로거는 개별 설정 가능
    logging.getLogger("src").setLevel(resolved_level)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("litellm").setLevel(logging.WARNING)
