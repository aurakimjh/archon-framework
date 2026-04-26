"""Tester Agent — 테스트 계획, 단위/통합/E2E 테스트 생성."""

from __future__ import annotations

from src.mcp.a2a import A2ARouter
from src.orchestrator.handoff import HandoffArtifact
from src.registry.models import AgentRole, ProjectRegistry

from .base import BaseAgent


class TesterAgent(BaseAgent):
    """테스트 전문 에이전트."""

    def __init__(self, a2a_router: A2ARouter | None = None, **kwargs) -> None:
        super().__init__(role=AgentRole.TESTER, a2a_router=a2a_router, **kwargs)

    def _build_system_prompt(
        self,
        handoff: HandoffArtifact,
        registry: ProjectRegistry,
    ) -> str:
        policy = registry.quality_policy
        tech = handoff.project_context.tech_stack
        tech_desc = ""
        if tech:
            tech_desc = (
                f"Language: {tech.language}, Framework: {tech.framework}, "
                f"Database: {tech.database or 'N/A'}, Runtime: {tech.runtime or 'N/A'}"
            )

        project = handoff.project_context.project_name
        return f"""You are a senior QA/test engineer working on {project}.

## Tech Stack
{tech_desc}

## Quality Targets
- Code coverage threshold: {policy.coverage_threshold}%
- Security block level: {policy.security_block_level}

## Rules
- Write comprehensive tests covering happy paths, edge cases, and error scenarios.
- Use the project's existing test framework and patterns (pytest, Jest, etc.).
- Include both unit tests and integration tests where appropriate.
- Mock external dependencies, but test real database interactions when possible.
- Use descriptive test names that explain the scenario being tested.
- Test boundary values, null inputs, and concurrent access where relevant.
- Generate test fixtures and factories for complex data structures.
- Do NOT modify protected paths: {registry.git_config.protected_paths}

## Output Format
Return ONLY the test code. No explanations unless asked.
"""
