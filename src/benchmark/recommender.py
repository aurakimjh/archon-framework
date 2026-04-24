"""모델 추천기 — 역할별 최적 모델을 추천하고 자동 적용한다."""

from __future__ import annotations

import logging

from src.benchmark.models import BenchmarkResult, ModelRanking
from src.benchmark.scorer import BenchmarkScorer

logger = logging.getLogger(__name__)


class ModelRecommender:
    """벤치마크 결과를 기반으로 역할별 최적 모델을 추천한다."""

    def __init__(self, scorer: BenchmarkScorer | None = None) -> None:
        self._scorer = scorer or BenchmarkScorer()

    def rank_models(self, results: list[BenchmarkResult], role: str) -> ModelRanking:
        """특정 역할의 모델들을 랭킹한다."""
        role_results = [r for r in results if r.role == role]
        if not role_results:
            return ModelRanking(role=role)

        scores = self._scorer.score_results(role_results)
        recommended = scores[0].model if scores else ""

        return ModelRanking(
            role=role,
            rankings=scores,
            recommended_model=recommended,
        )

    def recommend_all_roles(
        self, results: list[BenchmarkResult]
    ) -> dict[str, ModelRanking]:
        """모든 역할에 대해 모델 랭킹을 생성한다."""
        roles: set[str] = {r.role for r in results}
        return {role: self.rank_models(results, role) for role in sorted(roles)}

    def apply_recommendations(
        self,
        rankings: dict[str, ModelRanking],
        registry: object,
    ) -> list[str]:
        """추천 결과를 ProjectRegistry에 적용한다.

        Returns:
            변경된 역할 목록.
        """
        changes: list[str] = []
        if not hasattr(registry, "agent_config"):
            return changes

        agent_config = getattr(registry, "agent_config", {})
        for role, ranking in rankings.items():
            if not ranking.recommended_model:
                continue
            if role in agent_config:
                config = agent_config[role]
                current = getattr(config, "model_override", None) or getattr(config, "model", "")
                if current != ranking.recommended_model:
                    if hasattr(config, "model_override"):
                        config.model_override = ranking.recommended_model
                    changes.append(role)
                    logger.info(
                        "Model recommendation applied: %s → %s (score: %.4f)",
                        role,
                        ranking.recommended_model,
                        ranking.rankings[0].overall_score if ranking.rankings else 0,
                    )
        return changes
