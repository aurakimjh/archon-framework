"""Cross-Model Consensus Gate 테스트."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.gate.consensus import (
    ConsensusGate,
    ConsensusResult,
    ConsensusStrategy,
    ModelReview,
    _gate_severity,
    _parse_review_json,
)
from src.gate.models import GateDecision


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class TestModelReview:
    def test_defaults(self):
        r = ModelReview(model="gpt-4")
        assert r.review_score == 0
        assert r.gate_decision == GateDecision.L2_HUMAN
        assert r.is_success
        assert r.error is None

    def test_with_error(self):
        r = ModelReview(model="gpt-4", error="timeout")
        assert not r.is_success

    def test_with_data(self):
        r = ModelReview(
            model="gpt-4",
            review_score=85,
            gate_decision=GateDecision.AUTO_PASS,
            summary="looks good",
            latency_ms=1234.5,
        )
        assert r.review_score == 85
        assert r.summary == "looks good"


class TestConsensusResult:
    def test_empty(self):
        r = ConsensusResult()
        assert r.model_count == 0
        assert r.success_count == 0

    def test_counts(self):
        r = ConsensusResult(
            reviews=[
                ModelReview(model="m1", review_score=80),
                ModelReview(model="m2", error="fail"),
                ModelReview(model="m3", review_score=70),
            ]
        )
        assert r.model_count == 3
        assert r.success_count == 2


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class TestGateSeverity:
    def test_order(self):
        assert _gate_severity(GateDecision.AUTO_PASS) < _gate_severity(GateDecision.L1_REWORK)
        assert _gate_severity(GateDecision.L1_REWORK) < _gate_severity(GateDecision.L2_HUMAN)
        assert _gate_severity(GateDecision.L2_HUMAN) < _gate_severity(GateDecision.L3_HALT)
        assert _gate_severity(GateDecision.L3_HALT) < _gate_severity(GateDecision.L4_DEPLOY)


class TestParseReviewJson:
    def test_json_codeblock(self):
        text = '```json\n{"review_score": 85, "gate_decision": "auto_pass"}\n```'
        parsed = _parse_review_json(text)
        assert parsed["review_score"] == 85

    def test_bare_json(self):
        text = 'Here is my review: {"review_score": 70, "gate_decision": "l1_rework"}'
        parsed = _parse_review_json(text)
        assert parsed["review_score"] == 70

    def test_invalid_json(self):
        assert _parse_review_json("no json here") == {}

    def test_malformed_json(self):
        text = '```json\n{review_score: bad}\n```'
        assert _parse_review_json(text) == {}


# ---------------------------------------------------------------------------
# Consensus resolution (no LLM)
# ---------------------------------------------------------------------------


class TestResolveMajority:
    def test_all_agree_auto_pass(self):
        gate = ConsensusGate(strategy=ConsensusStrategy.MAJORITY)
        reviews = [
            ModelReview(model="m1", review_score=90, gate_decision=GateDecision.AUTO_PASS),
            ModelReview(model="m2", review_score=85, gate_decision=GateDecision.AUTO_PASS),
            ModelReview(model="m3", review_score=88, gate_decision=GateDecision.AUTO_PASS),
        ]
        result = gate._resolve_consensus(reviews)
        assert result.final_decision == GateDecision.AUTO_PASS
        assert result.consensus_reached
        assert result.dissenting_models == []

    def test_majority_wins(self):
        gate = ConsensusGate(
            strategy=ConsensusStrategy.MAJORITY,
            score_divergence_threshold=30.0,
        )
        reviews = [
            ModelReview(model="m1", review_score=90, gate_decision=GateDecision.AUTO_PASS),
            ModelReview(model="m2", review_score=85, gate_decision=GateDecision.AUTO_PASS),
            ModelReview(model="m3", review_score=70, gate_decision=GateDecision.L1_REWORK),
        ]
        result = gate._resolve_consensus(reviews)
        assert result.final_decision == GateDecision.AUTO_PASS
        assert "m3" in result.dissenting_models

    def test_no_majority_uses_strictest(self):
        gate = ConsensusGate(strategy=ConsensusStrategy.MAJORITY)
        reviews = [
            ModelReview(model="m1", review_score=90, gate_decision=GateDecision.AUTO_PASS),
            ModelReview(model="m2", review_score=40, gate_decision=GateDecision.L1_REWORK),
            ModelReview(model="m3", review_score=30, gate_decision=GateDecision.L2_HUMAN),
        ]
        result = gate._resolve_consensus(reviews)
        assert result.final_decision == GateDecision.L2_HUMAN

    def test_high_variance_breaks_consensus(self):
        gate = ConsensusGate(
            strategy=ConsensusStrategy.MAJORITY,
            score_divergence_threshold=10.0,
        )
        reviews = [
            ModelReview(model="m1", review_score=95, gate_decision=GateDecision.AUTO_PASS),
            ModelReview(model="m2", review_score=50, gate_decision=GateDecision.AUTO_PASS),
        ]
        result = gate._resolve_consensus(reviews)
        # 둘 다 AUTO_PASS지만 점수 차이가 커서 합의 실패
        assert not result.consensus_reached
        # 합의 실패 시 AUTO_PASS는 L1_REWORK로 상향
        assert result.final_decision == GateDecision.L1_REWORK


class TestResolveUnanimous:
    def test_all_agree(self):
        gate = ConsensusGate(strategy=ConsensusStrategy.UNANIMOUS)
        reviews = [
            ModelReview(model="m1", review_score=90, gate_decision=GateDecision.AUTO_PASS),
            ModelReview(model="m2", review_score=88, gate_decision=GateDecision.AUTO_PASS),
        ]
        result = gate._resolve_consensus(reviews)
        assert result.final_decision == GateDecision.AUTO_PASS
        assert result.consensus_reached

    def test_disagreement_escalates(self):
        gate = ConsensusGate(strategy=ConsensusStrategy.UNANIMOUS)
        reviews = [
            ModelReview(model="m1", review_score=90, gate_decision=GateDecision.AUTO_PASS),
            ModelReview(model="m2", review_score=60, gate_decision=GateDecision.L1_REWORK),
        ]
        result = gate._resolve_consensus(reviews)
        # L1_REWORK가 가장 엄격 → 한 단계 상향 → L2_HUMAN
        assert result.final_decision == GateDecision.L2_HUMAN
        assert len(result.dissenting_models) > 0


class TestResolveStrictest:
    def test_picks_strictest(self):
        gate = ConsensusGate(strategy=ConsensusStrategy.STRICTEST)
        reviews = [
            ModelReview(model="m1", review_score=90, gate_decision=GateDecision.AUTO_PASS),
            ModelReview(model="m2", review_score=60, gate_decision=GateDecision.L1_REWORK),
            ModelReview(model="m3", review_score=30, gate_decision=GateDecision.L2_HUMAN),
        ]
        result = gate._resolve_consensus(reviews)
        assert result.final_decision == GateDecision.L2_HUMAN
        assert "m1" in result.dissenting_models
        assert "m2" in result.dissenting_models

    def test_all_same_strict(self):
        gate = ConsensusGate(strategy=ConsensusStrategy.STRICTEST)
        reviews = [
            ModelReview(model="m1", review_score=50, gate_decision=GateDecision.L1_REWORK),
            ModelReview(model="m2", review_score=55, gate_decision=GateDecision.L1_REWORK),
        ]
        result = gate._resolve_consensus(reviews)
        assert result.final_decision == GateDecision.L1_REWORK
        assert result.dissenting_models == []


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_no_successful_reviews(self):
        gate = ConsensusGate()
        reviews = [
            ModelReview(model="m1", error="timeout"),
            ModelReview(model="m2", error="rate_limit"),
        ]
        result = gate._resolve_consensus(reviews)
        assert result.final_decision == GateDecision.L2_HUMAN
        assert not result.consensus_reached

    def test_single_model(self):
        gate = ConsensusGate()
        reviews = [
            ModelReview(model="m1", review_score=80, gate_decision=GateDecision.AUTO_PASS),
        ]
        result = gate._resolve_consensus(reviews)
        assert result.final_decision == GateDecision.AUTO_PASS
        assert result.consensus_reached

    def test_mixed_success_and_failure(self):
        gate = ConsensusGate()
        reviews = [
            ModelReview(model="m1", review_score=80, gate_decision=GateDecision.AUTO_PASS),
            ModelReview(model="m2", error="timeout"),
        ]
        result = gate._resolve_consensus(reviews)
        # 성공한 1개만으로 판정
        assert result.final_decision == GateDecision.AUTO_PASS
        assert result.success_count == 1

    def test_score_stats(self):
        gate = ConsensusGate()
        reviews = [
            ModelReview(model="m1", review_score=80, gate_decision=GateDecision.AUTO_PASS),
            ModelReview(model="m2", review_score=90, gate_decision=GateDecision.AUTO_PASS),
        ]
        result = gate._resolve_consensus(reviews)
        assert result.final_score == 85.0
        assert result.score_variance == 5.0

    def test_empty_models(self):
        gate = ConsensusGate()
        reviews: list[ModelReview] = []
        result = gate._resolve_consensus(reviews)
        assert result.final_decision == GateDecision.L2_HUMAN
        assert not result.consensus_reached


# ---------------------------------------------------------------------------
# Escalation
# ---------------------------------------------------------------------------


class TestEscalation:
    def test_auto_pass_escalates_to_l1(self):
        assert ConsensusGate._escalate(GateDecision.AUTO_PASS) == GateDecision.L1_REWORK

    def test_l1_escalates_to_l2(self):
        assert ConsensusGate._escalate(GateDecision.L1_REWORK) == GateDecision.L2_HUMAN

    def test_l4_stays(self):
        assert ConsensusGate._escalate(GateDecision.L4_DEPLOY) == GateDecision.L4_DEPLOY


# ---------------------------------------------------------------------------
# run_consensus (LLM mocked)
# ---------------------------------------------------------------------------


def _make_llm_response(score: int, decision: str) -> MagicMock:
    review_json = json.dumps({
        "review_score": score,
        "gate_decision": decision,
        "flags": [],
        "summary": "test review",
    })
    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock()]
    mock_resp.choices[0].message.content = review_json
    return mock_resp


class TestRunConsensus:
    @pytest.mark.asyncio
    async def test_two_models_agree(self):
        gate = ConsensusGate(strategy=ConsensusStrategy.MAJORITY)

        async def mock_completion(**kwargs):
            model = kwargs.get("model", "")
            if "gpt" in model:
                return _make_llm_response(85, "auto_pass")
            return _make_llm_response(80, "auto_pass")

        with patch("litellm.acompletion", side_effect=mock_completion):
            result = await gate.run_consensus(
                "Review this code",
                ["gpt-4", "claude-sonnet-4"],
            )

        assert result.model_count == 2
        assert result.success_count == 2
        assert result.final_decision == GateDecision.AUTO_PASS
        assert result.consensus_reached

    @pytest.mark.asyncio
    async def test_models_disagree(self):
        gate = ConsensusGate(strategy=ConsensusStrategy.MAJORITY)

        async def mock_completion(**kwargs):
            model = kwargs.get("model", "")
            if "gpt" in model:
                return _make_llm_response(90, "auto_pass")
            return _make_llm_response(40, "l1_rework")

        with patch("litellm.acompletion", side_effect=mock_completion):
            result = await gate.run_consensus(
                "Review this code",
                ["gpt-4", "claude-sonnet-4"],
            )

        assert result.model_count == 2
        # 50/50 split, no majority → strictest adopted
        assert result.final_decision in (GateDecision.L1_REWORK, GateDecision.L2_HUMAN)

    @pytest.mark.asyncio
    async def test_model_failure_handled(self):
        gate = ConsensusGate()

        call_count = 0

        async def mock_completion(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _make_llm_response(80, "auto_pass")
            raise RuntimeError("API error")

        with patch("litellm.acompletion", side_effect=mock_completion):
            result = await gate.run_consensus(
                "Review this code",
                ["gpt-4", "claude-sonnet-4"],
            )

        assert result.success_count == 1
        assert result.model_count == 2
        failed = [r for r in result.reviews if not r.is_success]
        assert len(failed) == 1
        assert "API error" in failed[0].error

    @pytest.mark.asyncio
    async def test_empty_models_list(self):
        gate = ConsensusGate()
        result = await gate.run_consensus("Review", [])
        assert result.model_count == 0

    @pytest.mark.asyncio
    async def test_three_models_majority(self):
        gate = ConsensusGate(
            strategy=ConsensusStrategy.MAJORITY,
            score_divergence_threshold=25.0,
        )

        responses = {
            "m1": _make_llm_response(85, "auto_pass"),
            "m2": _make_llm_response(82, "auto_pass"),
            "m3": _make_llm_response(70, "l1_rework"),
        }

        async def mock_completion(**kwargs):
            return responses[kwargs["model"]]

        with patch("litellm.acompletion", side_effect=mock_completion):
            result = await gate.run_consensus("Review", ["m1", "m2", "m3"])

        assert result.final_decision == GateDecision.AUTO_PASS
        assert "m3" in result.dissenting_models

    @pytest.mark.asyncio
    async def test_invalid_json_response(self):
        gate = ConsensusGate()

        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = "I cannot review this code."

        with patch("litellm.acompletion", new_callable=AsyncMock, return_value=mock_resp):
            result = await gate.run_consensus("Review", ["m1"])

        assert result.success_count == 1
        # 파싱 실패 → 기본값 (score=0, L2_HUMAN)
        assert result.reviews[0].review_score == 0
        assert result.reviews[0].gate_decision == GateDecision.L2_HUMAN

    @pytest.mark.asyncio
    async def test_score_clamped(self):
        gate = ConsensusGate()

        resp = _make_llm_response(150, "auto_pass")  # score > 100

        with patch("litellm.acompletion", new_callable=AsyncMock, return_value=resp):
            result = await gate.run_consensus("Review", ["m1"])

        assert result.reviews[0].review_score == 100
