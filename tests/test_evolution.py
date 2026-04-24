"""Self-Evolving Loop 테스트 — 수집기, 분석기, 튜너, 루프."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from src.evolution.analyzer import PatternAnalyzer
from src.evolution.collector import MetricsCollector
from src.evolution.loop import EvolutionLoop
from src.evolution.models import (
    AgentMetrics,
    EvolutionConfig,
    PipelineExecution,
    PipelineMetrics,
    TuningAction,
    TuningActionType,
)
from src.evolution.tuner import ThresholdTuner


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_execution(**kwargs) -> PipelineExecution:
    defaults = {
        "execution_id": "exec-1",
        "project_id": "proj-1",
        "task_id": "task-1",
        "agent_role": "backend",
        "model": "gpt-4",
        "gate_decision": "AUTO_PASS",
        "review_score": 85,
        "retry_count": 0,
        "latency_ms": 1000.0,
        "cost_usd": 0.05,
    }
    defaults.update(kwargs)
    return PipelineExecution(**defaults)


def _make_action(**kwargs) -> TuningAction:
    defaults = {
        "action_type": TuningActionType.ADJUST_THRESHOLD,
        "target": "quality_policy.review_score_threshold",
        "reason": "test",
        "confidence": 0.9,
    }
    defaults.update(kwargs)
    return TuningAction(**defaults)


# ---------------------------------------------------------------------------
# PipelineExecution / PipelineMetrics
# ---------------------------------------------------------------------------


class TestPipelineExecution:
    def test_defaults(self):
        e = _make_execution()
        assert e.execution_id == "exec-1"
        assert e.gate_decision == "AUTO_PASS"
        assert e.timestamp is not None

    def test_with_rework(self):
        e = _make_execution(gate_decision="L1_REWORK", rework_reason="lint failure")
        assert e.rework_reason == "lint failure"


class TestPipelineMetrics:
    def test_empty(self):
        m = PipelineMetrics()
        assert m.total_executions == 0
        assert m.success_rate == 0.0

    def test_with_data(self):
        m = PipelineMetrics(total_executions=10, success_rate=0.7, rework_rate=0.2)
        assert m.total_executions == 10


class TestAgentMetrics:
    def test_defaults(self):
        a = AgentMetrics(role="backend")
        assert a.executions == 0
        assert a.common_rework_reasons == []


# ---------------------------------------------------------------------------
# MetricsCollector
# ---------------------------------------------------------------------------


class TestMetricsCollector:
    def test_record_and_size(self):
        collector = MetricsCollector()
        collector.record(_make_execution())
        assert collector.history_size == 1

    def test_max_history_trim(self):
        collector = MetricsCollector(max_history=5)
        for i in range(10):
            collector.record(_make_execution(execution_id=f"exec-{i}"))
        assert collector.history_size == 5

    def test_get_metrics_empty(self):
        collector = MetricsCollector()
        m = collector.get_metrics()
        assert m.total_executions == 0

    def test_get_metrics_mixed_decisions(self):
        collector = MetricsCollector()
        collector.record(_make_execution(gate_decision="AUTO_PASS"))
        collector.record(_make_execution(gate_decision="AUTO_PASS"))
        collector.record(_make_execution(gate_decision="L1_REWORK"))
        collector.record(_make_execution(gate_decision="L2_HUMAN"))
        collector.record(_make_execution(gate_decision="L3_HALT"))
        m = collector.get_metrics()
        assert m.total_executions == 5
        assert m.success_rate == pytest.approx(0.4)
        assert m.rework_rate == pytest.approx(0.2)
        assert m.human_gate_rate == pytest.approx(0.2)
        assert m.halt_rate == pytest.approx(0.2)

    def test_get_metrics_windowing(self):
        collector = MetricsCollector()
        old = _make_execution(
            execution_id="old",
            timestamp=datetime.now(UTC) - timedelta(hours=48),
        )
        recent = _make_execution(execution_id="recent")
        collector.record(old)
        collector.record(recent)
        m = collector.get_metrics(window_hours=24)
        assert m.total_executions == 1

    def test_get_agent_metrics(self):
        collector = MetricsCollector()
        collector.record(_make_execution(agent_role="backend", gate_decision="AUTO_PASS"))
        collector.record(_make_execution(agent_role="backend", gate_decision="L1_REWORK",
                                          rework_reason="lint"))
        collector.record(_make_execution(agent_role="frontend", gate_decision="AUTO_PASS"))
        am = collector.get_agent_metrics("backend")
        assert am.executions == 2
        assert am.success_rate == pytest.approx(0.5)
        assert "lint" in am.common_rework_reasons

    def test_by_agent_in_metrics(self):
        collector = MetricsCollector()
        collector.record(_make_execution(agent_role="backend"))
        collector.record(_make_execution(agent_role="frontend"))
        m = collector.get_metrics()
        assert "backend" in m.by_agent
        assert "frontend" in m.by_agent

    def test_clear(self):
        collector = MetricsCollector()
        collector.record(_make_execution())
        collector.clear()
        assert collector.history_size == 0

    def test_get_all_executions(self):
        collector = MetricsCollector()
        collector.record(_make_execution(execution_id="a"))
        collector.record(_make_execution(execution_id="b"))
        execs = collector.get_all_executions()
        assert len(execs) == 2


# ---------------------------------------------------------------------------
# PatternAnalyzer
# ---------------------------------------------------------------------------


class TestPatternAnalyzer:
    def test_no_actions_on_good_metrics(self):
        analyzer = PatternAnalyzer()
        metrics = PipelineMetrics(
            total_executions=20,
            success_rate=0.8,
            rework_rate=0.15,
            halt_rate=0.05,
            avg_review_score=80,
        )
        actions = analyzer.analyze(metrics)
        assert len(actions) == 0

    def test_detect_high_rework_rate(self):
        analyzer = PatternAnalyzer()
        metrics = PipelineMetrics(
            total_executions=20,
            success_rate=0.3,
            rework_rate=0.5,
            avg_review_score=75,
        )
        actions = analyzer.analyze(metrics)
        types = [a.action_type for a in actions]
        assert TuningActionType.ADJUST_THRESHOLD in types

    def test_detect_high_halt_rate(self):
        analyzer = PatternAnalyzer()
        metrics = PipelineMetrics(
            total_executions=20,
            success_rate=0.6,
            halt_rate=0.25,
            avg_review_score=70,
        )
        actions = analyzer.analyze(metrics)
        assert any(a.action_type == TuningActionType.ALERT for a in actions)

    def test_detect_low_success_rate(self):
        analyzer = PatternAnalyzer()
        metrics = PipelineMetrics(
            total_executions=20,
            success_rate=0.3,
            rework_rate=0.5,
            avg_review_score=50,
        )
        actions = analyzer.analyze(metrics)
        assert any(a.action_type == TuningActionType.SUGGEST_PROMPT for a in actions)

    def test_detect_model_underperformance(self):
        analyzer = PatternAnalyzer()
        metrics = PipelineMetrics(
            total_executions=10,
            success_rate=0.6,
            avg_review_score=70,
            by_agent={
                "backend": AgentMetrics(role="backend", executions=5, success_rate=0.2),
            },
        )
        actions = analyzer.analyze(metrics)
        assert any(a.action_type == TuningActionType.SWITCH_MODEL for a in actions)

    def test_skip_agent_with_few_executions(self):
        analyzer = PatternAnalyzer()
        metrics = PipelineMetrics(
            total_executions=10,
            success_rate=0.8,
            avg_review_score=80,
            by_agent={
                "backend": AgentMetrics(role="backend", executions=2, success_rate=0.0),
            },
        )
        actions = analyzer.analyze(metrics)
        switch_actions = [a for a in actions if a.action_type == TuningActionType.SWITCH_MODEL]
        assert len(switch_actions) == 0

    def test_detect_cost_anomaly(self):
        analyzer = PatternAnalyzer()
        metrics = PipelineMetrics(
            total_executions=5,
            success_rate=0.8,
            avg_review_score=80,
            total_cost_usd=10.0,
        )
        actions = analyzer.analyze(metrics)
        assert any("cost" in a.target for a in actions)

    def test_empty_metrics_no_actions(self):
        analyzer = PatternAnalyzer()
        metrics = PipelineMetrics()
        actions = analyzer.analyze(metrics)
        assert len(actions) == 0


# ---------------------------------------------------------------------------
# ThresholdTuner
# ---------------------------------------------------------------------------


class TestThresholdTuner:
    def test_evaluate_actions_auto_apply(self):
        tuner = ThresholdTuner(EvolutionConfig(auto_apply_threshold=0.8))
        actions = [
            _make_action(confidence=0.9),
            _make_action(confidence=0.5),
        ]
        result = tuner.evaluate_actions(actions)
        assert result[0].applied is True
        assert result[1].applied is False

    def test_safe_adjust_increase(self):
        tuner = ThresholdTuner()
        assert tuner.safe_adjust(80, "increase", 10) == 90
        assert tuner.safe_adjust(95, "increase", 10) == 100

    def test_safe_adjust_decrease(self):
        tuner = ThresholdTuner()
        assert tuner.safe_adjust(80, "decrease", 10) == 70
        assert tuner.safe_adjust(5, "decrease", 10) == 0

    def test_safe_adjust_invalid_direction(self):
        tuner = ThresholdTuner()
        assert tuner.safe_adjust(50, "invalid") == 50

    def test_apply_to_policy(self):
        tuner = ThresholdTuner(EvolutionConfig(max_threshold_delta=5))
        policy = MagicMock()
        policy.review_score_threshold = 80
        actions = [
            TuningAction(
                action_type=TuningActionType.ADJUST_THRESHOLD,
                target="quality_policy.review_score_threshold",
                suggested_value="decrease",
                confidence=0.9,
                applied=True,
            ),
        ]
        applied = tuner.apply_to_policy(actions, policy)
        assert len(applied) == 1
        assert policy.review_score_threshold == 75

    def test_apply_to_policy_skips_unapplied(self):
        tuner = ThresholdTuner()
        policy = MagicMock()
        policy.review_score_threshold = 80
        actions = [_make_action(applied=False)]
        applied = tuner.apply_to_policy(actions, policy)
        assert len(applied) == 0

    def test_apply_to_policy_missing_field(self):
        tuner = ThresholdTuner()
        policy = MagicMock(spec=[])
        actions = [_make_action(applied=True)]
        applied = tuner.apply_to_policy(actions, policy)
        assert len(applied) == 0


# ---------------------------------------------------------------------------
# EvolutionLoop
# ---------------------------------------------------------------------------


class TestEvolutionLoop:
    def _make_loop(self, **config_kwargs) -> tuple[EvolutionLoop, MetricsCollector]:
        collector = MetricsCollector()
        defaults = {"enabled": True, "min_executions_for_analysis": 3}
        defaults.update(config_kwargs)
        config = EvolutionConfig(**defaults)
        loop = EvolutionLoop(collector=collector, config=config)
        return loop, collector

    @pytest.mark.asyncio
    async def test_disabled_returns_empty(self):
        config = EvolutionConfig(enabled=False)
        loop = EvolutionLoop(collector=MetricsCollector(), config=config)
        actions = await loop.run_cycle()
        assert actions == []

    @pytest.mark.asyncio
    async def test_insufficient_data_returns_empty(self):
        loop, collector = self._make_loop(min_executions_for_analysis=10)
        collector.record(_make_execution())
        actions = await loop.run_cycle()
        assert actions == []

    @pytest.mark.asyncio
    async def test_run_cycle_with_issues(self):
        loop, collector = self._make_loop()
        for i in range(5):
            collector.record(_make_execution(
                execution_id=f"exec-{i}",
                gate_decision="L1_REWORK",
                review_score=40,
            ))
        actions = await loop.run_cycle()
        assert len(actions) > 0

    @pytest.mark.asyncio
    async def test_cycle_count_increments(self):
        loop, collector = self._make_loop()
        for i in range(5):
            collector.record(_make_execution(execution_id=f"exec-{i}"))
        await loop.run_cycle()
        assert loop.cycle_count == 1

    @pytest.mark.asyncio
    async def test_start_and_stop_background(self):
        loop, collector = self._make_loop()
        for i in range(5):
            collector.record(_make_execution(execution_id=f"exec-{i}"))
        await loop.start_background(interval_seconds=3600)
        assert loop.is_running
        await loop.stop()
        assert not loop.is_running

    @pytest.mark.asyncio
    async def test_start_background_idempotent(self):
        loop, _ = self._make_loop()
        await loop.start_background(interval_seconds=3600)
        await loop.start_background(interval_seconds=3600)
        assert loop.is_running
        await loop.stop()
