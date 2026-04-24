"""메트릭 수집기 — 파이프라인 실행 기록을 수집하고 집계한다."""

from __future__ import annotations

import logging
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta

from src.evolution.models import AgentMetrics, PipelineExecution, PipelineMetrics
from src.log import get_logger

logger = logging.getLogger(__name__)
_slog = get_logger(__name__)


class MetricsCollector:
    """파이프라인 실행 메트릭을 수집하고 시간 윈도우 기반으로 집계한다."""

    def __init__(self, max_history: int = 1000) -> None:
        self._history: list[PipelineExecution] = []
        self._max_history = max_history

    @property
    def history_size(self) -> int:
        return len(self._history)

    def record(self, execution: PipelineExecution) -> None:
        """실행 기록을 추가한다."""
        self._history.append(execution)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]
        _slog.debug(
            "execution_recorded",
            execution_id=execution.execution_id,
            gate_decision=execution.gate_decision,
        )

    def get_metrics(self, window_hours: int = 24) -> PipelineMetrics:
        """시간 윈도우 내 집계 메트릭을 반환한다."""
        cutoff = datetime.now(UTC) - timedelta(hours=window_hours)
        recent = [e for e in self._history if e.timestamp >= cutoff]
        return self._aggregate(recent)

    def get_agent_metrics(self, role: str, window_hours: int = 24) -> AgentMetrics:
        """특정 역할의 에이전트 메트릭을 반환한다."""
        cutoff = datetime.now(UTC) - timedelta(hours=window_hours)
        recent = [e for e in self._history if e.timestamp >= cutoff and e.agent_role == role]
        return self._aggregate_agent(role, recent)

    def get_all_executions(self) -> list[PipelineExecution]:
        """전체 실행 기록을 반환한다."""
        return list(self._history)

    def clear(self) -> None:
        """수집된 기록을 모두 삭제한다."""
        self._history.clear()

    def _aggregate(self, executions: list[PipelineExecution]) -> PipelineMetrics:
        total = len(executions)
        if total == 0:
            return PipelineMetrics()

        success = sum(1 for e in executions if e.gate_decision == "AUTO_PASS")
        rework = sum(1 for e in executions if e.gate_decision == "L1_REWORK")
        human = sum(1 for e in executions if e.gate_decision == "L2_HUMAN")
        halt = sum(1 for e in executions if e.gate_decision == "L3_HALT")

        # 에이전트별 집계
        by_role: dict[str, list[PipelineExecution]] = defaultdict(list)
        for e in executions:
            by_role[e.agent_role].append(e)

        by_agent = {
            role: self._aggregate_agent(role, role_execs)
            for role, role_execs in by_role.items()
        }

        return PipelineMetrics(
            total_executions=total,
            success_rate=success / total,
            rework_rate=rework / total,
            human_gate_rate=human / total,
            halt_rate=halt / total,
            avg_review_score=sum(e.review_score for e in executions) / total,
            avg_retry_count=sum(e.retry_count for e in executions) / total,
            avg_latency_ms=sum(e.latency_ms for e in executions) / total,
            total_cost_usd=sum(e.cost_usd for e in executions),
            by_agent=by_agent,
        )

    @staticmethod
    def _aggregate_agent(role: str, executions: list[PipelineExecution]) -> AgentMetrics:
        total = len(executions)
        if total == 0:
            return AgentMetrics(role=role)

        success = sum(1 for e in executions if e.gate_decision == "AUTO_PASS")
        rework_reasons = Counter(
            e.rework_reason for e in executions if e.rework_reason
        )
        top_reasons = [r for r, _ in rework_reasons.most_common(5)]

        return AgentMetrics(
            role=role,
            executions=total,
            success_rate=success / total,
            avg_review_score=sum(e.review_score for e in executions) / total,
            avg_latency_ms=sum(e.latency_ms for e in executions) / total,
            common_rework_reasons=top_reasons,
        )
