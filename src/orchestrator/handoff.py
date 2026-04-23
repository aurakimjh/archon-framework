"""Handoff Artifact 스키마 — 에이전트 간 컨텍스트 전달 표준 JSON 문서."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from src.gate.models import GateDecision

# --- Envelope ---

class Envelope(BaseModel):
    """핸드오프 식별·라우팅·재시도 추적."""

    handoff_id: str
    schema_version: str = "1.0.0"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    expires_at: datetime | None = None
    from_agent: str
    to_agent: str
    retry_count: int = 0
    parent_handoff_id: str | None = None


# --- Project Context ---

class TechStack(BaseModel):
    language: str
    framework: str
    database: str | None = None
    runtime: str | None = None


class ProjectContext(BaseModel):
    """무상태 에이전트에 주입하는 프로젝트 네임스페이스."""

    project_id: str
    project_name: str
    git_repo: str
    git_branch: str
    base_commit_sha: str
    sop_path: str | None = None
    tech_stack: TechStack | None = None
    priority: str = "medium"


# --- Task ---

class Decision(BaseModel):
    decision: str
    reason: str
    alternatives_considered: list[str] = Field(default_factory=list)


class Blocker(BaseModel):
    issue: str
    impact: str = "medium"
    suggested_resolution: str = ""


class Task(BaseModel):
    """완료 작업 요약 + 다음 에이전트 지시."""

    task_id: str
    completed_summary: str
    decisions_made: list[Decision] = Field(default_factory=list)
    blockers: list[Blocker] = Field(default_factory=list)
    next_instructions: str = ""
    next_agent_context: dict[str, Any] = Field(default_factory=dict)


# --- Artifacts ---

class ChangedFile(BaseModel):
    path: str
    change_type: str  # added, modified, deleted
    reason: str = ""


class DependencyChange(BaseModel):
    name: str
    version: str
    action: str  # added, updated, removed
    license: str | None = None
    security_scan: str | None = None


class Artifacts(BaseModel):
    """변경 파일 목록 + 생성 산출물."""

    changed_files: list[ChangedFile] = Field(default_factory=list)
    generated_docs: list[str] = Field(default_factory=list)
    dependency_changes: list[DependencyChange] = Field(default_factory=list)
    config_changes: list[str] = Field(default_factory=list)


# --- Quality Gates ---

class TestResults(BaseModel):
    unit_passed: int = 0
    unit_failed: int = 0
    integration_passed: int = 0
    coverage_percent: float = 0.0


class SecurityScan(BaseModel):
    tool: str = "semgrep"
    critical: int = 0
    high: int = 0
    medium: int = 0
    low: int = 0


class ReviewFlag(BaseModel):
    severity: str
    category: str
    detail: str


class QualityGates(BaseModel):
    """자동 QA 결과 + Review Agent 평가 + gate_decision."""

    test_results: TestResults = Field(default_factory=TestResults)
    lint_result: str = "passed"
    build_result: str = "passed"
    security_scan: SecurityScan = Field(default_factory=SecurityScan)
    review_score: int = 0
    review_flags: list[ReviewFlag] = Field(default_factory=list)
    gate_decision: GateDecision = GateDecision.L2_HUMAN
    sop_compliance_score: int | None = None  # SOP 준수 점수 (0~100, None이면 미검사)


# --- Human Gate Package ---

class DecisionOption(BaseModel):
    option: str
    next_action: str
    risk: str = "low"


class HumanGatePackage(BaseModel):
    """L2 이상 발동 시 개발자에게 전달하는 컨텍스트."""

    gate_level: GateDecision
    trigger_reason: str
    required_decision: str
    decision_options: list[DecisionOption] = Field(default_factory=list)
    estimated_review_time: str = "5분"
    paused_agents: list[str] = Field(default_factory=list)


# --- Memory Context ---

class PastDecision(BaseModel):
    similarity: float
    project: str
    decision: str
    outcome: str


class KnownPattern(BaseModel):
    pattern: str
    reason: str
    example_file: str | None = None


class ErrorRecord(BaseModel):
    retry_num: int
    error: str
    resolution: str


class HumanFeedback(BaseModel):
    date: str
    decision: str
    applies_to: str


class MemoryContext(BaseModel):
    """Mem0에서 검색된 과거 패턴·결정."""

    relevant_past_decisions: list[PastDecision] = Field(default_factory=list)
    known_patterns: list[KnownPattern] = Field(default_factory=list)
    error_history: list[ErrorRecord] = Field(default_factory=list)
    human_feedback: list[HumanFeedback] = Field(default_factory=list)


# --- Root Model ---

class HandoffArtifact(BaseModel):
    """에이전트 간 컨텍스트를 전달하는 표준 JSON 문서 (7섹션)."""

    envelope: Envelope
    project_context: ProjectContext
    task: Task
    artifacts: Artifacts = Field(default_factory=Artifacts)
    quality_gates: QualityGates = Field(default_factory=QualityGates)
    human_gate_package: HumanGatePackage | None = None
    memory_context: MemoryContext | None = None
