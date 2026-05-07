"""AuditStore + NotificationRuleStore + Notifier 단위 테스트."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.dashboard.persistence import (
    DashboardStore,
    NotificationChannel,
    NotificationEvent,
    NotificationRule,
)


@pytest.fixture
def store(tmp_path) -> DashboardStore:
    return DashboardStore(tmp_path / "dashboard.db")


# ---------------------------------------------------------------------------
# AuditStore
# ---------------------------------------------------------------------------


class TestAuditStore:
    def test_emit_and_list(self, store):
        store.audit.emit(
            action="task.create", user_id="alice", user_role="admin",
            target="task_1", detail={"foo": "bar"},
        )
        evts = store.audit.list()
        assert len(evts) == 1
        assert evts[0].action == "task.create"
        assert evts[0].detail == {"foo": "bar"}

    def test_filter_by_user_action_target(self, store):
        store.audit.emit(action="task.create", user_id="alice", target="t1")
        store.audit.emit(action="task.cancel", user_id="alice", target="t1")
        store.audit.emit(action="task.create", user_id="bob", target="t2")

        assert len(store.audit.list(user_id="alice")) == 2
        assert len(store.audit.list(action="task.create")) == 2
        assert len(store.audit.list(target="t2")) == 1

    def test_search_q(self, store):
        store.audit.emit(action="budget.upsert", target="global:daily")
        store.audit.emit(action="user.delete", target="bob")

        hits = store.audit.list(q="bob")
        assert len(hits) == 1

    def test_filter_by_time_range(self, store):
        from datetime import UTC, datetime, timedelta
        # 직접 timestamp 가짜 주입
        with store._conn.tx() as cur:  # type: ignore[attr-defined]
            cur.execute(
                "INSERT INTO audit_events(timestamp, action, detail_json, result) "
                "VALUES (?, 'a.old', '{}', 'success')",
                ((datetime.now(UTC) - timedelta(days=10)).isoformat(),),
            )
            cur.execute(
                "INSERT INTO audit_events(timestamp, action, detail_json, result) "
                "VALUES (?, 'a.recent', '{}', 'success')",
                ((datetime.now(UTC) - timedelta(hours=1)).isoformat(),),
            )

        cutoff = (
            (datetime.now(UTC) - timedelta(days=2)).isoformat()
        )
        recent = store.audit.list(since=cutoff)
        assert {e.action for e in recent} == {"a.recent"}


# ---------------------------------------------------------------------------
# NotificationRuleStore
# ---------------------------------------------------------------------------


class TestNotificationStore:
    def test_upsert_and_list(self, store):
        rule = store.notifications.upsert(
            NotificationRule(
                event=NotificationEvent.GATE_ENQUEUED,
                channel=NotificationChannel.SLACK,
                target="https://hooks.slack.com/services/X/Y/Z",
                label="ops slack",
            )
        )
        assert rule.id is not None
        listing = store.notifications.list()
        assert len(listing) == 1
        assert listing[0].label == "ops slack"

    def test_filter_by_event(self, store):
        store.notifications.upsert(
            NotificationRule(
                event=NotificationEvent.GATE_ENQUEUED,
                channel=NotificationChannel.WEBHOOK,
                target="https://x",
            )
        )
        store.notifications.upsert(
            NotificationRule(
                event=NotificationEvent.BUDGET_EXCEEDED,
                channel=NotificationChannel.WEBHOOK,
                target="https://y",
            )
        )
        budget_rules = store.notifications.list(
            event=NotificationEvent.BUDGET_EXCEEDED
        )
        assert len(budget_rules) == 1

    def test_enabled_only(self, store):
        store.notifications.upsert(
            NotificationRule(
                event=NotificationEvent.GATE_ENQUEUED,
                channel=NotificationChannel.WEBHOOK,
                target="https://x",
                enabled=False,
            )
        )
        store.notifications.upsert(
            NotificationRule(
                event=NotificationEvent.GATE_ENQUEUED,
                channel=NotificationChannel.WEBHOOK,
                target="https://y",
                enabled=True,
            )
        )
        active = store.notifications.list(enabled_only=True)
        assert len(active) == 1
        assert active[0].target == "https://y"

    def test_delete(self, store):
        r = store.notifications.upsert(
            NotificationRule(
                event=NotificationEvent.BUDGET_EXCEEDED,
                channel=NotificationChannel.WEBHOOK,
                target="https://x",
            )
        )
        assert store.notifications.delete(r.id) is True
        assert store.notifications.delete(r.id) is False


# ---------------------------------------------------------------------------
# Notifier dispatch
# ---------------------------------------------------------------------------


class TestNotifierDispatch:
    @pytest.mark.asyncio
    async def test_webhook_dispatch_calls_post(self):
        from src.dashboard import notifications as N

        rule = NotificationRule(
            id=1,
            event=NotificationEvent.GATE_ENQUEUED,
            channel=NotificationChannel.WEBHOOK,
            target="https://example.test/hook",
        )

        client_mock = AsyncMock()
        resp_mock = AsyncMock()
        resp_mock.raise_for_status = lambda: None
        client_mock.post = AsyncMock(return_value=resp_mock)
        client_mock.__aenter__ = AsyncMock(return_value=client_mock)
        client_mock.__aexit__ = AsyncMock(return_value=False)

        with patch.object(N, "httpx") as httpx_mod:
            httpx_mod.AsyncClient = lambda **_: client_mock
            ok = await N._dispatch_one(rule, {"foo": "bar"})

        assert ok is True
        client_mock.post.assert_awaited_once()
        url, kwargs = client_mock.post.await_args.args, client_mock.post.await_args.kwargs
        assert url[0] == "https://example.test/hook"
        # 일반 webhook은 event + payload 를 그대로 전달
        assert kwargs["json"]["event"] == "gate.enqueued"
        assert kwargs["json"]["foo"] == "bar"

    @pytest.mark.asyncio
    async def test_slack_format(self):
        from src.dashboard import notifications as N

        rule = NotificationRule(
            id=2,
            event=NotificationEvent.BUDGET_EXCEEDED,
            channel=NotificationChannel.SLACK,
            target="https://hooks.slack.com/services/A/B/C",
        )

        client_mock = AsyncMock()
        resp_mock = AsyncMock()
        resp_mock.raise_for_status = lambda: None
        client_mock.post = AsyncMock(return_value=resp_mock)
        client_mock.__aenter__ = AsyncMock(return_value=client_mock)
        client_mock.__aexit__ = AsyncMock(return_value=False)

        with patch.object(N, "httpx") as httpx_mod:
            httpx_mod.AsyncClient = lambda **_: client_mock
            await N._dispatch_one(rule, {"scope": "global", "limit_usd": 5.0, "used_usd": 6.5})

        body = client_mock.post.await_args.kwargs["json"]
        assert "Budget exceeded" in body["text"]
        assert "global" in body["text"]

    @pytest.mark.asyncio
    async def test_dispatch_failure_swallowed(self):
        from src.dashboard import notifications as N

        rule = NotificationRule(
            id=3,
            event=NotificationEvent.GATE_ENQUEUED,
            channel=NotificationChannel.WEBHOOK,
            target="https://example.test/hook",
        )

        client_mock = AsyncMock()
        client_mock.post = AsyncMock(side_effect=RuntimeError("boom"))
        client_mock.__aenter__ = AsyncMock(return_value=client_mock)
        client_mock.__aexit__ = AsyncMock(return_value=False)

        with patch.object(N, "httpx") as httpx_mod:
            httpx_mod.AsyncClient = lambda **_: client_mock
            ok = await N._dispatch_one(rule, {})

        assert ok is False  # 예외가 흐름을 막지 않는다.

    def test_redact_url(self):
        from src.dashboard.notifications import _redact_url

        assert (
            _redact_url("https://hooks.slack.com/services/T/B/X")
            == "https://hooks.slack.com/services/****"
        )
        assert _redact_url("noscheme") == "noscheme"
