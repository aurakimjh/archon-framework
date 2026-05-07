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

    @pytest.mark.asyncio
    async def test_run_task(self):
        from src.dashboard.models import TaskRequest
        routes = DashboardRoutes()
        req = TaskRequest(
            project_id="test-p",
            instructions="test-instr",
            scenario="auto_pass",
            mock=True
        )
        
        # mock on_step (sync)
        on_step = MagicMock()
        
        result = await routes.run_task(req, on_step=on_step)
        assert result["status"] == "started"
        assert result["project_id"] == "test-p"
        assert result["task_id"].startswith("task_")


# ---------------------------------------------------------------------------
# DashboardApp
# ---------------------------------------------------------------------------


class TestDashboardApp:
    def test_creation(self):
        from src.dashboard.app import DashboardApp
        app = DashboardApp()
        assert app.routes is not None
        assert app.ws_manager is not None

    def test_create_app_requires_fastapi(self, monkeypatch, tmp_path):
        from src.dashboard.app import DashboardApp, _HAS_FASTAPI
        monkeypatch.setenv(
            "ARCHON_DASHBOARD_DB_PATH", str(tmp_path / "dashboard.db")
        )
        app = DashboardApp()
        if _HAS_FASTAPI:
            fastapi_app = app.create_app()
            assert fastapi_app is not None
        else:
            with pytest.raises(RuntimeError):
                app.create_app()


# ---------------------------------------------------------------------------
# Slice 1 — 보안 헤더 / 게이팅 / handoff_id 고유성
# ---------------------------------------------------------------------------


@pytest.fixture
def fastapi_client(monkeypatch, tmp_path):
    """인증 비활성 + 동일 출처 가정 TestClient. 격리된 DB 경로 사용."""
    from fastapi.testclient import TestClient

    from src.dashboard.app import DashboardApp

    monkeypatch.delenv("ARCHON_DASHBOARD_TOKEN", raising=False)
    monkeypatch.delenv("ARCHON_CORS_ORIGINS", raising=False)
    monkeypatch.delenv("ARCHON_ENV", raising=False)
    monkeypatch.setenv("ARCHON_DASHBOARD_DB_PATH", str(tmp_path / "dashboard.db"))

    app = DashboardApp().create_app()
    return TestClient(app)


class TestSecurityHeaders:
    def test_health_endpoint_has_security_headers(self, fastapi_client):
        res = fastapi_client.get("/api/health")
        assert res.status_code == 200
        assert res.headers.get("X-Content-Type-Options") == "nosniff"
        assert res.headers.get("X-Frame-Options") == "DENY"
        assert res.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
        assert "default-src 'self'" in res.headers.get("Content-Security-Policy", "")

    def test_csp_can_be_overridden(self, monkeypatch, tmp_path):
        from fastapi.testclient import TestClient

        from src.dashboard.app import DashboardApp

        monkeypatch.setenv("ARCHON_CSP", "default-src 'none'")
        monkeypatch.setenv(
            "ARCHON_DASHBOARD_DB_PATH", str(tmp_path / "dashboard.db")
        )
        app = DashboardApp().create_app()
        client = TestClient(app)
        res = client.get("/api/health")
        assert res.headers.get("Content-Security-Policy") == "default-src 'none'"


class TestCorsHardening:
    def test_no_origin_no_cors_header(self, fastapi_client):
        # 명시 origin이 없으면 CORS 미들웨어가 등록되지 않는다.
        res = fastapi_client.get(
            "/api/health", headers={"Origin": "https://evil.example"}
        )
        assert "Access-Control-Allow-Origin" not in res.headers

    def test_explicit_origin_allowed(self, monkeypatch, tmp_path):
        from fastapi.testclient import TestClient

        from src.dashboard.app import DashboardApp

        monkeypatch.setenv("ARCHON_CORS_ORIGINS", "https://app.example")
        monkeypatch.delenv("ARCHON_DASHBOARD_TOKEN", raising=False)
        monkeypatch.setenv(
            "ARCHON_DASHBOARD_DB_PATH", str(tmp_path / "dashboard.db")
        )
        client = TestClient(DashboardApp().create_app())
        res = client.get(
            "/api/health", headers={"Origin": "https://app.example"}
        )
        assert res.headers.get("Access-Control-Allow-Origin") == "https://app.example"


class TestHealthEndpoint:
    def test_shape(self, fastapi_client):
        res = fastapi_client.get("/api/health")
        body = res.json()
        assert body["status"] == "ok"
        assert "version" in body
        assert "env" in body
        assert body["auth_required"] is False


class TestMockGating:
    def test_mock_blocked_in_production(self, fastapi_client, monkeypatch):
        monkeypatch.delenv("ARCHON_ENV", raising=False)
        res = fastapi_client.post(
            "/api/tasks",
            json={
                "project_id": "p1",
                "instructions": "test",
                "scenario": "auto_pass",
                "mock": True,
                "agent_role": "backend",
            },
        )
        assert res.status_code == 403

    def test_non_default_scenario_blocked_in_production(
        self, fastapi_client, monkeypatch
    ):
        monkeypatch.delenv("ARCHON_ENV", raising=False)
        res = fastapi_client.post(
            "/api/tasks",
            json={
                "project_id": "p1",
                "instructions": "test",
                "scenario": "l1",
                "mock": False,
                "agent_role": "backend",
            },
        )
        assert res.status_code == 403

    def test_mock_allowed_in_dev(self, monkeypatch, tmp_path):
        from fastapi.testclient import TestClient

        from src.dashboard.app import DashboardApp

        monkeypatch.setenv("ARCHON_ENV", "dev")
        monkeypatch.delenv("ARCHON_DASHBOARD_TOKEN", raising=False)
        monkeypatch.setenv(
            "ARCHON_DASHBOARD_DB_PATH", str(tmp_path / "dashboard.db")
        )
        client = TestClient(DashboardApp().create_app())
        res = client.post(
            "/api/tasks",
            json={
                "project_id": "p1",
                "instructions": "test",
                "scenario": "auto_pass",
                "mock": True,
                "agent_role": "backend",
            },
        )
        assert res.status_code == 200
        assert res.json()["status"] == "started"


class TestHandoffIdUniqueness:
    @pytest.mark.asyncio
    async def test_repeat_calls_produce_unique_ids(self):
        from src.dashboard.models import TaskRequest

        routes = DashboardRoutes()
        req = TaskRequest(
            project_id="p-repeat",
            instructions="x",
            scenario="auto_pass",
            mock=True,
        )
        r1 = await routes.run_task(req)
        r2 = await routes.run_task(req)
        assert r1["task_id"] != r2["task_id"]
        assert r1["task_id"].startswith("task_p-repeat_")


class TestAgentConfigEndpoints:
    @pytest.fixture
    def configured_client(self, monkeypatch, tmp_path):
        from fastapi.testclient import TestClient
        import yaml as _yaml

        from src.dashboard.app import DashboardApp

        # 격리된 임시 파일로 store/litellm 경로를 지정.
        agent_path = tmp_path / "agent_config.yaml"
        litellm_path = tmp_path / "litellm.yaml"
        litellm_path.write_text(
            _yaml.safe_dump(
                {
                    "model_list": [
                        {
                            "model_name": "orchestrator",
                            "litellm_params": {"model": "anthropic/claude-opus-4-6"},
                        },
                        {
                            "model_name": "backend-agent",
                            "litellm_params": {"model": "openai/gpt-4o"},
                        },
                        {
                            "model_name": "reviewer",
                            "litellm_params": {"model": "anthropic/claude-sonnet-4-6"},
                        },
                    ]
                }
            )
        )
        monkeypatch.setenv("ARCHON_AGENT_CONFIG_PATH", str(agent_path))
        monkeypatch.setenv("ARCHON_LITELLM_CONFIG_PATH", str(litellm_path))
        monkeypatch.setenv(
            "ARCHON_DASHBOARD_DB_PATH", str(tmp_path / "dashboard.db")
        )
        monkeypatch.delenv("ARCHON_DASHBOARD_TOKEN", raising=False)

        return TestClient(DashboardApp().create_app())

    def test_get_agent_config_returns_defaults(self, configured_client):
        res = configured_client.get("/api/agent-config")
        assert res.status_code == 200
        body = res.json()
        assert "configs" in body
        assert "backend" in body["configs"]
        assert body["configs"]["backend"]["model"] == "backend-agent"

    def test_get_models(self, configured_client):
        res = configured_client.get("/api/models")
        assert res.status_code == 200
        names = [m["model_name"] for m in res.json()]
        assert "backend-agent" in names
        # 시크릿/URL이 응답에 없어야 한다.
        body_str = res.text
        assert "api_key" not in body_str
        assert "api_base" not in body_str

    def test_put_agent_config_updates_and_persists(
        self, configured_client, tmp_path
    ):
        res = configured_client.put(
            "/api/agent-config/backend",
            json={
                "role": "backend",
                "enabled": False,
                "model": "backend-agent",
                "fallback_models": [],
                "multi_provider_mode": "shadow",
                "system_prompt_override": "stay terse",
                "max_tokens": 8192,
                "temperature": 0.1,
            },
        )
        assert res.status_code == 200
        assert res.json()["enabled"] is False
        assert res.json()["multi_provider_mode"] == "shadow"

        # 디스크에도 영속화 — 다시 GET 시 반영.
        re_get = configured_client.get("/api/agent-config")
        assert re_get.json()["configs"]["backend"]["model"] == "backend-agent"
        assert re_get.json()["configs"]["backend"]["temperature"] == 0.1

    def test_put_unknown_role_returns_422(self, configured_client):
        res = configured_client.put(
            "/api/agent-config/unicorn",
            json={
                "role": "backend",
                "model": "backend-agent",
            },
        )
        assert res.status_code == 422

    def test_put_role_mismatch_returns_422(self, configured_client):
        res = configured_client.put(
            "/api/agent-config/backend",
            json={
                "role": "frontend",
                "model": "backend-agent",
            },
        )
        assert res.status_code == 422

    def test_put_unknown_model_returns_400(self, configured_client):
        res = configured_client.put(
            "/api/agent-config/backend",
            json={
                "role": "backend",
                "model": "no-such-model",
            },
        )
        assert res.status_code == 400
        assert "no-such-model" in res.json()["detail"]

    def test_put_unknown_fallback_model_returns_400(self, configured_client):
        res = configured_client.put(
            "/api/agent-config/backend",
            json={
                "role": "backend",
                "model": "backend-agent",
                "fallback_models": ["ghost-model"],
            },
        )
        assert res.status_code == 400


class TestTaskEndpoints:
    @pytest.fixture
    def dev_client(self, monkeypatch, tmp_path):
        from fastapi.testclient import TestClient

        from src.dashboard.app import DashboardApp

        monkeypatch.setenv("ARCHON_ENV", "dev")
        monkeypatch.delenv("ARCHON_DASHBOARD_TOKEN", raising=False)
        monkeypatch.setenv(
            "ARCHON_DASHBOARD_DB_PATH", str(tmp_path / "dashboard.db")
        )
        return TestClient(DashboardApp().create_app())

    def test_create_task_persists(self, dev_client):
        res = dev_client.post(
            "/api/tasks",
            json={
                "project_id": "p1",
                "instructions": "do X",
                "scenario": "auto_pass",
                "mock": True,
                "agent_role": "backend",
            },
        )
        assert res.status_code == 200
        task_id = res.json()["task_id"]
        assert task_id.startswith("task_p1_")

        # 파이프라인이 짧게 끝나도록 잠깐 대기 후 GET 확인.
        get = dev_client.get(f"/api/tasks/{task_id}")
        assert get.status_code == 200
        body = get.json()
        assert body["id"] == task_id
        assert body["project_id"] == "p1"
        assert body["status"] in {"pending", "running", "succeeded"}

    def test_list_tasks(self, dev_client):
        for _ in range(3):
            dev_client.post(
                "/api/tasks",
                json={
                    "project_id": "p1",
                    "instructions": "do",
                    "scenario": "auto_pass",
                    "mock": True,
                    "agent_role": "backend",
                },
            )
        res = dev_client.get("/api/tasks")
        assert res.status_code == 200
        assert len(res.json()) == 3

        filtered = dev_client.get("/api/tasks?project_id=p2")
        assert filtered.json() == []

    def test_get_task_404(self, dev_client):
        res = dev_client.get("/api/tasks/no-such-task")
        assert res.status_code == 404

    def test_cancel_task_404(self, dev_client):
        res = dev_client.post("/api/tasks/ghost/cancel")
        assert res.status_code == 404


class TestGateEndpointsWithStore:
    @pytest.fixture
    def gated_client(self, monkeypatch, tmp_path):
        from fastapi.testclient import TestClient

        from src.dashboard.app import DashboardApp
        from src.dashboard.persistence import DashboardStore

        monkeypatch.delenv("ARCHON_DASHBOARD_TOKEN", raising=False)
        store = DashboardStore(tmp_path / "dashboard.db")
        # enqueue 직접 — 사람이 수동으로 만든 핸드오프 테스트용
        store.gates.enqueue(
            handoff_id="h-pending",
            project_id="p1",
            gate_level="L2_HUMAN",
            trigger_reason="low score",
            agent_role="backend",
            review_score=65,
            payload={"diff": "+++ change", "files": ["x.py"]},
        )
        monkeypatch.setenv(
            "ARCHON_DASHBOARD_DB_PATH", str(tmp_path / "dashboard.db")
        )
        # store가 이미 같은 경로를 쓰므로 별도 주입 없이 새 앱이 같은 DB를 본다.
        store.close()
        return TestClient(DashboardApp().create_app())

    def test_get_gate_returns_payload(self, gated_client):
        res = gated_client.get("/api/gates/h-pending")
        assert res.status_code == 200
        body = res.json()
        assert body["handoff_id"] == "h-pending"
        assert body["payload"]["files"] == ["x.py"]
        assert body["status"] == "pending"

    def test_get_gate_404(self, gated_client):
        assert gated_client.get("/api/gates/missing").status_code == 404

    def test_approve_with_comment(self, gated_client):
        res = gated_client.post(
            "/api/gates/h-pending/approve",
            json={"comment": "LGTM", "reviewer": "alice"},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "approved"
        assert body["comment"] == "LGTM"

        # 이미 결정되었으므로 다시 approve는 404
        again = gated_client.post(
            "/api/gates/h-pending/approve", json={}
        )
        assert again.status_code == 404

    def test_reject_requires_comment(self, gated_client):
        res = gated_client.post("/api/gates/h-pending/reject", json={})
        assert res.status_code == 400

        res2 = gated_client.post(
            "/api/gates/h-pending/reject", json={"comment": "   "}
        )
        assert res2.status_code == 400

        ok = gated_client.post(
            "/api/gates/h-pending/reject",
            json={"comment": "missing tests", "reviewer": "bob"},
        )
        assert ok.status_code == 200
        assert ok.json()["status"] == "rejected"

    def test_queue_excludes_decided(self, gated_client):
        gated_client.post(
            "/api/gates/h-pending/approve", json={"comment": "ok"}
        )
        queue = gated_client.get("/api/gates/queue").json()
        assert queue == []


class TestUsageEndpoints:
    @pytest.fixture
    def usage_client(self, monkeypatch, tmp_path):
        from fastapi.testclient import TestClient

        from src.dashboard.app import DashboardApp

        monkeypatch.delenv("ARCHON_DASHBOARD_TOKEN", raising=False)
        monkeypatch.delenv("ARCHON_ENV", raising=False)
        monkeypatch.setenv(
            "ARCHON_DASHBOARD_DB_PATH", str(tmp_path / "dashboard.db")
        )
        return TestClient(DashboardApp().create_app())

    @pytest.fixture
    def dev_usage_client(self, monkeypatch, tmp_path):
        from fastapi.testclient import TestClient

        from src.dashboard.app import DashboardApp

        monkeypatch.delenv("ARCHON_DASHBOARD_TOKEN", raising=False)
        monkeypatch.setenv("ARCHON_ENV", "dev")
        monkeypatch.setenv(
            "ARCHON_DASHBOARD_DB_PATH", str(tmp_path / "dashboard.db")
        )
        return TestClient(DashboardApp().create_app())

    def test_summary_empty(self, usage_client):
        res = usage_client.get("/api/usage/summary")
        assert res.status_code == 200
        body = res.json()
        assert body["today_cost_usd"] == 0.0
        assert body["today_tokens"] == 0

    def test_timeseries_validation(self, usage_client):
        res = usage_client.get("/api/usage/timeseries?period=weekly")
        assert res.status_code == 422
        res = usage_client.get(
            "/api/usage/timeseries?period=daily&group_by=foo"
        )
        assert res.status_code == 422

    def test_seeder_blocked_in_production(self, usage_client):
        res = usage_client.post("/api/usage/seed?days=2&events_per_day=2")
        assert res.status_code == 403

    def test_seeder_works_in_dev_then_summary_nonzero(self, dev_usage_client):
        res = dev_usage_client.post(
            "/api/usage/seed?days=2&events_per_day=2"
        )
        assert res.status_code == 200
        assert res.json()["events"] == 4

        summary = dev_usage_client.get("/api/usage/summary").json()
        assert summary["today_cost_usd"] >= 0.0  # 시드는 오늘+어제 모두 채우므로 month_cost_usd가 양수
        assert summary["month_cost_usd"] > 0.0

        ts = dev_usage_client.get(
            "/api/usage/timeseries?period=daily&group_by=role"
        ).json()
        assert len(ts) >= 1
        assert {"backend", "frontend"} & {p["group"] for p in ts}


class TestBudgetEndpoints:
    @pytest.fixture
    def budget_client(self, monkeypatch, tmp_path):
        from fastapi.testclient import TestClient

        from src.dashboard.app import DashboardApp

        monkeypatch.delenv("ARCHON_DASHBOARD_TOKEN", raising=False)
        monkeypatch.delenv("ARCHON_ENV", raising=False)
        monkeypatch.setenv(
            "ARCHON_DASHBOARD_DB_PATH", str(tmp_path / "dashboard.db")
        )
        return TestClient(DashboardApp().create_app())

    def test_list_empty(self, budget_client):
        assert budget_client.get("/api/budgets").json() == []
        assert budget_client.get("/api/budgets/status").json() == []

    def test_upsert_then_list(self, budget_client):
        res = budget_client.put(
            "/api/budgets",
            json={"scope": "global", "period": "daily", "limit_usd": 5.0},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["limit_usd"] == 5.0
        assert body["id"] is not None

        # 같은 (scope,period)로 다시 PUT → 업데이트
        res2 = budget_client.put(
            "/api/budgets",
            json={
                "scope": "global",
                "period": "daily",
                "limit_usd": 10.0,
                "notify_email": "x@example.com",
            },
        )
        assert res2.status_code == 200
        assert res2.json()["limit_usd"] == 10.0

        listing = budget_client.get("/api/budgets").json()
        assert len(listing) == 1

    def test_negative_limit_rejected(self, budget_client):
        res = budget_client.put(
            "/api/budgets",
            json={"scope": "global", "period": "daily", "limit_usd": -1},
        )
        assert res.status_code == 400

    def test_delete_404(self, budget_client):
        assert budget_client.delete("/api/budgets/9999").status_code == 404

    def test_delete_round_trip(self, budget_client):
        created = budget_client.put(
            "/api/budgets",
            json={"scope": "global", "period": "monthly", "limit_usd": 50.0},
        ).json()
        tid = created["id"]
        assert budget_client.delete(f"/api/budgets/{tid}").status_code == 200
        assert budget_client.get("/api/budgets").json() == []


class TestSpaFallback:
    def test_serves_index_html_when_dist_exists(self, monkeypatch, tmp_path):
        """web/dist/index.html이 있으면 SPA index를 서빙하고 deep-link도 같은 페이지를 반환한다."""
        from fastapi.testclient import TestClient

        import src.dashboard.app as app_module

        dist = tmp_path / "dist"
        dist.mkdir()
        (dist / "index.html").write_text("<!DOCTYPE html><title>spa</title>")
        (dist / "assets").mkdir()
        (dist / "assets" / "x.js").write_text("// noop")

        monkeypatch.setattr(app_module, "WEB_DIST_DIR", dist)
        monkeypatch.delenv("ARCHON_DASHBOARD_TOKEN", raising=False)
        monkeypatch.setenv(
            "ARCHON_DASHBOARD_DB_PATH", str(tmp_path / "dashboard.db")
        )

        client = TestClient(app_module.DashboardApp().create_app())

        res_root = client.get("/")
        assert res_root.status_code == 200
        assert "<title>spa</title>" in res_root.text

        res_deep = client.get("/agents")
        assert res_deep.status_code == 200
        assert "<title>spa</title>" in res_deep.text

        res_asset = client.get("/assets/x.js")
        assert res_asset.status_code == 200
        assert res_asset.text.startswith("// noop")

    def test_returns_503_when_dist_missing(self, fastapi_client, monkeypatch, tmp_path):
        # web/dist와 legacy static/index.html이 모두 없는 경우 503.
        # 실제 환경에서는 둘 중 하나가 존재하므로, 격리된 임시 앱으로 검증한다.
        from fastapi.testclient import TestClient

        import src.dashboard.app as app_module

        monkeypatch.setattr(app_module, "WEB_DIST_DIR", tmp_path / "missing-dist")
        monkeypatch.setattr(app_module, "LEGACY_STATIC_DIR", tmp_path / "missing-static")
        monkeypatch.delenv("ARCHON_DASHBOARD_TOKEN", raising=False)
        monkeypatch.setenv(
            "ARCHON_DASHBOARD_DB_PATH", str(tmp_path / "dashboard.db")
        )

        app = app_module.DashboardApp().create_app()
        client = TestClient(app)
        res = client.get("/")
        assert res.status_code == 503
        assert "npm install" in res.text
