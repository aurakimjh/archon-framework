"""벤치마크 실행기 — 모델별 태스크를 병렬 실행하고 결과를 수집한다."""

from __future__ import annotations

import asyncio
import logging
import re
import time

from src.benchmark.models import BenchmarkResult, BenchmarkTask
from src.log import get_logger

logger = logging.getLogger(__name__)
_slog = get_logger(__name__)


class BenchmarkRunner:
    """벤치마크 태스크를 여러 모델에 대해 실행한다."""

    def __init__(self, models: list[str], concurrency: int = 3) -> None:
        self._models = list(models)
        self._concurrency = max(1, concurrency)

    @property
    def models(self) -> list[str]:
        return list(self._models)

    async def run_task(self, task: BenchmarkTask, model: str) -> BenchmarkResult:
        """단일 태스크를 단일 모델로 실행한다."""
        import litellm

        start = time.monotonic()
        try:
            response = await litellm.acompletion(
                model=model,
                messages=[
                    {"role": "system", "content": f"You are a {task.role} agent."},
                    {"role": "user", "content": task.prompt},
                ],
                max_tokens=task.max_tokens,
            )
            elapsed_ms = (time.monotonic() - start) * 1000
            output_text = response.choices[0].message.content or ""
            usage = response.usage or {}
            input_tokens = getattr(usage, "prompt_tokens", 0) or 0
            output_tokens = getattr(usage, "completion_tokens", 0) or 0

            # 정확도 점수 계산
            accuracy = self._compute_accuracy(output_text, task)

            # 비용 추정
            cost = self._estimate_cost(model, input_tokens, output_tokens)

            _slog.info(
                "benchmark_task_completed",
                task_id=task.task_id,
                model=model,
                accuracy=accuracy,
                latency_ms=elapsed_ms,
            )

            return BenchmarkResult(
                task_id=task.task_id,
                model=model,
                role=task.role,
                accuracy_score=accuracy,
                latency_ms=elapsed_ms,
                cost_usd=cost,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                output_text=output_text,
            )

        except Exception as exc:
            elapsed_ms = (time.monotonic() - start) * 1000
            logger.warning("Benchmark task %s failed on %s: %s", task.task_id, model, exc)
            return BenchmarkResult(
                task_id=task.task_id,
                model=model,
                role=task.role,
                latency_ms=elapsed_ms,
                error=str(exc),
            )

    async def run_suite(
        self, tasks: list[BenchmarkTask], models: list[str] | None = None
    ) -> list[BenchmarkResult]:
        """모든 태스크를 모든 모델에 대해 병렬 실행한다."""
        target_models = models or self._models
        semaphore = asyncio.Semaphore(self._concurrency)

        async def _run_with_limit(task: BenchmarkTask, model: str) -> BenchmarkResult:
            async with semaphore:
                return await self.run_task(task, model)

        coros = [_run_with_limit(task, model) for task in tasks for model in target_models]
        results = await asyncio.gather(*coros)
        return list(results)

    @staticmethod
    def _compute_accuracy(output: str, task: BenchmarkTask) -> float:
        """출력 텍스트의 키워드/패턴 매칭 기반 정확도 점수."""
        if not task.expected_keywords and not task.expected_patterns:
            return 1.0 if output.strip() else 0.0

        total_checks = len(task.expected_keywords) + len(task.expected_patterns)
        matches = 0
        output_lower = output.lower()

        for keyword in task.expected_keywords:
            if keyword.lower() in output_lower:
                matches += 1

        for pattern in task.expected_patterns:
            if re.search(pattern, output, re.IGNORECASE):
                matches += 1

        return matches / total_checks if total_checks > 0 else 0.0

    @staticmethod
    def _estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
        """모델별 비용 추정 (간이 가격표)."""
        pricing: dict[str, tuple[float, float]] = {
            "gpt-4": (0.03, 0.06),
            "gpt-4o": (0.005, 0.015),
            "gpt-3.5-turbo": (0.0005, 0.0015),
            "claude-3-opus": (0.015, 0.075),
            "claude-3-sonnet": (0.003, 0.015),
            "claude-3-haiku": (0.00025, 0.00125),
        }
        for key, (inp_rate, out_rate) in pricing.items():
            if key in model.lower():
                return (input_tokens / 1000 * inp_rate) + (output_tokens / 1000 * out_rate)
        # 기본 가격
        return (input_tokens / 1000 * 0.002) + (output_tokens / 1000 * 0.006)
