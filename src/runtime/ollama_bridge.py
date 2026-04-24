"""Ollama Bridge — Ollama 서빙 엔드포인트를 LiteLLM 라우팅에 통합."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import httpx

from src.log import get_logger

logger = logging.getLogger(__name__)
_slog = get_logger(__name__)

# Ollama 기본 설정
DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"


@dataclass
class OllamaEndpoint:
    """Ollama 서버 엔드포인트 설정.

    Attributes:
        name: LiteLLM에서 사용할 모델 이름 (e.g. "ollama/llama3").
        base_url: Ollama 서버 URL (e.g. "http://localhost:11434").
        model_name: Ollama에 로드된 모델명 (e.g. "llama3:8b").
        max_tokens: 최대 생성 토큰 수.
        keep_alive: 모델 메모리 유지 시간 (e.g. "5m", "24h", "-1"=무한).
        num_gpu: GPU 레이어 수 (-1=전체, 0=CPU만).
        tags: 라우팅 메타데이터 태그 (e.g. ["backend", "tester"]).
    """

    name: str
    base_url: str = DEFAULT_OLLAMA_BASE_URL
    model_name: str = ""
    max_tokens: int = 4096
    keep_alive: str = "5m"
    num_gpu: int = -1
    tags: list[str] = field(default_factory=list)

    @property
    def litellm_model(self) -> str:
        """LiteLLM에서 사용할 모델 식별자."""
        return f"ollama_chat/{self.model_name}"

    @property
    def api_url(self) -> str:
        """Ollama API base URL (trailing slash 제거)."""
        return self.base_url.rstrip("/")

    @property
    def tags_url(self) -> str:
        """로컬 모델 목록 URL."""
        return f"{self.api_url}/api/tags"


class OllamaBridge:
    """Ollama 엔드포인트를 관리하고 LiteLLM에 등록한다.

    로컬 또는 원격 Ollama 서버들을 관리하며,
    LiteLLM의 ollama_chat provider로 등록하여 기존 라우팅 인프라에 통합한다.
    """

    def __init__(self, timeout: float = 10.0) -> None:
        self._endpoints: dict[str, OllamaEndpoint] = {}
        self._healthy: set[str] = set()
        self._timeout = timeout

    def register(self, endpoint: OllamaEndpoint) -> None:
        """Ollama 엔드포인트를 등록한다."""
        self._endpoints[endpoint.name] = endpoint
        _slog.info(
            "ollama_registered",
            name=endpoint.name,
            base_url=endpoint.base_url,
            model=endpoint.model_name,
        )

    def unregister(self, name: str) -> bool:
        """엔드포인트 등록을 해제한다."""
        if name in self._endpoints:
            del self._endpoints[name]
            self._healthy.discard(name)
            _slog.info("ollama_unregistered", name=name)
            return True
        return False

    def get_endpoint(self, name: str) -> OllamaEndpoint | None:
        """이름으로 엔드포인트를 조회한다."""
        return self._endpoints.get(name)

    def list_endpoints(self) -> list[OllamaEndpoint]:
        """등록된 모든 엔드포인트를 반환한다."""
        return list(self._endpoints.values())

    def list_healthy(self) -> list[OllamaEndpoint]:
        """정상 상태인 엔드포인트만 반환한다."""
        return [
            ep for name, ep in self._endpoints.items()
            if name in self._healthy
        ]

    def is_healthy(self, name: str) -> bool:
        """엔드포인트의 정상 상태 여부를 반환한다."""
        return name in self._healthy

    async def health_check(self, name: str) -> bool:
        """단일 엔드포인트의 헬스체크를 수행한다.

        Ollama는 GET / 에 200 OK를 반환한다.
        추가로 해당 모델이 로드 가능한지 /api/tags에서 확인한다.
        """
        endpoint = self._endpoints.get(name)
        if not endpoint:
            return False

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(endpoint.api_url)
                if resp.status_code != 200:
                    self._healthy.discard(name)
                    logger.warning(
                        "Ollama [%s] health FAIL: HTTP %d",
                        name, resp.status_code,
                    )
                    return False

                # 모델 존재 여부 확인
                if endpoint.model_name:
                    tags_resp = await client.get(endpoint.tags_url)
                    if tags_resp.status_code == 200:
                        models = [
                            m.get("name", "")
                            for m in tags_resp.json().get("models", [])
                        ]
                        base_name = endpoint.model_name.split(":")[0]
                        found = any(
                            base_name in m for m in models
                        )
                        if not found:
                            self._healthy.discard(name)
                            logger.warning(
                                "Ollama [%s] model '%s' not found"
                                " in available models: %s",
                                name, endpoint.model_name, models,
                            )
                            return False

                self._healthy.add(name)
                _slog.debug("ollama_health_ok", name=name)
                return True

        except httpx.HTTPError as e:
            self._healthy.discard(name)
            logger.warning("Ollama [%s] health error: %s", name, e)
            return False

    async def health_check_all(self) -> dict[str, bool]:
        """모든 엔드포인트의 헬스체크를 수행한다."""
        results: dict[str, bool] = {}
        for name in self._endpoints:
            results[name] = await self.health_check(name)
        return results

    def get_litellm_config(self, name: str) -> dict | None:
        """엔드포인트를 LiteLLM 설정 형식으로 반환한다.

        litellm.completion()에 전달할 수 있는 파라미터 dict를 생성한다.
        """
        endpoint = self._endpoints.get(name)
        if not endpoint:
            return None

        return {
            "model": endpoint.litellm_model,
            "api_base": endpoint.api_url,
            "max_tokens": endpoint.max_tokens,
        }

    def get_all_litellm_configs(self) -> list[dict]:
        """정상 상태 엔드포인트들의 LiteLLM 설정을 반환한다."""
        configs = []
        for name in self._healthy:
            config = self.get_litellm_config(name)
            if config:
                configs.append(config)
        return configs

    async def list_models(self, name: str | None = None) -> list[str]:
        """Ollama 서버에서 사용 가능한 모델 목록을 조회한다.

        Args:
            name: 특정 엔드포인트 이름. None이면 첫 번째 엔드포인트 사용.
        """
        if name:
            endpoint = self._endpoints.get(name)
        else:
            endpoint = next(iter(self._endpoints.values()), None)

        if not endpoint:
            return []

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(endpoint.tags_url)
                if resp.status_code == 200:
                    return [
                        m["name"]
                        for m in resp.json().get("models", [])
                        if "name" in m
                    ]
                return []
        except httpx.HTTPError:
            return []

    async def pull_model(self, model_name: str, name: str | None = None) -> bool:
        """Ollama 서버에 모델을 다운로드(pull)한다.

        Args:
            model_name: 다운로드할 모델명 (e.g. "llama3:8b").
            name: 엔드포인트 이름. None이면 첫 번째 사용.

        Returns:
            pull 요청 성공 여부.
        """
        if name:
            endpoint = self._endpoints.get(name)
        else:
            endpoint = next(iter(self._endpoints.values()), None)

        if not endpoint:
            return False

        try:
            async with httpx.AsyncClient(timeout=600.0) as client:
                resp = await client.post(
                    f"{endpoint.api_url}/api/pull",
                    json={"name": model_name, "stream": False},
                )
                return resp.status_code == 200
        except httpx.HTTPError as e:
            logger.warning(
                "Ollama pull failed for '%s': %s", model_name, e,
            )
            return False
