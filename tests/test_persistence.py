"""DashboardStore (TaskStore + GateStore + UsageStore + BudgetStore) 단위 테스트."""

from __future__ import annotations

import pytest

from src.dashboard.persistence import (
    BudgetPeriod,
    BudgetThreshold,
    DashboardStore,
    GateStatus,
    TaskStatus,
)


@pytest.fixture
def store(tmp_path) -> DashboardStore:
    return DashboardStore(tmp_path / "dashboard.db")


# ---------------------------------------------------------------------------
# TaskStore
# ---------------------------------------------------------------------------


class TestTaskStore:
    def test_create_and_get(self, store):
        rec = store.tasks.create(
            task_id="t1",
            project_id="p1",
            agent_role="backend",
            instructions="do something",
        )
        assert rec.status == TaskStatus.PENDING

        loaded = store.tasks.get("t1")
        assert loaded is not None
        assert loaded.id == "t1"
        assert loaded.project_id == "p1"
        assert loaded.status == TaskStatus.PENDING
        assert loaded.created_at == loaded.updated_at

    def test_transition_to_running_sets_started_at(self, store):
        store.tasks.create(
            task_id="t1",
            project_id="p1",
            agent_role="backend",
            instructions="x",
        )
        rec = store.tasks.transition("t1", status=TaskStatus.RUNNING)
        assert rec is not None
        assert rec.status == TaskStatus.RUNNING
        assert rec.started_at is not None
        assert rec.completed_at is None

    def test_transition_to_completed_sets_completed_at(self, store):
        store.tasks.create(
            task_id="t1", project_id="p1", agent_role="backend", instructions="x"
        )
        store.tasks.transition("t1", status=TaskStatus.RUNNING)
        rec = store.tasks.transition(
            "t1", status=TaskStatus.SUCCEEDED, gate_decision="AUTO_PASS"
        )
        assert rec.completed_at is not None
        assert rec.gate_decision == "AUTO_PASS"

    def test_transition_unknown_returns_none(self, store):
        assert store.tasks.transition("ghost", status=TaskStatus.RUNNING) is None

    def test_list_active_only(self, store):
        store.tasks.create(
            task_id="t1", project_id="p1", agent_role="backend", instructions="a"
        )
        store.tasks.create(
            task_id="t2", project_id="p1", agent_role="backend", instructions="b"
        )
        store.tasks.transition("t2", status=TaskStatus.SUCCEEDED)

        active = store.tasks.list(active_only=True)
        ids = sorted(t.id for t in active)
        assert ids == ["t1"]

    def test_list_filter_by_status_and_project(self, store):
        store.tasks.create(
            task_id="t1", project_id="p1", agent_role="backend", instructions="a"
        )
        store.tasks.create(
            task_id="t2", project_id="p2", agent_role="backend", instructions="b"
        )
        store.tasks.transition("t1", status=TaskStatus.FAILED)

        failed = store.tasks.list(status=TaskStatus.FAILED)
        assert [t.id for t in failed] == ["t1"]

        p2 = store.tasks.list(project_id="p2")
        assert [t.id for t in p2] == ["t2"]

    def test_persist_across_reopen(self, tmp_path):
        path = tmp_path / "dashboard.db"
        s1 = DashboardStore(path)
        s1.tasks.create(
            task_id="t1", project_id="p1", agent_role="backend", instructions="x"
        )
        s1.close()

        s2 = DashboardStore(path)
        rec = s2.tasks.get("t1")
        assert rec is not None
        assert rec.id == "t1"
        s2.close()

    def test_metadata_round_trip(self, store):
        rec = store.tasks.create(
            task_id="t1",
            project_id="p1",
            agent_role="backend",
            instructions="x",
            metadata={"mock": True, "scenario": "auto_pass"},
        )
        loaded = store.tasks.get("t1")
        assert loaded.metadata == {"mock": True, "scenario": "auto_pass"}
        assert rec.metadata == loaded.metadata


# ---------------------------------------------------------------------------
# GateStore
# ---------------------------------------------------------------------------


class TestGateStore:
    def test_enqueue_and_list(self, store):
        store.gates.enqueue(
            handoff_id="h1",
            project_id="p1",
            gate_level="L2_HUMAN",
            agent_role="backend",
            review_score=72,
        )
        items = store.gates.list()
        assert len(items) == 1
        assert items[0].handoff_id == "h1"
        assert items[0].status == GateStatus.PENDING
        assert items[0].review_score == 72

    def test_approve_with_comment(self, store):
        store.gates.enqueue(
            handoff_id="h1",
            project_id="p1",
            gate_level="L2_HUMAN",
        )
        rec = store.gates.decide(
            "h1",
            status=GateStatus.APPROVED,
            comment="LGTM",
            decided_by="alice",
        )
        assert rec is not None
        assert rec.status == GateStatus.APPROVED
        assert rec.decision_comment == "LGTM"
        assert rec.decided_by == "alice"
        assert rec.decided_at is not None

    def test_approve_without_comment_allowed(self, store):
        store.gates.enqueue(
            handoff_id="h1", project_id="p1", gate_level="L2_HUMAN"
        )
        rec = store.gates.decide(
            "h1", status=GateStatus.APPROVED, comment=None
        )
        assert rec.status == GateStatus.APPROVED

    def test_reject_requires_comment(self, store):
        store.gates.enqueue(
            handoff_id="h1", project_id="p1", gate_level="L2_HUMAN"
        )
        with pytest.raises(ValueError):
            store.gates.decide("h1", status=GateStatus.REJECTED, comment=None)
        with pytest.raises(ValueError):
            store.gates.decide("h1", status=GateStatus.REJECTED, comment="   ")

    def test_decide_unknown_returns_none(self, store):
        assert (
            store.gates.decide(
                "ghost", status=GateStatus.APPROVED, comment=None
            )
            is None
        )

    def test_double_decide_returns_none(self, store):
        store.gates.enqueue(
            handoff_id="h1", project_id="p1", gate_level="L2_HUMAN"
        )
        store.gates.decide("h1", status=GateStatus.APPROVED, comment=None)
        # 두 번째 decide는 pending이 아니므로 None.
        assert (
            store.gates.decide(
                "h1", status=GateStatus.REJECTED, comment="too late"
            )
            is None
        )

    def test_list_filter_decided(self, store):
        store.gates.enqueue(
            handoff_id="h1", project_id="p1", gate_level="L2_HUMAN"
        )
        store.gates.decide("h1", status=GateStatus.APPROVED, comment="ok")
        approved = store.gates.list(status=GateStatus.APPROVED)
        assert len(approved) == 1
        pending = store.gates.list(status=GateStatus.PENDING)
        assert pending == []

    def test_payload_roundtrip(self, store):
        payload = {"diff": "+++ a", "score": 85, "files": ["a.py", "b.py"]}
        store.gates.enqueue(
            handoff_id="h1",
            project_id="p1",
            gate_level="L2_HUMAN",
            payload=payload,
        )
        rec = store.gates.get("h1")
        assert rec.payload == payload


# ---------------------------------------------------------------------------
# UsageStore
# ---------------------------------------------------------------------------


class TestUsageStore:
    def test_record_and_query(self, store):
        store.usage.record_event(
            project_id="p1",
            agent_role="backend",
            model="gpt-4o",
            tokens_in=1000,
            tokens_out=500,
            cost_usd=0.01,
        )
        store.usage.record_event(
            project_id="p1",
            agent_role="frontend",
            model="gpt-4o",
            tokens_in=2000,
            tokens_out=1000,
            cost_usd=0.02,
        )
        ts = store.usage.query_timeseries(period="daily")
        # 같은 날 두 이벤트 → 한 버킷.
        assert len(ts) == 1
        assert ts[0].cost_usd == pytest.approx(0.03)
        assert ts[0].tokens_in == 3000
        assert ts[0].events == 2

    def test_query_group_by_role(self, store):
        store.usage.record_event(
            project_id="p1", agent_role="backend", model="x",
            tokens_in=100, tokens_out=100, cost_usd=0.5,
        )
        store.usage.record_event(
            project_id="p1", agent_role="frontend", model="x",
            tokens_in=50, tokens_out=50, cost_usd=0.25,
        )
        ts = store.usage.query_timeseries(period="daily", group_by="role")
        roles = {p.group: p.cost_usd for p in ts}
        assert roles["backend"] == pytest.approx(0.5)
        assert roles["frontend"] == pytest.approx(0.25)

    def test_query_filter_project(self, store):
        store.usage.record_event(
            project_id="p1", agent_role="r", model="m",
            tokens_in=1, tokens_out=1, cost_usd=1.0,
        )
        store.usage.record_event(
            project_id="p2", agent_role="r", model="m",
            tokens_in=1, tokens_out=1, cost_usd=2.0,
        )
        ts = store.usage.query_timeseries(period="daily", project_id="p2")
        assert sum(p.cost_usd for p in ts) == pytest.approx(2.0)

    def test_query_invalid_period(self, store):
        with pytest.raises(ValueError):
            store.usage.query_timeseries(period="weekly")

    def test_query_invalid_group_by(self, store):
        with pytest.raises(ValueError):
            store.usage.query_timeseries(period="daily", group_by="bogus")

    def test_summary_today_and_month(self, store):
        from datetime import UTC, datetime, timedelta
        now = datetime.now(UTC)
        store.usage.record_event(
            project_id="p1", agent_role="backend", model="x",
            tokens_in=100, tokens_out=200, cost_usd=0.10,
            timestamp=now.isoformat(),
        )
        # 어제 이벤트
        store.usage.record_event(
            project_id="p2", agent_role="frontend", model="x",
            tokens_in=300, tokens_out=300, cost_usd=0.30,
            timestamp=(now - timedelta(days=1)).isoformat(),
        )
        s = store.usage.get_summary()
        assert s.today_cost_usd == pytest.approx(0.10)
        assert s.today_tokens == 300
        # 어제가 같은 달이면 0.40, 다른 달이면 0.10 — 둘 다 today를 포함.
        assert s.month_cost_usd >= 0.10 - 1e-9
        assert s.by_role_today.get("backend") == pytest.approx(0.10)

    def test_purge_older_than(self, store):
        from datetime import UTC, datetime, timedelta
        now = datetime.now(UTC)
        store.usage.record_event(
            project_id="p1", agent_role="r", model="x",
            tokens_in=1, tokens_out=1, cost_usd=1.0,
            timestamp=(now - timedelta(days=30)).isoformat(),
        )
        store.usage.record_event(
            project_id="p1", agent_role="r", model="x",
            tokens_in=1, tokens_out=1, cost_usd=2.0,
            timestamp=now.isoformat(),
        )
        cutoff = (now - timedelta(days=10)).isoformat()
        deleted = store.usage.purge_older_than(before=cutoff)
        assert deleted == 1
        remaining = store.usage.query_timeseries(period="daily")
        assert sum(p.cost_usd for p in remaining) == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# BudgetStore
# ---------------------------------------------------------------------------


class TestBudgetStore:
    def test_upsert_creates(self, store):
        t = store.budgets.upsert(
            BudgetThreshold(scope="global", period=BudgetPeriod.DAILY, limit_usd=10.0)
        )
        assert t.id is not None
        items = store.budgets.list()
        assert len(items) == 1

    def test_upsert_updates_existing(self, store):
        store.budgets.upsert(
            BudgetThreshold(scope="global", period=BudgetPeriod.DAILY, limit_usd=10.0)
        )
        store.budgets.upsert(
            BudgetThreshold(
                scope="global", period=BudgetPeriod.DAILY, limit_usd=20.0,
                notify_email="ops@example.com",
            )
        )
        items = store.budgets.list()
        assert len(items) == 1
        assert items[0].limit_usd == 20.0
        assert items[0].notify_email == "ops@example.com"

    def test_delete(self, store):
        t = store.budgets.upsert(
            BudgetThreshold(scope="global", period=BudgetPeriod.DAILY, limit_usd=5.0)
        )
        assert store.budgets.delete(t.id) is True
        assert store.budgets.delete(t.id) is False
        assert store.budgets.list() == []

    def test_status_ratio_and_exceeded(self, store):
        store.budgets.upsert(
            BudgetThreshold(scope="global", period=BudgetPeriod.DAILY, limit_usd=1.0)
        )
        store.usage.record_event(
            project_id="p1", agent_role="r", model="x",
            tokens_in=1, tokens_out=1, cost_usd=1.5,
        )
        statuses = store.budgets.status()
        assert len(statuses) == 1
        s = statuses[0]
        assert s.used_usd == pytest.approx(1.5)
        assert s.usage_ratio == pytest.approx(1.5)
        assert s.exceeded is True

    def test_status_scoped_to_project(self, store):
        store.budgets.upsert(
            BudgetThreshold(
                scope="project:p1", period=BudgetPeriod.DAILY, limit_usd=5.0
            )
        )
        store.usage.record_event(
            project_id="p1", agent_role="r", model="x",
            tokens_in=1, tokens_out=1, cost_usd=2.0,
        )
        store.usage.record_event(
            project_id="p2", agent_role="r", model="x",
            tokens_in=1, tokens_out=1, cost_usd=10.0,
        )
        statuses = store.budgets.status()
        assert statuses[0].used_usd == pytest.approx(2.0)
        assert statuses[0].exceeded is False

    def test_status_scoped_to_role(self, store):
        store.budgets.upsert(
            BudgetThreshold(
                scope="role:backend", period=BudgetPeriod.DAILY, limit_usd=5.0
            )
        )
        store.usage.record_event(
            project_id="p1", agent_role="backend", model="x",
            tokens_in=1, tokens_out=1, cost_usd=3.0,
        )
        store.usage.record_event(
            project_id="p1", agent_role="frontend", model="x",
            tokens_in=1, tokens_out=1, cost_usd=10.0,
        )
        statuses = store.budgets.status()
        assert statuses[0].used_usd == pytest.approx(3.0)
