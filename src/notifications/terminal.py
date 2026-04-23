"""터미널 알림 — Rich TUI + macOS 데스크톱 알림."""

from __future__ import annotations

import logging
import subprocess
import sys

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from src.gate.models import GateDecision
from src.notifications.base import GateEvent, Notifier

logger = logging.getLogger(__name__)

# Gate 레벨별 Rich 스타일
_GATE_STYLES: dict[str, str] = {
    GateDecision.AUTO_PASS: "bold green",
    GateDecision.L1_REWORK: "bold yellow",
    GateDecision.L2_HUMAN: "bold red",
    GateDecision.L3_HALT: "bold red on white",
    GateDecision.L4_DEPLOY: "bold blue",
}

_GATE_ICONS: dict[str, str] = {
    GateDecision.AUTO_PASS: "[green]\u2713[/green]",
    GateDecision.L1_REWORK: "[yellow]\u26a0[/yellow]",
    GateDecision.L2_HUMAN: "[red]\u2717[/red]",
    GateDecision.L3_HALT: "[red bold]\u26d4[/red bold]",
    GateDecision.L4_DEPLOY: "[blue]\u2708[/blue]",
}


class TerminalNotifier(Notifier):
    """터미널에 Rich 패널로 알림을 표시한다.

    macOS에서는 osascript를 통해 데스크톱 알림도 표시.
    """

    def __init__(
        self,
        console: Console | None = None,
        desktop_notification: bool = True,
        notify_on_auto_pass: bool = False,
    ) -> None:
        self._console = console or Console(stderr=True)
        self._desktop = desktop_notification
        self._notify_on_auto_pass = notify_on_auto_pass

    def should_notify(self, event: GateEvent) -> bool:
        if event.gate_decision == GateDecision.AUTO_PASS:
            return self._notify_on_auto_pass
        return True

    async def notify(self, event: GateEvent) -> bool:
        """터미널에 알림 패널을 출력한다."""
        try:
            self._print_panel(event)
            if self._desktop and sys.platform == "darwin":
                self._send_macos_notification(event)
            return True
        except Exception as e:
            logger.error("Terminal notification error: %s", e)
            return False

    def _print_panel(self, event: GateEvent) -> None:
        """Rich 패널로 Gate 이벤트를 표시한다."""
        style = _GATE_STYLES.get(event.gate_decision, "bold white")
        icon = _GATE_ICONS.get(event.gate_decision, "")

        body = Text()
        body.append(f"Project: {event.project_name}\n")
        body.append(f"Task:    {event.task_id}\n")
        body.append(f"Agent:   {event.agent_role}\n")
        body.append(f"Score:   {event.review_score}\n")
        body.append(f"Reason:  {event.trigger_reason}\n")
        if event.retry_count > 0:
            body.append(f"Retry:   {event.retry_count}\n")

        panel = Panel(
            body,
            title=f"{icon} {event.title}",
            border_style=style,
            expand=False,
        )
        self._console.print(panel)

    def _send_macos_notification(self, event: GateEvent) -> None:
        """macOS 네이티브 알림을 전송한다 (osascript)."""
        title = event.title
        message = f"{event.trigger_reason} (score: {event.review_score})"

        script = (
            f'display notification "{message}" '
            f'with title "Archon" '
            f'subtitle "{title}"'
        )

        try:
            subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                timeout=5,
                check=False,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            logger.debug("macOS notification unavailable")
