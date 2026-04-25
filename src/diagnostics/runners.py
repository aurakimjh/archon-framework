"""진단 도구 실행기 — ruff, mypy를 subprocess로 실행하고 결과를 파싱한다."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from src.diagnostics.models import DiagnosticItem, DiagnosticSeverity

logger = logging.getLogger(__name__)


async def _run_subprocess(cmd: list[str], cwd: str | None = None) -> tuple[int, str, str]:
    """비동기 subprocess 실행. (returncode, stdout, stderr) 반환."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        stdout_bytes, stderr_bytes = await proc.communicate()
        return (
            proc.returncode or 0,
            stdout_bytes.decode(errors="replace"),
            stderr_bytes.decode(errors="replace"),
        )
    except FileNotFoundError:
        logger.debug("Command not found: %s", cmd[0])
        return -1, "", f"{cmd[0]} not found"


# ---------------------------------------------------------------------------
# Ruff (lint)
# ---------------------------------------------------------------------------

_RUFF_SEVERITY_MAP: dict[str, DiagnosticSeverity] = {
    "E": DiagnosticSeverity.ERROR,      # pycodestyle error
    "F": DiagnosticSeverity.ERROR,      # pyflakes
    "W": DiagnosticSeverity.WARNING,    # pycodestyle warning
    "C": DiagnosticSeverity.WARNING,    # convention
    "I": DiagnosticSeverity.INFO,       # isort
    "N": DiagnosticSeverity.INFO,       # pep8-naming
    "D": DiagnosticSeverity.HINT,       # docstring
}


def _ruff_severity(code: str) -> DiagnosticSeverity:
    """ruff 룰 코드에서 심각도를 추정한다."""
    if not code:
        return DiagnosticSeverity.WARNING
    return _RUFF_SEVERITY_MAP.get(code[0], DiagnosticSeverity.WARNING)


def parse_ruff_output(stdout: str) -> list[DiagnosticItem]:
    """ruff --output-format json 출력을 파싱한다."""
    if not stdout.strip():
        return []
    try:
        data = json.loads(stdout)
    except (json.JSONDecodeError, ValueError):
        logger.debug("Failed to parse ruff JSON output")
        return []

    items: list[DiagnosticItem] = []
    for entry in data if isinstance(data, list) else []:
        code = entry.get("code", "")
        loc = entry.get("location", {})
        end_loc = entry.get("end_location", {})
        items.append(DiagnosticItem(
            file=entry.get("filename", ""),
            line=loc.get("row", 0),
            column=loc.get("column", 0),
            end_line=end_loc.get("row"),
            end_column=end_loc.get("column"),
            severity=_ruff_severity(code),
            message=entry.get("message", ""),
            source="ruff",
            code=code,
        ))
    return items


async def run_ruff(
    paths: list[str],
    *,
    cwd: str | None = None,
    select: list[str] | None = None,
    timeout: float = 30.0,
) -> list[DiagnosticItem]:
    """ruff check를 실행하고 DiagnosticItem 리스트를 반환한다.

    Args:
        paths: 검사할 파일/디렉토리 경로.
        cwd: 작업 디렉토리.
        select: 활성화할 ruff 룰 (예: ["E", "F", "W"]).
        timeout: 타임아웃 (초).
    """
    cmd = ["ruff", "check", "--output-format", "json"]
    if select:
        cmd.extend(["--select", ",".join(select)])
    cmd.extend(paths)

    try:
        rc, stdout, stderr = await asyncio.wait_for(
            _run_subprocess(cmd, cwd=cwd),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        logger.warning("ruff timed out after %.0fs", timeout)
        return []

    if rc == -1:
        return []  # ruff not installed

    return parse_ruff_output(stdout)


# ---------------------------------------------------------------------------
# Mypy (type check)
# ---------------------------------------------------------------------------

_MYPY_SEVERITY_MAP: dict[str, DiagnosticSeverity] = {
    "error": DiagnosticSeverity.ERROR,
    "warning": DiagnosticSeverity.WARNING,
    "note": DiagnosticSeverity.INFO,
}


def parse_mypy_output(stdout: str) -> list[DiagnosticItem]:
    """mypy --output json 출력을 파싱한다."""
    if not stdout.strip():
        return []

    items: list[DiagnosticItem] = []
    for line in stdout.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue

        severity_str = entry.get("severity", "error")
        items.append(DiagnosticItem(
            file=entry.get("file", ""),
            line=entry.get("line", 0),
            column=entry.get("column", 0),
            severity=_MYPY_SEVERITY_MAP.get(severity_str, DiagnosticSeverity.ERROR),
            message=entry.get("message", ""),
            source="mypy",
            code=entry.get("code", ""),
        ))
    return items


async def run_mypy(
    paths: list[str],
    *,
    cwd: str | None = None,
    timeout: float = 60.0,
) -> list[DiagnosticItem]:
    """mypy를 실행하고 DiagnosticItem 리스트를 반환한다.

    Args:
        paths: 검사할 파일/디렉토리 경로.
        cwd: 작업 디렉토리.
        timeout: 타임아웃 (초).
    """
    cmd = ["mypy", "--output", "json", "--no-error-summary"]
    cmd.extend(paths)

    try:
        rc, stdout, stderr = await asyncio.wait_for(
            _run_subprocess(cmd, cwd=cwd),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        logger.warning("mypy timed out after %.0fs", timeout)
        return []

    if rc == -1:
        return []  # mypy not installed

    return parse_mypy_output(stdout)
