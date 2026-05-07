"""알림 디스패처 — Slack incoming webhook · 일반 JSON · email(noop).

NotificationRuleStore의 enabled 규칙을 이벤트 단위로 호출한다.
HTTP는 httpx로 비동기 전송, 실패는 로그로만 흡수(요청 흐름을 막지 않는다).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from src.dashboard.persistence import (
    NotificationChannel,
    NotificationEvent,
    NotificationRule,
    NotificationRuleStore,
)

logger = logging.getLogger(__name__)

try:
    import httpx

    _HAS_HTTPX = True
except ImportError:  # pragma: no cover
    _HAS_HTTPX = False


def format_slack_payload(event: NotificationEvent, payload: dict[str, Any]) -> dict[str, Any]:
    """Slack 형식으로 메시지를 변환."""
    title = {
        NotificationEvent.BUDGET_EXCEEDED: ":warning: Budget exceeded",
        NotificationEvent.GATE_ENQUEUED: ":shield: Human gate pending",
    }.get(event, str(event))

    lines = [f"*{title}*"]
    for key in ("scope", "limit_usd", "used_usd", "ratio", "handoff_id", "project_id", "gate_level", "review_score", "agent_role"):
        if key in payload and payload[key] is not None:
            lines.append(f"• *{key}*: `{payload[key]}`")
    return {"text": "\n".join(lines)}


async def _dispatch_one(rule: NotificationRule, payload: dict[str, Any]) -> bool:
    """단일 규칙으로 발송. 실패 시 로그만 남기고 False 반환."""
    if not rule.enabled:
        return False

    if rule.channel == NotificationChannel.EMAIL:
        # SMTP 미구현 — 로그만 남긴다.
        logger.info(
            "notification_email", extra={"to": rule.target, "payload": payload}
        )
        return True

    if not _HAS_HTTPX:
        logger.warning("httpx not installed — skipping HTTP notification")
        return False

    if rule.channel == NotificationChannel.SLACK:
        body = format_slack_payload(rule.event, payload)
    else:
        body = {"event": rule.event.value, **payload}

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(rule.target, json=body)
            resp.raise_for_status()
        return True
    except Exception as exc:  # noqa: BLE001 — alert 실패가 흐름을 막지 않게.
        logger.warning(
            "notification_dispatch_failed",
            extra={
                "channel": rule.channel.value,
                "target": _redact_url(rule.target),
                "error": str(exc)[:200],
            },
        )
        return False


def _redact_url(url: str) -> str:
    """Slack incoming webhook 등 secret 토큰을 로그에서 마스킹."""
    if "://" not in url:
        return url
    head, _, _ = url.partition("/services/")
    return f"{head}/services/****" if head else url


async def notify(
    *,
    event: NotificationEvent,
    payload: dict[str, Any],
    store: NotificationRuleStore,
) -> int:
    """주어진 이벤트의 enabled 규칙 모두에 비동기 발송한다. 성공 카운트 반환."""
    rules = store.list(event=event, enabled_only=True)
    if not rules:
        return 0
    results = await asyncio.gather(
        *(_dispatch_one(r, payload) for r in rules),
        return_exceptions=True,
    )
    return sum(1 for r in results if r is True)


def fire_and_forget(
    *,
    event: NotificationEvent,
    payload: dict[str, Any],
    store: NotificationRuleStore,
) -> asyncio.Task[int]:
    """notify를 background task로 던지고 즉시 반환."""
    return asyncio.create_task(notify(event=event, payload=payload, store=store))
