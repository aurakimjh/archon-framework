"""Observability 설정 — 트레이싱 백엔드 선택 및 구성."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class TracingBackend(StrEnum):
    """트레이싱 백엔드 종류."""

    NONE = "none"
    LANGSMITH = "langsmith"
    LANGFUSE = "langfuse"
    AITOP = "aitop"
    BOTH = "both"
    ALL = "all"


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

    # AITOP (aiservice-monitoring)
    aitop_server_url: str = "http://localhost:8080"
    aitop_project_token: str | None = None
    aitop_service_name: str = "archon-framework"
    aitop_batch_size: int = Field(default=20, ge=1, le=200)

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
        return self.backend in (
            TracingBackend.LANGSMITH, TracingBackend.BOTH, TracingBackend.ALL,
        )

    @property
    def use_langfuse(self) -> bool:
        return self.backend in (
            TracingBackend.LANGFUSE, TracingBackend.BOTH, TracingBackend.ALL,
        )

    @property
    def use_aitop(self) -> bool:
        return self.backend in (TracingBackend.AITOP, TracingBackend.ALL)
