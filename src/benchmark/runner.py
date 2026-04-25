"""벤치마크 실행기 — 모델별 태스크를 병렬 실행하고 결과를 수집한다."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from pathlib import Path
from typing import Any

from src.benchmark.models import BenchmarkResult, BenchmarkTask
from src.log import get_logger

logger = logging.getLogger(__name__)
_slog = get_logger(__name__)

# 기본 가격표 JSON 경로
_DEFAULT_PRICING_PATH = Path(__file__).parent.parent.parent / "config" / "model_pricing.json"


def load_pricing(path: str | Path | None = None) -> dict[str, Any]:
    """모델 가격표를 JSON에서 로드한다.

    Args:
        path: JSON 경로. None이면 config/model_pricing.json 사용.

    Returns:
        {"default": {"input": float, "output": float}, "models": {...}}
    """
    target = Path(path) if path else _DEFAULT_PRICING_PATH
    if target.exists():
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
            return {
                "default": data.get("default", {"input": 0.002, "output": 0.006}),
                "models": data.get("models", {}),
            }
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load pricing from %s: %s", target, e)

    return {"default": {"input": 0.002, "output": 0.006}, "models": {}}


class BenchmarkRunner:
    """벤치마크 태스크를 여러 모델에 대해 실행한다."""

    def __init__(
        self,
        models: list[str],
        concurrency: int = 3,
        pricing_path: str | Path | None = None,
    ) -> None:
        self._models = list(models)
        self._concurrency = max(1, concurrency)
        self._pricing = load_pricing(pricing_path)

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

    def _estimate_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """모델별 비용 추정. config/model_pricing.json 기반."""
        models = self._pricing.get("models", {})
        default = self._pricing.get("default", {"input": 0.002, "output": 0.006})

        model_lower = model.lower()
        for key, rates in models.items():
            if key.lower() in model_lower:
                inp_rate = rates.get("input", default["input"])
                out_rate = rates.get("output", default["output"])
                return (input_tokens / 1000 * inp_rate) + (output_tokens / 1000 * out_rate)

        return (input_tokens / 1000 * default["input"]) + (output_tokens / 1000 * default["output"])
