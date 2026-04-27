"""LLM Selector / Router — 역할별 모델 라우팅 + 복잡도 + vLLM/Ollama 동적 선택."""

from __future__ import annotations

import logging

from src.orchestrator.handoff import HandoffArtifact
from src.registry.models import AgentRole, ProjectRegistry
from src.router.complexity import ComplexityLevel, measure_complexity
from src.runtime.ollama_bridge import OllamaBridge
from src.runtime.vllm_bridge import VLLMBridge

logger = logging.getLogger(__name__)

# 기본 역할-모델 매핑 (LiteLLM Proxy model_name)
ROLE_MODEL_MAP: dict[str, str] = {
    AgentRole.ORCHESTRATOR: "orchestrator",
    AgentRole.REVIEWER: "reviewer",
    AgentRole.FRONTEND: "frontend-agent",
    AgentRole.BACKEND: "backend-agent",
    AgentRole.TESTER: "tester-agent",
    AgentRole.DEVOPS: "devops-agent",
    AgentRole.DOCS: "docs-agent",
}


def get_model_for_role(role: str, registry: ProjectRegistry | None = None) -> str:
    """역할에 해당하는 LLM 모델명을 반환한다.

    우선순위:
    1. registry.agent_config[role].model_override
    2. registry.agent_config[role].model
    3. ROLE_MODEL_MAP 기본값
    """
    if registry:
        config = registry.agent_config.get(role)
        if config:
            if config.model_override:
                return config.model_override
            return config.model

    return ROLE_MODEL_MAP.get(role, "backend-agent")


def get_review_models(registry: ProjectRegistry) -> list[str]:
    """Multi-Provider 리뷰에 사용할 모델 목록을 반환한다.

    AgentModelConfig.review_models가 설정되어 있으면 그대로 반환,
    없으면 빈 리스트.
    """
    config = registry.agent_config.get(AgentRole.REVIEWER)
    if config and config.review_models:
        return list(config.review_models)
    return []


def get_model_for_handoff(
    role: str,
    handoff: HandoffArtifact,
    registry: ProjectRegistry,
) -> str:
    """핸드오프의 복잡도를 분석하여 적절한 모델을 선택한다.

    복잡도가 HIGH이고 high_complexity_model이 설정되어 있으면
    해당 모델로 라우팅한다. 그 외에는 기본 역할 라우팅을 따른다.

    Returns:
        선택된 LLM 모델명.
    """
    config = registry.agent_config.get(role)
    if not config or not config.high_complexity_model:
        return get_model_for_role(role, registry)

    complexity = measure_complexity(handoff)
    if complexity.level == ComplexityLevel.HIGH:
        return config.high_complexity_model

    return config.model_override or config.model


def get_model_with_vllm(
    role: str,
    handoff: HandoffArtifact,
    registry: ProjectRegistry,
    vllm_bridge: VLLMBridge | None = None,
) -> tuple[str, dict | None]:
    """vLLM 워커 가용 시 vLLM으로 라우팅, 아니면 기본 라우팅.

    Returns:
        (모델명, LiteLLM 추가 설정 dict 또는 None) 튜플.
        vLLM 라우팅 시 api_base 등 추가 설정이 포함된다.
    """
    # 1. vLLM 브릿지가 없으면 기본 라우팅
    if not vllm_bridge:
        return get_model_for_handoff(role, handoff, registry), None

    # 2. 역할에 매칭되는 healthy vLLM 엔드포인트 탐색
    for endpoint in vllm_bridge.list_healthy():
        if role in endpoint.tags or endpoint.name.startswith(role):
            config = vllm_bridge.get_litellm_config(endpoint.name)
            if config:
                logger.info(
                    "vLLM routing: [%s] → %s (%s)",
                    role,
                    endpoint.name,
                    endpoint.base_url,
                )
                return config["model"], config

    # 3. vLLM 매칭 없으면 기본 라우팅
    return get_model_for_handoff(role, handoff, registry), None


def get_model_with_ollama(
    role: str,
    handoff: HandoffArtifact,
    registry: ProjectRegistry,
    ollama_bridge: OllamaBridge | None = None,
) -> tuple[str, dict | None]:
    """Ollama 워커 가용 시 Ollama로 라우팅, 아니면 기본 라우팅.

    Returns:
        (모델명, LiteLLM 추가 설정 dict 또는 None) 튜플.
        Ollama 라우팅 시 api_base 등 추가 설정이 포함된다.
    """
    if not ollama_bridge:
        return get_model_for_handoff(role, handoff, registry), None

    for endpoint in ollama_bridge.list_healthy():
        if role in endpoint.tags or endpoint.name.startswith(role):
            config = ollama_bridge.get_litellm_config(endpoint.name)
            if config:
                logger.info(
                    "Ollama routing: [%s] → %s (%s)",
                    role, endpoint.name, endpoint.base_url,
                )
                return config["model"], config

    return get_model_for_handoff(role, handoff, registry), None


def get_model_with_provider(
    role: str,
    handoff: HandoffArtifact,
    registry: ProjectRegistry,
    vllm_bridge: VLLMBridge | None = None,
    ollama_bridge: OllamaBridge | None = None,
) -> tuple[str, dict | None]:
    """vLLM → Ollama → 기본 라우팅 순으로 모델을 선택한다.

    Returns:
        (모델명, LiteLLM 추가 설정 dict 또는 None) 튜플.
    """
    # 1. vLLM 우선
    if vllm_bridge:
        model, config = get_model_with_vllm(
            role, handoff, registry, vllm_bridge,
        )
        if config:
            return model, config

    # 2. Ollama
    if ollama_bridge:
        model, config = get_model_with_ollama(
            role, handoff, registry, ollama_bridge,
        )
        if config:
            return model, config

    # 3. 기본 라우팅
    return get_model_for_handoff(role, handoff, registry), None
