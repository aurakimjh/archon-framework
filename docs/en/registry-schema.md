# Project Registry Schema

> Version: 1.0.0 | Last updated: 2026-04-22

## Overview

The Project Registry is the central configuration store for each solution project.

- File location: `.harness/registry/{project_id}.json`
- Source code: `src/registry/models.py`

## 8-Section Structure

| Section | Role |
|---|---|
| project_meta | Identification · status · priority · scheduling |
| git_config | Repo · branch strategy · SOP paths · protected_paths |
| agent_config | Role-based LLM model assignment (plugin swap layer) |
| quality_policy | QA thresholds · Human Gate criteria · budget |
| work_queue | Task queue snapshot · current execution state |
| memory_config | Vector memory namespace · project isolation |
| metrics | Progress · cost · quality · velocity indicators |
| human_gate_history | Developer decision history · pattern learning source |

## Key Sections

### agent_config

Assigns LLM models and parameters per role. `model_override` takes precedence.

```json
{
  "orchestrator": { "model": "claude-opus-4-6", "max_tokens": 8192, "temperature": 0.3 },
  "backend": { "model": "ollama/deepseek-v3.2:70b", "max_tokens": 4096, "model_override": null }
}
```

### quality_policy

```json
{
  "coverage_threshold": 80,
  "review_score_threshold": 70,
  "max_retry_before_escalation": 3,
  "security_block_level": "critical",
  "require_human_on_schema_change": true,
  "daily_token_budget": 500
}
```

### work_queue

```json
{
  "current_task": { "task_id": "task_payment_api", "agent": "backend" },
  "pending_tasks": [{ "task_id": "task_payment_test", "depends_on": "task_payment_api" }],
  "active_agents": { "backend": { "status": "running" } },
  "overall_progress": 62
}
```

### memory_config

```json
{
  "vector_collection_id": "mem_proj_ecomm_v2",
  "scratchpad_key": "scratch:proj_ecomm_v2:",
  "cross_project_memory_enabled": false
}
```

## Pydantic Models

Full model definitions: `src/registry/models.py`

- `ProjectRegistry` — Root model
- `ProjectMeta`, `GitConfig`, `AgentModelConfig`, `QualityPolicy` — Core sections
- `WorkQueue`, `MemoryConfig`, `ProjectMetrics`, `HumanGateHistory` — State sections
