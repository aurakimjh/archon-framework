"""벤치마크 스코어러 — 결과를 분석하여 모델별 종합 점수를 산출한다."""

from __future__ import annotations

from collections import defaultdict

from src.benchmark.models import BenchmarkMetric, BenchmarkResult, ModelScore

# 기본 가중치
DEFAULT_WEIGHTS: dict[BenchmarkMetric, float] = {
    BenchmarkMetric.ACCURACY: 0.5,
    BenchmarkMetric.LATENCY: 0.3,
    BenchmarkMetric.COST: 0.2,
}


class BenchmarkScorer:
    """벤치마크 결과를 가중 점수로 변환한다."""

    def __init__(self, weights: dict[BenchmarkMetric, float] | None = None) -> None:
        self._weights = weights or dict(DEFAULT_WEIGHTS)
        total = sum(self._weights.values())
        if total > 0:
            self._weights = {k: v / total for k, v in self._weights.items()}

    @property
    def weights(self) -> dict[BenchmarkMetric, float]:
        return dict(self._weights)

    def score_results(self, results: list[BenchmarkResult]) -> list[ModelScore]:
        """결과 리스트를 모델별 종합 점수로 변환한다."""
        if not results:
            return []

        grouped: dict[str, list[BenchmarkResult]] = defaultdict(list)
        for r in results:
            grouped[r.model].append(r)

        # 정규화를 위한 최대/최소값 계산
        all_latencies = [r.latency_ms for r in results if r.is_success and r.latency_ms > 0]
        all_costs = [r.cost_usd for r in results if r.is_success and r.cost_usd > 0]
        max_latency = max(all_latencies) if all_latencies else 1.0
        max_cost = max(all_costs) if all_costs else 1.0

        scores: list[ModelScore] = []
        for model, model_results in grouped.items():
            success_results = [r for r in model_results if r.is_success]
            error_count = len(model_results) - len(success_results)

            if not success_results:
                scores.append(ModelScore(
                    model=model,
                    task_count=len(model_results),
                    error_count=error_count,
                ))
                continue

            avg_accuracy = sum(r.accuracy_score for r in success_results) / len(success_results)
            avg_latency = sum(r.latency_ms for r in success_results) / len(success_results)
            avg_cost = sum(r.cost_usd for r in success_results) / len(success_results)

            # 정규화 점수 (0~1, 높을수록 좋음)
            latency_score = 1.0 - (avg_latency / max_latency) if max_latency > 0 else 1.0
            cost_score = 1.0 - (avg_cost / max_cost) if max_cost > 0 else 1.0

            overall = (
                self._weights.get(BenchmarkMetric.ACCURACY, 0) * avg_accuracy
                + self._weights.get(BenchmarkMetric.LATENCY, 0) * max(0, latency_score)
                + self._weights.get(BenchmarkMetric.COST, 0) * max(0, cost_score)
            )

            scores.append(ModelScore(
                model=model,
                accuracy=round(avg_accuracy, 4),
                avg_latency_ms=round(avg_latency, 2),
                avg_cost_usd=round(avg_cost, 6),
                overall_score=round(min(1.0, max(0.0, overall)), 4),
                task_count=len(model_results),
                error_count=error_count,
            ))

        scores.sort(key=lambda s: s.overall_score, reverse=True)
        return scores
