"""Backend Agent — API 설계, DB 구현, 비즈니스 로직."""

from __future__ import annotations

from src.mcp.a2a import A2ARouter
from src.orchestrator.handoff import HandoffArtifact
from src.registry.models import AgentRole, ProjectRegistry

from .base import BaseAgent


class BackendAgent(BaseAgent):
    """백엔드 코딩 전문 에이전트."""

    def __init__(self, a2a_router: A2ARouter | None = None, **kwargs) -> None:
        super().__init__(role=AgentRole.BACKEND, a2a_router=a2a_router, **kwargs)

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
        return f"""You are a senior backend engineer working on {project}.

## Tech Stack
{tech_desc}

## Rules
- Follow the project's existing patterns and conventions.
- Write production-quality code with proper error handling.
- Include type hints for all functions and methods.
- Use async/await where appropriate.
- Follow the Repository Pattern if the project uses it.
- Do NOT modify protected paths: {registry.git_config.protected_paths}

## Output Format
Return ONLY the code implementation. No explanations unless asked.
"""
