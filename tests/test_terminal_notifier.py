"""TerminalNotifier 테스트 — Rich 패널 + macOS 데스크톱 알림."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from src.gate.models import GateDecision
from src.notifications.base import GateEvent
from src.notifications.terminal import TerminalNotifier, _GATE_ICONS, _GATE_STYLES


def _make_event(**kwargs) -> GateEvent:
    defaults = {
        "project_id": "proj-1",
        "project_name": "Archon",
        "task_id": "task-1",
        "gate_decision": GateDecision.L1_REWORK,
        "trigger_reason": "lint failure",
        "agent_role": "backend",
        "review_score": 60,
        "retry_count": 0,
    }
    defaults.update(kwargs)
    return GateEvent(**defaults)


# ---------------------------------------------------------------------------
# should_notify
# ---------------------------------------------------------------------------


class TestShouldNotify:
    def test_auto_pass_default_no_notify(self):
        notifier = TerminalNotifier(desktop_notification=False)
        event = _make_event(gate_decision=GateDecision.AUTO_PASS)
        assert not notifier.should_notify(event)

    def test_auto_pass_with_flag_notify(self):
        notifier = TerminalNotifier(
            desktop_notification=False, notify_on_auto_pass=True,
        )
        event = _make_event(gate_decision=GateDecision.AUTO_PASS)
        assert notifier.should_notify(event)

    def test_non_auto_pass_always_notifies(self):
        notifier = TerminalNotifier(desktop_notification=False)
        for decision in [
            GateDecision.L1_REWORK,
            GateDecision.L2_HUMAN,
            GateDecision.L3_HALT,
            GateDecision.L4_DEPLOY,
        ]:
            event = _make_event(gate_decision=decision)
            assert notifier.should_notify(event)


# ---------------------------------------------------------------------------
# _print_panel
# ---------------------------------------------------------------------------


class TestPrintPanel:
    def test_panel_printed(self):
        console = MagicMock()
        notifier = TerminalNotifier(console=console, desktop_notification=False)
        event = _make_event()
        notifier._print_panel(event)
        console.print.assert_called_once()

    def test_panel_with_retry(self):
        console = MagicMock()
        notifier = TerminalNotifier(console=console, desktop_notification=False)
        event = _make_event(retry_count=3)
        notifier._print_panel(event)
        console.print.assert_called_once()

    def test_all_gate_styles_covered(self):
        for decision in GateDecision:
            assert decision in _GATE_STYLES

    def test_all_gate_icons_covered(self):
        for decision in GateDecision:
            assert decision in _GATE_ICONS


# ---------------------------------------------------------------------------
# notify (async)
# ---------------------------------------------------------------------------


class TestNotify:
    @pytest.mark.asyncio
    async def test_notify_success_no_desktop(self):
        console = MagicMock()
        notifier = TerminalNotifier(console=console, desktop_notification=False)
        event = _make_event()
        result = await notifier.notify(event)
        assert result is True
        console.print.assert_called_once()

    @pytest.mark.asyncio
    async def test_notify_with_desktop_on_darwin(self):
        console = MagicMock()
        notifier = TerminalNotifier(console=console, desktop_notification=True)
        event = _make_event()

        with patch("src.notifications.terminal.sys") as mock_sys, \
             patch.object(notifier, "_send_macos_notification") as mock_macos:
            mock_sys.platform = "darwin"
            result = await notifier.notify(event)

        assert result is True
        mock_macos.assert_called_once_with(event)

    @pytest.mark.asyncio
    async def test_notify_no_desktop_on_linux(self):
        console = MagicMock()
        notifier = TerminalNotifier(console=console, desktop_notification=True)
        event = _make_event()

        with patch("src.notifications.terminal.sys") as mock_sys:
            mock_sys.platform = "linux"
            result = await notifier.notify(event)

        assert result is True

    @pytest.mark.asyncio
    async def test_notify_returns_false_on_exception(self):
        console = MagicMock()
        console.print.side_effect = RuntimeError("render fail")
        notifier = TerminalNotifier(console=console, desktop_notification=False)
        event = _make_event()
        result = await notifier.notify(event)
        assert result is False


# ---------------------------------------------------------------------------
# _send_macos_notification
# ---------------------------------------------------------------------------


class TestSendMacosNotification:
    def test_osascript_called(self):
        notifier = TerminalNotifier(desktop_notification=True)
        event = _make_event()

        with patch("src.notifications.terminal.subprocess.run") as mock_run:
            notifier._send_macos_notification(event)

        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "osascript"
        assert cmd[1] == "-e"
        assert "Archon" in cmd[2]

    def test_timeout_handled(self):
        notifier = TerminalNotifier(desktop_notification=True)
        event = _make_event()

        with patch(
            "src.notifications.terminal.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="osascript", timeout=5),
        ):
            # should not raise
            notifier._send_macos_notification(event)

    def test_file_not_found_handled(self):
        notifier = TerminalNotifier(desktop_notification=True)
        event = _make_event()

        with patch(
            "src.notifications.terminal.subprocess.run",
            side_effect=FileNotFoundError("osascript not found"),
        ):
            # should not raise
            notifier._send_macos_notification(event)
