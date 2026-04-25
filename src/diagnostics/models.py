"""진단 결과 모델."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class DiagnosticSeverity(StrEnum):
    """진단 심각도 — LSP DiagnosticSeverity와 동일."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"
    HINT = "hint"


class DiagnosticItem(BaseModel):
    """단일 진단 항목."""

    file: str
    line: int = 0
    column: int = 0
    severity: DiagnosticSeverity = DiagnosticSeverity.ERROR
    message: str
    source: str = ""       # ruff, mypy, pyright 등
    code: str = ""         # 룰 코드 (E501, type-error 등)
    end_line: int | None = None
    end_column: int | None = None

    def format_short(self) -> str:
        """한 줄 요약 포맷."""
        loc = f"{self.file}:{self.line}"
        if self.column:
            loc += f":{self.column}"
        code_str = f" [{self.code}]" if self.code else ""
        return f"{loc} {self.severity}{code_str}: {self.message}"


class DiagnosticSummary(BaseModel):
    """진단 결과 요약."""

    items: list[DiagnosticItem] = Field(default_factory=list)
    error_count: int = 0
    warning_count: int = 0
    info_count: int = 0
    sources: list[str] = Field(default_factory=list)

    @classmethod
    def from_items(cls, items: list[DiagnosticItem]) -> DiagnosticSummary:
        """DiagnosticItem 리스트에서 요약을 생성한다."""
        errors = sum(1 for i in items if i.severity == DiagnosticSeverity.ERROR)
        warnings = sum(1 for i in items if i.severity == DiagnosticSeverity.WARNING)
        infos = sum(
            1 for i in items
            if i.severity in (DiagnosticSeverity.INFO, DiagnosticSeverity.HINT)
        )
        sources = sorted({i.source for i in items if i.source})
        return cls(
            items=items,
            error_count=errors,
            warning_count=warnings,
            info_count=infos,
            sources=sources,
        )

    @property
    def has_errors(self) -> bool:
        return self.error_count > 0

    @property
    def total(self) -> int:
        return len(self.items)
