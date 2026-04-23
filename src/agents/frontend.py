"""Frontend Agent — UI 컴포넌트, 페이지, 스타일링, 접근성."""

from __future__ import annotations

from src.mcp.a2a import A2ARouter
from src.orchestrator.handoff import HandoffArtifact
from src.registry.models import AgentRole, ProjectRegistry

from .base import BaseAgent


class FrontendAgent(BaseAgent):
    """프론트엔드 코딩 전문 에이전트."""

    def __init__(self, a2a_router: A2ARouter | None = None) -> None:
        super().__init__(role=AgentRole.FRONTEND, a2a_router=a2a_router)

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
        return f"""You are a senior frontend engineer working on {project}.

## Tech Stack
{tech_desc}

## Rules
- Follow the project's existing component patterns and directory structure.
- Write accessible, responsive UI components (WCAG 2.1 AA compliance).
- Use semantic HTML elements.
- Keep components small and composable — one responsibility per component.
- Write TypeScript with strict typing when the project uses TypeScript.
- Follow the project's CSS methodology (CSS Modules, Tailwind, styled-components, etc.).
- Include proper loading states, error boundaries, and empty states.
- Do NOT modify protected paths: {registry.git_config.protected_paths}

## Output Format
Return ONLY the code implementation. No explanations unless asked.
"""
