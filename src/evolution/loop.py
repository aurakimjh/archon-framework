"""Self-Evolving Loop — 메트릭 수집 → 패턴 분석 → 임계값 튜닝 주기."""

from __future__ import annotations

import asyncio
import logging

from src.evolution.analyzer import PatternAnalyzer
from src.evolution.collector import MetricsCollector
from src.evolution.models import EvolutionConfig, TuningAction
from src.evolution.tuner import ThresholdTuner
from src.log import get_logger

logger = logging.getLogger(__name__)
_slog = get_logger(__name__)


class EvolutionLoop:
    """메트릭 수집 → 분석 → 튜닝의 피드백 루프를 관리한다."""

    def __init__(
        self,
        collector: MetricsCollector,
        analyzer: PatternAnalyzer | None = None,
        tuner: ThresholdTuner | None = None,
        config: EvolutionConfig | None = None,
    ) -> None:
        self._collector = collector
        self._config = config or EvolutionConfig()
        self._analyzer = analyzer or PatternAnalyzer()
        self._tuner = tuner or ThresholdTuner(self._config)
        self._running = False
        self._task: asyncio.Task | None = None
        self._cycle_count = 0

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def cycle_count(self) -> int:
        return self._cycle_count

    async def run_cycle(self, policy: object | None = None) -> list[TuningAction]:
        """단일 분석-튜닝 사이클을 실행한다.

        Returns:
            제안된 튜닝 액션 리스트.
        """
        if not self._config.enabled:
            return []

        metrics = self._collector.get_metrics(
            window_hours=self._config.analysis_window_hours
        )

        if metrics.total_executions < self._config.min_executions_for_analysis:
            _slog.debug(
                "evolution_skip",
                reason="insufficient_data",
                total=metrics.total_executions,
                min_required=self._config.min_executions_for_analysis,
            )
            return []

        actions = self._analyzer.analyze(metrics)
        if not actions:
            _slog.debug("evolution_no_actions", cycle=self._cycle_count)
            self._cycle_count += 1
            return []

        evaluated = self._tuner.evaluate_actions(actions)

        if policy is not None:
            self._tuner.apply_to_policy(evaluated, policy)

        self._cycle_count += 1
        _slog.info(
            "evolution_cycle_completed",
            cycle=self._cycle_count,
            actions_total=len(evaluated),
            actions_applied=sum(1 for a in evaluated if a.applied),
        )

        return evaluated

    async def start_background(
        self,
        policy: object | None = None,
        interval_seconds: int = 3600,
    ) -> None:
        """백그라운드에서 주기적으로 분석-튜닝 사이클을 실행한다."""
        if self._running:
            return

        self._running = True

        async def _loop() -> None:
            while self._running:
                try:
                    await self.run_cycle(policy)
                except Exception:
                    logger.warning("Evolution cycle failed", exc_info=True)
                await asyncio.sleep(interval_seconds)

        self._task = asyncio.create_task(_loop())

    async def stop(self) -> None:
        """백그라운드 루프를 중지한다."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
