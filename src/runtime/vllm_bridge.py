"""vLLM Bridge — vLLM 서빙 엔드포인트를 LiteLLM 라우팅에 통합."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger(__name__)


@dataclass
class VLLMEndpoint:
    """vLLM 서버 엔드포인트 설정.

    Attributes:
        name: LiteLLM에서 사용할 모델 이름 (e.g. "vllm/qwen-27b").
        base_url: vLLM 서버 URL (e.g. "http://gpu-node:8000").
        model_name: vLLM에 로드된 실제 모델명 (e.g. "Qwen/Qwen2.5-27B").
        api_key: vLLM API 키 (없으면 "EMPTY").
        max_tokens: 최대 생성 토큰 수.
        gpu_memory_utilization: GPU 메모리 점유율 (0.0~1.0).
        tensor_parallel_size: 텐서 병렬 GPU 수.
        tags: 라우팅 메타데이터 태그.
    """

    name: str
    base_url: str
    model_name: str
    api_key: str = "EMPTY"
    max_tokens: int = 4096
    gpu_memory_utilization: float = 0.9
    tensor_parallel_size: int = 1
    tags: list[str] = field(default_factory=list)

    @property
    def litellm_model(self) -> str:
        """LiteLLM에서 사용할 모델 식별자."""
        return f"openai/{self.model_name}"

    @property
    def health_url(self) -> str:
        """헬스체크 URL."""
        url = self.base_url.rstrip("/")
        return f"{url}/health"

    @property
    def models_url(self) -> str:
        """모델 목록 URL (OpenAI 호환)."""
        url = self.base_url.rstrip("/")
        return f"{url}/v1/models"


class VLLMBridge:
    """vLLM 엔드포인트를 관리하고 LiteLLM에 등록한다.

    GPU 워커 노드에서 실행 중인 vLLM 서버들을 관리하며,
    LiteLLM의 custom model로 등록하여 기존 라우팅 인프라에 통합한다.
    """

    def __init__(self, timeout: float = 5.0) -> None:
        self._endpoints: dict[str, VLLMEndpoint] = {}
        self._healthy: set[str] = set()
        self._timeout = timeout

    def register(self, endpoint: VLLMEndpoint) -> None:
        """vLLM 엔드포인트를 등록한다."""
        self._endpoints[endpoint.name] = endpoint
        logger.info(
            "vLLM endpoint registered: [%s] → %s (%s)",
            endpoint.name,
            endpoint.base_url,
            endpoint.model_name,
        )

    def unregister(self, name: str) -> bool:
        """엔드포인트 등록을 해제한다."""
        if name in self._endpoints:
            del self._endpoints[name]
            self._healthy.discard(name)
            logger.info("vLLM endpoint unregistered: [%s]", name)
            return True
        return False

    def get_endpoint(self, name: str) -> VLLMEndpoint | None:
        """이름으로 엔드포인트를 조회한다."""
        return self._endpoints.get(name)

    def list_endpoints(self) -> list[VLLMEndpoint]:
        """등록된 모든 엔드포인트를 반환한다."""
        return list(self._endpoints.values())

    def list_healthy(self) -> list[VLLMEndpoint]:
        """정상 상태인 엔드포인트만 반환한다."""
        return [ep for name, ep in self._endpoints.items() if name in self._healthy]

    def is_healthy(self, name: str) -> bool:
        """엔드포인트의 정상 상태 여부를 반환한다."""
        return name in self._healthy

    async def health_check(self, name: str) -> bool:
        """단일 엔드포인트의 헬스체크를 수행한다."""
        endpoint = self._endpoints.get(name)
        if not endpoint:
            return False

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(endpoint.health_url)
                healthy = response.status_code == 200
                if healthy:
                    self._healthy.add(name)
                    logger.debug("vLLM [%s] health OK", name)
                else:
                    self._healthy.discard(name)
                    logger.warning(
                        "vLLM [%s] health FAIL: HTTP %d",
                        name,
                        response.status_code,
                    )
                return healthy
        except httpx.HTTPError as e:
            self._healthy.discard(name)
            logger.warning("vLLM [%s] health error: %s", name, e)
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
            "api_base": endpoint.base_url + "/v1",
            "api_key": endpoint.api_key,
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

    async def list_models(self, name: str) -> list[str]:
        """vLLM 서버에 로드된 모델 목록을 조회한다."""
        endpoint = self._endpoints.get(name)
        if not endpoint:
            return []

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(
                    endpoint.models_url,
                    headers={"Authorization": f"Bearer {endpoint.api_key}"},
                )
                if response.status_code == 200:
                    data = response.json()
                    return [m["id"] for m in data.get("data", [])]
                return []
        except httpx.HTTPError:
            return []
