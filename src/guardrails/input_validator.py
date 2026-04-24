"""InputValidator — LLM 호출 전 프롬프트/컨텍스트 검증."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from src.guardrails.policy import GuardrailPolicy

logger = logging.getLogger(__name__)

# --- 민감 정보 탐지 패턴 ---

_SENSITIVE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("api_key", re.compile(
        r"(?:api[_\-]?key|apikey)\s*[=:]\s*['\"]?[\w\-]{20,}",
        re.IGNORECASE,
    )),
    ("aws_key", re.compile(
        r"AKIA[0-9A-Z]{16}",
    )),
    ("private_key", re.compile(
        r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
    )),
    ("password", re.compile(
        r"(?:password|passwd|pwd)\s*[=:]\s*['\"]?[^\s'\"]{6,}",
        re.IGNORECASE,
    )),
    ("jwt_token", re.compile(
        r"eyJ[A-Za-z0-9\-_]{10,}\.[A-Za-z0-9\-_]{10,}\.[A-Za-z0-9\-_]{10,}",
    )),
    ("credit_card", re.compile(
        r"\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13})\b",
    )),
    ("ssn", re.compile(
        r"\b\d{3}-\d{2}-\d{4}\b",
    )),
]

# --- 프롬프트 인젝션 탐지 패턴 ---

_INJECTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("ignore_instructions", re.compile(
        r"ignore\s+(?:previous|all|above|prior|your)\s+(?:instructions?|prompts?|context|rules?)",
        re.IGNORECASE,
    )),
    ("system_override", re.compile(
        r"(?:new\s+)?system\s*:\s*you\s+are|act\s+as\s+(?:a\s+)?(?:new|different|unrestricted)",
        re.IGNORECASE,
    )),
    ("jailbreak", re.compile(
        r"(?:DAN|jailbreak|do\s+anything\s+now|pretend\s+you\s+have\s+no\s+restrictions?)",
        re.IGNORECASE,
    )),
    ("role_override", re.compile(
        r"forget\s+(?:all\s+)?(?:previous\s+)?(?:instructions?|context|rules?|training)",
        re.IGNORECASE,
    )),
    ("leaked_prompt", re.compile(
        r"print\s+(?:your\s+)?(?:system\s+)?prompt|reveal\s+(?:your\s+)?(?:system\s+)?(?:prompt|instructions?)",
        re.IGNORECASE,
    )),
]


@dataclass
class InputViolation:
    """탐지된 입력 검증 위반."""

    violation_type: str       # sensitive_data | prompt_injection | token_limit | forbidden_keyword
    pattern_name: str         # 구체적인 패턴 이름
    severity: str             # "high" | "medium" | "low"
    excerpt: str              # 탐지된 텍스트 일부 (최대 80자, 마스킹)
    location: str = ""        # "system_prompt" | "user_prompt" | "context"


@dataclass
class InputValidationResult:
    """입력 검증 결과."""

    passed: bool
    violations: list[InputViolation] = field(default_factory=list)
    token_estimate: int = 0

    @property
    def has_high_severity(self) -> bool:
        return any(v.severity == "high" for v in self.violations)


def _mask_excerpt(text: str, match: re.Match[str], context: int = 20) -> str:
    """매칭된 텍스트 주변 일부를 마스킹해서 반환 (로그용)."""
    start = max(0, match.start() - context)
    end = min(len(text), match.end() + context)
    excerpt = text[start:end]
    # 매칭 부분 마스킹
    matched = match.group(0)
    masked = matched[:4] + "*" * max(0, len(matched) - 4)
    return excerpt.replace(matched, masked)[:80]


def _estimate_tokens(text: str) -> int:
    """간단한 토큰 추정 (영문 4자/토큰, 한글 2자/토큰 혼합 기준)."""
    korean_chars = sum(1 for c in text if "\uac00" <= c <= "\ud7a3")
    other_chars = len(text) - korean_chars
    return (korean_chars // 2) + (other_chars // 4)


class InputValidator:
    """LLM 호출 전 입력(프롬프트, 컨텍스트) 검증."""

    def __init__(self, policy: GuardrailPolicy | None = None) -> None:
        self._policy = policy or GuardrailPolicy()

    def validate(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        extra_context: str = "",
    ) -> InputValidationResult:
        """전체 입력을 검증하고 결과를 반환한다."""
        violations: list[InputViolation] = []
        full_text = "\n".join(filter(None, [system_prompt, user_prompt, extra_context]))

        token_estimate = _estimate_tokens(full_text)

        # 1. 토큰 수 제한
        if self._policy.max_input_tokens > 0 and token_estimate > self._policy.max_input_tokens:
            violations.append(InputViolation(
                violation_type="token_limit",
                pattern_name="max_input_tokens",
                severity="high",
                excerpt=(
                    f"estimated {token_estimate} tokens"
                    f" (limit: {self._policy.max_input_tokens})"
                ),
                location="full_input",
            ))

        inputs = [
            (system_prompt, "system_prompt"),
            (user_prompt, "user_prompt"),
            (extra_context, "context"),
        ]

        for text, location in inputs:
            if not text:
                continue

            # 2. 민감 정보 탐지
            if self._policy.detect_sensitive_data:
                violations.extend(
                    self._check_sensitive_data(text, location)
                )

            # 3. 프롬프트 인젝션 탐지
            if self._policy.detect_prompt_injection:
                violations.extend(
                    self._check_prompt_injection(text, location)
                )

            # 4. 금지 키워드 필터
            violations.extend(
                self._check_forbidden_keywords(text, location)
            )

        passed = not violations or (
            self._policy.input_violation_action == "warn"
            and not any(v.severity == "high" for v in violations)
        )

        result = InputValidationResult(
            passed=passed,
            violations=violations,
            token_estimate=token_estimate,
        )

        if violations:
            level = logging.WARNING if passed else logging.ERROR
            logger.log(
                level,
                "InputValidator: %d violation(s) — %s [action=%s]",
                len(violations),
                [v.pattern_name for v in violations],
                self._policy.input_violation_action,
            )

        return result

    def _check_sensitive_data(
        self, text: str, location: str
    ) -> list[InputViolation]:
        found: list[InputViolation] = []
        for name, pattern in _SENSITIVE_PATTERNS:
            match = pattern.search(text)
            if match:
                found.append(InputViolation(
                    violation_type="sensitive_data",
                    pattern_name=name,
                    severity="high",
                    excerpt=_mask_excerpt(text, match),
                    location=location,
                ))
        return found

    def _check_prompt_injection(
        self, text: str, location: str
    ) -> list[InputViolation]:
        found: list[InputViolation] = []
        for name, pattern in _INJECTION_PATTERNS:
            match = pattern.search(text)
            if match:
                found.append(InputViolation(
                    violation_type="prompt_injection",
                    pattern_name=name,
                    severity="high",
                    excerpt=_mask_excerpt(text, match),
                    location=location,
                ))
        return found

    def _check_forbidden_keywords(
        self, text: str, location: str
    ) -> list[InputViolation]:
        found: list[InputViolation] = []
        text_lower = text.lower()
        for keyword in self._policy.forbidden_keywords:
            if keyword.lower() in text_lower:
                idx = text_lower.index(keyword.lower())
                excerpt = text[max(0, idx - 10): idx + len(keyword) + 10]
                found.append(InputViolation(
                    violation_type="forbidden_keyword",
                    pattern_name=keyword,
                    severity="medium",
                    excerpt=excerpt[:80],
                    location=location,
                ))
        return found
