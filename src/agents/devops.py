"""DevOps Agent — CI/CD, 인프라, 컨테이너화, 배포 설정."""

from __future__ import annotations

from src.mcp.a2a import A2ARouter
from src.orchestrator.handoff import HandoffArtifact
from src.registry.models import AgentRole, ProjectRegistry

from .base import BaseAgent


class DevOpsAgent(BaseAgent):
    """DevOps/인프라 전문 에이전트."""

    def __init__(self, a2a_router: A2ARouter | None = None) -> None:
        super().__init__(role=AgentRole.DEVOPS, a2a_router=a2a_router)

    def _build_system_prompt(
        self,
        handoff: HandoffArtifact,
        registry: ProjectRegistry,
    ) -> str:
        tech = handoff.project_context.tech_stack
        tech_desc = ""
        if tech:
            tech_desc = (
                f"Language: {tech.language}, Framework: {tech.framework}, "
                f"Database: {tech.database or 'N/A'}, Runtime: {tech.runtime or 'N/A'}"
            )

        project = handoff.project_context.project_name
        return f"""You are a senior DevOps engineer working on {project}.

## Tech Stack
{tech_desc}

## Rules
- Write infrastructure-as-code using the project's preferred tools (Terraform, Pulumi, etc.).
- Create optimized, multi-stage Dockerfiles with minimal image sizes.
- Design CI/CD pipelines with proper stage separation (build, test, lint, deploy).
- Follow the principle of least privilege for all IAM/RBAC configurations.
- Include health checks, readiness probes, and resource limits in container configs.
- Use environment variables for configuration — never hardcode secrets.
- Document all required environment variables and their purpose.
- Ensure reproducible builds with pinned dependency versions.
- Do NOT modify protected paths: {registry.git_config.protected_paths}

## Output Format
Return ONLY the configuration/code. No explanations unless asked.
"""
