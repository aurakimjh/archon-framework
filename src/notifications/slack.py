"""Slack 알림 — Webhook 기반 알림 전송."""

from __future__ import annotations

import logging

import httpx

from src.gate.models import GateDecision
from src.notifications.base import GateEvent, Notifier

logger = logging.getLogger(__name__)

# Gate 레벨별 Slack 색상
_GATE_COLORS: dict[str, str] = {
    GateDecision.AUTO_PASS: "#36a64f",   # 초록
    GateDecision.L1_REWORK: "#ff9900",   # 주황
    GateDecision.L2_HUMAN: "#ff0000",    # 빨강
    GateDecision.L3_HALT: "#8b0000",     # 진빨강
    GateDecision.L4_DEPLOY: "#0066cc",   # 파랑
}

# Gate 레벨별 이모지
_GATE_EMOJI: dict[str, str] = {
    GateDecision.AUTO_PASS: ":white_check_mark:",
    GateDecision.L1_REWORK: ":warning:",
    GateDecision.L2_HUMAN: ":rotating_light:",
    GateDecision.L3_HALT: ":no_entry:",
    GateDecision.L4_DEPLOY: ":rocket:",
}


class SlackNotifier(Notifier):
    """Slack Incoming Webhook으로 알림을 전송한다."""

    def __init__(
        self,
        webhook_url: str,
        channel: str | None = None,
        username: str = "Archon Bot",
        timeout: float = 10.0,
        notify_on_auto_pass: bool = False,
    ) -> None:
        self._webhook_url = webhook_url
        self._channel = channel
        self._username = username
        self._timeout = timeout
        self._notify_on_auto_pass = notify_on_auto_pass

    def should_notify(self, event: GateEvent) -> bool:
        """AUTO_PASS 알림은 설정에 따라 결정."""
        if event.gate_decision == GateDecision.AUTO_PASS:
            return self._notify_on_auto_pass
        return True

    async def notify(self, event: GateEvent) -> bool:
        """Slack webhook으로 알림을 전송한다."""
        payload = self._build_payload(event)

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(self._webhook_url, json=payload)
                if response.status_code == 200:
                    logger.info(
                        "Slack notification sent: [%s] %s",
                        event.gate_decision,
                        event.task_id,
                    )
                    return True
                else:
                    logger.warning(
                        "Slack notification failed: HTTP %d — %s",
                        response.status_code,
                        response.text,
                    )
                    return False
        except httpx.HTTPError as e:
            logger.error("Slack notification error: %s", e)
            return False

    def _build_payload(self, event: GateEvent) -> dict:
        """Slack 메시지 페이로드를 구성한다."""
        color = _GATE_COLORS.get(event.gate_decision, "#808080")
        emoji = _GATE_EMOJI.get(event.gate_decision, ":bell:")

        attachment = {
            "color": color,
            "title": f"{emoji} {event.title}",
            "text": event.summary,
            "fields": [
                {"title": "Gate", "value": str(event.gate_decision), "short": True},
                {"title": "Score", "value": str(event.review_score), "short": True},
                {"title": "Agent", "value": event.agent_role, "short": True},
                {"title": "Retry", "value": str(event.retry_count), "short": True},
            ],
            "ts": int(event.timestamp.timestamp()),
        }

        payload: dict = {
            "username": self._username,
            "attachments": [attachment],
        }

        if self._channel:
            payload["channel"] = self._channel

        return payload
