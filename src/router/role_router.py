"""LLM Selector / Router — 역할별 모델 라우팅 + 복잡도 기반 동적 선택."""

from __future__ import annotations

from src.orchestrator.handoff import HandoffArtifact
from src.registry.models import AgentRole, ProjectRegistry
from src.router.complexity import ComplexityLevel, measure_complexity

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
