"""Self-Evolving Loop 데이터 모델 — 실행 기록, 메트릭, 튜닝 액션."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class PipelineExecution(BaseModel):
    """단일 파이프라인 실행 기록."""

    execution_id: str
    project_id: str
    task_id: str
    agent_role: str
    model: str
    gate_decision: str
    review_score: int = 0
    retry_count: int = 0
    latency_ms: float = 0.0
    token_count: int = 0
    cost_usd: float = 0.0
    rework_reason: str = ""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AgentMetrics(BaseModel):
    """에이전트별 집계 메트릭."""

    role: str
    executions: int = 0
    success_rate: float = 0.0
    avg_review_score: float = 0.0
    avg_latency_ms: float = 0.0
    common_rework_reasons: list[str] = Field(default_factory=list)


class PipelineMetrics(BaseModel):
    """시간 윈도우 내 파이프라인 집계 메트릭."""

    total_executions: int = 0
    success_rate: float = 0.0
    rework_rate: float = 0.0
    human_gate_rate: float = 0.0
    halt_rate: float = 0.0
    avg_review_score: float = 0.0
    avg_retry_count: float = 0.0
    avg_latency_ms: float = 0.0
    total_cost_usd: float = 0.0
    by_agent: dict[str, AgentMetrics] = Field(default_factory=dict)


class TuningActionType(StrEnum):
    """튜닝 액션 종류."""

    ADJUST_THRESHOLD = "adjust_threshold"
    SUGGEST_PROMPT = "suggest_prompt"
    SWITCH_MODEL = "switch_model"
    ALERT = "alert"


class TuningAction(BaseModel):
    """자동 튜닝 액션."""

    action_type: TuningActionType
    target: str
    current_value: Any = None
    suggested_value: Any = None
    reason: str = ""
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    applied: bool = False


class EvolutionConfig(BaseModel):
    """Self-Evolving Loop 설정."""

    enabled: bool = False
    analysis_window_hours: int = 24
    min_executions_for_analysis: int = 10
    auto_apply_threshold: float = Field(default=0.8, ge=0.0, le=1.0)
    max_threshold_delta: int = 10
    max_history: int = 1000
