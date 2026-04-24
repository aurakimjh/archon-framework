"""OutputValidator — LLM 응답 출력 검증."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from src.guardrails.policy import GuardrailPolicy

logger = logging.getLogger(__name__)

# --- 위험 코드 패턴 ---

_DANGEROUS_CODE_PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    # (name, pattern, severity)
    ("rm_rf", re.compile(r"\brm\s+-[^\s]*r[^\s]*f\b|\brm\s+-rf\b", re.IGNORECASE), "high"),
    ("drop_table", re.compile(r"\bDROP\s+TABLE\b", re.IGNORECASE), "high"),
    ("truncate_table", re.compile(r"\bTRUNCATE\s+TABLE\b", re.IGNORECASE), "high"),
    (
        "delete_where_1",
        re.compile(r"\bDELETE\s+FROM\s+\w+\s+WHERE\s+1\s*=\s*1", re.IGNORECASE),
        "high",
    ),
    ("eval_exec", re.compile(r"\beval\s*\(|exec\s*\(", re.IGNORECASE), "medium"),
    (
        "subprocess_shell",
        re.compile(r"subprocess\.\w+\([^)]*shell\s*=\s*True", re.IGNORECASE),
        "medium",
    ),
    ("os_system", re.compile(r"\bos\.system\s*\(", re.IGNORECASE), "medium"),
    ("pickle_load", re.compile(r"\bpickle\.loads?\s*\(", re.IGNORECASE), "medium"),
    ("yaml_unsafe_load", re.compile(r"\byaml\.load\s*\([^)]*\)", re.IGNORECASE), "medium"),
    (
        "format_string_injection",
        re.compile(r'%\s*\(\s*\w+\s*\)\s*[sdf]|\.format\s*\([^)]*\w+\s*=', re.IGNORECASE),
        "low",
    ),
]

# --- 보안 취약점 패턴 ---

_SECURITY_PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    ("hardcoded_secret", re.compile(
        r'(?:password|secret|api_key|token)\s*=\s*["\'][^"\']{8,}["\']',
        re.IGNORECASE,
    ), "high"),
    ("sql_injection_risk", re.compile(
        r'f["\'].*\b(?:SELECT|INSERT|UPDATE|DELETE)\b.*\{',
        re.IGNORECASE,
    ), "high"),
    ("xss_risk", re.compile(
        r'innerHTML\s*=\s*(?!`[^`]*`)["\']?[^"\']*\$\{|dangerouslySetInnerHTML',
        re.IGNORECASE,
    ), "medium"),
    ("insecure_random", re.compile(
        r'\brandom\.random\(\)|\bmath\.random\(\)',
        re.IGNORECASE,
    ), "low"),
    ("debug_mode_on", re.compile(
        r'\bDEBUG\s*=\s*True|\bapp\.run\s*\([^)]*debug\s*=\s*True',
        re.IGNORECASE,
    ), "medium"),
    ("assert_in_prod", re.compile(
        r'^\s*assert\s+.+,\s*["\']',
        re.MULTILINE,
    ), "low"),
]

# --- 환각 탐지 힌트 패턴 ---
# 존재 가능성이 낮은 모듈/함수 참조를 감지한다.

_HALLUCINATION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("nonexistent_stdlib", re.compile(
        r'\bimport\s+(?:requests2|urllib4|json2|os2|sys2|asyncio2)\b',
        re.IGNORECASE,
    )),
    ("nonexistent_method", re.compile(
        r'\b(?:str|list|dict|int|float)\.\b(?:from_json|to_json|serialize|deserialize)\s*\(',
        re.IGNORECASE,
    )),
    ("version_mismatch_hint", re.compile(
        r'(?:python|django|flask|fastapi)\s+\d+\.\d+\s+(?:added|introduced|supports?)\s+',
        re.IGNORECASE,
    )),
]


@dataclass
class OutputViolation:
    """탐지된 출력 검증 위반."""

    violation_type: str      # "dangerous_code" | "security_pattern" | "hallucination_hint"
    pattern_name: str
    severity: str            # "high" | "medium" | "low"
    excerpt: str             # 탐지된 텍스트 일부 (최대 120자)
    line_number: int = 0


@dataclass
class OutputValidationResult:
    """출력 검증 결과."""

    passed: bool
    violations: list[OutputViolation] = field(default_factory=list)
    hallucination_hints: list[OutputViolation] = field(default_factory=list)

    @property
    def has_high_severity(self) -> bool:
        return any(v.severity == "high" for v in self.violations)

    @property
    def high_violations(self) -> list[OutputViolation]:
        return [v for v in self.violations if v.severity == "high"]

    @property
    def medium_violations(self) -> list[OutputViolation]:
        return [v for v in self.violations if v.severity == "medium"]


def _extract_excerpt(text: str, match: re.Match[str], context: int = 30) -> str:
    start = max(0, match.start() - context)
    end = min(len(text), match.end() + context)
    return text[start:end].strip()[:120]


def _get_line_number(text: str, pos: int) -> int:
    return text[:pos].count("\n") + 1


class OutputValidator:
    """LLM 호출 후 응답 출력 검증."""

    def __init__(self, policy: GuardrailPolicy | None = None) -> None:
        self._policy = policy or GuardrailPolicy()

    def validate(self, output: str) -> OutputValidationResult:
        """LLM 출력 전체를 검증한다."""
        violations: list[OutputViolation] = []
        hallucinations: list[OutputViolation] = []

        if self._policy.detect_dangerous_code:
            violations.extend(self._check_dangerous_code(output))

        if self._policy.detect_security_patterns:
            violations.extend(self._check_security_patterns(output))

        hallucinations.extend(self._check_hallucination_hints(output))

        # 정책에 따라 통과 여부 결정
        if self._policy.output_violation_action == "warn":
            # warn 모드: 항상 통과, 단 high severity만 경고
            passed = True
        else:
            # block 모드: high severity 위반 시 차단
            passed = not any(v.severity == "high" for v in violations)

        result = OutputValidationResult(
            passed=passed,
            violations=violations,
            hallucination_hints=hallucinations,
        )

        if violations or hallucinations:
            level = logging.WARNING if passed else logging.ERROR
            logger.log(
                level,
                "OutputValidator: %d violation(s), %d hallucination hint(s) [action=%s]",
                len(violations),
                len(hallucinations),
                self._policy.output_violation_action,
            )

        return result

    def _check_dangerous_code(self, text: str) -> list[OutputViolation]:
        found: list[OutputViolation] = []
        for name, pattern, severity in _DANGEROUS_CODE_PATTERNS:
            for match in pattern.finditer(text):
                found.append(OutputViolation(
                    violation_type="dangerous_code",
                    pattern_name=name,
                    severity=severity,
                    excerpt=_extract_excerpt(text, match),
                    line_number=_get_line_number(text, match.start()),
                ))
        return found

    def _check_security_patterns(self, text: str) -> list[OutputViolation]:
        found: list[OutputViolation] = []
        for name, pattern, severity in _SECURITY_PATTERNS:
            for match in pattern.finditer(text):
                found.append(OutputViolation(
                    violation_type="security_pattern",
                    pattern_name=name,
                    severity=severity,
                    excerpt=_extract_excerpt(text, match),
                    line_number=_get_line_number(text, match.start()),
                ))
        return found

    def _check_hallucination_hints(self, text: str) -> list[OutputViolation]:
        found: list[OutputViolation] = []
        for name, pattern in _HALLUCINATION_PATTERNS:
            for match in pattern.finditer(text):
                found.append(OutputViolation(
                    violation_type="hallucination_hint",
                    pattern_name=name,
                    severity="low",
                    excerpt=_extract_excerpt(text, match),
                    line_number=_get_line_number(text, match.start()),
                ))
        return found
