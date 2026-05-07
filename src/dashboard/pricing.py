"""모델 단가 헬퍼 — config/model_pricing.json 기반 비용 계산.

캐시는 mtime 비교로 자동 무효화한다. 모델이 매핑에 없으면 default 사용.
경로: ARCHON_PRICING_PATH 환경변수, 기본 config/model_pricing.json.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from threading import Lock
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_PATH = "config/model_pricing.json"
_FALLBACK_DEFAULT: dict[str, float] = {"input": 0.002, "output": 0.006}


def get_pricing_path() -> Path:
    return Path(os.environ.get("ARCHON_PRICING_PATH", _DEFAULT_PATH))


class _PricingCache:
    """파일 mtime을 추적하며 캐시한다."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._path: Path | None = None
        self._mtime: float | None = None
        self._default: dict[str, float] = dict(_FALLBACK_DEFAULT)
        self._models: dict[str, dict[str, float]] = {}

    def load(self, path: Path | None = None) -> None:
        target = path or get_pricing_path()
        try:
            stat = target.stat()
        except FileNotFoundError:
            with self._lock:
                self._path = target
                self._mtime = None
                self._default = dict(_FALLBACK_DEFAULT)
                self._models = {}
            return

        with self._lock:
            if (
                self._path == target
                and self._mtime is not None
                and self._mtime >= stat.st_mtime
            ):
                return

        try:
            data = json.loads(target.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("pricing file invalid (%s): using defaults", e)
            data = {}

        default_raw = data.get("default") if isinstance(data, dict) else None
        models_raw = data.get("models") if isinstance(data, dict) else None

        with self._lock:
            self._path = target
            self._mtime = stat.st_mtime
            self._default = (
                {
                    "input": float(default_raw.get("input", _FALLBACK_DEFAULT["input"])),
                    "output": float(default_raw.get("output", _FALLBACK_DEFAULT["output"])),
                }
                if isinstance(default_raw, dict)
                else dict(_FALLBACK_DEFAULT)
            )
            self._models = {
                k: {
                    "input": float(v.get("input", self._default["input"])),
                    "output": float(v.get("output", self._default["output"])),
                }
                for k, v in (models_raw or {}).items()
                if isinstance(v, dict)
            }

    def lookup(self, model: str | None) -> dict[str, float]:
        with self._lock:
            cache = dict(self._models)
            default = dict(self._default)

        if not model:
            return default

        if model in cache:
            return cache[model]

        # `anthropic/claude-opus-4-7` 같은 형태에서 underlying만 추출하여 매칭.
        underlying = model.rsplit("/", 1)[-1]
        if underlying in cache:
            return cache[underlying]

        # 접두 매칭: "claude-opus-4" → "claude-opus-4-7"
        for key, val in cache.items():
            if underlying.startswith(key) or key.startswith(underlying):
                return val
        return default


_cache = _PricingCache()


def calc_cost(
    model: str | None,
    tokens_in: int,
    tokens_out: int,
    *,
    pricing_path: Path | None = None,
) -> float:
    """모델·토큰 수 기반 USD 환산. 1K tokens 단위."""
    _cache.load(pricing_path)
    rate = _cache.lookup(model)
    return (tokens_in / 1000.0) * rate["input"] + (tokens_out / 1000.0) * rate["output"]


def reset_cache_for_tests() -> None:
    """테스트에서 캐시를 비울 때 사용."""
    global _cache
    _cache = _PricingCache()
