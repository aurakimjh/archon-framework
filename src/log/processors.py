"""커스텀 structlog 프로세서."""

from __future__ import annotations

import re
import time
from typing import Any

# --- 민감 정보 마스킹 패턴 ---

_MASK_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("api_key", re.compile(
        r'(api[_\-]?key["\s]*[:=]["\s]*)[\w\-]{10,}',
        re.IGNORECASE,
    )),
    ("password", re.compile(
        r'(password["\s]*[:=]["\s]*)[\S]{6,}',
        re.IGNORECASE,
    )),
    ("aws_key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("jwt", re.compile(
        r"eyJ[A-Za-z0-9\-_]{10,}\.[A-Za-z0-9\-_]{10,}\.[A-Za-z0-9\-_]{10,}"
    )),
    ("bearer", re.compile(
        r"(Bearer\s+)[\w\-\.]{20,}",
        re.IGNORECASE,
    )),
]

_SENSITIVE_KEYS = frozenset({
    "api_key", "apikey", "password", "passwd", "secret",
    "token", "authorization", "auth", "credential", "private_key",
})


def _mask_string(value: str) -> str:
    """문자열 값에서 민감 패턴을 마스킹한다."""
    for _name, pattern in _MASK_PATTERNS:
        value = pattern.sub(lambda m: m.group(0)[:4] + "****", value)
    return value


def sensitive_data_masker(
    logger: Any, method: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """로그 이벤트 딕셔너리의 민감 키/값을 마스킹하는 프로세서."""
    for key in list(event_dict.keys()):
        if key.lower() in _SENSITIVE_KEYS:
            event_dict[key] = "****"
        elif isinstance(event_dict[key], str):
            event_dict[key] = _mask_string(event_dict[key])
    return event_dict


def agent_context_injector(
    logger: Any, method: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """structlog contextvars에서 에이전트 컨텍스트를 이벤트 딕셔너리에 추가한다.

    bind_agent_context()로 바인딩된 값이 자동으로 여기에 주입된다.
    """
    # structlog contextvars merge는 merge_contextvars 프로세서가 담당.
    # 이 프로세서는 필드 정규화만 수행.
    for key in ("agent_name", "agent_role", "project_id", "pipeline_id", "task_id"):
        val = event_dict.get(key)
        if val is not None:
            event_dict[key] = str(val)
    return event_dict


class TimingProcessor:
    """with_timing() 컨텍스트에서 경과 시간을 자동으로 기록하는 프로세서.

    event_dict에 "_start_time" 키가 있으면 elapsed_ms를 계산해 추가한다.
    """

    def __call__(
        self, logger: Any, method: str, event_dict: dict[str, Any]
    ) -> dict[str, Any]:
        start = event_dict.pop("_start_time", None)
        if start is not None:
            elapsed = (time.perf_counter() - start) * 1000
            event_dict["elapsed_ms"] = round(elapsed, 2)
        return event_dict


def token_usage_normalizer(
    logger: Any, method: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """토큰 사용량 필드를 정규화한다.

    input_tokens + output_tokens → total_tokens 자동 계산.
    cost_usd가 있으면 소수점 6자리로 정규화.
    """
    inp = event_dict.get("input_tokens")
    out = event_dict.get("output_tokens")
    if inp is not None and out is not None:
        event_dict.setdefault("total_tokens", int(inp) + int(out))
    if "cost_usd" in event_dict:
        event_dict["cost_usd"] = round(float(event_dict["cost_usd"]), 6)
    return event_dict
