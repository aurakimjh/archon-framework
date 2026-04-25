"""python -m archon — Archon CLI entrypoint."""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
import uuid
from pathlib import Path
from typing import Any

# Ensure project root is in sys.path so `src.*` is importable from any cwd.
_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

try:
    from src.gate.models import GateDecision
    from src.orchestrator.handoff import (
        Envelope,
        HandoffArtifact,
        ProjectContext,
        Task,
        TechStack,
    )
    from src.registry.models import GitConfig, ProjectMeta, ProjectRegistry, QualityPolicy
except ImportError as exc:
    print(f"[error] Cannot import archon modules: {exc}", file=sys.stderr)
    print("Hint: run from project root or `pip install -e '.[dev]'`", file=sys.stderr)
    sys.exit(1)

from archon import __version__ as VERSION

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
# Display constants
# ---------------------------------------------------------------------------

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

# CLI에서 선택 가능한 데모 시나리오 (l1_exhausted는 테스트 전용)
_DEMO_SCENARIOS = ["auto_pass", "l1", "l2"]


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
    from src.pipeline.demo_pipeline import DemoPipeline, SCENARIO_LABELS

    scenario_key: str = args.scenario
    force_mock: bool = args.mock

    _rule()
    _panel(
        f"[bold]Archon Framework v{VERSION}[/bold]\n"
        "Multi-agent AI development platform — PoC Demo",
        title="Archon",
        style="bold blue",
    )
    _out()
    _out(f"  Scenario : [bold]{SCENARIO_LABELS.get(scenario_key, scenario_key)}[/bold]")
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

    # 파이프라인 초기화
    task_id = f"demo-{uuid.uuid4().hex[:6]}"
    initial_handoff = _make_initial_handoff(task_id)

    _rule("3~5 / 5  파이프라인 실행")
    _out(f"  task_id     : [cyan]{task_id}[/cyan]")
    _out(f"  branch      : [cyan]{initial_handoff.project_context.git_branch}[/cyan]")
    _out(f"  instruction : {initial_handoff.task.next_instructions[:70]}...")

    def on_step(step: str, data: Any) -> None:
        if step == "loop":
            _out()
            _rule(f"  {data}  ")
        elif step == "backend":
            _out(f"\n  [bold cyan]▶ Backend [/bold cyan]  {data}")
        elif step == "backend_done":
            d = data
            _out(f"  {_OK} {d['summary'][:80]}")
            if d["files"]:
                _out(f"     files    : {', '.join(d['files'])}")
        elif step == "qa":
            _out(f"\n  [bold cyan]▶ QA      [/bold cyan]  {data}")
        elif step == "qa_done":
            d = data
            cov_ok = d["coverage"] >= p.coverage_threshold
            _out(f"     lint     : {_OK if d['lint'] == 'passed' else _FAIL}  {d['lint']}")
            _out(f"     build    : {_OK if d['build'] == 'passed' else _FAIL}  {d['build']}")
            tests_str = f"[green]{d['unit_passed']} passed[/green]"
            if d["unit_failed"]:
                tests_str += f"  [red]{d['unit_failed']} failed[/red]"
            _out(f"     tests    : {tests_str}")
            _out(
                f"     coverage : {_OK if cov_ok else _WARN}  "
                f"{d['coverage']:.1f}%  (threshold {p.coverage_threshold}%)"
            )
            sec = d["security"]
            _out(
                f"     security : critical={sec.critical}  "
                f"high={sec.high}  medium={sec.medium}"
            )
        elif step == "reviewer":
            _out(f"\n  [bold cyan]▶ Review  [/bold cyan]  {data}")
        elif step == "reviewer_done":
            d = data
            score_ok = d["review_score"] >= p.review_score_threshold
            _out(
                f"     score    : {_OK if score_ok else _FAIL}  "
                f"{d['review_score']}/100  (threshold {p.review_score_threshold})"
            )
            for flag in d["flags"]:
                _out(f"     flag     : [{flag.severity}] {flag.category}: {flag.detail}")
        elif step == "gate":
            gate = data["decision"]
            color = _GATE_COLORS.get(gate, "white")
            _out(f"\n  [bold cyan]▶ Gate    [/bold cyan]  [{color}]{gate.value}[/{color}]")
        elif step == "l1_rework":
            _out(f"  [yellow]  ↺ L1_REWORK[/yellow]  {data}")
        elif step in ("l2_escalated", "l2_human"):
            _out(f"  [red]  ⊘ L2_HUMAN[/red]  {data}")
        elif step == "l3_halt":
            _out(f"  [bold red]  ⊗ L3_HALT[/bold red]  {data}")
        elif step == "l4_deploy":
            _out(f"  [blue]  ⟳ L4_DEPLOY[/blue]  {data}")
        elif step == "commit":
            _out(f"  [dim]  → {data}[/dim]")

    pipeline = DemoPipeline(
        registry=registry,
        mock=not llm_ok,
        scenario=scenario_key,
        dry_run=True,
        on_step=on_step,
    )
    result = await pipeline.run(initial_handoff)

    # 최종 결과
    _rule()
    _out()
    color = _GATE_COLORS.get(result.gate, "white")
    _out(f"  gate        : [{color}]{result.gate.value}[/{color}]")
    _out(f"  attempt     : {result.attempt + 1}회")
    _out(f"  action      : {_GATE_ACTIONS.get(result.gate, '')}")
    _out()
    if result.gate == GateDecision.AUTO_PASS:
        _out(
            "  [dim](Demo: dry-run — 실제 환경에서는 "
            "GitExecutor가 브랜치 생성/커밋/푸시 실행)[/dim]"
        )
    elif result.gate in (GateDecision.L2_HUMAN, GateDecision.L3_HALT):
        _out(
            "  [dim](실제 환경: 터미널 알림 + 프로젝트 일시정지 "
            "→ 개발자 판단 대기)[/dim]"
        )

    _rule()
    _out()
    _out(
        f"[bold]Demo 완료.[/bold]  "
        f"handoff_id: [dim]{result.handoff.envelope.handoff_id}[/dim]"
    )
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
        choices=_DEMO_SCENARIOS,
        default="auto_pass",
        metavar="{" + ",".join(_DEMO_SCENARIOS) + "}",
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
