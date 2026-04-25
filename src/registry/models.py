"""Project Registry 스키마 — Pydantic v2 모델."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from src.evolution.models import EvolutionConfig
from src.observability.config import TracingConfig
from src.runtime.hybrid import HybridConfig
from src.runtime.kuberay import KubeRayConfig

# --- Enums ---

class ProjectStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class AgentStatus(StrEnum):
    RUNNING = "running"
    WAITING = "waiting"
    PAUSED = "paused"
    ERROR = "error"


class AgentRole(StrEnum):
    ORCHESTRATOR = "orchestrator"
    REVIEWER = "reviewer"
    FRONTEND = "frontend"
    BACKEND = "backend"
    TESTER = "tester"
    DEVOPS = "devops"
    DOCS = "docs"


# --- Sub-models ---

class ProjectMeta(BaseModel):
    project_id: str
    project_name: str
    status: ProjectStatus = ProjectStatus.ACTIVE
    priority: int = Field(default=5, ge=1, le=10)
    deadline: datetime | None = None
    owner: str = "dev_001"
    description: str = ""
    tags: list[str] = Field(default_factory=list)


class GitConfig(BaseModel):
    repo_url: str
    main_branch: str = "develop"
    agent_branch_prefix: str = "agent/"
    auto_commit_message_template: str = "feat({agent}): {summary} [task:{task_id}]"
    sop_directory: str = ".harness/sop/"
    protected_paths: list[str] = Field(
        default_factory=lambda: [".env", "infrastructure/", "secrets/"]
    )


class AgentModelConfig(BaseModel):
    model: str
    max_tokens: int = 4096
    temperature: float = 0.2
    model_override: str | None = None
    reviewer_guidelines_path: str | None = None
    # 프롬프트 오버레이 (Private 프롬프트 파일 경로)
    prompt_overlay_path: str | None = None
    # Async Streaming
    streaming: bool = False
    timeout_seconds: int = 300
    # Complexity Router
    high_complexity_model: str | None = None


class QualityPolicy(BaseModel):
    coverage_threshold: int = 80
    review_score_threshold: int = 70
    max_retry_before_escalation: int = 3
    security_block_level: str = "critical"
    require_human_on_schema_change: bool = True
    require_human_on_external_integration: bool = True
    daily_token_budget: int = 500
    sop_compliance_threshold: int = 70  # SOP 점수 이 미만이면 L2
    # Dynamic Guardrails — 위험 키워드/경로 감지 시 L2 강제 상향
    high_risk_paths: list[str] = Field(
        default_factory=lambda: [
            "payment", "billing", "auth", "security",
            "migration", "infrastructure/", "secrets/",
        ]
    )
    high_risk_keywords: list[str] = Field(
        default_factory=lambda: [
            "payment", "billing", "charge", "refund",
            "credential", "secret", "token", "api_key",
            "delete_all", "drop_table", "truncate",
            "production", "deploy",
        ]
    )


class TaskRef(BaseModel):
    task_id: str
    agent: str | None = None
    started_at: datetime | None = None
    estimated_completion: datetime | None = None
    depends_on: str | None = None
    priority: int = 1


class BlockedTask(BaseModel):
    task_id: str
    blocked_by: str
    unblock_condition: str


class ActiveAgent(BaseModel):
    status: AgentStatus
    current_task_id: str | None = None


class WorkQueue(BaseModel):
    current_task: TaskRef | None = None
    pending_tasks: list[TaskRef] = Field(default_factory=list)
    blocked_tasks: list[BlockedTask] = Field(default_factory=list)
    completed_tasks: list[TaskRef] = Field(default_factory=list)
    active_agents: dict[str, ActiveAgent] = Field(default_factory=dict)
    overall_progress: int = Field(default=0, ge=0, le=100)


class MemoryConfig(BaseModel):
    vector_collection_id: str
    scratchpad_key: str
    retain_handoff_count: int = 100
    auto_learn_patterns: bool = True
    cross_project_memory_enabled: bool = False
    # L1 Redis
    redis_url: str = "redis://localhost:6379/0"
    redis_ttl: int = 86400  # 24시간
    # L2 ChromaDB
    chroma_path: str | None = None  # None이면 인메모리
    chroma_collection_prefix: str = "archon"
    # L3 Mem0
    mem0_api_key: str | None = None
    mem0_user_id: str = "archon"


class ProjectMetrics(BaseModel):
    total_tokens_used: int = 0
    estimated_cost_usd: float = 0.0
    auto_commit_count: int = 0
    human_gate_count: int = 0
    l3_halt_count: int = 0
    average_review_score: float = 0.0
    agent_utilization: dict[str, float] = Field(default_factory=dict)


class HumanGateEntry(BaseModel):
    handoff_id: str
    gate_level: str
    trigger: str
    decision: str
    rationale: str
    response_time_minutes: float | None = None
    converted_to_policy: bool = False


class HumanGateHistory(BaseModel):
    entries: list[HumanGateEntry] = Field(default_factory=list)


# --- Root Model ---

class ProjectRegistry(BaseModel):
    """프로젝트별 전체 설정을 담는 중앙 레지스트리."""

    project_meta: ProjectMeta
    git_config: GitConfig
    agent_config: dict[str, AgentModelConfig] = Field(default_factory=dict)
    quality_policy: QualityPolicy = Field(default_factory=QualityPolicy)
    work_queue: WorkQueue = Field(default_factory=WorkQueue)
    memory_config: MemoryConfig | None = None
    metrics: ProjectMetrics = Field(default_factory=ProjectMetrics)
    human_gate_history: HumanGateHistory = Field(default_factory=HumanGateHistory)

    # --- Phase 3 Config (선택적 중앙 참조) ---
    tracing_config: TracingConfig | None = None
    evolution_config: EvolutionConfig | None = None
    hybrid_config: HybridConfig | None = None
    kuberay_config: KubeRayConfig | None = None

    def get_model_for_role(self, role: str) -> str:
        """역할에 해당하는 LLM 모델명 반환. model_override 우선."""
        config = self.agent_config.get(role)
        if config:
            return config.model_override or config.model
        return f"{role}-agent"
