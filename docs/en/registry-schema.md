# Project Registry Schema

[한국어](../ko/registry-schema.md)

> Version: 2.0.0 | Last updated: 2026-04-24

## Overview

The Project Registry is the **central configuration store** for each solution project. When you register a project with Archon, this file is created. All behavior -- agents, QA, memory, scheduling -- is determined by these settings.

- File location: `.harness/registry/{project_id}.json`
- Source code: `src/registry/models.py`, `src/registry/store.py`

---

## 8-Section Structure

| Section | Purpose |
|---|---|
| project_meta | Project identity, status, priority, scheduling |
| git_config | Repository, branch strategy, SOP path, protected_paths |
| agent_config | Per-role LLM model assignment (plugin swap layer) |
| quality_policy | QA thresholds, Human Gate criteria, budget, Dynamic Guardrails |
| work_queue | Task queue snapshot, current execution state |
| memory_config | 3-layer memory settings (Redis / ChromaDB / Mem0) |
| metrics | Progress, cost, quality, throughput indicators |
| human_gate_history | Developer decision log, pattern learning source |

---

## Section Details

### project_meta

Basic project information. `status` and `priority` directly affect the Orchestrator's scheduling decisions.

| Field | Type | Default | Description |
|---|---|---|---|
| `project_id` | `str` | (required) | Unique project identifier (e.g., `"proj_ecomm_v2"`) |
| `project_name` | `str` | (required) | Human-readable project name |
| `status` | `str` | `"active"` | Project status: `"active"` \| `"paused"` \| `"completed"` \| `"archived"` |
| `priority` | `int` | `5` | Priority 1-10 (higher = more urgent) |
| `deadline` | `str` (ISO 8601) \| `null` | `null` | Deadline. When set, affects scheduling |
| `owner` | `str` | (required) | Developer identifier responsible for the project |
| `description` | `str` | `""` | Project description |
| `tags` | `list[str]` | `[]` | Tags for search and classification |

**When to use:** Set when initially registering a project. Changing `status` to `"paused"` suspends all agent execution for that project.

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

---

### git_config

Configures the Git repository, branch strategy, SOP path, and protected paths.

| Field | Type | Default | Description |
|---|---|---|---|
| `repo_url` | `str` | (required) | Git repository URL |
| `main_branch` | `str` | `"main"` | Main branch name |
| `agent_branch_prefix` | `str` | `"agent/"` | Agent working branch prefix (e.g., `agent/backend/hf_a3b4`) |
| `auto_commit_message_template` | `str` | `"feat({agent}): {summary} [task:{task_id}]"` | Auto-commit message template. Supports `{agent}`, `{summary}`, `{task_id}` variables |
| `sop_directory` | `str` | `".harness/sop/"` | SOP file directory path |
| `protected_paths` | `list[str]` | `[]` | Paths agents can never modify. Violations raise `ProtectedPathError` |

**When to use:** Set when initially registering a project. Always add sensitive paths like `.env` and `secrets/` to `protected_paths`.

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

---

### agent_config

Specifies the LLM model and parameters per role. Each agent role (orchestrator, reviewer, backend, etc.) can be individually configured.

| Field | Type | Default | Description |
|---|---|---|---|
| `model` | `str` | (required) | Base LLM model (e.g., `"claude-opus-4-6"`, `"ollama/deepseek-v3.2:70b"`) |
| `max_tokens` | `int` | `4096` | Maximum generation tokens |
| `temperature` | `float` | `0.2` | Generation temperature. Lower values produce more deterministic output |
| `model_override` | `str` \| `null` | `null` | When set, takes precedence over `model`. Useful for temporarily testing a different model |
| `streaming` | `bool` | `false` | Enable streaming output. When `true`, agent responses are received in real time |
| `timeout_seconds` | `int` | `300` | Agent execution timeout in seconds. Execution is aborted if this time is exceeded |
| `high_complexity_model` | `str` \| `null` | `null` | Model to use when the Complexity Router scores HIGH. When null, the base `model` is used |
| `reviewer_guidelines_path` | `str` \| `null` | `null` | Path to reviewer guidelines file (used only by the reviewer role) |
| `context_window_tokens` | `int` \| `null` | `null` | Model context window (tokens). When null, estimated as `max_tokens × 3` |
| `prompt_overlay_path` | `str` \| `null` | `null` | Path to a private prompt overlay file |
| `multi_provider_mode` | `str` | `"single"` | Multi-Provider mode. `"single"` \| `"shadow"` \| `"consensus"` \| `"strict"` |
| `review_models` | `list[str]` | `[]` | Models used for Multi-Provider review (e.g., `["gpt-4o", "gemini-2.0-flash"]`) |
| `consensus_strategy` | `str` | `"majority"` | Consensus strategy. `"majority"` \| `"unanimous"` \| `"strictest"` |
| `score_divergence_threshold` | `float` | `20.0` | Score variance threshold. Values above this are treated as consensus failure |

**Multi-Provider modes:**
- **single**: Traditional single-model review (default)
- **shadow**: Uses primary reviewer result; additional models run in background for comparison logging only
- **consensus**: Sends the same review to all `review_models` and resolves via consensus strategy
- **strict**: Same as consensus, but escalates to L2_HUMAN when consensus is not reached

**When to use:**
- **streaming**: Set to `true` when you want to monitor progress in real time during long code generation tasks.
- **timeout_seconds**: Complex tasks (e.g., large-scale refactoring) may need more than the default 300 seconds. Set to 600+ for such agents.
- **high_complexity_model**: Useful for cost optimization. Use a smaller model for routine tasks and a larger model only for complex ones.

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
    "timeout_seconds": 300,
    "reviewer_guidelines_path": ".harness/guidelines/review.md",
    "multi_provider_mode": "consensus",
    "review_models": ["claude-sonnet-4-6", "gpt-4o", "gemini-2.0-flash"],
    "consensus_strategy": "majority",
    "score_divergence_threshold": 20.0
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

---

### quality_policy

QA thresholds, Human Gate criteria, token budget, and Dynamic Guardrails configuration. These settings are used directly by `evaluate_gate()` to determine gate decisions.

| Field | Type | Default | Description |
|---|---|---|---|
| `coverage_threshold` | `int` | `80` | Test coverage target (%). Below this triggers L1 rework |
| `review_score_threshold` | `int` | `70` | Minimum Review Agent score. Below this triggers L1 rework |
| `max_retry_before_escalation` | `int` | `3` | Maximum L1 retries. Exceeding this escalates to L2 |
| `security_block_level` | `str` | `"critical"` | Security vulnerabilities at or above this level trigger L3 halt. `"critical"` \| `"high"` \| `"medium"` |
| `require_human_on_schema_change` | `bool` | `true` | Auto-trigger L2 Human Gate on DB schema changes |
| `require_human_on_external_integration` | `bool` | `true` | Auto-trigger L2 Human Gate when external API integrations are detected |
| `daily_token_budget` | `int` | `500` | Daily token budget (in thousands). Exceeding triggers a warning |
| `sop_compliance_threshold` | `int` | `70` | Minimum SOP compliance score (0-100). Below this triggers L2 Human Gate. Skipped when no SOP file exists |
| `high_risk_paths` | `list[str]` | `[]` | File path patterns that auto-trigger L2 Human Gate when modified |
| `high_risk_keywords` | `list[str]` | `[]` | Task instruction keywords that auto-trigger L2 Human Gate |

**When to use:**
- **sop_compliance_threshold**: If your team enforces SOPs strictly, raise this to 80-90. If you don't use SOPs, this field is ignored.
- **high_risk_paths**: Register sensitive code paths like payment, auth, and infrastructure. When an agent modifies files in these paths, developer review is automatically required.
- **high_risk_keywords**: Register keywords like `"payment"`, `"delete_all"`, `"production"`. When a task contains these keywords, L2 gate is automatically triggered.

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

---

### work_queue

Snapshot of active tasks, the pending queue, and blocked tasks. Managed automatically by the Orchestrator.

| Field | Type | Default | Description |
|---|---|---|---|
| `current_task` | `CurrentTask` \| `null` | `null` | Currently executing task |
| `current_task.task_id` | `str` | (required) | Task identifier |
| `current_task.agent` | `str` | (required) | Agent role currently executing |
| `current_task.started_at` | `str` (ISO 8601) | (required) | Execution start time |
| `current_task.priority` | `int` | (required) | Task priority |
| `pending_tasks` | `list[PendingTask]` | `[]` | List of pending tasks |
| `blocked_tasks` | `list[BlockedTask]` | `[]` | List of blocked tasks |
| `active_agents` | `dict[str, AgentStatus]` | `{}` | Per-agent status (`"running"` \| `"waiting"` \| `"paused"`) |
| `overall_progress` | `int` | `0` | Overall progress percentage (0-100) |

**When to use:** You generally don't need to modify this directly. The Orchestrator manages it automatically. Use it as a reference for monitoring dashboards to check real-time status.

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

Connection settings for the 3-layer memory system. Each layer is optional; missing layers fall back to in-memory storage.

| Field | Type | Default | Description |
|---|---|---|---|
| `vector_collection_id` | `str` | (auto-generated) | Vector DB collection ID |
| `scratchpad_key` | `str` | (auto-generated) | Redis scratchpad key prefix |
| `retain_handoff_count` | `int` | `100` | Number of recent handoffs to retain |
| `auto_learn_patterns` | `bool` | `true` | Automatically learn success patterns |
| `cross_project_memory_enabled` | `bool` | `false` | Allow referencing patterns from other projects |
| `redis_url` | `str` | `"redis://localhost:6379/0"` | L1 Redis connection URL |
| `redis_ttl` | `int` | `86400` | L1 scratchpad TTL in seconds (default 24h) |
| `chroma_host` | `str` \| `null` | `null` | L2 ChromaDB server host. null means local/in-memory |
| `chroma_port` | `int` | `8000` | L2 ChromaDB server port |
| `chroma_collection` | `str` | `"archon"` | L2 ChromaDB collection name |
| `mem0_api_key` | `str` \| `null` | `null` | L3 Mem0 API key. null disables L3 |

**3-layer memory overview:**

| Layer | Implementation | TTL | Scope | Purpose |
|---|---|---|---|---|
| L1 short-term | Redis scratchpad | 24h | Per-task | Temporary data for the current task |
| L2 mid-term | ChromaDB vector search | unlimited | Per-project | Search similar decisions/patterns within a project |
| L3 long-term | Mem0 pattern learning | unlimited | Cross-project | Learn and reference patterns across all projects |

**When to use:**
- **Minimal setup**: Just connecting Redis is enough for basic operation. ChromaDB and Mem0 can be added incrementally.
- **chroma_host**: If your team runs a ChromaDB server, specify the host. When null, it operates in-memory and data is lost when the process exits.
- **mem0_api_key**: Using Mem0 cloud enables cross-project pattern learning. Handle with care for security.

```json
{
  "vector_collection_id": "mem_proj_ecomm_v2",
  "scratchpad_key": "scratch:proj_ecomm_v2:",
  "retain_handoff_count": 100,
  "auto_learn_patterns": true,
  "cross_project_memory_enabled": false,
  "redis_url": "redis://localhost:6379/0",
  "redis_ttl": 86400,
  "chroma_host": null,
  "chroma_port": 8000,
  "chroma_collection": "archon",
  "mem0_api_key": null
}
```

---

### metrics

Project-level metrics. Automatically updated by the Orchestrator.

| Field | Type | Default | Description |
|---|---|---|---|
| `total_tokens_used` | `int` | `0` | Cumulative tokens used |
| `estimated_cost_usd` | `float` | `0.0` | Estimated cost in USD |
| `auto_commit_count` | `int` | `0` | Number of auto-commits (auto_pass) |
| `human_gate_count` | `int` | `0` | Number of Human Gate triggers |
| `l3_halt_count` | `int` | `0` | Number of L3 halts |
| `average_review_score` | `float` | `0.0` | Average Review Agent score |
| `agent_utilization` | `dict[str, float]` | `{}` | Per-agent utilization rate (0.0 to 1.0) |

**When to use:** You don't need to modify this directly. Use it to check project progress, cost, and quality trends on your dashboard.

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

Log of developer decisions. Fed into Mem0 to automatically reference similar situations in the future.

| Field | Type | Default | Description |
|---|---|---|---|
| `entries` | `list[GateEntry]` | `[]` | List of decision entries |
| `entries[].handoff_id` | `str` | (required) | Associated handoff ID |
| `entries[].gate_level` | `str` | (required) | Triggered gate level |
| `entries[].trigger` | `str` | (required) | Trigger cause |
| `entries[].decision` | `str` | (required) | Developer's decision |
| `entries[].rationale` | `str` | (required) | Reasoning behind the decision |
| `entries[].response_time_minutes` | `int` | (required) | Time to respond in minutes |
| `entries[].converted_to_policy` | `bool` | `false` | Whether this decision has been promoted to a quality_policy rule |

**When to use:** You don't need to modify this directly. It is automatically populated when a developer makes a decision at a Human Gate. When `converted_to_policy` is `true`, the decision has been promoted to a quality_policy rule.

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

---

## Related Configs

The following configurations are not part of the Project Registry itself, but are independent config files that configure Archon's extension features. Use them as needed.

### TracingConfig

LLM call tracing and observability settings. Essential for debugging and cost analysis.

| Field | Type | Default | Description |
|---|---|---|---|
| `backend` | `str` | `"none"` | Tracing backend: `"none"` \| `"langsmith"` \| `"langfuse"` \| `"aitop"` |
| `langsmith_api_key` | `str` \| `null` | `null` | LangSmith API key |
| `langsmith_project` | `str` \| `null` | `null` | LangSmith project name |
| `langfuse_public_key` | `str` \| `null` | `null` | Langfuse public key |
| `langfuse_secret_key` | `str` \| `null` | `null` | Langfuse secret key |
| `langfuse_host` | `str` | `"https://cloud.langfuse.com"` | Langfuse server URL |
| `aitop_endpoint` | `str` \| `null` | `null` | AITop endpoint URL |
| `aitop_api_key` | `str` \| `null` | `null` | AITop API key |

**When to use:** Set this up when you want to trace agent LLM calls. Strongly recommended to enable in production environments.

```json
{
  "backend": "langsmith",
  "langsmith_api_key": "ls-your-api-key",
  "langsmith_project": "archon-ecomm-v2",
  "langfuse_public_key": null,
  "langfuse_secret_key": null,
  "langfuse_host": "https://cloud.langfuse.com",
  "aitop_endpoint": null,
  "aitop_api_key": null
}
```

---

### EvolutionConfig

Agent self-evolution settings. Analyzes past handoff data to automatically improve SOPs and prompts.

| Field | Type | Default | Description |
|---|---|---|---|
| `enabled` | `bool` | `false` | Enable self-evolution |
| `analysis_window` | `int` | `50` | Number of recent handoffs to analyze |
| `auto_apply_threshold` | `float` | `0.85` | Automatically apply improvements above this confidence level (0.0 to 1.0) |

**When to use:** Enable when your project is mature enough and has accumulated 50+ handoff records. Setting `auto_apply_threshold` higher makes it more conservative.

```json
{
  "enabled": true,
  "analysis_window": 50,
  "auto_apply_threshold": 0.85
}
```

---

### HybridConfig

Hybrid LLM routing settings. Combines multiple LLM providers to optimize cost and performance.

| Field | Type | Default | Description |
|---|---|---|---|
| `strategy` | `str` | `"cost_optimized"` | Routing strategy: `"cost_optimized"` \| `"quality_first"` \| `"latency_first"` |
| `budget` | `float` | `10.0` | Daily budget in USD |
| `providers` | `list[str]` | `["anthropic"]` | Available provider list (e.g., `["anthropic", "openai", "ollama"]`) |

**When to use:** Set this up when you want to reduce costs by using multiple LLM providers. The routing behavior varies by `strategy`.

```json
{
  "strategy": "cost_optimized",
  "budget": 10.0,
  "providers": ["anthropic", "openai", "ollama"]
}
```

---

### KubeRayConfig

KubeRay-based distributed execution settings. Used for running agents in parallel on a Kubernetes cluster for large-scale projects.

| Field | Type | Default | Description |
|---|---|---|---|
| `namespace` | `str` | `"archon"` | Kubernetes namespace |
| `cluster_name` | `str` | `"archon-ray"` | Ray cluster name |
| `worker_groups` | `list[WorkerGroup]` | `[]` | Worker group configurations |
| `worker_groups[].name` | `str` | (required) | Worker group name |
| `worker_groups[].replicas` | `int` | `1` | Number of worker instances |
| `worker_groups[].resources` | `object` | `{}` | CPU/memory resource limits |

**When to use:** Use for large-scale projects where local execution doesn't provide enough throughput. Requires Kubernetes and Ray to be already installed.

```json
{
  "namespace": "archon",
  "cluster_name": "archon-ray",
  "worker_groups": [
    {
      "name": "agent-workers",
      "replicas": 4,
      "resources": {
        "cpu": "2",
        "memory": "4Gi"
      }
    },
    {
      "name": "review-workers",
      "replicas": 2,
      "resources": {
        "cpu": "1",
        "memory": "2Gi"
      }
    }
  ]
}
```

---

### GuardrailPolicy

Agent input/output guardrail settings. Prevents budget overruns, risky path access, and malicious inputs.

| Field | Type | Default | Description |
|---|---|---|---|
| `input_max_tokens` | `int` | `32000` | Maximum tokens in agent input |
| `output_max_tokens` | `int` | `16000` | Maximum tokens in agent output |
| `budget_hard_limit_usd` | `float` | `50.0` | Daily hard budget limit in USD. Exceeding this halts all agent execution |
| `blocked_paths` | `list[str]` | `[]` | Paths agents cannot even read |
| `allowed_domains` | `list[str]` | `[]` | Whitelist of external domains agents can access. Empty means all domains allowed |

**When to use:** Set this up when you want to restrict agent behavior in production. `budget_hard_limit_usd` prevents unexpected cost spikes.

```json
{
  "input_max_tokens": 32000,
  "output_max_tokens": 16000,
  "budget_hard_limit_usd": 50.0,
  "blocked_paths": [".git/", "node_modules/", ".env"],
  "allowed_domains": ["api.stripe.com", "api.github.com"]
}
```

---

### HealingConfig

Self-healing settings. Automatically switches to a fallback model or substitute role when agent execution fails.

| Field | Type | Default | Description |
|---|---|---|---|
| `fallback_model` | `str` \| `null` | `null` | Fallback model when the primary model fails. null means no fallback |
| `substitute_role` | `str` \| `null` | `null` | Substitute role when the assigned agent role fails. null means no substitution |

**When to use:** Set this up when you want to guard against outages from specific LLM providers. For example, if the Anthropic API goes down, it can automatically switch to OpenAI.

```json
{
  "fallback_model": "gpt-4o",
  "substitute_role": "general"
}
```
