"""Context Compression 테스트."""

from __future__ import annotations

import pytest

from src.memory.compressor import (
    compress_decisions,
    compress_handoff,
    compress_memory_context,
    compress_text,
    estimate_tokens,
)
from src.orchestrator.handoff import (
    Artifacts,
    Decision,
    Envelope,
    HandoffArtifact,
    KnownPattern,
    MemoryContext,
    PastDecision,
    ProjectContext,
    Task,
)


# --- estimate_tokens ---


class TestEstimateTokens:
    def test_ascii_text(self):
        tokens = estimate_tokens("Hello World!")
        # 12 chars / 4 = 3 + 1 = 4
        assert tokens == 4

    def test_korean_text(self):
        tokens = estimate_tokens("안녕하세요")
        # 5 한글 / 2 = 2 + 1 = 3
        assert tokens == 3

    def test_mixed_text(self):
        tokens = estimate_tokens("Hello 안녕")
        # 6 ascii / 4 = 1, 2 한글 / 2 = 1, +1 = 3
        assert tokens == 3

    def test_empty_string(self):
        assert estimate_tokens("") == 1


# --- compress_text ---


class TestCompressText:
    def test_short_text_unchanged(self):
        text = "Short text."
        assert compress_text(text, max_length=100) == text

    def test_truncates_at_sentence_boundary(self):
        text = "First sentence. Second sentence. Third sentence. Fourth sentence."
        result = compress_text(text, max_length=40)
        assert "[...truncated]" in result
        assert len(result) <= 60  # 여유 포함

    def test_truncates_at_newline(self):
        text = "Line one\nLine two\nLine three\nLine four\nLine five"
        result = compress_text(text, max_length=25)
        assert "[...truncated]" in result

    def test_hard_truncation_no_boundary(self):
        text = "a" * 100
        result = compress_text(text, max_length=50)
        assert "[...truncated]" in result


# --- compress_decisions ---


class TestCompressDecisions:
    def test_within_limit(self):
        decisions = [Decision(decision=f"d{i}", reason=f"r{i}") for i in range(3)]
        result = compress_decisions(decisions, max_count=5)
        assert len(result) == 3

    def test_exceeds_limit_keeps_recent(self):
        decisions = [Decision(decision=f"d{i}", reason=f"r{i}") for i in range(10)]
        result = compress_decisions(decisions, max_count=3)
        assert len(result) == 3
        assert result[0].decision == "d7"  # 최근 3개
        assert result[2].decision == "d9"


# --- compress_memory_context ---


class TestCompressMemoryContext:
    def test_none_returns_none(self):
        assert compress_memory_context(None) is None

    def test_limits_patterns(self):
        ctx = MemoryContext(
            known_patterns=[
                KnownPattern(pattern=f"p{i}", reason=f"r{i}") for i in range(10)
            ],
        )
        result = compress_memory_context(ctx, max_patterns=3)
        assert len(result.known_patterns) == 3

    def test_limits_decisions(self):
        ctx = MemoryContext(
            relevant_past_decisions=[
                PastDecision(
                    similarity=0.9, project="p", decision=f"d{i}", outcome="ok"
                )
                for i in range(10)
            ],
        )
        result = compress_memory_context(ctx, max_decisions=2)
        assert len(result.relevant_past_decisions) == 2


# --- compress_handoff ---


def _make_handoff(
    summary_len: int = 100,
    instructions_len: int = 100,
    decision_count: int = 0,
    pattern_count: int = 0,
) -> HandoffArtifact:
    return HandoffArtifact(
        envelope=Envelope(
            handoff_id="hf_compress_test",
            from_agent="backend",
            to_agent="reviewer",
        ),
        project_context=ProjectContext(
            project_id="proj_test",
            project_name="Test",
            git_repo="/tmp/test",
            git_branch="develop",
            base_commit_sha="abc123",
        ),
        task=Task(
            task_id="task_compress",
            completed_summary="x" * summary_len,
            next_instructions="y" * instructions_len,
            decisions_made=[
                Decision(decision=f"d{i}", reason=f"r{i}")
                for i in range(decision_count)
            ],
        ),
        memory_context=MemoryContext(
            known_patterns=[
                KnownPattern(pattern=f"p{i}", reason=f"r{i}")
                for i in range(pattern_count)
            ],
        ) if pattern_count > 0 else None,
    )


class TestCompressHandoff:
    def test_small_handoff_unchanged(self):
        handoff = _make_handoff(summary_len=50, instructions_len=50)
        result = compress_handoff(handoff, max_context_tokens=50000)
        # 작은 핸드오프는 그대로
        assert result.task.completed_summary == handoff.task.completed_summary

    def test_large_summary_compressed(self):
        handoff = _make_handoff(summary_len=5000, instructions_len=100)
        result = compress_handoff(handoff, max_context_tokens=500)
        assert len(result.task.completed_summary) < 5000

    def test_large_decisions_compressed(self):
        handoff = _make_handoff(decision_count=20)
        result = compress_handoff(handoff, max_context_tokens=500)
        assert len(result.task.decisions_made) <= 5

    def test_memory_context_compressed(self):
        handoff = _make_handoff(pattern_count=20)
        result = compress_handoff(handoff, max_context_tokens=500)
        assert result.memory_context is not None
        assert len(result.memory_context.known_patterns) <= 3

    def test_original_unchanged(self):
        """원본이 변경되지 않는다 (deep copy)."""
        handoff = _make_handoff(summary_len=5000, decision_count=20, pattern_count=20)
        original_summary = handoff.task.completed_summary
        compress_handoff(handoff, max_context_tokens=500)
        assert handoff.task.completed_summary == original_summary
        assert len(handoff.task.decisions_made) == 20
