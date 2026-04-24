"""패턴 분석기 — 메트릭에서 튜닝 대상 패턴을 감지한다."""

from __future__ import annotations

import logging

from src.evolution.models import PipelineMetrics, TuningAction, TuningActionType
from src.log import get_logger

logger = logging.getLogger(__name__)
_slog = get_logger(__name__)


class PatternAnalyzer:
    """파이프라인 메트릭을 분석하여 튜닝 액션을 제안한다."""

    # 임계값 기본값
    HIGH_REWORK_RATE = 0.4
    HIGH_HALT_RATE = 0.15
    LOW_SUCCESS_RATE = 0.5
    LOW_REVIEW_SCORE = 60
    HIGH_AGENT_FAILURE_RATE = 0.5

    def analyze(self, metrics: PipelineMetrics) -> list[TuningAction]:
        """메트릭을 분석하여 튜닝 액션 리스트를 반환한다."""
        actions: list[TuningAction] = []
        actions.extend(self._detect_threshold_drift(metrics))
        actions.extend(self._detect_model_underperformance(metrics))
        actions.extend(self._detect_cost_anomaly(metrics))
        return actions

    def _detect_threshold_drift(self, metrics: PipelineMetrics) -> list[TuningAction]:
        """임계값 드리프트를 감지한다."""
        actions: list[TuningAction] = []

        if metrics.total_executions == 0:
            return actions

        # 재작업률이 너무 높으면 → review_score_threshold를 낮춰야 할 수 있음
        if metrics.rework_rate > self.HIGH_REWORK_RATE:
            confidence = min(1.0, metrics.rework_rate / 0.8)
            actions.append(TuningAction(
                action_type=TuningActionType.ADJUST_THRESHOLD,
                target="quality_policy.review_score_threshold",
                current_value=None,
                suggested_value="decrease",
                reason=(
                    f"Rework rate {metrics.rework_rate:.1%} "
                    f"exceeds {self.HIGH_REWORK_RATE:.0%} threshold"
                ),
                confidence=round(confidence, 2),
            ))

        # 중단률이 너무 높으면 → 경고
        if metrics.halt_rate > self.HIGH_HALT_RATE:
            actions.append(TuningAction(
                action_type=TuningActionType.ALERT,
                target="pipeline.halt_rate",
                current_value=metrics.halt_rate,
                suggested_value=None,
                reason=f"Halt rate {metrics.halt_rate:.1%} is unusually high",
                confidence=0.9,
            ))

        # 성공률이 낮으면 → 프롬프트 개선 제안
        if metrics.success_rate < self.LOW_SUCCESS_RATE:
            actions.append(TuningAction(
                action_type=TuningActionType.SUGGEST_PROMPT,
                target="agent.system_prompt",
                current_value=None,
                suggested_value="Consider improving agent prompts",
                reason=f"Success rate {metrics.success_rate:.1%} below {self.LOW_SUCCESS_RATE:.0%}",
                confidence=0.6,
            ))

        # 평균 리뷰 점수가 낮으면 → 임계값 조정
        if metrics.avg_review_score < self.LOW_REVIEW_SCORE:
            actions.append(TuningAction(
                action_type=TuningActionType.ADJUST_THRESHOLD,
                target="quality_policy.review_score_threshold",
                current_value=None,
                suggested_value="decrease",
                reason=(
                    f"Avg review score {metrics.avg_review_score:.0f} "
                    f"below {self.LOW_REVIEW_SCORE}"
                ),
                confidence=0.7,
            ))

        return actions

    def _detect_model_underperformance(self, metrics: PipelineMetrics) -> list[TuningAction]:
        """에이전트별 모델 성능 저하를 감지한다."""
        actions: list[TuningAction] = []

        for role, agent_metrics in metrics.by_agent.items():
            if agent_metrics.executions < 3:
                continue

            if agent_metrics.success_rate < self.HIGH_AGENT_FAILURE_RATE:
                actions.append(TuningAction(
                    action_type=TuningActionType.SWITCH_MODEL,
                    target=f"agent_config.{role}.model",
                    current_value=None,
                    suggested_value="Consider switching to a more capable model",
                    reason=(
                        f"Agent '{role}' success rate {agent_metrics.success_rate:.1%} "
                        f"below {self.HIGH_AGENT_FAILURE_RATE:.0%}"
                    ),
                    confidence=0.7,
                ))

        return actions

    def _detect_cost_anomaly(self, metrics: PipelineMetrics) -> list[TuningAction]:
        """비용 이상을 감지한다."""
        actions: list[TuningAction] = []

        if metrics.total_executions == 0:
            return actions

        avg_cost = metrics.total_cost_usd / metrics.total_executions
        if avg_cost > 1.0:
            actions.append(TuningAction(
                action_type=TuningActionType.ALERT,
                target="pipeline.avg_cost",
                current_value=avg_cost,
                suggested_value=None,
                reason=f"Average execution cost ${avg_cost:.2f} is high",
                confidence=0.8,
            ))

        return actions
