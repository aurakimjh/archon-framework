"""Handoff Artifact 스키마 직렬화/역직렬화 테스트."""

import json

from src.gate.models import GateDecision
from src.orchestrator.handoff import (
    Artifacts,
    ChangedFile,
    Envelope,
    HandoffArtifact,
    ProjectContext,
    QualityGates,
    Task,
    TechStack,
)


def test_handoff_roundtrip():
    """HandoffArtifact JSON 직렬화 → 역직렬화 라운드트립."""
    original = HandoffArtifact(
        envelope=Envelope(
            handoff_id="hf_test001",
            from_agent="backend",
            to_agent="reviewer",
        ),
        project_context=ProjectContext(
            project_id="proj_test",
            project_name="Test Project",
            git_repo="https://github.com/test/repo.git",
            git_branch="agent/backend/test001",
            base_commit_sha="abc123",
            tech_stack=TechStack(
                language="Python",
                framework="FastAPI",
                database="PostgreSQL",
            ),
        ),
        task=Task(
            task_id="task_test_api",
            completed_summary="Implemented test API endpoint",
            next_instructions="Write unit tests",
        ),
        artifacts=Artifacts(
            changed_files=[
                ChangedFile(path="src/api.py", change_type="added", reason="new endpoint")
            ]
        ),
        quality_gates=QualityGates(review_score=85, gate_decision=GateDecision.AUTO_PASS),
    )

    json_str = original.model_dump_json(indent=2)
    restored = HandoffArtifact.model_validate_json(json_str)

    assert restored.envelope.handoff_id == "hf_test001"
    assert restored.project_context.project_id == "proj_test"
    assert restored.task.task_id == "task_test_api"
    assert restored.quality_gates.gate_decision == GateDecision.AUTO_PASS
    assert len(restored.artifacts.changed_files) == 1


def test_handoff_minimal():
    """최소 필수 필드만으로 HandoffArtifact 생성."""
    h = HandoffArtifact(
        envelope=Envelope(
            handoff_id="hf_min",
            from_agent="orchestrator",
            to_agent="backend",
        ),
        project_context=ProjectContext(
            project_id="proj_min",
            project_name="Minimal",
            git_repo="https://github.com/test/min.git",
            git_branch="main",
            base_commit_sha="000000",
        ),
        task=Task(
            task_id="task_min",
            completed_summary="",
        ),
    )
    assert h.human_gate_package is None
    assert h.memory_context is None
    assert h.artifacts.changed_files == []
