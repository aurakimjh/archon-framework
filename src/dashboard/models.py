"""Dashboard API 응답 모델."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


class ProjectSummary(BaseModel):
    """프로젝트 요약."""

    project_id: str
    project_name: str = ""
    status: str = "active"
    priority: int = 0
    pending_tasks: int = 0
    completed_tasks: int = 0
    active_agents: int = 0


class AgentStatusResponse(BaseModel):
    """에이전트 상태."""

    role: str
    health_status: str = "healthy"
    consecutive_failures: int = 0
    avg_latency_ms: float = 0.0
    total_executions: int = 0
    model: str = ""


class CostSummary(BaseModel):
    """비용 요약."""

    project_id: str
    date: str = ""
    daily_tokens_used: int = 0
    daily_token_limit: int = 0
    total_cost_usd: float = 0.0
    agent_breakdown: dict[str, int] = Field(default_factory=dict)
    usage_ratio: float = 0.0


class GateQueueItem(BaseModel):
    """Human Gate 대기열 항목."""

    handoff_id: str
    project_id: str
    gate_level: str
    trigger_reason: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    agent_role: str = ""
    review_score: int | None = None


class DashboardEvent(BaseModel):
    """WebSocket 푸시 이벤트."""

    event_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class TaskRequest(BaseModel):
    """작업 요청."""

    project_id: str
    instructions: str
    scenario: str = "auto_pass"
    mock: bool = True
    agent_role: str = "backend"
