"""Reviewer Agent — 코드 리뷰, 품질 점수, gate_decision 판정."""

from __future__ import annotations

from src.gate.models import GateDecision
from src.orchestrator.handoff import HandoffArtifact
from src.registry.models import AgentRole, ProjectRegistry

from .base import BaseAgent


class ReviewerAgent(BaseAgent):
    """코드 리뷰 전문 에이전트. Claude Sonnet 사용."""

    def __init__(self) -> None:
        super().__init__(role=AgentRole.REVIEWER)

    def _build_system_prompt(
        self,
        handoff: HandoffArtifact,
        registry: ProjectRegistry,
    ) -> str:
        policy = registry.quality_policy
        return f"""You are a senior code reviewer for {handoff.project_context.project_name}.

## Quality Policy
- Coverage threshold: {policy.coverage_threshold}%
- Review score threshold: {policy.review_score_threshold}
- Max retry before escalation: {policy.max_retry_before_escalation}
- Security block level: {policy.security_block_level}
- Require human on schema change: {policy.require_human_on_schema_change}
- Require human on external integration: {policy.require_human_on_external_integration}

## Review Criteria
1. Code quality and readability
2. Architecture consistency
3. Security vulnerabilities
4. Performance implications
5. Test coverage adequacy

## Output Format (JSON)
{{
  "review_score": <0-100>,
  "gate_decision": "auto_pass|l1_rework|l2_human|l3_halt",
  "flags": [
    {{"severity": "low|medium|high|critical", "category": "...", "detail": "..."}}
  ],
  "summary": "..."
}}
"""
