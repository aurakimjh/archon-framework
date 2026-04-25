"""Cross-Model Consensus Gate — 이종 모델 합의 기반 리뷰 판정.

2개 이상의 이종 LLM에 동일한 리뷰를 요청하고,
각 모델의 판정을 종합하여 합의된 gate_decision을 도출한다.
특정 모델의 아키텍처적 편향/스타일 고착화를 방지한다.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from src.gate.models import GateDecision
from src.log import get_logger

logger = logging.getLogger(__name__)
_slog = get_logger(__name__)

# gate_decision 엄격도 순서 (높을수록 엄격)
_GATE_SEVERITY_ORDER: list[GateDecision] = [
    GateDecision.AUTO_PASS,
    GateDecision.L1_REWORK,
    GateDecision.L2_HUMAN,
    GateDecision.L3_HALT,
    GateDecision.L4_DEPLOY,
]


class ConsensusStrategy(StrEnum):
    """합의 전략."""

    MAJORITY = "majority"         # 과반수 판정
    UNANIMOUS = "unanimous"       # 만장일치 (하나라도 다르면 상향)
    STRICTEST = "strictest"       # 가장 엄격한 판정 채택


class ModelReview(BaseModel):
    """개별 모델의 리뷰 결과."""

    model: str
    review_score: int = 0
    gate_decision: GateDecision = GateDecision.L2_HUMAN
    flags: list[dict[str, str]] = Field(default_factory=list)
    summary: str = ""
    latency_ms: float = 0.0
    error: str | None = None

    @property
    def is_success(self) -> bool:
        return self.error is None


class ConsensusResult(BaseModel):
    """합의 결과."""

    reviews: list[ModelReview] = Field(default_factory=list)
    strategy: ConsensusStrategy = ConsensusStrategy.MAJORITY
    final_decision: GateDecision = GateDecision.L2_HUMAN
    final_score: float = 0.0
    consensus_reached: bool = False
    score_variance: float = 0.0
    dissenting_models: list[str] = Field(default_factory=list)

    @property
    def model_count(self) -> int:
        return len(self.reviews)

    @property
    def success_count(self) -> int:
        return sum(1 for r in self.reviews if r.is_success)


def _gate_severity(decision: GateDecision) -> int:
    """gate_decision의 엄격도 인덱스."""
    try:
        return _GATE_SEVERITY_ORDER.index(decision)
    except ValueError:
        return len(_GATE_SEVERITY_ORDER)


def _parse_review_json(text: str) -> dict[str, Any]:
    """LLM 응답에서 JSON 리뷰를 파싱한다."""
    # JSON 코드블록 시도
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except (json.JSONDecodeError, ValueError):
            pass

    # 직접 JSON 시도
    match = re.search(r"\{[^{}]*\"review_score\"[^{}]*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except (json.JSONDecodeError, ValueError):
            pass

    return {}


class ConsensusGate:
    """이종 모델 합의 기반 리뷰 게이트.

    사용 흐름:
    1. `run_consensus(prompt, models)` → 모든 모델에 동일 리뷰 요청
    2. 각 모델의 review_score + gate_decision 수집
    3. 전략에 따라 최종 판정 도출
    """

    def __init__(
        self,
        strategy: ConsensusStrategy = ConsensusStrategy.MAJORITY,
        min_agreement_ratio: float = 0.5,
        score_divergence_threshold: float = 20.0,
        timeout: float = 60.0,
    ) -> None:
        """
        Args:
            strategy: 합의 전략.
            min_agreement_ratio: MAJORITY 전략에서 과반수 기준 (0.5 = 50%).
            score_divergence_threshold: 점수 분산이 이 값 이상이면 합의 실패.
            timeout: 모델별 LLM 호출 타임아웃 (초).
        """
        self._strategy = strategy
        self._min_agreement_ratio = min_agreement_ratio
        self._score_divergence_threshold = score_divergence_threshold
        self._timeout = timeout

    @property
    def strategy(self) -> ConsensusStrategy:
        return self._strategy

    async def run_consensus(
        self,
        review_prompt: str,
        models: list[str],
        *,
        system_prompt: str = "",
        max_tokens: int = 2048,
    ) -> ConsensusResult:
        """여러 모델에 동일 리뷰를 요청하고 합의를 도출한다.

        Args:
            review_prompt: 리뷰 프롬프트 (유저 메시지).
            models: 사용할 모델 리스트 (최소 2개 권장).
            system_prompt: 시스템 프롬프트.
            max_tokens: 모델별 최대 토큰.

        Returns:
            합의 결과.
        """
        if not models:
            return ConsensusResult(strategy=self._strategy)

        coros = [
            self._query_model(model, review_prompt, system_prompt, max_tokens)
            for model in models
        ]
        reviews = await asyncio.gather(*coros)

        return self._resolve_consensus(list(reviews))

    async def _query_model(
        self,
        model: str,
        user_prompt: str,
        system_prompt: str,
        max_tokens: int,
    ) -> ModelReview:
        """단일 모델에 리뷰를 요청한다."""
        import litellm

        start = time.monotonic()
        try:
            response = await asyncio.wait_for(
                litellm.acompletion(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt or _DEFAULT_SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    max_tokens=max_tokens,
                    temperature=0.1,
                ),
                timeout=self._timeout,
            )
            elapsed_ms = (time.monotonic() - start) * 1000
            text = response.choices[0].message.content or ""

            parsed = _parse_review_json(text)
            score = int(parsed.get("review_score", 0))
            gate_str = parsed.get("gate_decision", "l2_human")
            try:
                gate = GateDecision(gate_str)
            except ValueError:
                gate = GateDecision.L2_HUMAN

            flags = parsed.get("flags", [])
            summary = parsed.get("summary", text[:200])

            return ModelReview(
                model=model,
                review_score=max(0, min(100, score)),
                gate_decision=gate,
                flags=flags if isinstance(flags, list) else [],
                summary=summary,
                latency_ms=elapsed_ms,
            )

        except Exception as exc:
            elapsed_ms = (time.monotonic() - start) * 1000
            logger.warning("Consensus review failed for %s: %s", model, exc)
            return ModelReview(
                model=model,
                latency_ms=elapsed_ms,
                error=str(exc),
            )

    def _resolve_consensus(self, reviews: list[ModelReview]) -> ConsensusResult:
        """개별 리뷰를 종합하여 합의를 도출한다."""
        successful = [r for r in reviews if r.is_success]

        if not successful:
            _slog.warning("consensus_no_successful_reviews", total=len(reviews))
            return ConsensusResult(
                reviews=reviews,
                strategy=self._strategy,
                final_decision=GateDecision.L2_HUMAN,
                consensus_reached=False,
            )

        # 점수 통계
        scores = [r.review_score for r in successful]
        avg_score = sum(scores) / len(scores)
        variance = (
            sum((s - avg_score) ** 2 for s in scores) / len(scores)
        ) ** 0.5

        # 전략별 판정
        if self._strategy == ConsensusStrategy.STRICTEST:
            final, dissenting = self._resolve_strictest(successful)
        elif self._strategy == ConsensusStrategy.UNANIMOUS:
            final, dissenting = self._resolve_unanimous(successful)
        else:
            final, dissenting = self._resolve_majority(successful)

        # 합의 판정: 전략에 따라 dissenting 허용 여부 결정
        if self._strategy == ConsensusStrategy.UNANIMOUS:
            # 만장일치: dissenting 있으면 합의 실패
            consensus_reached = len(dissenting) == 0
        elif self._strategy == ConsensusStrategy.MAJORITY:
            # 과반수: 점수 분산만 체크 (dissenting 존재는 허용)
            consensus_reached = variance <= self._score_divergence_threshold
        else:
            # STRICTEST: 항상 합의 도달 (가장 엄격한 것을 채택하므로)
            consensus_reached = variance <= self._score_divergence_threshold

        # 합의 실패 시 한 단계 상향
        if not consensus_reached and final == GateDecision.AUTO_PASS:
            final = GateDecision.L1_REWORK

        result = ConsensusResult(
            reviews=reviews,
            strategy=self._strategy,
            final_decision=final,
            final_score=round(avg_score, 1),
            consensus_reached=consensus_reached,
            score_variance=round(variance, 2),
            dissenting_models=dissenting,
        )

        _slog.info(
            "consensus_resolved",
            strategy=self._strategy,
            models=[r.model for r in reviews],
            scores=scores,
            final_decision=final,
            consensus=consensus_reached,
            variance=round(variance, 2),
        )
        return result

    def _resolve_majority(
        self, reviews: list[ModelReview],
    ) -> tuple[GateDecision, list[str]]:
        """과반수 판정."""
        decision_counts: dict[GateDecision, int] = {}
        for r in reviews:
            decision_counts[r.gate_decision] = decision_counts.get(r.gate_decision, 0) + 1

        threshold = len(reviews) * self._min_agreement_ratio
        # 가장 많은 표를 받은 판정
        sorted_decisions = sorted(
            decision_counts.items(), key=lambda x: x[1], reverse=True,
        )
        top_decision, top_count = sorted_decisions[0]

        if top_count >= threshold:
            dissenting = [
                r.model for r in reviews if r.gate_decision != top_decision
            ]
            return top_decision, dissenting

        # 과반수 미달 → 가장 엄격한 판정
        strictest = max(reviews, key=lambda r: _gate_severity(r.gate_decision))
        dissenting = [
            r.model for r in reviews if r.gate_decision != strictest.gate_decision
        ]
        return strictest.gate_decision, dissenting

    def _resolve_unanimous(
        self, reviews: list[ModelReview],
    ) -> tuple[GateDecision, list[str]]:
        """만장일치 — 모두 같아야 합의, 아니면 한 단계 상향."""
        decisions = {r.gate_decision for r in reviews}
        if len(decisions) == 1:
            return reviews[0].gate_decision, []

        # 불일치 → 가장 엄격한 판정의 한 단계 위
        strictest_decision = max(
            reviews, key=lambda r: _gate_severity(r.gate_decision),
        ).gate_decision
        escalated = self._escalate(strictest_decision)
        dissenting = [
            r.model for r in reviews if r.gate_decision != strictest_decision
        ]
        return escalated, dissenting

    def _resolve_strictest(
        self, reviews: list[ModelReview],
    ) -> tuple[GateDecision, list[str]]:
        """가장 엄격한 판정 채택."""
        strictest = max(reviews, key=lambda r: _gate_severity(r.gate_decision))
        dissenting = [
            r.model for r in reviews
            if r.gate_decision != strictest.gate_decision
        ]
        return strictest.gate_decision, dissenting

    @staticmethod
    def _escalate(decision: GateDecision) -> GateDecision:
        """한 단계 상향."""
        idx = _gate_severity(decision)
        if idx + 1 < len(_GATE_SEVERITY_ORDER):
            return _GATE_SEVERITY_ORDER[idx + 1]
        return decision


_DEFAULT_SYSTEM_PROMPT = """You are a code reviewer. Analyze the code and return a JSON response:
{
  "review_score": <0-100>,
  "gate_decision": "auto_pass|l1_rework|l2_human|l3_halt",
  "flags": [{"severity": "low|medium|high|critical", "category": "...", "detail": "..."}],
  "summary": "..."
}
Only output valid JSON."""
