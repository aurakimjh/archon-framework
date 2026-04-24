"""Observability 설정 — 트레이싱 백엔드 선택 및 구성."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class TracingBackend(StrEnum):
    """트레이싱 백엔드 종류."""

    NONE = "none"
    LANGSMITH = "langsmith"
    LANGFUSE = "langfuse"
    BOTH = "both"


class TracingConfig(BaseModel):
    """트레이싱 설정 모델."""

    backend: TracingBackend = TracingBackend.NONE

    # LangSmith
    langsmith_api_key: str | None = None
    langsmith_project: str = "archon"
    langsmith_endpoint: str | None = None

    # Langfuse
    langfuse_host: str | None = None
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None

    # 공통
    trace_all_llm_calls: bool = True
    trace_pipeline: bool = True
    sample_rate: float = Field(default=1.0, ge=0.0, le=1.0)

    @property
    def is_enabled(self) -> bool:
        """트레이싱이 활성화되어 있는지 확인."""
        return self.backend != TracingBackend.NONE

    @property
    def use_langsmith(self) -> bool:
        return self.backend in (TracingBackend.LANGSMITH, TracingBackend.BOTH)

    @property
    def use_langfuse(self) -> bool:
        return self.backend in (TracingBackend.LANGFUSE, TracingBackend.BOTH)
