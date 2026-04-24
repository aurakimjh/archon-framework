# Project Registry Schema

🇰🇷 [한국어](../ko/registry-schema.md)

> Version: 1.1.0 | Last updated: 2026-04-23

## Overview

The Project Registry is the **central configuration store** for each solution project.

- File location: `.harness/registry/{project_id}.json`
- Source code: `src/registry/models.py`, `src/registry/store.py`

## 8-Section Structure

| Section | Purpose |
|---|---|
| project_meta | Identity · status · priority · scheduling |
| git_config | Repo · branch strategy · SOP path · protected_paths |
| agent_config | Per-role LLM model assignment (plugin swap layer) |
| quality_policy | QA thresholds · Human Gate criteria · budget · Dynamic Guardrails |
| work_queue | Task queue snapshot · current execution state |
| memory_config | 3-layer memory settings (Redis/ChromaDB/Mem0) |
| metrics | Progress · cost · quality · throughput indicators |
| human_gate_history | Developer decision log · pattern learning source |

## Section Details

### project_meta

```json
{
  "project_id": "proj_ecomm_v2",
  "project_name": "E-Commerce Platform v2",
  "status": "active",
  "priority": 10,
  "deadline": "2026-06-01T00:00:00Z",
  "owner": "dev_001",
  "description": "B2C e-commerce platform v2 redesign",
  "tags": ["backend", "api", "payment", "v2"]
}
```

- `status`: `active` | `paused` | `completed` | `archived`
- `priority`: 1–10 (higher = more urgent)

---

### git_config

```json
{
  "repo_url": "https://github.com/org/ecomm-v2.git",
  "main_branch": "develop",
  "agent_branch_prefix": "agent/",
  "auto_commit_message_template": "feat({agent}): {summary} [task:{task_id}]",
  "sop_directory": ".harness/sop/",
  "protected_paths": [".env", "infrastructure/", "secrets/"]
}
```

- `protected_paths`: paths agents can never modify. Violations raise `ProtectedPathError`.

---

### agent_config

Specifies the LLM model and parameters per role. `model_override` takes precedence when set.

```json
{
  "orchestrator": {
    "model": "claude-opus-4-6",
    "max_tokens": 8192,
    "temperature": 0.3,
    "streaming": false,
    "timeout_seconds": 300,
    "high_complexity_model": null
  },
  "reviewer": {
    "model": "claude-sonnet-4-6",
    "max_tokens": 4096,
    "temperature": 0.1,
    "streaming": false,
    "timeout_seconds": 300
  },
  "backend": {
    "model": "ollama/deepseek-v3.2:70b",
    "max_tokens": 4096,
    "temperature": 0.2,
    "model_override": null,
    "streaming": true,
    "timeout_seconds": 600,
    "high_complexity_model": "ollama/deepseek-v3.2:70b"
  }
}
```

| Field | Default | Description |
|---|---|---|
| `model` | — | Base LLM model |
| `max_tokens` | 4096 | Maximum generation tokens |
| `temperature` | 0.2 | Generation temperature |
| `model_override` | null | Overrides `model` when set |
| `streaming` | false | Enable streaming output |
| `timeout_seconds` | 300 | Streaming timeout in seconds |
| `high_complexity_model` | null | Model used when Complexity Router scores HIGH |
| `reviewer_guidelines_path` | null | Path to reviewer guidelines file |

---

### quality_policy

QA thresholds, Human Gate criteria, budget, and Dynamic Guardrails configuration.

```json
{
  "coverage_threshold": 80,
  "review_score_threshold": 70,
  "max_retry_before_escalation": 3,
  "security_block_level": "critical",
  "require_human_on_schema_change": true,
  "require_human_on_external_integration": true,
  "daily_token_budget": 500,
  "sop_compliance_threshold": 70,
  "high_risk_paths": [
    "payment", "billing", "auth", "security",
    "migration", "infrastructure/", "secrets/"
  ],
  "high_risk_keywords": [
    "payment", "billing", "charge", "refund",
    "credential", "secret", "token", "api_key",
    "delete_all", "drop_table", "truncate",
    "production", "deploy"
  ]
}
```

| Field | Default | Description |
|---|---|---|
| `coverage_threshold` | 80 | Test coverage target (%) |
| `review_score_threshold` | 70 | Minimum review_score |
| `max_retry_before_escalation` | 3 | Max L1 retries before L2 escalation |
| `sop_compliance_threshold` | 70 | Minimum SOP compliance score |
| `high_risk_paths` | (list above) | File path patterns that auto-escalate to L2 |
| `high_risk_keywords` | (list above) | Instruction keywords that auto-escalate to L2 |

---

### work_queue

Snapshot of active tasks, queue, and blocked tasks.

```json
{
  "current_task": {
    "task_id": "task_payment_api",
    "agent": "backend",
    "started_at": "2026-04-23T10:00:00Z",
    "priority": 8
  },
  "pending_tasks": [
    { "task_id": "task_payment_test", "depends_on": "task_payment_api", "priority": 7 }
  ],
  "blocked_tasks": [
    { "task_id": "task_refund_api", "blocked_by": "task_payment_api", "unblock_condition": "After payment API complete" }
  ],
  "active_agents": {
    "backend": { "status": "running", "current_task_id": "task_payment_api" },
    "tester": { "status": "waiting" }
  },
  "overall_progress": 62
}
```

---

### memory_config

Connection settings for the 3-layer memory system. Each layer is optional; missing layers fall back to in-memory.

```json
{
  "vector_collection_id": "mem_proj_ecomm_v2",
  "scratchpad_key": "scratch:proj_ecomm_v2:",
  "retain_handoff_count": 100,
  "auto_learn_patterns": true,
  "cross_project_memory_enabled": false,
  "redis_url": "redis://localhost:6379/0",
  "redis_ttl": 86400,
  "chroma_path": null,
  "chroma_collection_prefix": "archon",
  "mem0_api_key": null,
  "mem0_user_id": "archon"
}
```

| Field | Default | Description |
|---|---|---|
| `redis_url` | `redis://localhost:6379/0` | L1 Redis connection URL |
| `redis_ttl` | 86400 | L1 scratchpad TTL in seconds (default 24h) |
| `chroma_path` | null | L2 ChromaDB local path (null = in-memory) |
| `chroma_collection_prefix` | `"archon"` | L2 collection name prefix |
| `mem0_api_key` | null | L3 Mem0 API key (null = L3 disabled) |
| `cross_project_memory_enabled` | false | Allow referencing other project patterns |

**3-layer memory overview**:

| Layer | Implementation | TTL | Scope |
|---|---|---|---|
| L1 short-term | Redis scratchpad | 24h | Per-task |
| L2 mid-term | ChromaDB vector search | unlimited | Per-project |
| L3 long-term | Mem0 pattern learning | unlimited | Cross-project |

---

### metrics

```json
{
  "total_tokens_used": 1240000,
  "estimated_cost_usd": 4.82,
  "auto_commit_count": 34,
  "human_gate_count": 3,
  "l3_halt_count": 0,
  "average_review_score": 81.2,
  "agent_utilization": {
    "backend": 0.78,
    "tester": 0.45,
    "frontend": 0.12
  }
}
```

---

### human_gate_history

Log of developer decisions. Fed into Mem0 to auto-reference similar future situations.

```json
{
  "entries": [
    {
      "handoff_id": "hf_20260410b2c3",
      "gate_level": "l2_human",
      "trigger": "New Stripe integration",
      "decision": "Keep mock, integrate later",
      "rationale": "Real payments unnecessary at MVP stage",
      "response_time_minutes": 4,
      "converted_to_policy": false
    }
  ]
}
```

- `converted_to_policy`: whether this decision has been promoted to a `quality_policy` rule
