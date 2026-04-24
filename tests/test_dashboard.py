"""Dashboard 모듈 테스트 — 모델, 라우트, WebSocket, 앱."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.dashboard.models import (
    AgentStatusResponse,
    CostSummary,
    DashboardEvent,
    GateQueueItem,
    ProjectSummary,
)
from src.dashboard.routes import DashboardRoutes
from src.dashboard.websocket import WebSocketManager


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class TestProjectSummary:
    def test_defaults(self):
        p = ProjectSummary(project_id="p1")
        assert p.project_id == "p1"
        assert p.status == "active"
        assert p.pending_tasks == 0

    def test_with_values(self):
        p = ProjectSummary(project_id="p1", project_name="My Project", priority=5)
        assert p.project_name == "My Project"
        assert p.priority == 5


class TestAgentStatusResponse:
    def test_defaults(self):
        a = AgentStatusResponse(role="backend")
        assert a.health_status == "healthy"
        assert a.consecutive_failures == 0

    def test_with_values(self):
        a = AgentStatusResponse(role="backend", health_status="degraded", consecutive_failures=3)
        assert a.health_status == "degraded"


class TestCostSummary:
    def test_defaults(self):
        c = CostSummary(project_id="p1")
        assert c.total_cost_usd == 0.0
        assert c.usage_ratio == 0.0

    def test_with_values(self):
        c = CostSummary(project_id="p1", daily_tokens_used=1000, total_cost_usd=0.5)
        assert c.daily_tokens_used == 1000


class TestGateQueueItem:
    def test_defaults(self):
        g = GateQueueItem(handoff_id="h1", project_id="p1", gate_level="L2_HUMAN")
        assert g.gate_level == "L2_HUMAN"
        assert g.created_at is not None


class TestDashboardEvent:
    def test_defaults(self):
        e = DashboardEvent(event_type="test")
        assert e.event_type == "test"
        assert e.payload == {}
        assert e.timestamp is not None

    def test_with_payload(self):
        e = DashboardEvent(event_type="gate_approved", payload={"id": "h1"})
        assert e.payload["id"] == "h1"

    def test_serialization(self):
        e = DashboardEvent(event_type="test", payload={"key": "value"})
        data = e.model_dump_json()
        assert "test" in data


# ---------------------------------------------------------------------------
# WebSocketManager
# ---------------------------------------------------------------------------


class TestWebSocketManager:
    @pytest.mark.asyncio
    async def test_connect_increments_count(self):
        mgr = WebSocketManager()
        ws = AsyncMock()
        await mgr.connect(ws)
        assert mgr.connection_count == 1

    @pytest.mark.asyncio
    async def test_disconnect_decrements_count(self):
        mgr = WebSocketManager()
        ws = AsyncMock()
        await mgr.connect(ws)
        await mgr.disconnect(ws)
        assert mgr.connection_count == 0

    @pytest.mark.asyncio
    async def test_disconnect_unknown_no_error(self):
        mgr = WebSocketManager()
        await mgr.disconnect(MagicMock())
        assert mgr.connection_count == 0

    @pytest.mark.asyncio
    async def test_broadcast_to_connections(self):
        mgr = WebSocketManager()
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        await mgr.connect(ws1)
        await mgr.connect(ws2)
        event = DashboardEvent(event_type="test", payload={"k": "v"})
        sent = await mgr.broadcast(event)
        assert sent == 2

    @pytest.mark.asyncio
    async def test_broadcast_removes_dead_connections(self):
        mgr = WebSocketManager()
        ws_good = AsyncMock()
        ws_dead = AsyncMock()
        ws_dead.send_text.side_effect = ConnectionError("closed")
        await mgr.connect(ws_good)
        await mgr.connect(ws_dead)
        event = DashboardEvent(event_type="test")
        sent = await mgr.broadcast(event)
        assert sent == 1
        assert mgr.connection_count == 1

    @pytest.mark.asyncio
    async def test_broadcast_empty_no_error(self):
        mgr = WebSocketManager()
        event = DashboardEvent(event_type="test")
        sent = await mgr.broadcast(event)
        assert sent == 0

    @pytest.mark.asyncio
    async def test_broadcast_dict(self):
        mgr = WebSocketManager()
        ws = AsyncMock()
        await mgr.connect(ws)
        sent = await mgr.broadcast_dict("test_event", {"data": 1})
        assert sent == 1


# ---------------------------------------------------------------------------
# DashboardRoutes
# ---------------------------------------------------------------------------


class TestDashboardRoutes:
    @pytest.mark.asyncio
    async def test_list_projects_empty(self):
        routes = DashboardRoutes()
        result = await routes.list_projects()
        assert result == []

    @pytest.mark.asyncio
    async def test_list_projects_with_store(self):
        store = MagicMock()
        store.list_projects.return_value = ["p1", "p2"]
        reg = MagicMock()
        reg.project_name = "Project 1"
        reg.status = "active"
        reg.priority = 1
        store.load.return_value = reg

        routes = DashboardRoutes(registry_store=store)
        result = await routes.list_projects()
        assert len(result) == 2
        assert result[0].project_name == "Project 1"

    @pytest.mark.asyncio
    async def test_get_project_not_found(self):
        routes = DashboardRoutes()
        result = await routes.get_project("p1")
        assert result is None

    @pytest.mark.asyncio
    async def test_list_agents_empty(self):
        routes = DashboardRoutes()
        result = await routes.list_agents()
        assert result == []

    @pytest.mark.asyncio
    async def test_list_agents_with_registry(self):
        monitor = MagicMock()
        monitor.get_summary.return_value = {
            "status": "healthy",
            "consecutive_failures": 0,
            "avg_latency_ms": 500.0,
            "total_checks": 10,
        }
        health_reg = MagicMock()
        health_reg._monitors = {"backend": monitor}

        routes = DashboardRoutes(health_registry=health_reg)
        result = await routes.list_agents()
        assert len(result) == 1
        assert result[0].role == "backend"
        assert result[0].health_status == "healthy"

    @pytest.mark.asyncio
    async def test_get_agent_found(self):
        monitor = MagicMock()
        monitor.get_summary.return_value = {
            "status": "degraded", "consecutive_failures": 3,
            "avg_latency_ms": 2000.0, "total_checks": 5,
        }
        health_reg = MagicMock()
        health_reg._monitors = {"backend": monitor}

        routes = DashboardRoutes(health_registry=health_reg)
        result = await routes.get_agent("backend")
        assert result is not None
        assert result.health_status == "degraded"

    @pytest.mark.asyncio
    async def test_get_agent_not_found(self):
        routes = DashboardRoutes()
        result = await routes.get_agent("unknown")
        assert result is None

    @pytest.mark.asyncio
    async def test_list_gate_queue(self):
        items = [
            GateQueueItem(handoff_id="h1", project_id="p1", gate_level="L2_HUMAN"),
            GateQueueItem(handoff_id="h2", project_id="p1", gate_level="L3_HALT"),
        ]
        routes = DashboardRoutes(gate_queue=items)
        result = await routes.list_gate_queue()
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_approve_gate(self):
        items = [GateQueueItem(handoff_id="h1", project_id="p1", gate_level="L2_HUMAN")]
        routes = DashboardRoutes(gate_queue=items)
        result = await routes.approve_gate("h1")
        assert result["status"] == "approved"
        assert len(await routes.list_gate_queue()) == 0

    @pytest.mark.asyncio
    async def test_reject_gate(self):
        items = [GateQueueItem(handoff_id="h1", project_id="p1", gate_level="L2_HUMAN")]
        routes = DashboardRoutes(gate_queue=items)
        result = await routes.reject_gate("h1")
        assert result["status"] == "rejected"

    @pytest.mark.asyncio
    async def test_get_metrics_empty(self):
        routes = DashboardRoutes()
        result = await routes.get_metrics()
        assert result == {}

    @pytest.mark.asyncio
    async def test_get_metrics_with_collector(self):
        from src.evolution.models import PipelineMetrics
        collector = MagicMock()
        collector.get_metrics.return_value = PipelineMetrics(
            total_executions=10, success_rate=0.8,
        )
        routes = DashboardRoutes(metrics_collector=collector)
        result = await routes.get_metrics()
        assert result["total_executions"] == 10

    @pytest.mark.asyncio
    async def test_add_gate_item(self):
        routes = DashboardRoutes()
        item = GateQueueItem(handoff_id="h1", project_id="p1", gate_level="L2_HUMAN")
        routes.add_gate_item(item)
        queue = await routes.list_gate_queue()
        assert len(queue) == 1

    @pytest.mark.asyncio
    async def test_list_costs_empty(self):
        routes = DashboardRoutes()
        result = await routes.list_costs()
        assert result == []


# ---------------------------------------------------------------------------
# DashboardApp
# ---------------------------------------------------------------------------


class TestDashboardApp:
    def test_creation(self):
        from src.dashboard.app import DashboardApp
        app = DashboardApp()
        assert app.routes is not None
        assert app.ws_manager is not None

    def test_create_app_requires_fastapi(self):
        from src.dashboard.app import DashboardApp, _HAS_FASTAPI
        app = DashboardApp()
        if _HAS_FASTAPI:
            fastapi_app = app.create_app()
            assert fastapi_app is not None
        else:
            with pytest.raises(RuntimeError):
                app.create_app()
