"""LLM Selector / Router — 역할별 모델 라우팅."""

from __future__ import annotations

from src.registry.models import AgentRole, ProjectRegistry

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
