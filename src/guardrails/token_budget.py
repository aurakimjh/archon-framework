"""TokenBudget — 프로젝트/에이전트별 토큰 예산 추적 및 비용 환산."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime

from src.guardrails.policy import GuardrailPolicy

logger = logging.getLogger(__name__)

# 기본 모델 단가 (USD per 1K tokens)
_DEFAULT_PRICING: dict[str, dict[str, float]] = {
    "claude-sonnet-4-6": {"input": 0.003, "output": 0.015},
    "claude-haiku-4-5-20251001": {"input": 0.00025, "output": 0.00125},
    "claude-opus-4-7": {"input": 0.015, "output": 0.075},
}


@dataclass
class TokenUsage:
    """단일 LLM 호출의 토큰 사용량."""

    agent_role: str
    model: str
    task_id: str
    input_tokens: int
    output_tokens: int
    timestamp: datetime = field(default_factory=datetime.utcnow)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class BudgetStatus:
    """현재 예산 상태."""

    project_id: str
    date: str                         # YYYY-MM-DD
    daily_tokens_used: int
    daily_token_limit: int            # 0 = 무제한
    total_cost_usd: float
    agent_breakdown: dict[str, int]   # role → tokens_used
    warn_threshold_reached: bool
    limit_exceeded: bool

    @property
    def remaining_tokens(self) -> int:
        if self.daily_token_limit == 0:
            return -1  # 무제한
        return max(0, self.daily_token_limit - self.daily_tokens_used)

    @property
    def usage_ratio(self) -> float:
        if self.daily_token_limit == 0:
            return 0.0
        return self.daily_tokens_used / self.daily_token_limit


class TokenBudgetTracker:
    """프로젝트별 토큰 예산 실시간 추적.

    인메모리로 동작하며, 재시작 시 초기화된다.
    영속화가 필요하면 ProjectRegistry.metrics.total_tokens_used와 연동할 것.
    """

    def __init__(
        self,
        project_id: str,
        policy: GuardrailPolicy | None = None,
    ) -> None:
        self._project_id = project_id
        self._policy = policy or GuardrailPolicy()
        # date → list[TokenUsage]
        self._usage: dict[str, list[TokenUsage]] = {}

    def record(
        self,
        agent_role: str,
        model: str,
        task_id: str,
        input_tokens: int,
        output_tokens: int,
    ) -> BudgetStatus:
        """토큰 사용량을 기록하고 현재 예산 상태를 반환한다."""
        today = date.today().isoformat()
        usage = TokenUsage(
            agent_role=agent_role,
            model=model,
            task_id=task_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
        self._usage.setdefault(today, []).append(usage)

        status = self.get_status(today)

        # 로깅
        if status.limit_exceeded:
            logger.error(
                "TokenBudget [%s]: daily limit exceeded — %d / %d tokens (cost: $%.4f)",
                self._project_id,
                status.daily_tokens_used,
                status.daily_token_limit,
                status.total_cost_usd,
            )
        elif status.warn_threshold_reached:
            logger.warning(
                "TokenBudget [%s]: %.0f%% of daily budget used — %d / %d tokens",
                self._project_id,
                status.usage_ratio * 100,
                status.daily_tokens_used,
                status.daily_token_limit,
            )

        return status

    def check_before_call(
        self,
        agent_role: str,
        estimated_tokens: int,
    ) -> BudgetStatus:
        """LLM 호출 전 예산 여유를 확인한다 (기록은 하지 않음)."""
        today = date.today().isoformat()
        status = self.get_status(today)

        per_task_limit = self._policy.per_task_token_limit
        if per_task_limit > 0 and estimated_tokens > per_task_limit:
            logger.warning(
                "TokenBudget [%s/%s]: estimated %d tokens exceeds per-task limit %d",
                self._project_id,
                agent_role,
                estimated_tokens,
                self._policy.per_task_token_limit,
            )

        return status

    def get_status(self, date_str: str | None = None) -> BudgetStatus:
        """특정 날짜(기본 오늘)의 예산 상태를 반환한다."""
        target = date_str or date.today().isoformat()
        usages = self._usage.get(target, [])

        daily_tokens = sum(u.total_tokens for u in usages)
        cost = self._calculate_cost(usages)
        breakdown: dict[str, int] = {}
        for u in usages:
            breakdown[u.agent_role] = breakdown.get(u.agent_role, 0) + u.total_tokens

        limit = self._policy.daily_token_limit
        exceeded = limit > 0 and daily_tokens > limit
        warn = (
            limit > 0
            and not exceeded
            and daily_tokens / limit >= self._policy.budget_warn_threshold
        )

        return BudgetStatus(
            project_id=self._project_id,
            date=target,
            daily_tokens_used=daily_tokens,
            daily_token_limit=limit,
            total_cost_usd=cost,
            agent_breakdown=breakdown,
            warn_threshold_reached=warn,
            limit_exceeded=exceeded,
        )

    def get_agent_usage(self, agent_role: str, date_str: str | None = None) -> int:
        """특정 에이전트의 당일 토큰 사용량을 반환한다."""
        target = date_str or date.today().isoformat()
        return sum(
            u.total_tokens
            for u in self._usage.get(target, [])
            if u.agent_role == agent_role
        )

    def reset_daily(self, date_str: str | None = None) -> None:
        """특정 날짜의 사용량을 초기화한다."""
        target = date_str or date.today().isoformat()
        self._usage.pop(target, None)
        logger.info("TokenBudget [%s]: daily usage reset for %s", self._project_id, target)

    def _calculate_cost(self, usages: list[TokenUsage]) -> float:
        """토큰 사용량을 USD 비용으로 환산한다."""
        pricing = {**_DEFAULT_PRICING, **self._policy.model_pricing}
        total = 0.0
        for u in usages:
            rates = pricing.get(u.model)
            if not rates:
                # 미지정 모델은 sonnet 기준으로 추정
                rates = pricing.get("claude-sonnet-4-6", {"input": 0.003, "output": 0.015})
            total += (u.input_tokens / 1000) * rates.get("input", 0.003)
            total += (u.output_tokens / 1000) * rates.get("output", 0.015)
        return round(total, 6)
