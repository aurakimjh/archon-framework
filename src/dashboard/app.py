"""Dashboard 앱 팩토리 — FastAPI 앱 생성 및 라우트 마운트."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from src.dashboard.agent_config import AgentConfigStore, AgentRoleConfig
from src.dashboard.auth import extract_bearer_token, extract_ws_token, get_dashboard_token, verify_token
from src.dashboard.model_registry import is_known_model, load_models
from src.dashboard.models import TaskRequest
from src.dashboard.persistence import (
    BudgetPeriod,
    BudgetThreshold,
    DashboardStore,
)
from src.dashboard.routes import DashboardRoutes
from src.dashboard.websocket import WebSocketManager
from src.log import get_logger
from src.registry.models import AgentRole


class GateDecisionBody(BaseModel):
    """Approve/Reject 요청 body. comment는 reject에서 필수."""

    comment: str | None = None
    reviewer: str | None = None


class BudgetUpsertBody(BaseModel):
    """예산 임계치 upsert body — id/timestamps 제외."""

    scope: str = "global"
    period: BudgetPeriod = BudgetPeriod.DAILY
    limit_usd: float
    notify_email: str | None = None
    notify_webhook: str | None = None

logger = logging.getLogger(__name__)
_slog = get_logger(__name__)

try:
    from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
    from fastapi.staticfiles import StaticFiles
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.websockets import WebSocketState

    _HAS_FASTAPI = True
except ImportError:
    _HAS_FASTAPI = False

# Vite 빌드 산출물(우선) → 레거시 정적 파일(폴백) 순으로 탐색.
WEB_DIST_DIR = Path(__file__).parent / "web" / "dist"
LEGACY_STATIC_DIR = Path(__file__).parent / "static"
STATIC_DIR = LEGACY_STATIC_DIR  # 하위 호환 — 외부에서 참조하던 상수 유지

# 기본 CSP — 동일 출처에서만 스크립트/스타일을 실행, ws:/wss: 만 허용.
_DEFAULT_CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "font-src 'self' data:; "
    "connect-src 'self' ws: wss:; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'"
)


def _is_dev() -> bool:
    """ARCHON_ENV가 dev/development/local 이면 True. 기본값은 production."""
    return os.environ.get("ARCHON_ENV", "production").lower() in {
        "dev",
        "development",
        "local",
    }


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
        store: DashboardStore | None = None,
    ) -> None:
        self._ws_manager = WebSocketManager()

        async def _on_event(event_type: str, payload: dict[str, Any]) -> None:
            await self._ws_manager.broadcast_dict(event_type, payload)

        self._routes = DashboardRoutes(
            registry_store=registry_store,
            health_registry=health_registry,
            token_budgets=token_budgets,
            metrics_collector=metrics_collector,
            store=store,
            on_event=_on_event,
        )
        self._store = store

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

        # store가 주입되지 않았으면 환경 경로 기반으로 생성한다.
        if self._store is None:
            self._store = DashboardStore()
            self._routes._store = self._store

        app = FastAPI(title="Archon Dashboard", version="0.1.0")

        # --- 보안 헤더 미들웨어 (CORS보다 먼저 등록 → 더 늦게 실행) ---
        csp = os.environ.get("ARCHON_CSP", _DEFAULT_CSP)

        class SecurityHeadersMiddleware(BaseHTTPMiddleware):
            async def dispatch(self, request: Request, call_next):
                response = await call_next(request)
                response.headers.setdefault("X-Content-Type-Options", "nosniff")
                response.headers.setdefault("X-Frame-Options", "DENY")
                response.headers.setdefault(
                    "Referrer-Policy", "strict-origin-when-cross-origin"
                )
                response.headers.setdefault("Content-Security-Policy", csp)
                if request.url.scheme == "https":
                    response.headers.setdefault(
                        "Strict-Transport-Security",
                        "max-age=31536000; includeSubDomains",
                    )
                return response

        app.add_middleware(SecurityHeadersMiddleware)

        # --- CORS 미들웨어 ---
        # 기본값은 빈 목록(동일 출처만 허용). 명시 origin이 필요하면 ARCHON_CORS_ORIGINS 사용.
        cors_origins_env = os.environ.get("ARCHON_CORS_ORIGINS", "")
        cors_origins = [
            o.strip() for o in cors_origins_env.split(",") if o.strip()
        ]
        if cors_origins:
            app.add_middleware(
                CORSMiddleware,
                allow_origins=cors_origins,
                allow_credentials=True,
                allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
                allow_headers=["Authorization", "Content-Type"],
            )

        routes = self._routes
        ws_manager = self._ws_manager

        # --- 인증 의존성 ---

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

        @app.post("/api/tasks", dependencies=[Depends(require_auth)])
        async def run_task(request: TaskRequest):
            # mock 모드와 비-default 시나리오는 dev 환경에서만 허용한다.
            if not _is_dev() and (request.mock or request.scenario != "auto_pass"):
                raise HTTPException(
                    status_code=403,
                    detail="mock/scenario fields are only allowed when ARCHON_ENV=dev",
                )

            import asyncio
            def on_step(step_name: str, data: Any):
                # DemoPipeline은 sync 콜백을 기대하므로 create_task로 브로드캐스트
                asyncio.create_task(ws_manager.broadcast_dict("pipeline_step", {
                    "step": step_name,
                    "data": data,
                    "project_id": request.project_id
                }))

            result = await routes.run_task(request, on_step=on_step)
            return result

        @app.get("/api/tasks", dependencies=[Depends(require_auth)])
        async def list_tasks(
            status: str | None = Query(None),
            project_id: str | None = Query(None),
            active_only: bool = Query(False),
            limit: int = Query(100, ge=1, le=500),
        ):
            data = await routes.list_tasks(
                status=status,
                project_id=project_id,
                active_only=active_only,
                limit=limit,
            )
            return [t.model_dump(mode="json") for t in data]

        @app.get("/api/tasks/{task_id}", dependencies=[Depends(require_auth)])
        async def get_task(task_id: str):
            record = await routes.get_task(task_id)
            if record is None:
                raise HTTPException(status_code=404, detail="task not found")
            return record.model_dump(mode="json")

        @app.post(
            "/api/tasks/{task_id}/cancel", dependencies=[Depends(require_auth)]
        )
        async def cancel_task(task_id: str):
            result = await routes.cancel_task(task_id)
            if result.get("status") == "not_found":
                raise HTTPException(status_code=404, detail="task not found")
            return result

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

        # --- Agent Config (Slice 2) ---
        agent_config_store = AgentConfigStore()

        @app.get("/api/agent-config", dependencies=[Depends(require_auth)])
        async def get_agent_config():
            cfg = agent_config_store.load()
            return cfg.model_dump(mode="json")

        @app.put("/api/agent-config/{role}", dependencies=[Depends(require_auth)])
        async def update_agent_config(role: str, body: AgentRoleConfig):
            try:
                role_enum = AgentRole(role)
            except ValueError as exc:
                raise HTTPException(
                    status_code=422, detail=f"unknown role: {role}"
                ) from exc

            if body.role != role_enum:
                raise HTTPException(
                    status_code=422,
                    detail=f"role mismatch: path={role_enum} body={body.role}",
                )

            models = load_models()
            if models and not is_known_model(body.model, models):
                raise HTTPException(
                    status_code=400,
                    detail=f"model '{body.model}' is not in litellm registry",
                )
            for fb in body.fallback_models:
                if models and not is_known_model(fb, models):
                    raise HTTPException(
                        status_code=400,
                        detail=f"fallback model '{fb}' is not in litellm registry",
                    )

            updated = agent_config_store.update_role(role_enum, body)
            payload = updated.get(role_enum).model_dump(mode="json")
            await ws_manager.broadcast_dict("agent_config_updated", payload)
            return payload

        @app.get("/api/models", dependencies=[Depends(require_auth)])
        async def list_models():
            return [m.model_dump() for m in load_models()]

        # --- Usage / Cost timeseries (Slice 4) ---
        @app.get("/api/usage/summary", dependencies=[Depends(require_auth)])
        async def usage_summary():
            data = await routes.get_usage_summary()
            return data.model_dump(mode="json")

        @app.get(
            "/api/usage/timeseries", dependencies=[Depends(require_auth)]
        )
        async def usage_timeseries(
            period: str = Query("daily", pattern="^(daily|hourly)$"),
            start: str | None = Query(None),
            end: str | None = Query(None),
            group_by: str = Query("none", pattern="^(none|project|role|model)$"),
            project_id: str | None = Query(None),
        ):
            data = await routes.query_timeseries(
                period=period,
                start=start,
                end=end,
                group_by=group_by,
                project_id=project_id,
            )
            return [p.model_dump(mode="json") for p in data]

        @app.post(
            "/api/usage/seed", dependencies=[Depends(require_auth)]
        )
        async def usage_seed(
            days: int = Query(14, ge=1, le=90),
            events_per_day: int = Query(24, ge=1, le=200),
        ):
            if not _is_dev():
                raise HTTPException(
                    status_code=403,
                    detail="seeder is only available when ARCHON_ENV=dev",
                )
            count = await routes.seed_usage(
                days=days, events_per_day=events_per_day
            )
            return {"status": "ok", "events": count}

        @app.get("/api/budgets", dependencies=[Depends(require_auth)])
        async def list_budgets():
            return [t.model_dump(mode="json") for t in await routes.list_budgets()]

        @app.get(
            "/api/budgets/status", dependencies=[Depends(require_auth)]
        )
        async def budgets_status():
            return [s.model_dump(mode="json") for s in await routes.budget_status()]

        @app.put("/api/budgets", dependencies=[Depends(require_auth)])
        async def upsert_budget(body: BudgetUpsertBody):
            if body.limit_usd < 0:
                raise HTTPException(
                    status_code=400, detail="limit_usd must be >= 0"
                )
            t = BudgetThreshold(
                scope=body.scope,
                period=body.period,
                limit_usd=body.limit_usd,
                notify_email=body.notify_email,
                notify_webhook=body.notify_webhook,
            )
            saved = await routes.upsert_budget(t)
            await ws_manager.broadcast_dict(
                "budget_updated", saved.model_dump(mode="json")
            )
            return saved.model_dump(mode="json")

        @app.delete(
            "/api/budgets/{threshold_id}", dependencies=[Depends(require_auth)]
        )
        async def delete_budget(threshold_id: int):
            ok = await routes.delete_budget(threshold_id)
            if not ok:
                raise HTTPException(status_code=404, detail="budget not found")
            return {"status": "deleted", "id": threshold_id}

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

        @app.get(
            "/api/gates/{handoff_id}", dependencies=[Depends(require_auth)]
        )
        async def get_gate(handoff_id: str):
            record = await routes.get_gate(handoff_id)
            if record is None:
                raise HTTPException(status_code=404, detail="gate not found")
            return record.model_dump(mode="json")

        @app.post("/api/gates/{handoff_id}/approve", dependencies=[Depends(require_auth)])
        async def approve_gate(
            handoff_id: str, body: GateDecisionBody | None = None
        ):
            comment = body.comment if body else None
            reviewer = body.reviewer if body else None
            try:
                result = await routes.approve_gate(
                    handoff_id, comment=comment, reviewer=reviewer
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            if result.get("status") == "not_found":
                raise HTTPException(status_code=404, detail="gate not found")
            await ws_manager.broadcast_dict("gate_approved", result)
            return result

        @app.post("/api/gates/{handoff_id}/reject", dependencies=[Depends(require_auth)])
        async def reject_gate(handoff_id: str, body: GateDecisionBody):
            if not body.comment or not body.comment.strip():
                raise HTTPException(
                    status_code=400, detail="reject requires a non-empty comment"
                )
            try:
                result = await routes.reject_gate(
                    handoff_id, comment=body.comment, reviewer=body.reviewer
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            if result.get("status") == "not_found":
                raise HTTPException(status_code=404, detail="gate not found")
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

        # --- 헬스 / 환경 메타 ---
        @app.get("/api/health")
        async def health():
            return {
                "status": "ok",
                "version": "0.1.0",
                "env": "development" if _is_dev() else "production",
                "auth_required": get_dashboard_token() is not None,
            }

        # --- Static files ---
        # Vite 빌드 산출물(web/dist)이 있으면 SPA 라우팅을 지원한다.
        # 없으면 레거시 static/ 디렉토리, 둘 다 없으면 안내 페이지.
        index_html = WEB_DIST_DIR / "index.html"
        if index_html.exists():
            assets_dir = WEB_DIST_DIR / "assets"
            if assets_dir.exists():
                app.mount(
                    "/assets",
                    StaticFiles(directory=str(assets_dir)),
                    name="assets",
                )

            @app.get("/{full_path:path}", include_in_schema=False)
            async def spa_fallback(full_path: str):
                # API/WS 경로는 위 라우트가 우선 매칭되므로 도달하지 않는다.
                # 정적 파일이 web/dist에 있으면 직접 반환, 그 외는 index.html.
                candidate = WEB_DIST_DIR / full_path
                if (
                    full_path
                    and candidate.is_file()
                    and candidate.resolve().is_relative_to(WEB_DIST_DIR.resolve())
                ):
                    return FileResponse(candidate)
                return FileResponse(index_html)
        elif LEGACY_STATIC_DIR.exists() and (LEGACY_STATIC_DIR / "index.html").exists():
            app.mount(
                "/",
                StaticFiles(directory=str(LEGACY_STATIC_DIR), html=True),
                name="static",
            )
        else:
            @app.get("/", include_in_schema=False)
            async def missing_dist():
                return PlainTextResponse(
                    "Dashboard frontend not built. Run:\n"
                    "  cd src/dashboard/web && npm install && npm run build\n",
                    status_code=503,
                )

        return app
