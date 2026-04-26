"""QA Pipeline — ruff, mypy, pytest subprocess 실행 후 QualityGates 바인딩."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from src.orchestrator.handoff import QualityGates, SecurityScan, TestResults
from src.registry.models import ProjectRegistry

logger = logging.getLogger(__name__)


@dataclass
class SubprocessResult:
    """subprocess 실행 결과."""

    returncode: int
    stdout: str
    stderr: str

    @property
    def success(self) -> bool:
        return self.returncode == 0


QA_SUBPROCESS_TIMEOUT = 300  # 5분 기본 타임아웃


async def _run(
    cmd: list[str],
    cwd: str | None = None,
    timeout: int = QA_SUBPROCESS_TIMEOUT,
) -> SubprocessResult:
    """비동기 subprocess 실행 (타임아웃 포함)."""
    logger.debug("Running: %s (timeout=%ds)", " ".join(cmd), timeout)
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(), timeout=timeout,
        )
        return SubprocessResult(
            returncode=proc.returncode or 0,
            stdout=stdout_bytes.decode(errors="replace"),
            stderr=stderr_bytes.decode(errors="replace"),
        )
    except TimeoutError:
        proc.kill()  # type: ignore[union-attr]
        logger.error("Command timed out after %ds: %s", timeout, " ".join(cmd))
        return SubprocessResult(
            returncode=-2,
            stdout="",
            stderr=f"timeout after {timeout}s",
        )
    except FileNotFoundError:
        logger.warning("Command not found: %s", cmd[0])
        return SubprocessResult(returncode=-1, stdout="", stderr=f"{cmd[0]} not found")


async def run_lint(project_root: str) -> str:
    """ruff check 실행. 'passed' 또는 'failed' 반환."""
    result = await _run(["ruff", "check", ".", "--quiet"], cwd=project_root)
    if result.returncode == -1:
        logger.warning("ruff not available — skipping lint")
        return "skipped"
    return "passed" if result.success else "failed"


async def run_typecheck(project_root: str) -> str:
    """mypy 실행. 'passed' 또는 'failed' 반환."""
    result = await _run(["mypy", "src/", "--ignore-missing-imports"], cwd=project_root)
    if result.returncode == -1:
        logger.warning("mypy not available — skipping typecheck")
        return "skipped"
    return "passed" if result.success else "failed"


async def run_tests(
    project_root: str,
    run_id: str | None = None,
) -> TestResults:
    """pytest 실행. TestResults 반환.

    Args:
        project_root: 프로젝트 루트 경로.
        run_id: 파일 격리용 고유 ID. None이면 자동 생성.
    """
    rid = run_id or uuid.uuid4().hex[:8]
    xml_filename = f".test-results-{rid}.xml"

    result = await _run(
        ["pytest", "tests/", "-v", "--tb=short", f"--junitxml={xml_filename}"],
        cwd=project_root,
    )

    if result.returncode == -1:
        logger.warning("pytest not available — returning empty test results")
        return TestResults()

    # JUnit XML 파싱 시도
    xml_path = Path(project_root) / xml_filename
    if xml_path.exists():
        try:
            return _parse_junit_xml(xml_path)
        except Exception as e:
            logger.warning("Failed to parse JUnit XML: %s", e)
        finally:
            xml_path.unlink(missing_ok=True)

    # XML 파싱 실패 시 exit code로 판단
    return TestResults(
        unit_passed=1 if result.success else 0,
        unit_failed=0 if result.success else 1,
    )


def _parse_junit_xml(xml_path: Path) -> TestResults:
    """JUnit XML 결과를 TestResults로 변환."""
    tree = ET.parse(xml_path)
    root = tree.getroot()

    tests = int(root.attrib.get("tests", 0))
    failures = int(root.attrib.get("failures", 0))
    errors = int(root.attrib.get("errors", 0))

    return TestResults(
        unit_passed=max(0, tests - failures - errors),
        unit_failed=failures + errors,
    )


async def run_build(project_root: str) -> str:
    """Python syntax check로 빌드 검증."""
    result = await _run(["python", "-m", "py_compile", "src/__init__.py"], cwd=project_root)
    if result.returncode == -1:
        return "skipped"
    # 전체 src/ 디렉토리의 .py 파일 컴파일 체크
    result = await _run(
        ["python", "-c", "import compileall; compileall.compile_dir('src/', quiet=1)"],
        cwd=project_root,
    )
    return "passed" if result.success else "failed"


async def run_security_scan(project_root: str) -> SecurityScan:
    """semgrep 보안 스캔 실행."""
    result = await _run(
        ["semgrep", "scan", "--config=auto", "--json", "--quiet", "src/"],
        cwd=project_root,
    )

    if result.returncode == -1:
        logger.warning("semgrep not available — returning clean scan")
        return SecurityScan(tool="semgrep")

    # JSON 결과 파싱 시도
    try:
        data = json.loads(result.stdout)
        findings = data.get("results", [])
        severity_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
        for finding in findings:
            sev = finding.get("extra", {}).get("severity", "low").lower()
            if sev in severity_counts:
                severity_counts[sev] += 1
        return SecurityScan(tool="semgrep", **severity_counts)
    except (json.JSONDecodeError, KeyError):
        return SecurityScan(tool="semgrep")


async def run_coverage(
    project_root: str,
    run_id: str | None = None,
) -> float:
    """pytest --cov로 커버리지 측정.

    Args:
        project_root: 프로젝트 루트 경로.
        run_id: 파일 격리용 고유 ID. None이면 자동 생성.
    """
    rid = run_id or uuid.uuid4().hex[:8]
    cov_filename = f".coverage-{rid}.json"

    result = await _run(
        ["pytest", "tests/", "--cov=src", f"--cov-report=json:{cov_filename}", "-q"],
        cwd=project_root,
    )

    if result.returncode == -1:
        return 0.0

    cov_path = Path(project_root) / cov_filename
    if cov_path.exists():
        try:
            data = json.loads(cov_path.read_text())
            coverage = data.get("totals", {}).get("percent_covered", 0.0)
            return float(coverage)
        except (json.JSONDecodeError, KeyError):
            pass
        finally:
            cov_path.unlink(missing_ok=True)

    return 0.0


async def run_sop_compliance(
    project_root: str,
    sop_path: str | None = None,
) -> int | None:
    """SOP 체크리스트 커버리지를 산출한다.

    .harness/sop/production/ 하위의 역할별 SOP 파일을 읽어
    체크리스트 항목 중 완료된 비율을 반환한다.
    SOP 파일이 없으면 None(미검사).
    """
    sop_dir = Path(project_root) / (sop_path or ".harness/sop/production")
    if not sop_dir.is_dir():
        logger.debug("SOP directory not found: %s", sop_dir)
        return None

    total_items = 0
    checked_items = 0

    for md_file in sop_dir.glob("*.md"):
        try:
            content = md_file.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("- [ ]") or stripped.startswith("- [x]"):
                total_items += 1
                if stripped.startswith("- [x]"):
                    checked_items += 1

    if total_items == 0:
        return None

    score = int((checked_items / total_items) * 100)
    logger.info("SOP compliance: %d/%d items (%d%%)", checked_items, total_items, score)
    return score


async def run_qa_pipeline(
    project_root: str,
    registry: ProjectRegistry,
    run_id: str | None = None,
) -> QualityGates:
    """전체 QA 파이프라인 실행. 병렬로 lint, typecheck, test, build, security, SOP를 돌린다.

    Args:
        project_root: 프로젝트 루트 경로.
        registry: 프로젝트 레지스트리.
        run_id: 파일 격리용 고유 ID. None이면 자동 생성.
    """
    rid = run_id or uuid.uuid4().hex[:8]
    logger.info("Running QA pipeline for project root: %s (run_id: %s)", project_root, rid)

    # 병렬 실행
    lint_task = asyncio.create_task(run_lint(project_root))
    build_task = asyncio.create_task(run_build(project_root))
    test_task = asyncio.create_task(run_tests(project_root, run_id=rid))
    security_task = asyncio.create_task(run_security_scan(project_root))
    coverage_task = asyncio.create_task(run_coverage(project_root, run_id=rid))
    sop_task = asyncio.create_task(run_sop_compliance(
        project_root,
        sop_path=registry.git_config.sop_directory,
    ))

    (
        lint_result, build_result, test_results,
        security_scan, coverage, sop_score,
    ) = await asyncio.gather(
        lint_task, build_task, test_task,
        security_task, coverage_task, sop_task,
    )

    test_results.coverage_percent = coverage

    quality = QualityGates(
        test_results=test_results,
        lint_result=lint_result,
        build_result=build_result,
        security_scan=security_scan,
        sop_compliance_score=sop_score,
    )

    logger.info(
        "QA results — lint: %s, build: %s, tests: %d passed / %d failed, "
        "coverage: %.1f%%, sop: %s",
        lint_result,
        build_result,
        test_results.unit_passed,
        test_results.unit_failed,
        coverage,
        f"{sop_score}%" if sop_score is not None else "N/A",
    )

    return quality
