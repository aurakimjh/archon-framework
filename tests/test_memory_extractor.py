"""Semantic Memory Extractor 테스트."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.gate.models import GateDecision
from src.memory.extractor import (
    ExtractionResult,
    ExtractedMemory,
    MemoryCategory,
    MemoryExtractor,
)
from src.orchestrator.handoff import (
    Artifacts,
    ChangedFile,
    Decision,
    DependencyChange,
    Envelope,
    ErrorRecord,
    HandoffArtifact,
    HumanFeedback,
    MemoryContext,
    ProjectContext,
    QualityGates,
    ReviewFlag,
    Task,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_handoff(**overrides) -> HandoffArtifact:
    defaults = dict(
        envelope=Envelope(
            handoff_id="h1",
            from_agent="backend",
            to_agent="reviewer",
        ),
        project_context=ProjectContext(
            project_id="proj-001",
            project_name="Test",
            git_repo="https://github.com/test/repo",
            git_branch="develop",
            base_commit_sha="abc123",
        ),
        task=Task(task_id="t1", completed_summary=""),
    )
    defaults.update(overrides)
    return HandoffArtifact(**defaults)


# ---------------------------------------------------------------------------
# ExtractedMemory / ExtractionResult models
# ---------------------------------------------------------------------------


class TestModels:
    def test_extracted_memory_defaults(self):
        m = ExtractedMemory(
            category=MemoryCategory.DECISION_PATTERN,
            content="test",
        )
        assert m.source_handoff_id == ""
        assert m.metadata == {}

    def test_extraction_result_defaults(self):
        r = ExtractionResult(handoff_id="h1", project_id="p1")
        assert r.extracted_count == 0
        assert r.stored_count == 0
        assert r.memories == []

    def test_memory_category_values(self):
        assert MemoryCategory.DECISION_PATTERN == "decision_pattern"
        assert MemoryCategory.ERROR_RESOLUTION == "error_resolution"
        assert MemoryCategory.QUALITY_INSIGHT == "quality_insight"
        assert MemoryCategory.HUMAN_FEEDBACK == "human_feedback"
        assert MemoryCategory.TECH_PATTERN == "tech_pattern"


# ---------------------------------------------------------------------------
# Decision extraction
# ---------------------------------------------------------------------------


class TestDecisionExtraction:
    def test_no_decisions(self):
        ext = MemoryExtractor()
        h = _make_handoff()
        memories = ext.extract(h)
        assert not any(m.category == MemoryCategory.DECISION_PATTERN for m in memories)

    def test_single_decision(self):
        ext = MemoryExtractor()
        h = _make_handoff(
            task=Task(
                task_id="t1",
                completed_summary="",
                decisions_made=[
                    Decision(
                        decision="Use FastAPI",
                        reason="Performance",
                        alternatives_considered=["Flask", "Django"],
                    )
                ],
            )
        )
        memories = ext.extract(h)
        decisions = [m for m in memories if m.category == MemoryCategory.DECISION_PATTERN]
        assert len(decisions) == 1
        assert "FastAPI" in decisions[0].content
        assert "Flask" in decisions[0].content
        assert decisions[0].reason == "Performance"
        assert decisions[0].source_handoff_id == "h1"
        assert decisions[0].source_agent == "backend"
        assert decisions[0].project_id == "proj-001"

    def test_multiple_decisions(self):
        ext = MemoryExtractor()
        h = _make_handoff(
            task=Task(
                task_id="t1",
                completed_summary="",
                decisions_made=[
                    Decision(decision="d1", reason="r1"),
                    Decision(decision="d2", reason="r2"),
                ],
            )
        )
        decisions = [
            m for m in ext.extract(h)
            if m.category == MemoryCategory.DECISION_PATTERN
        ]
        assert len(decisions) == 2


# ---------------------------------------------------------------------------
# Review flag extraction
# ---------------------------------------------------------------------------


class TestReviewFlagExtraction:
    def test_with_flags(self):
        ext = MemoryExtractor()
        h = _make_handoff(
            quality_gates=QualityGates(
                review_score=85,
                review_flags=[
                    ReviewFlag(severity="high", category="security", detail="SQL injection risk"),
                ],
            )
        )
        insights = [m for m in ext.extract(h) if m.category == MemoryCategory.QUALITY_INSIGHT]
        assert len(insights) == 1
        assert "SQL injection" in insights[0].content
        assert insights[0].metadata["severity"] == "high"

    def test_low_score_still_extracted_by_default(self):
        ext = MemoryExtractor()
        h = _make_handoff(
            quality_gates=QualityGates(
                review_score=30,
                review_flags=[
                    ReviewFlag(severity="low", category="style", detail="naming"),
                ],
            )
        )
        insights = [m for m in ext.extract(h) if m.category == MemoryCategory.QUALITY_INSIGHT]
        assert len(insights) == 1

    def test_low_score_skipped_when_disabled(self):
        ext = MemoryExtractor(extract_from_low_score=False)
        h = _make_handoff(
            quality_gates=QualityGates(
                review_score=30,
                review_flags=[
                    ReviewFlag(severity="low", category="style", detail="naming"),
                ],
            )
        )
        insights = [m for m in ext.extract(h) if m.category == MemoryCategory.QUALITY_INSIGHT]
        assert len(insights) == 0


# ---------------------------------------------------------------------------
# Error resolution extraction
# ---------------------------------------------------------------------------


class TestErrorResolutionExtraction:
    def test_with_errors(self):
        ext = MemoryExtractor()
        h = _make_handoff(
            memory_context=MemoryContext(
                error_history=[
                    ErrorRecord(retry_num=1, error="ImportError", resolution="Add missing import"),
                ],
            )
        )
        errors = [m for m in ext.extract(h) if m.category == MemoryCategory.ERROR_RESOLUTION]
        assert len(errors) == 1
        assert "ImportError" in errors[0].content
        assert "missing import" in errors[0].content

    def test_skip_error_without_resolution(self):
        ext = MemoryExtractor()
        h = _make_handoff(
            memory_context=MemoryContext(
                error_history=[
                    ErrorRecord(retry_num=1, error="Timeout", resolution=""),
                ],
            )
        )
        errors = [m for m in ext.extract(h) if m.category == MemoryCategory.ERROR_RESOLUTION]
        assert len(errors) == 0

    def test_no_memory_context(self):
        ext = MemoryExtractor()
        h = _make_handoff()
        errors = [m for m in ext.extract(h) if m.category == MemoryCategory.ERROR_RESOLUTION]
        assert len(errors) == 0


# ---------------------------------------------------------------------------
# Human feedback extraction
# ---------------------------------------------------------------------------


class TestHumanFeedbackExtraction:
    def test_with_feedback(self):
        ext = MemoryExtractor()
        h = _make_handoff(
            memory_context=MemoryContext(
                human_feedback=[
                    HumanFeedback(
                        date="2026-04-25",
                        decision="Approve with conditions",
                        applies_to="auth module",
                    ),
                ],
            )
        )
        fb = [m for m in ext.extract(h) if m.category == MemoryCategory.HUMAN_FEEDBACK]
        assert len(fb) == 1
        assert "auth module" in fb[0].content
        assert fb[0].metadata["date"] == "2026-04-25"

    def test_no_feedback(self):
        ext = MemoryExtractor()
        h = _make_handoff(memory_context=MemoryContext())
        fb = [m for m in ext.extract(h) if m.category == MemoryCategory.HUMAN_FEEDBACK]
        assert len(fb) == 0


# ---------------------------------------------------------------------------
# Tech pattern extraction
# ---------------------------------------------------------------------------


class TestTechPatternExtraction:
    def test_dependency_changes(self):
        ext = MemoryExtractor()
        h = _make_handoff(
            artifacts=Artifacts(
                dependency_changes=[
                    DependencyChange(
                        name="pydantic",
                        version="2.0.0",
                        action="updated",
                        license="MIT",
                    ),
                ],
            )
        )
        tech = [m for m in ext.extract(h) if m.category == MemoryCategory.TECH_PATTERN]
        assert len(tech) == 1
        assert "pydantic" in tech[0].content
        assert "2.0.0" in tech[0].content
        assert tech[0].metadata["action"] == "updated"

    def test_no_dependencies(self):
        ext = MemoryExtractor()
        h = _make_handoff()
        tech = [m for m in ext.extract(h) if m.category == MemoryCategory.TECH_PATTERN]
        assert len(tech) == 0


# ---------------------------------------------------------------------------
# Success pattern extraction
# ---------------------------------------------------------------------------


class TestSuccessPatternExtraction:
    def test_high_score_extracts_summary(self):
        ext = MemoryExtractor(min_review_score=70)
        h = _make_handoff(
            task=Task(
                task_id="t1",
                completed_summary="Implemented caching layer with Redis",
            ),
            quality_gates=QualityGates(review_score=90),
        )
        success = [
            m for m in ext.extract(h)
            if m.category == MemoryCategory.DECISION_PATTERN
            and m.metadata.get("type") == "success_pattern"
        ]
        assert len(success) == 1
        assert "caching" in success[0].content

    def test_low_score_no_success_pattern(self):
        ext = MemoryExtractor(min_review_score=70)
        h = _make_handoff(
            task=Task(
                task_id="t1",
                completed_summary="Some work done",
            ),
            quality_gates=QualityGates(review_score=50),
        )
        success = [
            m for m in ext.extract(h)
            if m.metadata.get("type") == "success_pattern"
        ]
        assert len(success) == 0

    def test_empty_summary_no_extraction(self):
        ext = MemoryExtractor()
        h = _make_handoff(
            task=Task(task_id="t1", completed_summary=""),
            quality_gates=QualityGates(review_score=90),
        )
        success = [
            m for m in ext.extract(h)
            if m.metadata.get("type") == "success_pattern"
        ]
        assert len(success) == 0


# ---------------------------------------------------------------------------
# extract_and_store
# ---------------------------------------------------------------------------


class TestExtractAndStore:
    @pytest.mark.asyncio
    async def test_stores_all_extracted(self):
        ext = MemoryExtractor()
        h = _make_handoff(
            task=Task(
                task_id="t1",
                completed_summary="Built API",
                decisions_made=[Decision(decision="REST", reason="simplicity")],
            ),
            quality_gates=QualityGates(review_score=80),
        )
        mock_store = MagicMock()
        result = await ext.extract_and_store(h, mock_store)

        assert isinstance(result, ExtractionResult)
        assert result.extracted_count > 0
        assert result.stored_count == result.extracted_count
        assert mock_store.store_pattern.call_count == result.extracted_count

    @pytest.mark.asyncio
    async def test_store_failure_partial(self):
        ext = MemoryExtractor()
        h = _make_handoff(
            task=Task(
                task_id="t1",
                completed_summary="",
                decisions_made=[
                    Decision(decision="d1", reason="r1"),
                    Decision(decision="d2", reason="r2"),
                ],
            ),
        )
        mock_store = MagicMock()
        mock_store.store_pattern.side_effect = [None, RuntimeError("fail")]

        result = await ext.extract_and_store(h, mock_store)
        assert result.extracted_count == 2
        assert result.stored_count == 1

    @pytest.mark.asyncio
    async def test_empty_handoff(self):
        ext = MemoryExtractor()
        h = _make_handoff()
        mock_store = MagicMock()
        result = await ext.extract_and_store(h, mock_store)

        assert result.extracted_count == 0
        assert result.stored_count == 0
        mock_store.store_pattern.assert_not_called()


# ---------------------------------------------------------------------------
# Combined extraction
# ---------------------------------------------------------------------------


class TestCombinedExtraction:
    def test_full_handoff_extracts_all_categories(self):
        ext = MemoryExtractor(min_review_score=70)
        h = _make_handoff(
            task=Task(
                task_id="t1",
                completed_summary="Full implementation complete",
                decisions_made=[Decision(decision="d1", reason="r1")],
            ),
            artifacts=Artifacts(
                dependency_changes=[
                    DependencyChange(name="fastapi", version="0.100", action="added"),
                ],
            ),
            quality_gates=QualityGates(
                review_score=85,
                review_flags=[
                    ReviewFlag(severity="medium", category="perf", detail="slow query"),
                ],
            ),
            memory_context=MemoryContext(
                error_history=[
                    ErrorRecord(retry_num=1, error="err", resolution="fix"),
                ],
                human_feedback=[
                    HumanFeedback(
                        date="2026-04-25",
                        decision="approved",
                        applies_to="all",
                    ),
                ],
            ),
        )
        memories = ext.extract(h)
        categories = {m.category for m in memories}

        assert MemoryCategory.DECISION_PATTERN in categories
        assert MemoryCategory.QUALITY_INSIGHT in categories
        assert MemoryCategory.ERROR_RESOLUTION in categories
        assert MemoryCategory.HUMAN_FEEDBACK in categories
        assert MemoryCategory.TECH_PATTERN in categories
        assert len(memories) >= 5  # at least one per category + success pattern
