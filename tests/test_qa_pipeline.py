"""QA Pipeline 테스트 — subprocess 모킹, 결과 파싱, 전체 파이프라인."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from src.orchestrator.handoff import SecurityScan, TestResults
from src.registry.models import ProjectRegistry, ProjectMeta, GitConfig, QualityPolicy
from src.runtime.qa import (
    SubprocessResult,
    _parse_junit_xml,
    _run,
    run_build,
    run_coverage,
    run_lint,
    run_qa_pipeline,
    run_security_scan,
    run_tests,
    run_typecheck,
)


# ---------------------------------------------------------------------------
# SubprocessResult
# ---------------------------------------------------------------------------


class TestSubprocessResult:
    def test_success_when_returncode_zero(self):
        r = SubprocessResult(returncode=0, stdout="ok", stderr="")
        assert r.success is True

    def test_failure_when_nonzero(self):
        r = SubprocessResult(returncode=1, stdout="", stderr="error")
        assert r.success is False

    def test_failure_when_negative(self):
        r = SubprocessResult(returncode=-1, stdout="", stderr="not found")
        assert r.success is False


# ---------------------------------------------------------------------------
# _run helper
# ---------------------------------------------------------------------------


class TestRun:
    @pytest.mark.asyncio
    async def test_run_success(self):
        result = await _run(["echo", "hello"])
        assert result.success is True
        assert "hello" in result.stdout

    @pytest.mark.asyncio
    async def test_run_command_not_found(self):
        result = await _run(["__nonexistent_binary_xyz__"])
        assert result.returncode == -1
        assert "not found" in result.stderr

    @pytest.mark.asyncio
    async def test_run_failure(self):
        result = await _run(["python3", "-c", "import sys; sys.exit(1)"])
        assert result.success is False


# ---------------------------------------------------------------------------
# run_lint
# ---------------------------------------------------------------------------


class TestRunLint:
    @pytest.mark.asyncio
    async def test_lint_passed(self):
        mock_result = SubprocessResult(returncode=0, stdout="", stderr="")
        with patch("src.runtime.qa._run", new_callable=AsyncMock, return_value=mock_result):
            assert await run_lint("/tmp/project") == "passed"

    @pytest.mark.asyncio
    async def test_lint_failed(self):
        mock_result = SubprocessResult(returncode=1, stdout="error", stderr="")
        with patch("src.runtime.qa._run", new_callable=AsyncMock, return_value=mock_result):
            assert await run_lint("/tmp/project") == "failed"

    @pytest.mark.asyncio
    async def test_lint_skipped_when_not_found(self):
        mock_result = SubprocessResult(returncode=-1, stdout="", stderr="ruff not found")
        with patch("src.runtime.qa._run", new_callable=AsyncMock, return_value=mock_result):
            assert await run_lint("/tmp/project") == "skipped"


# ---------------------------------------------------------------------------
# run_typecheck
# ---------------------------------------------------------------------------


class TestRunTypecheck:
    @pytest.mark.asyncio
    async def test_typecheck_passed(self):
        mock_result = SubprocessResult(returncode=0, stdout="", stderr="")
        with patch("src.runtime.qa._run", new_callable=AsyncMock, return_value=mock_result):
            assert await run_typecheck("/tmp/project") == "passed"

    @pytest.mark.asyncio
    async def test_typecheck_failed(self):
        mock_result = SubprocessResult(returncode=1, stdout="error", stderr="")
        with patch("src.runtime.qa._run", new_callable=AsyncMock, return_value=mock_result):
            assert await run_typecheck("/tmp/project") == "failed"

    @pytest.mark.asyncio
    async def test_typecheck_skipped(self):
        mock_result = SubprocessResult(returncode=-1, stdout="", stderr="")
        with patch("src.runtime.qa._run", new_callable=AsyncMock, return_value=mock_result):
            assert await run_typecheck("/tmp/project") == "skipped"


# ---------------------------------------------------------------------------
# run_build
# ---------------------------------------------------------------------------


class TestRunBuild:
    @pytest.mark.asyncio
    async def test_build_passed(self):
        mock_result = SubprocessResult(returncode=0, stdout="", stderr="")
        with patch("src.runtime.qa._run", new_callable=AsyncMock, return_value=mock_result):
            assert await run_build("/tmp/project") == "passed"

    @pytest.mark.asyncio
    async def test_build_failed(self):
        results = [
            SubprocessResult(returncode=0, stdout="", stderr=""),
            SubprocessResult(returncode=1, stdout="", stderr="compile error"),
        ]
        with patch("src.runtime.qa._run", new_callable=AsyncMock, side_effect=results):
            assert await run_build("/tmp/project") == "failed"

    @pytest.mark.asyncio
    async def test_build_skipped(self):
        mock_result = SubprocessResult(returncode=-1, stdout="", stderr="")
        with patch("src.runtime.qa._run", new_callable=AsyncMock, return_value=mock_result):
            assert await run_build("/tmp/project") == "skipped"


# ---------------------------------------------------------------------------
# _parse_junit_xml
# ---------------------------------------------------------------------------


class TestParseJunitXml:
    def test_parse_success(self, tmp_path: Path):
        xml_content = textwrap.dedent("""\
            <?xml version="1.0" ?>
            <testsuite tests="10" failures="2" errors="1">
            </testsuite>
        """)
        xml_file = tmp_path / "results.xml"
        xml_file.write_text(xml_content)
        result = _parse_junit_xml(xml_file)
        assert result.unit_passed == 7
        assert result.unit_failed == 3

    def test_parse_all_pass(self, tmp_path: Path):
        xml_content = textwrap.dedent("""\
            <?xml version="1.0" ?>
            <testsuite tests="5" failures="0" errors="0">
            </testsuite>
        """)
        xml_file = tmp_path / "results.xml"
        xml_file.write_text(xml_content)
        result = _parse_junit_xml(xml_file)
        assert result.unit_passed == 5
        assert result.unit_failed == 0

    def test_parse_missing_attributes(self, tmp_path: Path):
        xml_content = '<testsuite></testsuite>'
        xml_file = tmp_path / "results.xml"
        xml_file.write_text(xml_content)
        result = _parse_junit_xml(xml_file)
        assert result.unit_passed == 0
        assert result.unit_failed == 0


# ---------------------------------------------------------------------------
# run_tests
# ---------------------------------------------------------------------------


class TestRunTests:
    @pytest.mark.asyncio
    async def test_run_tests_not_found(self):
        mock_result = SubprocessResult(returncode=-1, stdout="", stderr="pytest not found")
        with patch("src.runtime.qa._run", new_callable=AsyncMock, return_value=mock_result):
            result = await run_tests("/tmp/project", run_id="test01")
            assert isinstance(result, TestResults)
            assert result.unit_passed == 0

    @pytest.mark.asyncio
    async def test_run_tests_no_xml(self):
        mock_result = SubprocessResult(returncode=0, stdout="passed", stderr="")
        with patch("src.runtime.qa._run", new_callable=AsyncMock, return_value=mock_result):
            result = await run_tests("/tmp/nonexistent", run_id="test02")
            assert result.unit_passed == 1
            assert result.unit_failed == 0

    @pytest.mark.asyncio
    async def test_run_tests_failure_no_xml(self):
        mock_result = SubprocessResult(returncode=1, stdout="FAILED", stderr="")
        with patch("src.runtime.qa._run", new_callable=AsyncMock, return_value=mock_result):
            result = await run_tests("/tmp/nonexistent", run_id="test03")
            assert result.unit_failed == 1

    @pytest.mark.asyncio
    async def test_run_tests_with_xml(self, tmp_path: Path):
        xml_content = textwrap.dedent("""\
            <?xml version="1.0" ?>
            <testsuite tests="20" failures="3" errors="0">
            </testsuite>
        """)
        xml_file = tmp_path / ".test-results-run42.xml"
        xml_file.write_text(xml_content)

        mock_result = SubprocessResult(returncode=1, stdout="", stderr="")
        with patch("src.runtime.qa._run", new_callable=AsyncMock, return_value=mock_result):
            result = await run_tests(str(tmp_path), run_id="run42")
            assert result.unit_passed == 17
            assert result.unit_failed == 3
        # XML은 파싱 후 삭제됨
        assert not xml_file.exists()

    @pytest.mark.asyncio
    async def test_run_tests_auto_run_id(self):
        mock_result = SubprocessResult(returncode=-1, stdout="", stderr="")
        with patch("src.runtime.qa._run", new_callable=AsyncMock, return_value=mock_result):
            result = await run_tests("/tmp/project")
            assert isinstance(result, TestResults)


# ---------------------------------------------------------------------------
# run_security_scan
# ---------------------------------------------------------------------------


class TestRunSecurityScan:
    @pytest.mark.asyncio
    async def test_scan_not_available(self):
        mock_result = SubprocessResult(returncode=-1, stdout="", stderr="semgrep not found")
        with patch("src.runtime.qa._run", new_callable=AsyncMock, return_value=mock_result):
            result = await run_security_scan("/tmp/project")
            assert isinstance(result, SecurityScan)
            assert result.tool == "semgrep"
            assert result.critical == 0

    @pytest.mark.asyncio
    async def test_scan_with_findings(self):
        findings_json = json.dumps({
            "results": [
                {"extra": {"severity": "HIGH"}},
                {"extra": {"severity": "HIGH"}},
                {"extra": {"severity": "MEDIUM"}},
                {"extra": {"severity": "LOW"}},
            ]
        })
        mock_result = SubprocessResult(returncode=0, stdout=findings_json, stderr="")
        with patch("src.runtime.qa._run", new_callable=AsyncMock, return_value=mock_result):
            result = await run_security_scan("/tmp/project")
            assert result.high == 2
            assert result.medium == 1
            assert result.low == 1
            assert result.critical == 0

    @pytest.mark.asyncio
    async def test_scan_clean(self):
        findings_json = json.dumps({"results": []})
        mock_result = SubprocessResult(returncode=0, stdout=findings_json, stderr="")
        with patch("src.runtime.qa._run", new_callable=AsyncMock, return_value=mock_result):
            result = await run_security_scan("/tmp/project")
            assert result.critical == 0
            assert result.high == 0

    @pytest.mark.asyncio
    async def test_scan_invalid_json(self):
        mock_result = SubprocessResult(returncode=0, stdout="not json", stderr="")
        with patch("src.runtime.qa._run", new_callable=AsyncMock, return_value=mock_result):
            result = await run_security_scan("/tmp/project")
            assert result.tool == "semgrep"


# ---------------------------------------------------------------------------
# run_coverage
# ---------------------------------------------------------------------------


class TestRunCoverage:
    @pytest.mark.asyncio
    async def test_coverage_not_available(self):
        mock_result = SubprocessResult(returncode=-1, stdout="", stderr="")
        with patch("src.runtime.qa._run", new_callable=AsyncMock, return_value=mock_result):
            result = await run_coverage("/tmp/project", run_id="cov01")
            assert result == 0.0

    @pytest.mark.asyncio
    async def test_coverage_with_json(self, tmp_path: Path):
        cov_data = {"totals": {"percent_covered": 85.3}}
        cov_file = tmp_path / ".coverage-cov02.json"
        cov_file.write_text(json.dumps(cov_data))

        mock_result = SubprocessResult(returncode=0, stdout="", stderr="")
        with patch("src.runtime.qa._run", new_callable=AsyncMock, return_value=mock_result):
            result = await run_coverage(str(tmp_path), run_id="cov02")
            assert result == 85.3
        assert not cov_file.exists()

    @pytest.mark.asyncio
    async def test_coverage_no_json_file(self):
        mock_result = SubprocessResult(returncode=0, stdout="", stderr="")
        with patch("src.runtime.qa._run", new_callable=AsyncMock, return_value=mock_result):
            result = await run_coverage("/tmp/nonexistent", run_id="cov03")
            assert result == 0.0

    @pytest.mark.asyncio
    async def test_coverage_invalid_json(self, tmp_path: Path):
        cov_file = tmp_path / ".coverage-cov04.json"
        cov_file.write_text("not json")

        mock_result = SubprocessResult(returncode=0, stdout="", stderr="")
        with patch("src.runtime.qa._run", new_callable=AsyncMock, return_value=mock_result):
            result = await run_coverage(str(tmp_path), run_id="cov04")
            assert result == 0.0


# ---------------------------------------------------------------------------
# run_qa_pipeline (integration)
# ---------------------------------------------------------------------------


def _make_registry() -> ProjectRegistry:
    return ProjectRegistry(
        project_meta=ProjectMeta(
            project_id="qa-test",
            project_name="QA Test Project",
        ),
        git_config=GitConfig(repo_url="https://github.com/test/repo.git"),
        quality_policy=QualityPolicy(),
    )


class TestRunQaPipeline:
    @pytest.mark.asyncio
    async def test_full_pipeline(self):
        """모든 단계 모킹하여 전체 파이프라인 통합 검증."""
        async def mock_run(cmd, cwd=None):
            if "ruff" in cmd:
                return SubprocessResult(0, "", "")
            if "mypy" in cmd:
                return SubprocessResult(0, "", "")
            if "pytest" in cmd and "--cov" in cmd:
                return SubprocessResult(0, "", "")
            if "pytest" in cmd:
                return SubprocessResult(0, "", "")
            if "semgrep" in cmd:
                return SubprocessResult(0, json.dumps({"results": []}), "")
            if "py_compile" in cmd or "compileall" in cmd:
                return SubprocessResult(0, "", "")
            return SubprocessResult(0, "", "")

        with patch("src.runtime.qa._run", side_effect=mock_run):
            result = await run_qa_pipeline("/tmp/project", _make_registry(), run_id="qa01")

        assert result.lint_result == "passed"
        assert result.build_result == "passed"
        assert isinstance(result.test_results, TestResults)
        assert isinstance(result.security_scan, SecurityScan)

    @pytest.mark.asyncio
    async def test_pipeline_with_failures(self):
        """일부 단계 실패 시에도 파이프라인 완료."""
        async def mock_run(cmd, cwd=None):
            if "ruff" in cmd:
                return SubprocessResult(1, "lint error", "")
            if "semgrep" in cmd:
                return SubprocessResult(-1, "", "not found")
            return SubprocessResult(0, "", "")

        with patch("src.runtime.qa._run", side_effect=mock_run):
            result = await run_qa_pipeline("/tmp/project", _make_registry(), run_id="qa02")

        assert result.lint_result == "failed"
        assert result.security_scan.tool == "semgrep"

    @pytest.mark.asyncio
    async def test_pipeline_auto_run_id(self):
        """run_id 미지정 시 자동 생성."""
        mock_result = SubprocessResult(returncode=-1, stdout="", stderr="")
        with patch("src.runtime.qa._run", new_callable=AsyncMock, return_value=mock_result):
            result = await run_qa_pipeline("/tmp/project", _make_registry())
        assert result is not None
