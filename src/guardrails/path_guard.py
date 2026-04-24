"""PathGuard — 파일 경로 보호 및 설정 파일 변경 감지."""

from __future__ import annotations

import fnmatch
import logging
from dataclasses import dataclass, field

from src.guardrails.policy import GuardrailPolicy
from src.orchestrator.handoff import HandoffArtifact

logger = logging.getLogger(__name__)

# 기본 민감 파일 패턴 (extra_protected_paths에 없어도 항상 보호)
_ALWAYS_PROTECTED: list[str] = [
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "id_rsa",
    "id_ed25519",
]


@dataclass
class PathViolation:
    """탐지된 경로 보호 위반."""

    path: str
    violation_type: str    # "protected_path" | "sensitive_file" | "config_change"
    matched_pattern: str
    severity: str          # "high" | "medium"
    requires_human_gate: bool = False


@dataclass
class PathGuardResult:
    """경로 보호 검증 결과."""

    passed: bool
    violations: list[PathViolation] = field(default_factory=list)
    requires_human_gate: bool = False

    @property
    def blocked_paths(self) -> list[str]:
        return [v.path for v in self.violations if v.severity == "high"]

    @property
    def config_changes(self) -> list[str]:
        return [v.path for v in self.violations if v.violation_type == "config_change"]


class PathGuard:
    """파일 경로 보호 검증.

    git_executor.GitExecutor.validate_protected_paths()는 커밋 직전 차단에 초점.
    PathGuard는 코드 생성/제안 단계에서 조기 탐지해 Human Gate를 유도한다.
    """

    def __init__(
        self,
        protected_paths: list[str] | None = None,
        policy: GuardrailPolicy | None = None,
    ) -> None:
        self._protected_paths = protected_paths or []
        self._policy = policy or GuardrailPolicy()

    def check_handoff(self, handoff: HandoffArtifact) -> PathGuardResult:
        """HandoffArtifact의 changed_files를 검사한다."""
        changed_paths = [cf.path for cf in handoff.artifacts.changed_files]
        return self.check_paths(changed_paths)

    def check_paths(self, paths: list[str]) -> PathGuardResult:
        """파일 경로 목록을 검사하고 위반 사항을 반환한다."""
        violations: list[PathViolation] = []

        for path in paths:
            violations.extend(self._check_single_path(path))

        requires_human = any(v.requires_human_gate for v in violations)

        # 항상 보호 경로 → blocked(high) → passed=False
        # 설정 파일 변경 → requires_human_gate=True (통과는 하지만 Human Gate 강제)
        high_violations = [v for v in violations if v.severity == "high"]
        passed = len(high_violations) == 0

        result = PathGuardResult(
            passed=passed,
            violations=violations,
            requires_human_gate=requires_human,
        )

        if violations:
            level = logging.ERROR if not passed else logging.WARNING
            logger.log(
                level,
                "PathGuard: %d violation(s) on paths %s [passed=%s, human_gate=%s]",
                len(violations),
                [v.path for v in violations],
                passed,
                requires_human,
            )

        return result

    def _check_single_path(self, path: str) -> list[PathViolation]:
        found: list[PathViolation] = []

        # 1. 항상 보호 패턴 (최우선)
        for pattern in _ALWAYS_PROTECTED:
            if self._path_matches(path, pattern):
                found.append(PathViolation(
                    path=path,
                    violation_type="sensitive_file",
                    matched_pattern=pattern,
                    severity="high",
                    requires_human_gate=True,
                ))
                return found  # 이미 high — 더 검사 불필요

        # 2. GitConfig.protected_paths
        for protected in self._protected_paths:
            matched = (
                path.startswith(protected)
                or path == protected
                or self._path_matches(path, protected)
            )
            if matched:
                found.append(PathViolation(
                    path=path,
                    violation_type="protected_path",
                    matched_pattern=protected,
                    severity="high",
                    requires_human_gate=True,
                ))
                return found

        # 3. GuardrailPolicy.extra_protected_paths
        for pattern in self._policy.extra_protected_paths:
            if path.startswith(pattern) or path == pattern or self._path_matches(path, pattern):
                found.append(PathViolation(
                    path=path,
                    violation_type="protected_path",
                    matched_pattern=pattern,
                    severity="high",
                    requires_human_gate=True,
                ))
                return found

        # 4. 설정 파일 패턴 (Human Gate 강제이지만 차단은 아님)
        if self._policy.force_human_gate_on_config_change:
            for pattern in self._policy.config_file_patterns:
                if self._path_matches(path, pattern) or path.startswith(pattern):
                    found.append(PathViolation(
                        path=path,
                        violation_type="config_change",
                        matched_pattern=pattern,
                        severity="medium",
                        requires_human_gate=True,
                    ))
                    break

        return found

    @staticmethod
    def _path_matches(path: str, pattern: str) -> bool:
        """fnmatch 글로브 매칭. 경로 마지막 컴포넌트와 전체 경로 모두 비교한다."""
        basename = path.rsplit("/", 1)[-1]
        return fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(basename, pattern)
