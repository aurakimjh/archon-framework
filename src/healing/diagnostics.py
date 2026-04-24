"""AgentDiagnostician — 에이전트 장애 원인 진단 및 리포트 생성."""

from __future__ import annotations

import re
import time
from collections import Counter
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from src.log import get_logger

slog = get_logger(__name__)


class ErrorCategory(StrEnum):
    LLM_TIMEOUT = "llm_timeout"
    RATE_LIMIT = "rate_limit"
    AUTH_FAILURE = "auth_failure"
    OOM = "out_of_memory"
    NETWORK = "network_error"
    VALIDATION = "validation_error"
    CONTEXT_LENGTH = "context_length_exceeded"
    UNKNOWN = "unknown"


class RootCause(StrEnum):
    LLM_SERVER_DOWN = "llm_server_down"
    PROMPT_ISSUE = "prompt_issue"
    NETWORK_INSTABILITY = "network_instability"
    RESOURCE_EXHAUSTION = "resource_exhaustion"
    AUTH_MISCONFIGURATION = "auth_misconfiguration"
    RATE_LIMIT_QUOTA = "rate_limit_quota"
    INPUT_TOO_LARGE = "input_too_large"
    UNKNOWN = "unknown"


@dataclass
class ErrorRecord:
    """단일 에러 기록."""

    error_message: str
    category: ErrorCategory
    timestamp: float = field(default_factory=time.monotonic)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class DiagnosticReport:
    """에이전트 진단 결과."""

    agent_role: str
    error_count: int
    dominant_category: ErrorCategory
    root_cause: RootCause
    pattern_summary: str
    repeated_errors: list[tuple[str, int]]  # (error_snippet, count)
    recommendations: list[str]
    confidence: float  # 0.0–1.0
    generated_at: float = field(default_factory=time.monotonic)

    def as_dict(self) -> dict[str, Any]:
        return {
            "agent_role": self.agent_role,
            "error_count": self.error_count,
            "dominant_category": self.dominant_category,
            "root_cause": self.root_cause,
            "pattern_summary": self.pattern_summary,
            "repeated_errors": [
                {"snippet": s, "count": c} for s, c in self.repeated_errors
            ],
            "recommendations": self.recommendations,
            "confidence": round(self.confidence, 3),
            "generated_at": self.generated_at,
        }


# ---------------------------------------------------------------------------
# Error classification patterns
# ---------------------------------------------------------------------------

_CATEGORY_PATTERNS: list[tuple[ErrorCategory, list[str]]] = [
    (
        ErrorCategory.LLM_TIMEOUT,
        [r"timeout", r"timed out", r"read timeout", r"connect timeout", r"deadline"],
    ),
    (
        ErrorCategory.RATE_LIMIT,
        [r"rate.?limit", r"429", r"too many requests", r"quota exceeded", r"throttl"],
    ),
    (
        ErrorCategory.AUTH_FAILURE,
        [r"401", r"403", r"unauthorized", r"authentication", r"api.?key", r"invalid.?key"],
    ),
    (
        ErrorCategory.OOM,
        [r"out of memory", r"memory error", r"oom", r"killed", r"cannot allocate"],
    ),
    (
        ErrorCategory.CONTEXT_LENGTH,
        [r"context.?length", r"max.?token", r"too.?long", r"input.?exceed", r"token.?limit"],
    ),
    (
        ErrorCategory.NETWORK,
        [r"connection.?error", r"connection.?refused", r"network", r"dns", r"socket", r"host"],
    ),
    (
        ErrorCategory.VALIDATION,
        [r"validation.?error", r"invalid.?input", r"schema", r"pydantic", r"json.?decode"],
    ),
]

_ROOT_CAUSE_MAP: dict[tuple[ErrorCategory, ...], RootCause] = {
    (ErrorCategory.LLM_TIMEOUT, ErrorCategory.NETWORK): RootCause.LLM_SERVER_DOWN,
    (ErrorCategory.RATE_LIMIT,): RootCause.RATE_LIMIT_QUOTA,
    (ErrorCategory.AUTH_FAILURE,): RootCause.AUTH_MISCONFIGURATION,
    (ErrorCategory.OOM,): RootCause.RESOURCE_EXHAUSTION,
    (ErrorCategory.CONTEXT_LENGTH,): RootCause.INPUT_TOO_LARGE,
    (ErrorCategory.VALIDATION,): RootCause.PROMPT_ISSUE,
    (ErrorCategory.NETWORK,): RootCause.NETWORK_INSTABILITY,
}

_RECOMMENDATIONS: dict[RootCause, list[str]] = {
    RootCause.LLM_SERVER_DOWN: [
        "Switch to a fallback LLM provider",
        "Enable CircuitBreaker to pause requests",
        "Check LLM provider status page",
    ],
    RootCause.RATE_LIMIT_QUOTA: [
        "Implement exponential backoff with jitter",
        "Distribute load across multiple API keys",
        "Upgrade API plan or reduce request rate",
    ],
    RootCause.AUTH_MISCONFIGURATION: [
        "Verify API key is valid and not expired",
        "Check environment variable configuration",
        "Rotate credentials if compromised",
    ],
    RootCause.RESOURCE_EXHAUSTION: [
        "Increase memory allocation for the process",
        "Reduce batch size or concurrency",
        "Switch to a model with lower memory footprint",
    ],
    RootCause.INPUT_TOO_LARGE: [
        "Truncate or summarize long context",
        "Switch to a model with larger context window",
        "Split task into smaller sub-tasks",
    ],
    RootCause.PROMPT_ISSUE: [
        "Review prompt structure for schema compliance",
        "Add input validation before LLM calls",
        "Test prompt with minimal input to isolate issue",
    ],
    RootCause.NETWORK_INSTABILITY: [
        "Retry with exponential backoff",
        "Check network connectivity and firewall rules",
        "Switch to a geographically closer endpoint",
    ],
    RootCause.UNKNOWN: [
        "Enable verbose logging to capture full stack traces",
        "Review recent changes to agent configuration",
        "Contact support with the diagnostic report",
    ],
}


def classify_error(error_message: str) -> ErrorCategory:
    """에러 메시지를 분석하여 ErrorCategory를 반환한다."""
    lower = error_message.lower()
    for category, patterns in _CATEGORY_PATTERNS:
        if any(re.search(p, lower) for p in patterns):
            return category
    return ErrorCategory.UNKNOWN


class AgentDiagnostician:
    """에이전트 에러 패턴을 분석하고 진단 리포트를 생성한다."""

    def __init__(self, agent_role: str, max_history: int = 50) -> None:
        self.agent_role = agent_role
        self._max_history = max_history
        self._errors: list[ErrorRecord] = []

    def record_error(self, error_message: str, **extra: Any) -> ErrorRecord:
        """에러를 기록하고 분류된 ErrorRecord를 반환한다."""
        category = classify_error(error_message)
        record = ErrorRecord(
            error_message=error_message,
            category=category,
            extra=extra,
        )
        self._errors.append(record)
        if len(self._errors) > self._max_history:
            self._errors = self._errors[-self._max_history :]
        slog.debug(
            "error_recorded",
            agent_role=self.agent_role,
            category=category,
            error=error_message[:120],
        )
        return record

    def analyze_patterns(self) -> dict[str, Any]:
        """최근 에러 패턴을 분석한다."""
        if not self._errors:
            return {"error_count": 0, "categories": {}, "repeated": []}

        category_counts = Counter(r.category for r in self._errors)
        snippet_counts: Counter[str] = Counter()
        for r in self._errors:
            snippet = r.error_message[:80].strip()
            snippet_counts[snippet] += 1

        repeated = [(s, c) for s, c in snippet_counts.most_common(5) if c > 1]

        return {
            "error_count": len(self._errors),
            "categories": dict(category_counts),
            "repeated": repeated,
        }

    def _estimate_root_cause(
        self, dominant: ErrorCategory, categories: dict[str, int]
    ) -> tuple[RootCause, float]:
        """지배적 에러 유형으로 근본 원인을 추정한다."""
        total = sum(categories.values()) or 1
        dominant_ratio = categories.get(dominant, 0) / total

        # 복합 패턴 먼저 체크 (timeout + network → server down)
        has_timeout = categories.get(ErrorCategory.LLM_TIMEOUT, 0) > 0
        has_network = categories.get(ErrorCategory.NETWORK, 0) > 0
        if has_timeout and has_network:
            return RootCause.LLM_SERVER_DOWN, min(0.85, dominant_ratio + 0.2)

        for key_tuple, cause in _ROOT_CAUSE_MAP.items():
            if dominant in key_tuple:
                confidence = min(0.9, dominant_ratio + 0.1)
                return cause, confidence

        return RootCause.UNKNOWN, 0.3

    def generate_report(self) -> DiagnosticReport:
        """현재까지의 에러 기록으로 진단 리포트를 생성한다."""
        analysis = self.analyze_patterns()
        error_count = analysis["error_count"]
        categories: dict[str, int] = analysis["categories"]
        repeated: list[tuple[str, int]] = analysis["repeated"]

        if not categories:
            return DiagnosticReport(
                agent_role=self.agent_role,
                error_count=0,
                dominant_category=ErrorCategory.UNKNOWN,
                root_cause=RootCause.UNKNOWN,
                pattern_summary="No errors recorded.",
                repeated_errors=[],
                recommendations=_RECOMMENDATIONS[RootCause.UNKNOWN],
                confidence=0.0,
            )

        dominant_str = max(categories, key=lambda k: categories[k])
        dominant = ErrorCategory(dominant_str)
        root_cause, confidence = self._estimate_root_cause(dominant, categories)

        category_desc = ", ".join(
            f"{k}×{v}" for k, v in sorted(categories.items(), key=lambda x: -x[1])
        )
        repeat_desc = (
            f" Repeated pattern detected ({repeated[0][1]}× same error)."
            if repeated
            else ""
        )
        pattern_summary = f"{error_count} errors: {category_desc}.{repeat_desc}"

        report = DiagnosticReport(
            agent_role=self.agent_role,
            error_count=error_count,
            dominant_category=dominant,
            root_cause=root_cause,
            pattern_summary=pattern_summary,
            repeated_errors=repeated,
            recommendations=_RECOMMENDATIONS.get(root_cause, _RECOMMENDATIONS[RootCause.UNKNOWN]),
            confidence=confidence,
        )
        slog.info(
            "diagnostic_report",
            agent_role=self.agent_role,
            root_cause=root_cause,
            dominant_category=dominant,
            confidence=confidence,
            error_count=error_count,
        )
        return report

    def clear(self) -> None:
        """에러 기록을 초기화한다."""
        self._errors.clear()


class DiagnosticRegistry:
    """전체 에이전트의 Diagnostician을 한 곳에서 관리한다."""

    def __init__(self) -> None:
        self._diagnosticians: dict[str, AgentDiagnostician] = {}

    def get(self, agent_role: str) -> AgentDiagnostician:
        if agent_role not in self._diagnosticians:
            self._diagnosticians[agent_role] = AgentDiagnostician(agent_role)
        return self._diagnosticians[agent_role]

    def all_reports(self) -> list[DiagnosticReport]:
        return [d.generate_report() for d in self._diagnosticians.values()]
