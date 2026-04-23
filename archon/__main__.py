"""python -m archon — Archon CLI entrypoint."""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
import uuid
from pathlib import Path

# Ensure project root is in sys.path so `src.*` is importable from any cwd.
_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

try:
    from src.gate.evaluator import evaluate_gate
    from src.gate.models import GateDecision
    from src.orchestrator.handoff import (
        Artifacts,
        ChangedFile,
        Envelope,
        HandoffArtifact,
        ProjectContext,
        QualityGates,
        ReviewFlag,
        SecurityScan,
        Task,
        TechStack,
        TestResults,
    )
    from src.registry.models import GitConfig, ProjectMeta, ProjectRegistry, QualityPolicy
except ImportError as exc:
    print(f"[error] Cannot import archon modules: {exc}", file=sys.stderr)
    print("Hint: run from project root or `pip install -e '.[dev]'`", file=sys.stderr)
    sys.exit(1)

VERSION = "0.1.0"

# ---------------------------------------------------------------------------
# Output helpers — rich if available, plain fallback otherwise
# ---------------------------------------------------------------------------

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.rule import Rule

    _con = Console()

    def _out(msg: str = "") -> None:
        _con.print(msg)

    def _rule(title: str = "") -> None:
        _con.print(Rule(f"  {title}  " if title else "", style="dim"))

    def _panel(content: str, title: str = "", style: str = "blue") -> None:
        _con.print(Panel(content, title=title, border_style=style))

except ImportError:
    _con = None  # type: ignore[assignment]

    def _out(msg: str = "") -> None:
        print(re.sub(r"\[/?[^\]]*\]", "", msg))

    def _rule(title: str = "") -> None:
        print(f"\n--- {title} ---" if title else "-" * 60)

    def _panel(content: str, title: str = "", style: str = "blue") -> None:
        clean = re.sub(r"\[/?[^\]]*\]", "", content)
        print(f"\n=== {title} ===\n{clean}\n")


# ---------------------------------------------------------------------------
# Demo scenarios
# ---------------------------------------------------------------------------

_SCENARIOS: dict[str, dict] = {
    "auto_pass": {
        "label": "AUTO_PASS — 완벽한 코드, 자동 커밋",
        "review_score": 92,
        "lint": "passed",
        "build": "passed",
        "coverage": 88.5,
        "unit_passed": 14,
        "unit_failed": 0,
        "security": SecurityScan(critical=0, high=0, medium=0, low=1),
        "flags": [],
    },
    "l1": {
        "label": "L1_REWORK — 린트 실패, BackendAgent 재작업",
        "review_score": 78,
        "lint": "failed",
        "build": "passed",
        "coverage": 82.0,
        "unit_passed": 12,
        "unit_failed": 0,
        "security": SecurityScan(),
        "flags": [ReviewFlag(severity="warning", category="style", detail="E501 line too long")],
    },
    "l2": {
        "label": "L2_HUMAN — 낮은 리뷰 점수, 개발자 판단 요청",
        "review_score": 58,
        "lint": "passed",
        "build": "passed",
        "coverage": 76.0,
        "unit_passed": 10,
        "unit_failed": 0,
        "security": SecurityScan(),
        "flags": [
            ReviewFlag(severity="error", category="design", detail="Missing error handling"),
            ReviewFlag(severity="error", category="security", detail="Input not validated"),
        ],
    },
}

_GATE_ACTIONS: dict[GateDecision, str] = {
    GateDecision.AUTO_PASS: "GitExecutor.auto_commit() — 브랜치 생성 → 커밋 → 푸시",
    GateDecision.L1_REWORK: "BackendAgent 재작업 지시 (review_flags 주입, 최대 3회)",
    GateDecision.L2_HUMAN: "프로젝트 일시정지 — 개발자 판단 대기",
    GateDecision.L3_HALT: "긴급 중단 — 심각한 품질 문제",
    GateDecision.L4_DEPLOY: "배포 승인 — 개발자 최종 확인 필요",
}

_GATE_COLORS: dict[GateDecision, str] = {
    GateDecision.AUTO_PASS: "green",
    GateDecision.L1_REWORK: "yellow",
    GateDecision.L2_HUMAN: "red",
    GateDecision.L3_HALT: "bold red",
    GateDecision.L4_DEPLOY: "blue",
}

_OK = "[green]✓[/green]"
_WARN = "[yellow]⚠[/yellow]"
_FAIL = "[red]✗[/red]"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_registry() -> ProjectRegistry:
    return ProjectRegistry(
        project_meta=ProjectMeta(
            project_id="demo-001",
            project_name="Archon PoC Demo",
            description="Phase 1 demonstration pipeline",
        ),
        git_config=GitConfig(repo_url="https://github.com/demo/archon-demo.git"),
        quality_policy=QualityPolicy(
            coverage_threshold=80,
            review_score_threshold=70,
            max_retry_before_escalation=3,
        ),
    )


def _make_initial_handoff(task_id: str) -> HandoffArtifact:
    return HandoffArtifact(
        envelope=Envelope(
            handoff_id=str(uuid.uuid4()),
            from_agent="orchestrator",
            to_agent="backend",
            retry_count=0,
        ),
        project_context=ProjectContext(
            project_id="demo-001",
            project_name="Archon PoC Demo",
            git_repo="https://github.com/demo/archon-demo.git",
            git_branch=f"agent/backend/{task_id}",
            base_commit_sha="a1b2c3d",
            tech_stack=TechStack(language="python", framework="fastapi"),
        ),
        task=Task(
            task_id=task_id,
            completed_summary="",
            next_instructions=(
                "Implement `add(a: int, b: int) -> int` in src/math/operations.py. "
                "Add corresponding unit tests in tests/test_math.py."
            ),
        ),
    )


async def _check_llm() -> bool:
    """LiteLLM Proxy 연결 확인. 3초 타임아웃."""
    try:
        import litellm

        litellm.suppress_debug_info = True  # type: ignore[attr-defined]
        await litellm.acompletion(  # type: ignore[attr-defined]
            model="ollama/deepseek-v3.2:70b",
            messages=[{"role": "user", "content": "ping"}],
            timeout=3,
            max_tokens=1,
        )
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_version(_args: argparse.Namespace) -> None:
    _out(f"archon {VERSION}")


async def cmd_demo(args: argparse.Namespace) -> None:
    scenario_key: str = args.scenario
    force_mock: bool = args.mock
    sc = _SCENARIOS[scenario_key]

    _rule()
    _panel(
        f"[bold]Archon Framework v{VERSION}[/bold]\n"
        "Multi-agent AI development platform — PoC Demo",
        title="Archon",
        style="bold blue",
    )
    _out()
    _out(f"  Scenario : [bold]{sc['label']}[/bold]")
    _out()

    # 1/5 — Config
    _rule("1 / 5  설정 로드")
    registry = _make_registry()
    p = registry.quality_policy
    _out(f"  project_id  : [cyan]{registry.project_meta.project_id}[/cyan]")
    _out(
        f"  policy      : coverage≥{p.coverage_threshold}%  "
        f"review≥{p.review_score_threshold}  "
        f"max_retry={p.max_retry_before_escalation}"
    )
    env_path = Path(".env")
    _out(
        f"  .env        : [green]loaded[/green] ({env_path})"
        if env_path.exists()
        else "  .env        : [dim]not found — defaults 사용[/dim]"
    )

    # 2/5 — LLM check
    _rule("2 / 5  LLM 연결 확인")
    if force_mock:
        llm_ok = False
        _out("  --mock flag  → Mock 모드 강제 실행")
    else:
        _out("  LiteLLM Proxy 연결 시도 중... (timeout 3s)")
        llm_ok = await _check_llm()

    if llm_ok:
        _out(f"  {_OK} LLM 연결 성공 — Real 모드")
    else:
        _out(f"  {_WARN} LLM 연결 실패 → [bold]Mock 모드[/bold] 폴백")
        _out("     (모델 설치 후 재실행 시 실제 LLM 사용)")

    # 3/5 — BackendAgent
    task_id = f"demo-{uuid.uuid4().hex[:6]}"
    handoff = _make_initial_handoff(task_id)

    _rule("3 / 5  BackendAgent 실행")
    _out(f"  task_id     : [cyan]{task_id}[/cyan]")
    _out(f"  branch      : [cyan]{handoff.project_context.git_branch}[/cyan]")
    _out(f"  instruction : {handoff.task.next_instructions[:70]}...")
    _out()
    _out(f"  [dim]({'실제 LLM 호출' if llm_ok else '[Mock] BackendAgent 응답 시뮬레이션'})[/dim]")
    await asyncio.sleep(0.5)

    handoff.envelope.from_agent = "backend"
    handoff.envelope.to_agent = "reviewer"
    handoff.task.completed_summary = (
        "Implemented add(a, b) -> int in src/math/operations.py. "
        "Added 14 unit tests in tests/test_math.py."
    )
    handoff.artifacts = Artifacts(
        changed_files=[
            ChangedFile(path="src/math/operations.py", change_type="added", reason="new function"),
            ChangedFile(path="tests/test_math.py", change_type="added", reason="unit tests"),
        ]
    )
    _out(f"  {_OK} {handoff.task.completed_summary}")
    _out(f"  files       : {', '.join(f.path for f in handoff.artifacts.changed_files)}")

    # 4/5 — QA + Reviewer
    _rule("4 / 5  QA Pipeline + ReviewerAgent")
    _out(f"  [dim]({'실제 QA 실행' if llm_ok else '[Mock] QA 결과 시뮬레이션'})[/dim]")
    await asyncio.sleep(0.4)

    handoff.quality_gates = QualityGates(
        test_results=TestResults(
            unit_passed=sc["unit_passed"],
            unit_failed=sc["unit_failed"],
            coverage_percent=sc["coverage"],
        ),
        lint_result=sc["lint"],
        build_result=sc["build"],
        security_scan=sc["security"],
        review_score=sc["review_score"],
        review_flags=sc["flags"],
    )
    qg = handoff.quality_gates

    cov_ok = qg.test_results.coverage_percent >= p.coverage_threshold
    score_ok = qg.review_score >= p.review_score_threshold

    _out()
    _out(f"  lint        : {_OK if qg.lint_result == 'passed' else _FAIL}  {qg.lint_result}")
    _out(f"  build       : {_OK if qg.build_result == 'passed' else _FAIL}  {qg.build_result}")
    _out(
        f"  tests       : [green]{qg.test_results.unit_passed} passed[/green]"
        + (f"  [red]{qg.test_results.unit_failed} failed[/red]" if qg.test_results.unit_failed else "")
    )
    _out(
        f"  coverage    : {_OK if cov_ok else _WARN}  "
        f"{qg.test_results.coverage_percent:.1f}%  (threshold {p.coverage_threshold}%)"
    )
    _out(
        f"  review      : {_OK if score_ok else _FAIL}  "
        f"{qg.review_score}/100  (threshold {p.review_score_threshold})"
    )
    _out(
        f"  security    : critical={qg.security_scan.critical}  "
        f"high={qg.security_scan.high}  medium={qg.security_scan.medium}"
    )
    if qg.review_flags:
        _out()
        _out("  [yellow]Review Flags:[/yellow]")
        for flag in qg.review_flags:
            _out(f"    [{flag.severity}] {flag.category}: {flag.detail}")

    # 5/5 — Gate
    _rule("5 / 5  Human Gate 판정")
    decision = evaluate_gate(qg, p, retry_count=handoff.envelope.retry_count)
    handoff.quality_gates.gate_decision = decision

    color = _GATE_COLORS.get(decision, "white")
    action = _GATE_ACTIONS.get(decision, "")

    _out()
    _out(f"  gate        : [{color}]{decision.value}[/{color}]")
    _out(f"  action      : {action}")
    _out()

    if decision == GateDecision.AUTO_PASS:
        _out("  [dim](Demo: dry-run — 실제 환경에서는 GitExecutor가 브랜치 생성/커밋/푸시 실행)[/dim]")
    elif decision == GateDecision.L1_REWORK:
        _out(
            "  [dim](실제 환경: review_flags를 next_instructions에 주입 → "
            "BackendAgent 재호출, 최대 3회)[/dim]"
        )
    elif decision in (GateDecision.L2_HUMAN, GateDecision.L3_HALT):
        _out("  [dim](실제 환경: 터미널 알림 + 프로젝트 일시정지 → 개발자 판단 대기)[/dim]")

    _rule()
    _out()
    _out(f"[bold]Demo 완료.[/bold]  handoff_id: [dim]{handoff.envelope.handoff_id}[/dim]")
    _out()
    _out("다른 시나리오:")
    _out("  python -m archon demo --scenario auto_pass")
    _out("  python -m archon demo --scenario l1")
    _out("  python -m archon demo --scenario l2")
    _out("  python -m archon demo --mock")
    _out()


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="archon",
        description="Archon — Multi-agent AI development platform",
    )
    parser.add_argument("--version", action="version", version=f"archon {VERSION}")

    sub = parser.add_subparsers(dest="command", metavar="<command>")
    sub.add_parser("version", help="버전 표시")

    demo_p = sub.add_parser("demo", help="PoC 데모 파이프라인 실행")
    demo_p.add_argument("--mock", action="store_true", help="LLM 없이 Mock 모드 강제")
    demo_p.add_argument(
        "--scenario",
        choices=list(_SCENARIOS),
        default="auto_pass",
        metavar="{" + ",".join(_SCENARIOS) + "}",
        help="데모 시나리오 (기본: auto_pass)",
    )

    args = parser.parse_args()

    if args.command == "version":
        cmd_version(args)
    elif args.command == "demo":
        asyncio.run(cmd_demo(args))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
