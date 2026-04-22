# Handoff Artifact Schema

> Version: 1.0.0 | Last updated: 2026-04-22

## Overview

A Handoff Artifact is the **standard JSON document** that carries context between agents. One is created per handoff and committed to Git.

Source code: `src/orchestrator/handoff.py`

## 7-Section Structure

| Section | Role | Required |
|---|---|---|
| envelope | Handoff identification · routing · retry tracking | Yes |
| project_context | Project namespace injected into stateless agents | Yes |
| task | Completed work summary + next agent instructions | Yes |
| artifacts | Changed files + generated outputs | Yes |
| quality_gates | Automated QA results + Review Agent evaluation + gate_decision | Yes |
| human_gate_package | Context for developer when L2+ is triggered | Conditional |
| memory_context | Past patterns/decisions retrieved from Mem0 | Optional |

## Section Details

### envelope

```json
{
  "handoff_id": "hf_20260413a3b4c5",
  "schema_version": "1.0.0",
  "created_at": "2026-04-13T09:23:11Z",
  "from_agent": "backend",
  "to_agent": "reviewer",
  "retry_count": 0,
  "parent_handoff_id": "hf_20260413f9a2b1"
}
```

### project_context

```json
{
  "project_id": "proj_ecomm_v2",
  "project_name": "E-Commerce Platform v2",
  "git_repo": "https://github.com/org/ecomm-v2.git",
  "git_branch": "agent/backend/hf_a3b4",
  "base_commit_sha": "a3f9d2c",
  "tech_stack": { "language": "TypeScript", "framework": "NestJS", "database": "PostgreSQL 15" }
}
```

### task

```json
{
  "task_id": "task_payment_api_v2",
  "completed_summary": "Implemented 3 payment API v2 endpoints",
  "decisions_made": [
    { "decision": "UUID v4 for idempotency key", "reason": "Stripe recommended approach" }
  ],
  "next_instructions": "Write unit tests for payment API. Coverage >= 85%."
}
```

### artifacts

```json
{
  "changed_files": [
    { "path": "src/payments/payments.controller.ts", "change_type": "added" }
  ],
  "dependency_changes": [
    { "name": "stripe", "version": "14.21.0", "action": "added", "license": "MIT" }
  ]
}
```

### quality_gates

```json
{
  "test_results": { "unit_passed": 42, "unit_failed": 0, "coverage_percent": 87.3 },
  "lint_result": "passed",
  "build_result": "passed",
  "security_scan": { "tool": "semgrep", "critical": 0, "high": 0, "medium": 1 },
  "review_score": 74,
  "gate_decision": "l2_human"
}
```

### human_gate_package

Included only when L2+ is triggered.

```json
{
  "gate_level": "l2_human",
  "trigger_reason": "New external API integration detected (Stripe)",
  "required_decision": "Proceed with Stripe production integration?",
  "decision_options": [
    { "option": "Proceed with production", "risk": "low" },
    { "option": "Keep mock for now", "risk": "none" }
  ],
  "paused_agents": ["tester", "devops"]
}
```

### memory_context

```json
{
  "relevant_past_decisions": [
    { "similarity": 0.92, "project": "proj_ecomm_v1", "decision": "Auto-retry payment 3 times" }
  ],
  "known_patterns": [
    { "pattern": "Repository Pattern", "reason": "Standard DB access pattern" }
  ]
}
```

## Pydantic Models

Full model definitions: `src/orchestrator/handoff.py`

- `HandoffArtifact` — Root model
- `Envelope`, `ProjectContext`, `Task`, `Artifacts`, `QualityGates` — Required sections
- `HumanGatePackage`, `MemoryContext` — Conditional/optional sections
