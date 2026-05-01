"""Dashboard 앱 팩토리 — FastAPI 앱 생성 및 라우트 마운트."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from src.dashboard.auth import extract_bearer_token, extract_ws_token, get_dashboard_token, verify_token
from src.dashboard.routes import DashboardRoutes
from src.dashboard.websocket import WebSocketManager
from src.log import get_logger

logger = logging.getLogger(__name__)
_slog = get_logger(__name__)

try:
    from fastapi import Depends, FastAPI, Header, Query, WebSocket, WebSocketDisconnect
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse
    from fastapi.staticfiles import StaticFiles
    from starlette.websockets import WebSocketState

    _HAS_FASTAPI = True
except ImportError:
    _HAS_FASTAPI = False

STATIC_DIR = Path(__file__).parent / "static"


class DashboardApp:
    """Archon Dashboard 앱.

    FastAPI 기반 REST API + WebSocket + 정적 파일 서빙.
    FastAPI가 설치되지 않으면 DashboardRoutes만 독립 사용 가능.
    """

    def __init__(
        self,
        registry_store: Any = None,
        health_registry: Any = None,
        token_budgets: dict[str, Any] | None = None,
        metrics_collector: Any = None,
    ) -> None:
        self._routes = DashboardRoutes(
            registry_store=registry_store,
            health_registry=health_registry,
            token_budgets=token_budgets,
            metrics_collector=metrics_collector,
        )
        self._ws_manager = WebSocketManager()

    @property
    def routes(self) -> DashboardRoutes:
        return self._routes

    @property
    def ws_manager(self) -> WebSocketManager:
        return self._ws_manager

    def create_app(self) -> Any:
        """FastAPI 앱 인스턴스를 생성한다.

        Raises:
            RuntimeError: FastAPI가 설치되지 않은 경우.
        """
        if not _HAS_FASTAPI:
            raise RuntimeError(
                "fastapi 패키지가 필요합니다: pip install archon-framework[dashboard]"
            )

        app = FastAPI(title="Archon Dashboard", version="0.1.0")

        cors_origins_env = os.environ.get("ARCHON_CORS_ORIGINS", "*")
        cors_origins = [
            o.strip() for o in cors_origins_env.split(",") if o.strip()
        ] or ["*"]

        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        routes = self._routes
        ws_manager = self._ws_manager

        # --- 인증 의존성 ---
        from fastapi import HTTPException

        async def require_auth(authorization: str | None = Header(None)) -> None:
            """REST API Bearer 토큰 인증. 토큰 미설정 시 통과."""
            token = get_dashboard_token()
            if token is None:
                return
            provided = extract_bearer_token(authorization)
            if not verify_token(provided, token):
                raise HTTPException(
                    status_code=401,
                    detail="Invalid or missing authentication token",
                    headers={"WWW-Authenticate": "Bearer"},
                )

        # --- REST endpoints ---
        @app.get("/api/projects", dependencies=[Depends(require_auth)])
        async def list_projects():
            data = await routes.list_projects()
            return [p.model_dump() for p in data]

        @app.get("/api/projects/{project_id}", dependencies=[Depends(require_auth)])
        async def get_project(project_id: str):
            data = await routes.get_project(project_id)
            if data is None:
                return JSONResponse({"error": "not found"}, status_code=404)
            return data.model_dump()

        @app.get("/api/agents", dependencies=[Depends(require_auth)])
        async def list_agents():
            data = await routes.list_agents()
            return [a.model_dump() for a in data]

        @app.get("/api/agents/{role}", dependencies=[Depends(require_auth)])
        async def get_agent(role: str):
            data = await routes.get_agent(role)
            if data is None:
                return JSONResponse({"error": "not found"}, status_code=404)
            return data.model_dump()

        @app.get("/api/cost", dependencies=[Depends(require_auth)])
        async def list_costs():
            data = await routes.list_costs()
            return [c.model_dump() for c in data]

        @app.get("/api/cost/{project_id}", dependencies=[Depends(require_auth)])
        async def get_cost(project_id: str):
            data = await routes.get_cost(project_id)
            if data is None:
                return JSONResponse({"error": "not found"}, status_code=404)
            return data.model_dump()

        @app.get("/api/gates/queue", dependencies=[Depends(require_auth)])
        async def gate_queue():
            data = await routes.list_gate_queue()
            return [g.model_dump() for g in data]

        @app.post("/api/gates/{handoff_id}/approve", dependencies=[Depends(require_auth)])
        async def approve_gate(handoff_id: str):
            result = await routes.approve_gate(handoff_id)
            await ws_manager.broadcast_dict("gate_approved", result)
            return result

        @app.post("/api/gates/{handoff_id}/reject", dependencies=[Depends(require_auth)])
        async def reject_gate(handoff_id: str):
            result = await routes.reject_gate(handoff_id)
            await ws_manager.broadcast_dict("gate_rejected", result)
            return result

        @app.get("/api/metrics", dependencies=[Depends(require_auth)])
        async def get_metrics():
            return await routes.get_metrics()

        # --- WebSocket (토큰 인증) ---
        @app.websocket("/ws")
        async def websocket_endpoint(websocket: WebSocket, token: str | None = Query(None)):
            expected = get_dashboard_token()
            if not verify_token(token, expected):
                await websocket.close(code=4401, reason="Unauthorized")
                return

            await ws_manager.connect(websocket)
            try:
                while True:
                    await websocket.receive_text()
            except (WebSocketDisconnect, Exception):
                await ws_manager.disconnect(websocket)

        # --- Static files ---
        if STATIC_DIR.exists():
            app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")

        return app
