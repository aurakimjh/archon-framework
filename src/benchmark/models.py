"""벤치마크 데이터 모델 — 태스크, 결과, 모델 점수, 랭킹."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class BenchmarkMetric(StrEnum):
    """벤치마크 평가 기준."""

    ACCURACY = "accuracy"
    LATENCY = "latency"
    COST = "cost"
    OVERALL = "overall"


class BenchmarkTask(BaseModel):
    """벤치마크 태스크 정의."""

    task_id: str
    role: str
    description: str
    prompt: str
    expected_keywords: list[str] = Field(default_factory=list)
    expected_patterns: list[str] = Field(default_factory=list)
    max_latency_ms: float = 30000.0
    max_cost_usd: float = 1.0
    max_tokens: int = 2048


class BenchmarkResult(BaseModel):
    """단일 벤치마크 실행 결과."""

    task_id: str
    model: str
    role: str
    accuracy_score: float = Field(default=0.0, ge=0.0, le=1.0)
    latency_ms: float = 0.0
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    output_text: str = ""
    error: str | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def is_success(self) -> bool:
        return self.error is None

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class ModelScore(BaseModel):
    """모델별 종합 점수."""

    model: str
    accuracy: float = Field(default=0.0, ge=0.0, le=1.0)
    avg_latency_ms: float = 0.0
    avg_cost_usd: float = 0.0
    overall_score: float = Field(default=0.0, ge=0.0, le=1.0)
    task_count: int = 0
    error_count: int = 0


class ModelRanking(BaseModel):
    """역할별 모델 랭킹."""

    role: str
    rankings: list[ModelScore] = Field(default_factory=list)
    recommended_model: str = ""
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def top_model(self) -> str | None:
        if self.rankings:
            return self.rankings[0].model
        return None
