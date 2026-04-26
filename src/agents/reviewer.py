"""Reviewer Agent — 코드 리뷰, 품질 점수, gate_decision 판정."""

from __future__ import annotations

import json
import logging
import re

from src.mcp.a2a import A2ARouter
from src.orchestrator.handoff import (
    Artifacts,
    Envelope,
    HandoffArtifact,
    QualityGates,
    ReviewFlag,
    Task,
)
from src.registry.models import AgentRole, ProjectRegistry

from .base import BaseAgent

logger = logging.getLogger(__name__)

_REVIEW_OUTPUT_PATTERN = re.compile(
    r"<archon-output>(.*?)</archon-output>",
    re.DOTALL,
)

_GATE_DECISION_MAP: dict[str, str] = {
    "auto_pass": "auto_pass",
    "l1_rework": "l1_rework",
    "l2_human": "l2_human",
    "l3_halt": "l3_halt",
    "l4_deploy": "l4_deploy",
}


class ReviewerAgent(BaseAgent):
    """코드 리뷰 전문 에이전트. Claude Sonnet 사용."""

    def __init__(self, a2a_router: A2ARouter | None = None, **kwargs) -> None:
        super().__init__(role=AgentRole.REVIEWER, a2a_router=a2a_router, **kwargs)

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

    def _build_handoff_result(
        self,
        input_handoff: HandoffArtifact,
        result_text: str,
    ) -> HandoffArtifact:
        """Reviewer 전용 result builder.

        review_score, gate_decision, flags를 QualityGates에 매핑하고,
        input_handoff의 기존 QA 결과(test_results, lint, build, security)를 보존한다.
        """
        parsed = self._parse_structured_output(result_text)
        review_fields = self._extract_review_fields(result_text)

        merged_gates = input_handoff.quality_gates.model_copy(
            update=review_fields,
        )

        return HandoffArtifact(
            envelope=Envelope(
                handoff_id=f"hf_{input_handoff.envelope.handoff_id}_review",
                from_agent=self.role,
                to_agent="orchestrator",
                parent_handoff_id=input_handoff.envelope.handoff_id,
            ),
            project_context=input_handoff.project_context,
            task=Task(
                task_id=input_handoff.task.task_id,
                completed_summary=parsed.get(
                    "summary", result_text[:500]
                ),
                decisions_made=parsed.get("decisions", []),
                next_instructions="Gate evaluation pending.",
            ),
            artifacts=input_handoff.artifacts,
            quality_gates=merged_gates,
        )

    @staticmethod
    def _extract_review_fields(result_text: str) -> dict:
        """Reviewer LLM 출력에서 review_score, gate_decision, flags를 추출한다."""
        match = _REVIEW_OUTPUT_PATTERN.search(result_text)
        if not match:
            return {}

        try:
            data = json.loads(match.group(1))
        except (json.JSONDecodeError, ValueError):
            logger.warning("Reviewer returned malformed JSON")
            return {}

        fields: dict = {}

        if "review_score" in data:
            score = data["review_score"]
            if isinstance(score, (int, float)):
                fields["review_score"] = max(0, min(100, int(score)))

        if "flags" in data and isinstance(data["flags"], list):
            fields["review_flags"] = [
                ReviewFlag(
                    severity=f.get("severity", "low"),
                    category=f.get("category", "general"),
                    detail=f.get("detail", ""),
                )
                for f in data["flags"]
                if isinstance(f, dict)
            ]

        return fields
