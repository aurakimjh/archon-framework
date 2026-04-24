"""임계값 튜너 — 분석 결과를 기반으로 품질 임계값을 안전하게 조정한다."""

from __future__ import annotations

import logging

from src.evolution.models import EvolutionConfig, TuningAction, TuningActionType
from src.log import get_logger

logger = logging.getLogger(__name__)
_slog = get_logger(__name__)


class ThresholdTuner:
    """품질 임계값을 안전 범위 내에서 자동 조정한다."""

    def __init__(self, config: EvolutionConfig | None = None) -> None:
        self._config = config or EvolutionConfig()

    @property
    def auto_apply_threshold(self) -> float:
        return self._config.auto_apply_threshold

    def evaluate_actions(self, actions: list[TuningAction]) -> list[TuningAction]:
        """액션 중 자동 적용 가능한 것과 수동 검토 필요한 것을 분류한다.

        Returns:
            confidence >= auto_apply_threshold인 액션만 applied=True로 표시.
        """
        result: list[TuningAction] = []
        for action in actions:
            if action.confidence >= self._config.auto_apply_threshold:
                action.applied = True
                _slog.info(
                    "tuning_action_auto_applied",
                    action_type=action.action_type,
                    target=action.target,
                    confidence=action.confidence,
                )
            else:
                _slog.info(
                    "tuning_action_needs_review",
                    action_type=action.action_type,
                    target=action.target,
                    confidence=action.confidence,
                )
            result.append(action)
        return result

    def safe_adjust(self, current: int, direction: str, max_delta: int | None = None) -> int:
        """값을 안전 범위 내에서 조정한다.

        Args:
            current: 현재 값.
            direction: "increase" 또는 "decrease".
            max_delta: 최대 변경 폭 (기본: config.max_threshold_delta).

        Returns:
            조정된 값 (0~100 범위).
        """
        delta = max_delta or self._config.max_threshold_delta
        if direction == "increase":
            return min(100, current + delta)
        if direction == "decrease":
            return max(0, current - delta)
        return current

    def apply_to_policy(
        self,
        actions: list[TuningAction],
        policy: object,
    ) -> list[TuningAction]:
        """적용 가능한 액션을 QualityPolicy에 반영한다.

        Returns:
            실제 적용된 액션 리스트.
        """
        applied: list[TuningAction] = []
        for action in actions:
            if not action.applied:
                continue
            if action.action_type != TuningActionType.ADJUST_THRESHOLD:
                applied.append(action)
                continue

            field_name = action.target.split(".")[-1] if "." in action.target else action.target
            if not hasattr(policy, field_name):
                continue

            current = getattr(policy, field_name)
            if not isinstance(current, int):
                continue

            direction = action.suggested_value if isinstance(action.suggested_value, str) else ""
            new_value = self.safe_adjust(current, direction)
            if new_value != current:
                action.current_value = current
                action.suggested_value = new_value
                setattr(policy, field_name, new_value)
                applied.append(action)
                logger.info(
                    "Threshold adjusted: %s %d → %d",
                    field_name, current, new_value,
                )

        return applied
