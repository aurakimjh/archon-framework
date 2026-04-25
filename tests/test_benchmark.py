"""Benchmark 모듈 테스트 — 모델, 러너, 스코어러, 추천기, 태스크."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.benchmark.models import (
    BenchmarkMetric,
    BenchmarkResult,
    BenchmarkTask,
    ModelRanking,
    ModelScore,
)
from src.benchmark.recommender import ModelRecommender
from src.benchmark.runner import BenchmarkRunner
from src.benchmark.scorer import BenchmarkScorer, DEFAULT_WEIGHTS
from src.benchmark.tasks import ALL_BENCHMARK_TASKS, get_tasks_for_role


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _make_task(**kwargs) -> BenchmarkTask:
    defaults = {
        "task_id": "t1",
        "role": "backend",
        "description": "test task",
        "prompt": "Write a function",
    }
    defaults.update(kwargs)
    return BenchmarkTask(**defaults)


def _make_result(**kwargs) -> BenchmarkResult:
    defaults = {
        "task_id": "t1",
        "model": "gpt-4",
        "role": "backend",
        "accuracy_score": 0.8,
        "latency_ms": 1000.0,
        "cost_usd": 0.05,
        "output_text": "def hello(): pass",
    }
    defaults.update(kwargs)
    return BenchmarkResult(**defaults)


# ---------------------------------------------------------------------------
# BenchmarkTask
# ---------------------------------------------------------------------------


class TestBenchmarkTask:
    def test_defaults(self):
        t = _make_task()
        assert t.task_id == "t1"
        assert t.max_latency_ms == 30000.0
        assert t.max_tokens == 2048
        assert t.expected_keywords == []

    def test_with_keywords(self):
        t = _make_task(expected_keywords=["fastapi", "post"])
        assert len(t.expected_keywords) == 2

    def test_with_patterns(self):
        t = _make_task(expected_patterns=[r"def \w+"])
        assert len(t.expected_patterns) == 1


# ---------------------------------------------------------------------------
# BenchmarkResult
# ---------------------------------------------------------------------------


class TestBenchmarkResult:
    def test_defaults(self):
        r = _make_result()
        assert r.is_success
        assert r.total_tokens == 0

    def test_with_error(self):
        r = _make_result(error="timeout")
        assert not r.is_success

    def test_total_tokens(self):
        r = _make_result(input_tokens=100, output_tokens=50)
        assert r.total_tokens == 150

    def test_accuracy_bounds(self):
        r = _make_result(accuracy_score=1.0)
        assert r.accuracy_score == 1.0
        with pytest.raises(Exception):
            _make_result(accuracy_score=1.5)


# ---------------------------------------------------------------------------
# ModelScore / ModelRanking
# ---------------------------------------------------------------------------


class TestModelScore:
    def test_defaults(self):
        s = ModelScore(model="gpt-4")
        assert s.accuracy == 0.0
        assert s.overall_score == 0.0

    def test_with_values(self):
        s = ModelScore(model="gpt-4", accuracy=0.9, overall_score=0.85, task_count=5)
        assert s.task_count == 5


class TestModelRanking:
    def test_empty_ranking(self):
        r = ModelRanking(role="backend")
        assert r.top_model is None
        assert r.recommended_model == ""

    def test_with_rankings(self):
        scores = [
            ModelScore(model="gpt-4", overall_score=0.9),
            ModelScore(model="gpt-3.5", overall_score=0.7),
        ]
        r = ModelRanking(role="backend", rankings=scores, recommended_model="gpt-4")
        assert r.top_model == "gpt-4"
        assert r.recommended_model == "gpt-4"


# ---------------------------------------------------------------------------
# BenchmarkRunner
# ---------------------------------------------------------------------------


class TestBenchmarkRunner:
    def test_models_property(self):
        runner = BenchmarkRunner(models=["m1", "m2"])
        assert runner.models == ["m1", "m2"]

    @pytest.mark.asyncio
    async def test_run_task_success(self):
        runner = BenchmarkRunner(models=["test-model"])
        task = _make_task(expected_keywords=["hello"])

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "hello world"
        mock_usage = MagicMock()
        mock_usage.prompt_tokens = 10
        mock_usage.completion_tokens = 20
        mock_response.usage = mock_usage

        with patch("litellm.acompletion", new_callable=AsyncMock, return_value=mock_response):
            result = await runner.run_task(task, "test-model")

        assert result.is_success
        assert result.model == "test-model"
        assert result.accuracy_score > 0
        assert result.latency_ms > 0

    @pytest.mark.asyncio
    async def test_run_task_error(self):
        runner = BenchmarkRunner(models=["test-model"])
        task = _make_task()

        with patch("litellm.acompletion", new_callable=AsyncMock, side_effect=RuntimeError("API error")):
            result = await runner.run_task(task, "test-model")

        assert not result.is_success
        assert "API error" in result.error

    @pytest.mark.asyncio
    async def test_run_suite(self):
        runner = BenchmarkRunner(models=["m1", "m2"], concurrency=2)
        tasks = [_make_task(task_id="t1"), _make_task(task_id="t2")]

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "output"
        mock_response.usage = MagicMock(prompt_tokens=5, completion_tokens=10)

        with patch("litellm.acompletion", new_callable=AsyncMock, return_value=mock_response):
            results = await runner.run_suite(tasks)

        assert len(results) == 4  # 2 tasks × 2 models

    def test_compute_accuracy_with_keywords(self):
        task = _make_task(expected_keywords=["fastapi", "post", "missing"])
        score = BenchmarkRunner._compute_accuracy("FastAPI POST endpoint", task)
        assert score == pytest.approx(2 / 3, rel=1e-2)

    def test_compute_accuracy_with_patterns(self):
        task = _make_task(expected_patterns=[r"def \w+", r"class \w+"])
        score = BenchmarkRunner._compute_accuracy("def hello():\n  pass", task)
        assert score == pytest.approx(0.5, rel=1e-2)

    def test_compute_accuracy_empty_checks(self):
        task = _make_task()
        assert BenchmarkRunner._compute_accuracy("some output", task) == 1.0
        assert BenchmarkRunner._compute_accuracy("", task) == 0.0

    def test_estimate_cost_known_model(self):
        runner = BenchmarkRunner(models=["gpt-4"])
        cost = runner._estimate_cost("gpt-4", 1000, 500)
        assert cost > 0

    def test_estimate_cost_unknown_model(self):
        runner = BenchmarkRunner(models=["unknown-model"])
        cost = runner._estimate_cost("unknown-model", 1000, 500)
        assert cost > 0


# ---------------------------------------------------------------------------
# BenchmarkScorer
# ---------------------------------------------------------------------------


class TestBenchmarkScorer:
    def test_default_weights(self):
        scorer = BenchmarkScorer()
        w = scorer.weights
        assert abs(sum(w.values()) - 1.0) < 1e-6

    def test_custom_weights(self):
        scorer = BenchmarkScorer(weights={BenchmarkMetric.ACCURACY: 1.0})
        w = scorer.weights
        assert w[BenchmarkMetric.ACCURACY] == pytest.approx(1.0)

    def test_score_empty_results(self):
        scorer = BenchmarkScorer()
        assert scorer.score_results([]) == []

    def test_score_single_model(self):
        scorer = BenchmarkScorer()
        results = [
            _make_result(model="m1", accuracy_score=0.9, latency_ms=500, cost_usd=0.01),
            _make_result(model="m1", accuracy_score=0.8, latency_ms=600, cost_usd=0.02),
        ]
        scores = scorer.score_results(results)
        assert len(scores) == 1
        assert scores[0].model == "m1"
        assert scores[0].accuracy == pytest.approx(0.85, rel=1e-2)

    def test_score_multiple_models_sorted(self):
        scorer = BenchmarkScorer()
        results = [
            _make_result(model="good", accuracy_score=0.95, latency_ms=500, cost_usd=0.01),
            _make_result(model="bad", accuracy_score=0.3, latency_ms=5000, cost_usd=0.1),
        ]
        scores = scorer.score_results(results)
        assert scores[0].model == "good"
        assert scores[0].overall_score > scores[1].overall_score

    def test_score_with_errors(self):
        scorer = BenchmarkScorer()
        results = [
            _make_result(model="m1", error="fail", accuracy_score=0.0),
        ]
        scores = scorer.score_results(results)
        assert len(scores) == 1
        assert scores[0].error_count == 1
        assert scores[0].overall_score == 0.0


# ---------------------------------------------------------------------------
# ModelRecommender
# ---------------------------------------------------------------------------


class TestModelRecommender:
    def test_rank_empty(self):
        rec = ModelRecommender()
        ranking = rec.rank_models([], "backend")
        assert ranking.role == "backend"
        assert ranking.recommended_model == ""

    def test_rank_single_role(self):
        rec = ModelRecommender()
        results = [
            _make_result(model="m1", role="backend", accuracy_score=0.9, latency_ms=500, cost_usd=0.01),
            _make_result(model="m2", role="backend", accuracy_score=0.7, latency_ms=800, cost_usd=0.05),
        ]
        ranking = rec.rank_models(results, "backend")
        assert ranking.recommended_model == "m1"
        assert len(ranking.rankings) == 2

    def test_recommend_all_roles(self):
        rec = ModelRecommender()
        results = [
            _make_result(model="m1", role="backend", accuracy_score=0.9, latency_ms=500, cost_usd=0.01),
            _make_result(model="m1", role="frontend", accuracy_score=0.8, latency_ms=600, cost_usd=0.02),
        ]
        rankings = rec.recommend_all_roles(results)
        assert "backend" in rankings
        assert "frontend" in rankings

    def test_apply_recommendations_no_config(self):
        rec = ModelRecommender()
        rankings = {"backend": ModelRanking(role="backend", recommended_model="m1")}
        changes = rec.apply_recommendations(rankings, object())
        assert changes == []

    def test_apply_recommendations_with_config(self):
        rec = ModelRecommender()
        rankings = {
            "backend": ModelRanking(
                role="backend",
                recommended_model="new-model",
                rankings=[ModelScore(model="new-model", overall_score=0.9)],
            )
        }
        mock_config = MagicMock()
        mock_config.model_override = "old-model"
        mock_registry = MagicMock()
        mock_registry.agent_config = {"backend": mock_config}
        changes = rec.apply_recommendations(rankings, mock_registry)
        assert "backend" in changes


# ---------------------------------------------------------------------------
# Predefined Tasks
# ---------------------------------------------------------------------------


class TestPredefinedTasks:
    def test_all_tasks_have_ids(self):
        for task in ALL_BENCHMARK_TASKS:
            assert task.task_id
            assert task.role
            assert task.prompt

    def test_get_tasks_for_role(self):
        backend = get_tasks_for_role("backend")
        assert len(backend) >= 1
        assert all(t.role == "backend" for t in backend)

    def test_get_tasks_unknown_role(self):
        assert get_tasks_for_role("unknown") == []

    def test_all_roles_covered(self):
        roles = {"backend", "frontend", "tester", "devops", "docs", "reviewer"}
        for role in roles:
            assert len(get_tasks_for_role(role)) >= 1
