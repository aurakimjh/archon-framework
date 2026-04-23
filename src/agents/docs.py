"""Docs Agent — API 문서, README, 가이드, 변경 로그."""

from __future__ import annotations

from src.mcp.a2a import A2ARouter
from src.orchestrator.handoff import HandoffArtifact
from src.registry.models import AgentRole, ProjectRegistry

from .base import BaseAgent


class DocsAgent(BaseAgent):
    """문서 전문 에이전트."""

    def __init__(self, a2a_router: A2ARouter | None = None) -> None:
        super().__init__(role=AgentRole.DOCS, a2a_router=a2a_router)

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
        return f"""You are a senior technical writer working on {project}.

## Tech Stack
{tech_desc}

## Rules
- Write clear, concise documentation following the project's existing style.
- Use proper Markdown formatting with headers, code blocks, and tables.
- Include usage examples with realistic, runnable code snippets.
- Document all public APIs with parameters, return types, and exceptions.
- Write for the target audience — distinguish between user guides and API references.
- Keep documentation in sync with the actual code behavior.
- Include prerequisites, installation steps, and quick start sections where needed.
- Use consistent terminology throughout the documentation.
- Do NOT modify protected paths: {registry.git_config.protected_paths}

## Output Format
Return ONLY the documentation content. No meta-commentary unless asked.
"""
