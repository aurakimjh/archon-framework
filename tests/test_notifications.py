"""알림 시스템 테스트 — GateEvent, Notifier, Slack, Terminal."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.gate.models import GateDecision
from src.notifications.base import CompositeNotifier, GateEvent, Notifier
from src.notifications.slack import SlackNotifier, _GATE_COLORS, _GATE_EMOJI
from src.notifications.terminal import TerminalNotifier


# --- GateEvent ---


class TestGateEvent:
    def test_create_event(self):
        event = GateEvent(
            project_id="proj_1",
            project_name="Test Project",
            task_id="task_1",
            gate_decision=GateDecision.L2_HUMAN,
            trigger_reason="Quality threshold not met",
            agent_role="backend",
            review_score=55,
        )
        assert event.project_id == "proj_1"
        assert event.gate_decision == GateDecision.L2_HUMAN
        assert event.review_score == 55

    def test_severity_mapping(self):
        for gate, expected in [
            (GateDecision.AUTO_PASS, "info"),
            (GateDecision.L1_REWORK, "warning"),
            (GateDecision.L2_HUMAN, "error"),
            (GateDecision.L3_HALT, "critical"),
            (GateDecision.L4_DEPLOY, "warning"),
        ]:
            event = GateEvent(
                project_id="p",
                project_name="P",
                task_id="t",
                gate_decision=gate,
                trigger_reason="test",
                agent_role="backend",
            )
            assert event.severity == expected

    def test_title(self):
        event = GateEvent(
            project_id="p",
            project_name="MyProject",
            task_id="task_42",
            gate_decision=GateDecision.L3_HALT,
            trigger_reason="Critical issue",
            agent_role="backend",
        )
        assert "L3_HALT" in event.title
        assert "MyProject" in event.title
        assert "task_42" in event.title

    def test_summary(self):
        event = GateEvent(
            project_id="p",
            project_name="P",
            task_id="t",
            gate_decision=GateDecision.L2_HUMAN,
            trigger_reason="test reason",
            agent_role="tester",
            review_score=70,
        )
        summary = event.summary
        assert "tester" in summary
        assert "70" in summary
        assert "test reason" in summary


# --- Notifier ABC ---


class TestNotifierABC:
    def test_should_notify_skips_auto_pass(self):
        class DummyNotifier(Notifier):
            async def notify(self, event: GateEvent) -> bool:
                return True

        notifier = DummyNotifier()
        auto_pass = GateEvent(
            project_id="p", project_name="P", task_id="t",
            gate_decision=GateDecision.AUTO_PASS,
            trigger_reason="ok", agent_role="backend",
        )
        l2 = GateEvent(
            project_id="p", project_name="P", task_id="t",
            gate_decision=GateDecision.L2_HUMAN,
            trigger_reason="fail", agent_role="backend",
        )
        assert notifier.should_notify(auto_pass) is False
        assert notifier.should_notify(l2) is True


# --- CompositeNotifier ---


class TestCompositeNotifier:
    @pytest.mark.asyncio
    async def test_empty_composite_returns_false(self):
        composite = CompositeNotifier()
        event = GateEvent(
            project_id="p", project_name="P", task_id="t",
            gate_decision=GateDecision.L2_HUMAN,
            trigger_reason="test", agent_role="backend",
        )
        assert await composite.notify(event) is False

    @pytest.mark.asyncio
    async def test_composite_sends_to_all(self):
        mock1 = AsyncMock(spec=Notifier)
        mock1.should_notify.return_value = True
        mock1.notify.return_value = True

        mock2 = AsyncMock(spec=Notifier)
        mock2.should_notify.return_value = True
        mock2.notify.return_value = True

        composite = CompositeNotifier([mock1, mock2])
        event = GateEvent(
            project_id="p", project_name="P", task_id="t",
            gate_decision=GateDecision.L2_HUMAN,
            trigger_reason="test", agent_role="backend",
        )
        result = await composite.notify(event)
        assert result is True
        mock1.notify.assert_called_once()
        mock2.notify.assert_called_once()

    @pytest.mark.asyncio
    async def test_composite_partial_failure(self):
        """하나가 실패해도 다른 게 성공하면 True."""
        mock1 = AsyncMock(spec=Notifier)
        mock1.should_notify.return_value = True
        mock1.notify.side_effect = Exception("fail")

        mock2 = AsyncMock(spec=Notifier)
        mock2.should_notify.return_value = True
        mock2.notify.return_value = True

        composite = CompositeNotifier([mock1, mock2])
        event = GateEvent(
            project_id="p", project_name="P", task_id="t",
            gate_decision=GateDecision.L2_HUMAN,
            trigger_reason="test", agent_role="backend",
        )
        result = await composite.notify(event)
        assert result is True

    @pytest.mark.asyncio
    async def test_composite_skips_auto_pass(self):
        mock1 = AsyncMock(spec=Notifier)
        mock1.should_notify.return_value = False

        composite = CompositeNotifier([mock1])
        event = GateEvent(
            project_id="p", project_name="P", task_id="t",
            gate_decision=GateDecision.AUTO_PASS,
            trigger_reason="ok", agent_role="backend",
        )
        # should_notify returns False → notify not called → no results → False
        result = await composite.notify(event)
        assert result is False

    def test_add_notifier(self):
        composite = CompositeNotifier()
        mock = AsyncMock(spec=Notifier)
        composite.add(mock)
        assert len(composite._notifiers) == 1


# --- SlackNotifier ---


class TestSlackNotifier:
    def test_should_notify_default(self):
        slack = SlackNotifier(webhook_url="https://hooks.slack.com/test")
        auto_pass = GateEvent(
            project_id="p", project_name="P", task_id="t",
            gate_decision=GateDecision.AUTO_PASS,
            trigger_reason="ok", agent_role="backend",
        )
        l2 = GateEvent(
            project_id="p", project_name="P", task_id="t",
            gate_decision=GateDecision.L2_HUMAN,
            trigger_reason="fail", agent_role="backend",
        )
        assert slack.should_notify(auto_pass) is False
        assert slack.should_notify(l2) is True

    def test_should_notify_with_auto_pass_enabled(self):
        slack = SlackNotifier(
            webhook_url="https://hooks.slack.com/test",
            notify_on_auto_pass=True,
        )
        event = GateEvent(
            project_id="p", project_name="P", task_id="t",
            gate_decision=GateDecision.AUTO_PASS,
            trigger_reason="ok", agent_role="backend",
        )
        assert slack.should_notify(event) is True

    def test_build_payload(self):
        slack = SlackNotifier(
            webhook_url="https://hooks.slack.com/test",
            channel="#alerts",
        )
        event = GateEvent(
            project_id="p",
            project_name="Test",
            task_id="task_1",
            gate_decision=GateDecision.L2_HUMAN,
            trigger_reason="Quality issue",
            agent_role="backend",
            review_score=55,
            timestamp=datetime(2026, 4, 24, 12, 0, 0),
        )
        payload = slack._build_payload(event)
        assert payload["channel"] == "#alerts"
        assert payload["username"] == "Archon Bot"
        assert len(payload["attachments"]) == 1
        attachment = payload["attachments"][0]
        assert attachment["color"] == _GATE_COLORS[GateDecision.L2_HUMAN]
        assert len(attachment["fields"]) == 4

    @pytest.mark.asyncio
    async def test_notify_success(self):
        slack = SlackNotifier(webhook_url="https://hooks.slack.com/test")
        event = GateEvent(
            project_id="p", project_name="P", task_id="t",
            gate_decision=GateDecision.L2_HUMAN,
            trigger_reason="test", agent_role="backend",
        )
        with patch("src.notifications.slack.httpx.AsyncClient") as mock_client_cls:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await slack.notify(event)
            assert result is True

    @pytest.mark.asyncio
    async def test_notify_failure(self):
        slack = SlackNotifier(webhook_url="https://hooks.slack.com/test")
        event = GateEvent(
            project_id="p", project_name="P", task_id="t",
            gate_decision=GateDecision.L2_HUMAN,
            trigger_reason="test", agent_role="backend",
        )
        with patch("src.notifications.slack.httpx.AsyncClient") as mock_client_cls:
            mock_response = MagicMock()
            mock_response.status_code = 500
            mock_response.text = "Internal Server Error"
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await slack.notify(event)
            assert result is False

    def test_gate_colors_and_emojis_cover_all(self):
        for gate in GateDecision:
            assert gate in _GATE_COLORS
            assert gate in _GATE_EMOJI


# --- TerminalNotifier ---


class TestTerminalNotifier:
    @pytest.mark.asyncio
    async def test_notify_prints_panel(self):
        from io import StringIO

        from rich.console import Console

        output = StringIO()
        console = Console(file=output, force_terminal=True)
        notifier = TerminalNotifier(console=console, desktop_notification=False)
        event = GateEvent(
            project_id="p",
            project_name="TestProject",
            task_id="task_1",
            gate_decision=GateDecision.L2_HUMAN,
            trigger_reason="Quality threshold",
            agent_role="backend",
            review_score=55,
            retry_count=1,
        )
        result = await notifier.notify(event)
        assert result is True
        text = output.getvalue()
        assert "TestProject" in text
        assert "task_1" in text

    @pytest.mark.asyncio
    async def test_notify_auto_pass_skipped(self):
        notifier = TerminalNotifier(desktop_notification=False)
        event = GateEvent(
            project_id="p", project_name="P", task_id="t",
            gate_decision=GateDecision.AUTO_PASS,
            trigger_reason="ok", agent_role="backend",
        )
        assert notifier.should_notify(event) is False

    @pytest.mark.asyncio
    async def test_notify_auto_pass_enabled(self):
        from io import StringIO

        from rich.console import Console

        output = StringIO()
        console = Console(file=output, force_terminal=True)
        notifier = TerminalNotifier(
            console=console,
            desktop_notification=False,
            notify_on_auto_pass=True,
        )
        event = GateEvent(
            project_id="p", project_name="P", task_id="t",
            gate_decision=GateDecision.AUTO_PASS,
            trigger_reason="ok", agent_role="backend",
        )
        assert notifier.should_notify(event) is True
        result = await notifier.notify(event)
        assert result is True
