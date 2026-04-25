"""Diagnostic Whisper — 에이전트 프롬프트에 LSP 진단을 실시간 주입한다.

에이전트가 코드를 생성/수정할 때, 변경 파일에 대해 ruff/mypy 진단을 실행하고
결과를 프롬프트 컨텍스트로 주입하여 할루시네이션을 방지한다.
"""

from __future__ import annotations

import logging
from typing import Any

from src.diagnostics.models import (
    DiagnosticItem,
    DiagnosticSeverity,
    DiagnosticSummary,
)
from src.diagnostics.runners import run_mypy, run_ruff
from src.log import get_logger

logger = logging.getLogger(__name__)
_slog = get_logger(__name__)


class DiagnosticWhisper:
    """코드 진단 결과를 에이전트 ��텍스트에 주입한다.

    사용 흐름:
    1. 에이전트가 코드를 생성/수정
    2. `diagnose(paths)` 호출 → ruff + mypy 진단 실행
    3. `format_whisper(summary)` → 프롬프트 주입용 텍스트 생성
    4. 에이전트의 다음 LLM 호출에 whisper 텍스트를 주입
    """

    def __init__(
        self,
        enable_ruff: bool = True,
        enable_mypy: bool = True,
        max_items: int = 20,
        severity_threshold: DiagnosticSeverity = DiagnosticSeverity.WARNING,
        ruff_select: list[str] | None = None,
    ) -> None:
        """
        Args:
            enable_ruff: ruff 진단 활성화.
            enable_mypy: mypy 진단 활성화.
            max_items: 프롬프트에 주입할 최대 진단 항목 수.
            severity_threshold: 이 심각도 이상만 포함.
            ruff_select: ruff에서 활성화할 룰.
        """
        self._enable_ruff = enable_ruff
        self._enable_mypy = enable_mypy
        self._max_items = max_items
        self._severity_threshold = severity_threshold
        self._ruff_select = ruff_select
        self._last_summary: DiagnosticSummary | None = None

    @property
    def last_summary(self) -> DiagnosticSummary | None:
        """마지막 진단 결과."""
        return self._last_summary

    async def diagnose(
        self,
        paths: list[str],
        *,
        cwd: str | None = None,
    ) -> DiagnosticSummary:
        """지정 경로에 대해 진단을 실행한다.

        Args:
            paths: 검사할 파일/디렉토리 경로.
            cwd: 작업 디렉토리.

        Returns:
            진단 결과 요약.
        """
        all_items: list[DiagnosticItem] = []

        if self._enable_ruff:
            ruff_items = await run_ruff(
                paths, cwd=cwd, select=self._ruff_select,
            )
            all_items.extend(ruff_items)

        if self._enable_mypy:
            mypy_items = await run_mypy(paths, cwd=cwd)
            all_items.extend(mypy_items)

        # severity 필터링
        filtered = self._filter_by_severity(all_items)

        summary = DiagnosticSummary.from_items(filtered)
        self._last_summary = summary

        _slog.info(
            "diagnostic_complete",
            paths=paths,
            total=summary.total,
            errors=summary.error_count,
            warnings=summary.warning_count,
            sources=summary.sources,
        )
        return summary

    def format_whisper(
        self,
        summary: DiagnosticSummary | None = None,
    ) -> str:
        """진단 결과를 에이전트 프롬프트 주입용 텍스트로 포맷한다.

        Args:
            summary: 진단 결과. None이면 last_summary 사용.

        Returns:
            프롬프트에 주입할 텍스트. 진단 결과가 없으면 빈 문자열.
        """
        target = summary or self._last_summary
        if not target or not target.items:
            return ""

        items_to_show = target.items[: self._max_items]
        lines = [
            f"⚠ Code diagnostics found {target.total} issue(s) "
            f"({target.error_count} errors, {target.warning_count} warnings):",
            "",
        ]
        for item in items_to_show:
            lines.append(f"  {item.format_short()}")

        if target.total > self._max_items:
            lines.append(f"  ... and {target.total - self._max_items} more")

        lines.append("")
        lines.append("Fix these issues in your output to avoid regressions.")
        return "\n".join(lines)

    async def diagnose_and_format(
        self,
        paths: list[str],
        *,
        cwd: str | None = None,
    ) -> str:
        """진단 실행 + 포맷을 한번에 수행한다."""
        summary = await self.diagnose(paths, cwd=cwd)
        return self.format_whisper(summary)

    def _filter_by_severity(
        self, items: list[DiagnosticItem],
    ) -> list[DiagnosticItem]:
        """severity_threshold 이상만 필터링한다."""
        severity_order = [
            DiagnosticSeverity.HINT,
            DiagnosticSeverity.INFO,
            DiagnosticSeverity.WARNING,
            DiagnosticSeverity.ERROR,
        ]
        threshold_idx = severity_order.index(self._severity_threshold)
        return [
            item for item in items
            if severity_order.index(item.severity) >= threshold_idx
        ]
