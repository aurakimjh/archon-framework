"""Diagnostic Whisper 테스트 — 모델, 파서, Whisper 통합."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from src.diagnostics.models import (
    DiagnosticItem,
    DiagnosticSeverity,
    DiagnosticSummary,
)
from src.diagnostics.runners import parse_mypy_output, parse_ruff_output, run_mypy, run_ruff
from src.diagnostics.whisper import DiagnosticWhisper


# ---------------------------------------------------------------------------
# DiagnosticItem
# ---------------------------------------------------------------------------


class TestDiagnosticItem:
    def test_defaults(self):
        item = DiagnosticItem(file="test.py", message="unused import")
        assert item.line == 0
        assert item.severity == DiagnosticSeverity.ERROR
        assert item.source == ""

    def test_format_short(self):
        item = DiagnosticItem(
            file="src/main.py",
            line=10,
            column=5,
            severity=DiagnosticSeverity.WARNING,
            message="unused variable",
            source="ruff",
            code="F841",
        )
        formatted = item.format_short()
        assert "src/main.py:10:5" in formatted
        assert "warning" in formatted
        assert "[F841]" in formatted
        assert "unused variable" in formatted

    def test_format_short_no_column(self):
        item = DiagnosticItem(
            file="test.py", line=5, message="error",
            severity=DiagnosticSeverity.ERROR,
        )
        assert "test.py:5 " in item.format_short()

    def test_format_short_no_code(self):
        item = DiagnosticItem(
            file="test.py", line=1, message="msg",
            severity=DiagnosticSeverity.INFO,
        )
        assert "[" not in item.format_short()


# ---------------------------------------------------------------------------
# DiagnosticSummary
# ---------------------------------------------------------------------------


class TestDiagnosticSummary:
    def test_from_items_empty(self):
        summary = DiagnosticSummary.from_items([])
        assert summary.total == 0
        assert summary.error_count == 0
        assert not summary.has_errors

    def test_from_items_mixed(self):
        items = [
            DiagnosticItem(file="a.py", message="e1", severity=DiagnosticSeverity.ERROR, source="ruff"),
            DiagnosticItem(file="a.py", message="w1", severity=DiagnosticSeverity.WARNING, source="ruff"),
            DiagnosticItem(file="b.py", message="i1", severity=DiagnosticSeverity.INFO, source="mypy"),
            DiagnosticItem(file="c.py", message="h1", severity=DiagnosticSeverity.HINT, source="ruff"),
        ]
        summary = DiagnosticSummary.from_items(items)
        assert summary.total == 4
        assert summary.error_count == 1
        assert summary.warning_count == 1
        assert summary.info_count == 2  # info + hint
        assert summary.has_errors
        assert set(summary.sources) == {"mypy", "ruff"}

    def test_defaults(self):
        summary = DiagnosticSummary()
        assert summary.total == 0
        assert not summary.has_errors


# ---------------------------------------------------------------------------
# Ruff parser
# ---------------------------------------------------------------------------


class TestRuffParser:
    def test_empty_output(self):
        assert parse_ruff_output("") == []
        assert parse_ruff_output("  ") == []

    def test_invalid_json(self):
        assert parse_ruff_output("not json") == []

    def test_valid_output(self):
        data = [
            {
                "code": "F401",
                "message": "unused import os",
                "filename": "src/main.py",
                "location": {"row": 1, "column": 1},
                "end_location": {"row": 1, "column": 10},
            },
            {
                "code": "E501",
                "message": "line too long",
                "filename": "src/main.py",
                "location": {"row": 5, "column": 80},
                "end_location": {"row": 5, "column": 120},
            },
        ]
        items = parse_ruff_output(json.dumps(data))
        assert len(items) == 2
        assert items[0].source == "ruff"
        assert items[0].code == "F401"
        assert items[0].severity == DiagnosticSeverity.ERROR  # F → error
        assert items[0].file == "src/main.py"
        assert items[0].line == 1
        assert items[1].code == "E501"
        assert items[1].severity == DiagnosticSeverity.ERROR  # E → error

    def test_warning_code(self):
        data = [{"code": "W291", "message": "trailing whitespace",
                 "filename": "x.py", "location": {"row": 1, "column": 1},
                 "end_location": {"row": 1, "column": 2}}]
        items = parse_ruff_output(json.dumps(data))
        assert items[0].severity == DiagnosticSeverity.WARNING

    def test_info_code(self):
        data = [{"code": "I001", "message": "import order",
                 "filename": "x.py", "location": {"row": 1, "column": 1},
                 "end_location": {"row": 1, "column": 2}}]
        items = parse_ruff_output(json.dumps(data))
        assert items[0].severity == DiagnosticSeverity.INFO


# ---------------------------------------------------------------------------
# Mypy parser
# ---------------------------------------------------------------------------


class TestMypyParser:
    def test_empty_output(self):
        assert parse_mypy_output("") == []

    def test_valid_output(self):
        lines = [
            json.dumps({
                "file": "src/main.py",
                "line": 10,
                "column": 5,
                "severity": "error",
                "message": "Incompatible types",
                "code": "assignment",
            }),
            json.dumps({
                "file": "src/main.py",
                "line": 20,
                "column": 0,
                "severity": "note",
                "message": "See docs",
                "code": "",
            }),
        ]
        items = parse_mypy_output("\n".join(lines))
        assert len(items) == 2
        assert items[0].source == "mypy"
        assert items[0].severity == DiagnosticSeverity.ERROR
        assert items[0].code == "assignment"
        assert items[1].severity == DiagnosticSeverity.INFO

    def test_mixed_valid_invalid(self):
        lines = [
            "not json line",
            json.dumps({"file": "a.py", "line": 1, "severity": "warning",
                        "message": "msg", "column": 0, "code": ""}),
        ]
        items = parse_mypy_output("\n".join(lines))
        assert len(items) == 1
        assert items[0].severity == DiagnosticSeverity.WARNING


# ---------------------------------------------------------------------------
# run_ruff / run_mypy (subprocess mock)
# ---------------------------------------------------------------------------


class TestRunRuff:
    @pytest.mark.asyncio
    async def test_ruff_success(self):
        ruff_data = [{"code": "F401", "message": "unused import",
                      "filename": "x.py", "location": {"row": 1, "column": 1},
                      "end_location": {"row": 1, "column": 5}}]
        with patch(
            "src.diagnostics.runners._run_subprocess",
            new_callable=AsyncMock,
            return_value=(1, json.dumps(ruff_data), ""),
        ):
            items = await run_ruff(["x.py"])
        assert len(items) == 1
        assert items[0].code == "F401"

    @pytest.mark.asyncio
    async def test_ruff_not_installed(self):
        with patch(
            "src.diagnostics.runners._run_subprocess",
            new_callable=AsyncMock,
            return_value=(-1, "", "ruff not found"),
        ):
            items = await run_ruff(["x.py"])
        assert items == []

    @pytest.mark.asyncio
    async def test_ruff_timeout(self):
        async def slow_run(*args, **kwargs):
            import asyncio
            await asyncio.sleep(10)
            return (0, "[]", "")

        with patch("src.diagnostics.runners._run_subprocess", side_effect=slow_run):
            items = await run_ruff(["x.py"], timeout=0.1)
        assert items == []

    @pytest.mark.asyncio
    async def test_ruff_with_select(self):
        with patch(
            "src.diagnostics.runners._run_subprocess",
            new_callable=AsyncMock,
            return_value=(0, "[]", ""),
        ) as mock_run:
            await run_ruff(["x.py"], select=["E", "F"])
        cmd = mock_run.call_args[0][0]
        assert "--select" in cmd
        assert "E,F" in cmd


class TestRunMypy:
    @pytest.mark.asyncio
    async def test_mypy_success(self):
        mypy_line = json.dumps({
            "file": "a.py", "line": 1, "column": 0,
            "severity": "error", "message": "type error", "code": "type-arg",
        })
        with patch(
            "src.diagnostics.runners._run_subprocess",
            new_callable=AsyncMock,
            return_value=(1, mypy_line, ""),
        ):
            items = await run_mypy(["a.py"])
        assert len(items) == 1

    @pytest.mark.asyncio
    async def test_mypy_not_installed(self):
        with patch(
            "src.diagnostics.runners._run_subprocess",
            new_callable=AsyncMock,
            return_value=(-1, "", "mypy not found"),
        ):
            items = await run_mypy(["a.py"])
        assert items == []


# ---------------------------------------------------------------------------
# DiagnosticWhisper
# ---------------------------------------------------------------------------


class TestDiagnosticWhisper:
    @pytest.mark.asyncio
    async def test_diagnose_combines_sources(self):
        ruff_data = [{"code": "F401", "message": "unused",
                      "filename": "x.py", "location": {"row": 1, "column": 1},
                      "end_location": {"row": 1, "column": 5}}]
        mypy_line = json.dumps({
            "file": "x.py", "line": 5, "column": 0,
            "severity": "error", "message": "type mismatch", "code": "",
        })

        with patch("src.diagnostics.whisper.run_ruff", new_callable=AsyncMock) as mock_ruff, \
             patch("src.diagnostics.whisper.run_mypy", new_callable=AsyncMock) as mock_mypy:
            mock_ruff.return_value = parse_ruff_output(json.dumps(ruff_data))
            mock_mypy.return_value = parse_mypy_output(mypy_line)

            whisper = DiagnosticWhisper()
            summary = await whisper.diagnose(["x.py"])

        assert summary.total == 2
        assert summary.error_count == 2
        assert set(summary.sources) == {"ruff", "mypy"}
        assert whisper.last_summary is summary

    @pytest.mark.asyncio
    async def test_diagnose_ruff_only(self):
        whisper = DiagnosticWhisper(enable_ruff=True, enable_mypy=False)

        with patch("src.diagnostics.whisper.run_ruff", new_callable=AsyncMock, return_value=[]), \
             patch("src.diagnostics.whisper.run_mypy", new_callable=AsyncMock) as mock_mypy:
            await whisper.diagnose(["x.py"])
            mock_mypy.assert_not_called()

    @pytest.mark.asyncio
    async def test_diagnose_mypy_only(self):
        whisper = DiagnosticWhisper(enable_ruff=False, enable_mypy=True)

        with patch("src.diagnostics.whisper.run_ruff", new_callable=AsyncMock) as mock_ruff, \
             patch("src.diagnostics.whisper.run_mypy", new_callable=AsyncMock, return_value=[]):
            await whisper.diagnose(["x.py"])
            mock_ruff.assert_not_called()

    def test_format_whisper_empty(self):
        whisper = DiagnosticWhisper()
        assert whisper.format_whisper() == ""
        assert whisper.format_whisper(DiagnosticSummary()) == ""

    def test_format_whisper_with_items(self):
        items = [
            DiagnosticItem(
                file="src/main.py", line=10, severity=DiagnosticSeverity.ERROR,
                message="unused import", source="ruff", code="F401",
            ),
            DiagnosticItem(
                file="src/main.py", line=20, severity=DiagnosticSeverity.WARNING,
                message="type mismatch", source="mypy", code="assignment",
            ),
        ]
        summary = DiagnosticSummary.from_items(items)
        whisper = DiagnosticWhisper()
        text = whisper.format_whisper(summary)

        assert "2 issue(s)" in text
        assert "1 errors" in text
        assert "1 warnings" in text
        assert "src/main.py:10" in text
        assert "F401" in text
        assert "Fix these issues" in text

    def test_format_whisper_truncation(self):
        items = [
            DiagnosticItem(
                file=f"f{i}.py", line=i, message=f"msg{i}",
                severity=DiagnosticSeverity.ERROR, source="ruff",
            )
            for i in range(30)
        ]
        summary = DiagnosticSummary.from_items(items)
        whisper = DiagnosticWhisper(max_items=5)
        text = whisper.format_whisper(summary)

        assert "and 25 more" in text

    def test_severity_threshold_filters(self):
        items = [
            DiagnosticItem(file="a.py", line=1, message="err",
                           severity=DiagnosticSeverity.ERROR, source="ruff"),
            DiagnosticItem(file="a.py", line=2, message="warn",
                           severity=DiagnosticSeverity.WARNING, source="ruff"),
            DiagnosticItem(file="a.py", line=3, message="info",
                           severity=DiagnosticSeverity.INFO, source="ruff"),
            DiagnosticItem(file="a.py", line=4, message="hint",
                           severity=DiagnosticSeverity.HINT, source="ruff"),
        ]
        # ERROR threshold — only errors
        whisper = DiagnosticWhisper(severity_threshold=DiagnosticSeverity.ERROR)
        filtered = whisper._filter_by_severity(items)
        assert len(filtered) == 1

        # WARNING threshold — errors + warnings
        whisper = DiagnosticWhisper(severity_threshold=DiagnosticSeverity.WARNING)
        filtered = whisper._filter_by_severity(items)
        assert len(filtered) == 2

        # INFO threshold — errors + warnings + info
        whisper = DiagnosticWhisper(severity_threshold=DiagnosticSeverity.INFO)
        filtered = whisper._filter_by_severity(items)
        assert len(filtered) == 3

        # HINT threshold — all
        whisper = DiagnosticWhisper(severity_threshold=DiagnosticSeverity.HINT)
        filtered = whisper._filter_by_severity(items)
        assert len(filtered) == 4

    @pytest.mark.asyncio
    async def test_diagnose_and_format(self):
        whisper = DiagnosticWhisper()
        with patch("src.diagnostics.whisper.run_ruff", new_callable=AsyncMock, return_value=[
            DiagnosticItem(
                file="x.py", line=1, severity=DiagnosticSeverity.ERROR,
                message="error here", source="ruff", code="E001",
            ),
        ]), patch("src.diagnostics.whisper.run_mypy", new_callable=AsyncMock, return_value=[]):
            text = await whisper.diagnose_and_format(["x.py"])

        assert "1 issue(s)" in text
        assert "error here" in text

    @pytest.mark.asyncio
    async def test_diagnose_no_issues(self):
        whisper = DiagnosticWhisper()
        with patch("src.diagnostics.whisper.run_ruff", new_callable=AsyncMock, return_value=[]), \
             patch("src.diagnostics.whisper.run_mypy", new_callable=AsyncMock, return_value=[]):
            text = await whisper.diagnose_and_format(["x.py"])
        assert text == ""

    def test_last_summary_initially_none(self):
        whisper = DiagnosticWhisper()
        assert whisper.last_summary is None
