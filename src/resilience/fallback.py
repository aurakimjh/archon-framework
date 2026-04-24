"""FallbackStrategy — 에이전트/모델 실패 시 대체 전략."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


class FallbackMode(StrEnum):
    NONE = "none"               # 폴백 없음 (즉시 실패)
    CACHED = "cached"           # 캐시된 마지막 성공 결과 반환
    ALTERNATIVE_MODEL = "alternative_model"  # 다른 모델로 재실행
    ALTERNATIVE_AGENT = "alternative_agent"  # 다른 역할 에이전트로 위임
    DEGRADED = "degraded"       # 품질 저하 허용 결과 (에러 없이 빈 결과 반환)


@dataclass
class FallbackConfig:
    mode: FallbackMode = FallbackMode.DEGRADED
    # ALTERNATIVE_MODEL 모드: 대체 모델명
    fallback_model: str | None = None
    # ALTERNATIVE_AGENT 모드: 대체 에이전트 역할명
    fallback_agent_role: str | None = None
    # 폴백 결과에 경고 플래그를 붙일지 여부
    annotate_result: bool = True


class FallbackStrategy:
    """에이전트 실행 실패 시 적용할 폴백 전략.

    실제 에이전트 재실행은 FallbackStrategy 외부(RecoveryManager)에서 담당한다.
    이 클래스는 폴백 결정 로직과 캐시 관리에 집중한다.
    """

    def __init__(self, config: FallbackConfig | None = None) -> None:
        self._config = config or FallbackConfig()
        # agent_role → last_successful_result
        self._cache: dict[str, Any] = {}

    def cache_result(self, agent_role: str, result: Any) -> None:
        """성공한 결과를 캐시에 저장한다."""
        self._cache[agent_role] = result

    def get_cached(self, agent_role: str) -> Any | None:
        return self._cache.get(agent_role)

    def decide(
        self,
        agent_role: str,
        exc: Exception,
    ) -> tuple[FallbackMode, dict]:
        """실패 원인과 설정을 바탕으로 폴백 모드와 파라미터를 반환한다."""
        cfg = self._config
        mode = cfg.mode

        if mode == FallbackMode.CACHED:
            cached = self.get_cached(agent_role)
            if cached is None:
                logger.warning(
                    "Fallback [%s]: CACHED mode but no cached result — degrading",
                    agent_role,
                )
                mode = FallbackMode.DEGRADED
            else:
                logger.info("Fallback [%s]: serving cached result", agent_role)
                return FallbackMode.CACHED, {"result": cached}

        if mode == FallbackMode.ALTERNATIVE_MODEL:
            if not cfg.fallback_model:
                logger.warning(
                    "Fallback [%s]: ALTERNATIVE_MODEL but fallback_model not set — degrading",
                    agent_role,
                )
                mode = FallbackMode.DEGRADED
            else:
                logger.info(
                    "Fallback [%s]: switching to model %s",
                    agent_role,
                    cfg.fallback_model,
                )
                return FallbackMode.ALTERNATIVE_MODEL, {"model": cfg.fallback_model}

        if mode == FallbackMode.ALTERNATIVE_AGENT:
            if not cfg.fallback_agent_role:
                logger.warning(
                    "Fallback [%s]: ALTERNATIVE_AGENT but fallback_agent_role not set — degrading",
                    agent_role,
                )
                mode = FallbackMode.DEGRADED
            else:
                logger.info(
                    "Fallback [%s]: delegating to agent %s",
                    agent_role,
                    cfg.fallback_agent_role,
                )
                return FallbackMode.ALTERNATIVE_AGENT, {
                    "agent_role": cfg.fallback_agent_role
                }

        # DEGRADED 또는 NONE
        logger.warning(
            "Fallback [%s]: mode=%s — error was: %s",
            agent_role,
            mode,
            exc,
        )
        return mode, {}
