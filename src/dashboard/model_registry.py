"""litellm 설정에서 모델 목록만 추출하는 reader.

반환 객체에는 시크릿(api_key/api_base 등)이 절대 포함되지 않는다.
경로는 ARCHON_LITELLM_CONFIG_PATH 환경변수, 기본값은 config/litellm_config.yaml.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

logger = logging.getLogger(__name__)

_DEFAULT_PATH = "config/litellm_config.yaml"


class ModelEntry(BaseModel):
    """UI에 노출되는 모델 메타데이터(시크릿 제외)."""

    model_name: str
    provider: str | None = None
    underlying_model: str | None = None


def get_litellm_path() -> Path:
    return Path(os.environ.get("ARCHON_LITELLM_CONFIG_PATH", _DEFAULT_PATH))


def _split_model_id(model_id: str) -> tuple[str | None, str | None]:
    """`anthropic/claude-opus-4-6` → ("anthropic", "claude-opus-4-6")."""
    if not model_id:
        return None, None
    head, sep, tail = model_id.partition("/")
    if not sep:
        return None, model_id
    return head, tail


def load_models(path: str | Path | None = None) -> list[ModelEntry]:
    """litellm config에서 model_list 항목을 ModelEntry로 변환한다.

    파일이 없거나 깨졌으면 빈 목록을 반환한다 (UI는 빈 상태로 처리).
    """
    target = Path(path) if path else get_litellm_path()
    if not target.exists():
        return []

    try:
        data = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        logger.warning("litellm config invalid (%s)", e)
        return []

    raw = data.get("model_list") or []
    if not isinstance(raw, list):
        return []

    out: list[ModelEntry] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = item.get("model_name")
        if not isinstance(name, str) or not name or name in seen:
            continue
        seen.add(name)

        params = item.get("litellm_params") or {}
        model_id = params.get("model") if isinstance(params, dict) else None
        provider, underlying = _split_model_id(
            model_id if isinstance(model_id, str) else ""
        )
        out.append(
            ModelEntry(
                model_name=name,
                provider=provider,
                underlying_model=underlying,
            )
        )
    return out


def is_known_model(model_name: str, models: list[ModelEntry] | None = None) -> bool:
    """주어진 model_name이 litellm registry에 존재하는지 확인."""
    pool = models if models is not None else load_models()
    return any(m.model_name == model_name for m in pool)


def sanitize_dict(d: dict[str, Any]) -> dict[str, Any]:
    """디버그/로깅용 — 시크릿 키를 마스킹한다 (UI 응답에는 사용하지 않음)."""
    masked = {"api_key", "master_key", "api_base"}
    return {k: ("***" if k in masked else v) for k, v in d.items()}
