# Archon System Architecture

🇰🇷 [한국어](../ko/architecture.md)

> Version: 2.0.0 | Last updated: 2026-04-24

## Overview

Archon is a multi-agent AI development platform built around a **7-layer architecture**. It uses the Claude API as the master orchestrator and open-source LLMs as specialized agents, enabling a solo developer to achieve team-level productivity.

This document explains the complete architecture of Archon. It focuses on what each layer does and why it was designed that way, so even newcomers can understand the overall flow.

## Core Design Principles

| Principle | Description |
|---|---|
| P1. Agents are stateless | No project affinity — `project_context` is injected per task. |
| P2. Structure is open, soul is private | Schema and design are open-source; prompts and SOPs stay private. |
| P3. Scale-out without code changes | Ray-based — linear scaling by simply adding nodes. |
| P4. Work never stops | Only the affected project pauses on Human Gate trigger; others continue. |
| P5. Models are always swappable | Role-based model YAML swap via LiteLLM Proxy. |
| P6. High-risk areas always get human eyes | Dynamic Guardrails auto-escalate payment/auth/infra changes to L2. |
| P7. Everything is traced | Observability tracing records every LLM call, cost, and latency. |
| P8. The system evolves itself | Evolution Loop monitors quality metrics and auto-tunes thresholds. |

## 7-Layer Structure

The diagram below shows Archon's complete data flow. A developer's request starts at the top (Layer 0) and flows through each layer for processing.

```
Layer 0 — Human in the Loop
  Developer: ideas · design review · real-world testing · final approval
          │
          │ Human Gate (bidirectional)
          ▼
Layer 1 — Orchestrator (Claude API)
  src/orchestrator/orchestrator.py
  Master architect · code reviewer · Human Gate manager
  Models: Claude Opus 4.6 (design) / Claude Sonnet 4.6 (review)
          │
          │ MCP / A2A Protocol
          ▼
Layer 2 — Protocol Bus
  src/mcp/server.py    — MCP 5 tools
  src/mcp/a2a.py       — A2A mailbox routing
  src/orchestrator/handoff.py  — Handoff Artifact JSON
          │
          │ Task Queue
          ▼
Layer 3 — LLM Selector / Router
  src/router/complexity.py     — 8-criteria complexity scoring, dynamic routing
  src/router/role_router.py    — vLLM → Ollama → default routing chain
  LiteLLM Proxy (localhost:4000)
          │
          ▼
Layer 4 — Specialized Agent Pool
  src/agents/base.py           — BaseAgent (streaming, A2A, structured output)
  src/agents/{backend,frontend,tester,devops,docs}.py
  src/guardrails/              — I/O validation, token budget, path protection
  BaseAgent: self-correction, structured output parsing
  (stateless · context injected · shared pool)
          │
          ▼
Layer 5 — QA Pipeline + Human Gate
  src/runtime/qa.py            — parallel lint/build/test/security
  src/runtime/git_executor.py  — auto-commit + transaction snapshot/rollback
  src/gate/evaluator.py        — 5-level gate decision
  src/notifications/           — Slack · Terminal notifications
          │
          ▼
Layer 6 — Shared Memory & Context Store
  src/memory/context_injector.py   — 3-layer facade (MemoryStore)
  src/memory/redis_scratchpad.py   — L1: Redis (TTL 24h)
  src/memory/vector_store.py       — L2: ChromaDB vector search
  src/memory/mem0_store.py         — L3: Mem0 cross-project patterns
  src/memory/compressor.py         — large handoff compression + token_gap precision
          │
          ▼
Layer 7 — LLM Runtime
  src/runtime/vllm_bridge.py   — vLLM endpoint management
  src/runtime/ollama_bridge.py — Ollama local LLM integration
  src/runtime/cluster.py       — Ray cluster
  src/runtime/kuberay.py       — KubeRay CRD management
  src/runtime/hybrid.py        — cloud hybrid scheduling
  MLX (Apple Silicon) · Ollama · vLLM · Claude API
```

---

## Module Details

### Orchestrator (`src/orchestrator/`)

The orchestrator is Archon's brain. It receives developer requests, decides which agents should handle them and in what order, and verifies the quality of results.

`orchestrator.py` — drives the entire pipeline.

- **6-agent pool**: `backend`, `frontend`, `tester`, `devops`, `docs`, `reviewer`
- **Task Chain**: sequential execution after agent completion. Defaults:
  - `backend` → tester → docs
  - `frontend` → tester → docs
  - `devops` → tester
- **`process_chain()`**: runs the chain sequentially, returning each handoff.
- **Notifications**: sends gate events to Slack/Terminal via `CompositeNotifier`.

`handoff.py` — the inter-agent context transfer standard.

7-section Pydantic model: `Envelope` · `ProjectContext` · `Task` · `Artifacts` · `QualityGates` · `HumanGatePackage` · `MemoryContext`

---

### BaseAgent (`src/agents/base.py`)

BaseAgent is the common base class that every specialized agent inherits from. It consolidates shared functionality (LLM calls, context management, communication) in one place to eliminate duplication.

**Core features:**

- **Stateless**: agent instances remember nothing. Context is injected via `HandoffArtifact` per task.
- **3 execution modes**:
  - `execute()` — standard synchronous LLM call
  - `execute_streaming()` — chunk-by-chunk streaming (`AsyncIterator[str]`)
  - `execute_with_streaming()` — uses streaming if `AgentModelConfig.streaming` is True, falls back otherwise
- **Auto-compression**: `compress_handoff()` on token overflow.
- **Structured output**: parses `changed_files`, `decisions`, etc. from `<archon-output>JSON</archon-output>` tags.
- **A2A messaging**: `send_a2a()`, `receive_a2a()` for direct inter-agent communication.

**Added in Phase 3:**

- **Self-correction**: When JSON parsing fails on an LLM response, the agent retries once with a correction prompt. This significantly improves structured output success rates without risking infinite loops.

  ```python
  # Conceptual flow inside BaseAgent
  result = await self.call_llm(prompt)
  parsed = try_parse_structured(result)
  if parsed is None:
      # Retry once with correction prompt
      result = await self.call_llm(correction_prompt + result)
      parsed = try_parse_structured(result)
  ```

- **Guardrails integration**: Every `execute()` call automatically applies input/output validation, token budget deduction, and path protection.
- **Tracing integration**: `TracingMiddleware` automatically records latency, token count, and cost for every LLM call.
- **Health monitoring**: `AgentHealthMonitor` tracks agent state and triggers self-healing on anomalies.

---

### Human Gate (`src/gate/`)

The Human Gate implements the principle that "dangerous operations must always be reviewed by a human." The AI operates autonomously, but high-risk actions require developer approval.

`evaluate_gate()` in `evaluator.py` decides the 5-level outcome.

**Decision order** (highest priority first):

1. `L4_DEPLOY` — if `is_deploy_request=True`, unconditionally
2. `L3_HALT` — build failure, Critical/High security vulnerabilities
3. `L2_HUMAN` — review_score below threshold, schema/external integration, retries exhausted
4. `L2_HUMAN` (Dynamic Guardrails) — high-risk path/keyword detected
5. `L2_HUMAN` (SOP) — SOP compliance score below threshold
6. `L1_REWORK` — lint failure, borderline coverage, few unit test failures
7. `AUTO_PASS` — all checks passed

Full details: [human-gate.md](human-gate.md)

---

### Complexity Router (`src/router/complexity.py`)

Measures task complexity to dynamically select LLM models. This prevents wasting expensive models on simple tasks while ensuring complex tasks get high-performance models.

**8 scoring criteria**:
1. Instruction length (>=500 chars -> +2)
2. Changed file count (>=5 files -> +2)
3. Past decision count (>=3 -> +1)
4. Blocker presence (+2)
5. External integration flag (`has_external_integration` -> +2)
6. Schema change flag (`has_schema_change` -> +2)
7. High priority (priority >= 8 -> +1)
8. Prior L2+ gate history (`gate_decision` L2/L3/L4 -> +2)

**Level thresholds**: LOW (0-3) / MEDIUM (4-6) / HIGH (7+)

`select_model_by_complexity()` returns `AgentModelConfig.high_complexity_model` for HIGH tasks.

---

### Role Router (`src/router/role_router.py`)

Manages the per-role model routing chain. When multiple LLM backends are available, it determines which order to try them in — a **priority fallback chain**.

**Routing priority**:
1. **vLLM** — Models running on GPU workers are tried first.
2. **Ollama** — If vLLM is unavailable, try the local Ollama instance.
3. **default** — If neither works, fall back to the default model defined in YAML (via LiteLLM Proxy).

This ensures a working model is always selected regardless of infrastructure status.

---

### 3-Layer Memory (`src/memory/`)

Agents are stateless, but the system as a whole remembers. The 3-layer memory system manages short-term, mid-term, and long-term memory.

| Class | Layer | Backend | TTL | Purpose |
|---|---|---|---|---|
| `RedisScratchpad` | L1 short-term | Redis | 24h | Temporary data for the current task |
| `VectorStore` | L2 mid-term | ChromaDB | unlimited | Search similar past experiences within a project |
| `Mem0Store` | L3 long-term | Mem0 API | unlimited | Cross-project patterns |
| `MemoryStore` | Facade | all layers | — | Unified interface |

`MemoryStore.inject_memory_context()` — queries L2+L3 with task instructions as a search key, assembles a `MemoryContext` for injection into the agent.

Each layer falls back to an in-memory dict if not connected, so the system works without any infrastructure.

**Compressor (`src/memory/compressor.py`)**

Compresses large handoff artifacts. Phase 3 added **token_gap precision targeting**: when an API returns a "prompt too long" error, the compressor parses the exact token overage from the error message and compresses only what is necessary. This minimizes information loss compared to blanket compression.

---

### Task Scheduler (`src/queue/scheduler.py`)

A dependency-based async task scheduler. It defines ordering constraints between tasks and runs independent tasks concurrently.

1. `add_task(TaskSpec)` — register a task (task_id, agent_role, depends_on, priority)
2. `topological_sort()` — Kahn's algorithm for execution order; detects cyclic dependencies
3. `run(executor)` — asyncio Semaphore limits concurrency (`concurrency=3` default)

---

### MCP Server (`src/mcp/server.py`)

Provides 5 MCP tools for external clients (IDE, CLI) to control Archon.

| Tool | Description |
|---|---|
| `execute_task` | Submit a task to a specific agent |
| `get_status` | Query project/task status |
| `list_agents` | List available agents |
| `get_project` | Get project registry details |
| `list_projects` | List registered projects |

---

### A2A Messaging (`src/mcp/a2a.py`)

Enables direct agent-to-agent communication (based on Google A2A protocol). Used when agents need to exchange information without going through the orchestrator.

- `A2ARouter.send(message)` — places a message in the recipient agent's mailbox
- `A2ARouter.receive(agent_role)` — pulls messages from own mailbox
- `BaseAgent.send_a2a()`, `receive_a2a()` — agent-level interface
- Message types: `REQUEST`, `RESPONSE`, `BROADCAST`, `NOTIFY`
- Priorities: `LOW`, `NORMAL`, `HIGH`, `URGENT`

---

### Notifications (`src/notifications/`)

Sends developer alerts when a Gate event fires.

- `GateEvent` — notification payload model (project_id, task_id, gate_decision, trigger_reason, severity)
- `TerminalNotifier` — rich TUI + macOS `osascript` desktop notifications
- `SlackNotifier` — Slack incoming webhook
- `CompositeNotifier` — fan-out to multiple notifiers (True if any succeeds)

AUTO_PASS events are suppressed by default (`Notifier.should_notify()`).

---

### vLLM Bridge (`src/runtime/vllm_bridge.py`)

Integrates GPU worker vLLM servers into LiteLLM. This lets you use large models running on remote GPUs as if they were local.

```python
bridge = VLLMBridge()
bridge.register(VLLMEndpoint(
    name="vllm/qwen-27b",
    base_url="http://gpu-node:8000",
    model_name="Qwen/Qwen2.5-27B",
))
await bridge.health_check("vllm/qwen-27b")
config = bridge.get_litellm_config("vllm/qwen-27b")
# -> {"model": "openai/Qwen2.5-27B", "api_base": "http://gpu-node:8000/v1", ...}
```

---

## Phase 3 New Modules

The following modules were added in Phase 3. They are the core features that elevate Archon's autonomy, safety, and observability to the next level.

### Observability (`src/observability/`)

**Why does this exist?** LLM-based systems are non-deterministic — the same input can produce different outputs. When problems occur, you need to trace "which model, with what prompt, how long it took, and how much it cost" to enable debugging and optimization.

**Components:**

| Class | Role |
|---|---|
| `ArchonTracer` (ABC) | Abstract tracing interface |
| `NoOpTracer` | Used when tracing is disabled (default) |
| `CompositeTracer` | Sends to multiple backends simultaneously |
| `SamplingTracer` | Records only a fraction of traces based on sampling rate (cost saving) |

**Supported backends:**
- **LangSmith** — LangChain ecosystem tracing
- **Langfuse** — Open-source LLM observability
- **AITOP** — Custom backend via OTLP/HTTP protocol

**How it works:**

`TracingMiddleware` hooks into `BaseAgent.execute()` and `Orchestrator.process_handoff()` automatically. No code changes needed — just enable it via `TracingConfig`:

```yaml
# Enable tracing via config
tracing:
  enabled: true
  backends: ["langfuse"]
  sampling_rate: 0.5  # Record 50% of traces
```

---

### Benchmark (`src/benchmark/`)

**Why does this exist?** New LLM models are constantly being released and updated. You need objective comparisons to determine which model is best for each role, so you can maintain optimal model assignments.

**Components:**

| Class | Role |
|---|---|
| `BenchmarkRunner` | Runs identical tasks across multiple models in parallel via litellm |
| `BenchmarkScorer` | Converts accuracy / latency / cost into weighted scores |
| `ModelRecommender` | Recommends the best model per role and auto-updates ProjectRegistry |

**Flow:**
1. `BenchmarkRunner` executes models against a standardized test set.
2. `BenchmarkScorer` combines accuracy, response time, and cost into a composite score.
3. `ModelRecommender` selects the optimal model for each role (backend, tester, etc.) and automatically updates the project configuration.

---

### Evolution (`src/evolution/`)

**Why does this exist?** As a project progresses, the codebase characteristics change. Quality thresholds set early on (coverage targets, complexity scores, etc.) may no longer be appropriate later. The Evolution Loop lets the system learn and adapt on its own.

**Components:**

| Class | Role |
|---|---|
| `MetricsCollector` | Gathers quality metrics from completed tasks |
| `PatternAnalyzer` | Identifies patterns and trends in collected metrics |
| `ThresholdTuner` | Auto-adjusts thresholds based on analysis |
| `EvolutionLoop` | Runs the above steps continuously as an asyncio background loop |

**How it works:**

```
MetricsCollector → PatternAnalyzer → ThresholdTuner → (repeat)
```

Runs as a background asyncio loop. Whenever thresholds change, it fires the `on_policy_updated` callback to persist the changes.

---

### Dashboard (`src/dashboard/`)

**Why does this exist?** Terminal logs alone make it hard to grasp overall system state. The web dashboard lets you see projects, agents, costs, and pending Human Gate requests at a glance.

**Components:**

- **FastAPI REST API** — 10 endpoints
- **WebSocket** — real-time event streaming
- **SPA frontend** — `index.html` + `dashboard.js`

**Key views:**

| View | Content |
|---|---|
| Projects | Per-project progress and recent tasks |
| Agents | Agent pool status (HEALTHY/DEGRADED, etc.) |
| Cost | Cost tracking by model and time period |
| Gate Queue | Pending Human Gate approval requests |
| Metrics | Quality metric trends and Evolution Loop tuning history |

---

### Guardrails (`src/guardrails/`)

**Why does this exist?** In a system where AI agents modify code, safety mechanisms are essential. You need to prevent sensitive data leaks, prompt injection, dangerous code execution, and cost overruns before they happen.

**Components:**

| Class | Role |
|---|---|
| `InputValidator` | Detects sensitive data, defends against prompt injection, enforces token limits, checks banned keywords |
| `OutputValidator` | Catches dangerous code patterns, security vulnerabilities, hallucination hints |
| `TokenBudgetTracker` | Tracks daily/per-agent token usage and prevents budget overruns |
| `PathGuard` | Blocks `protected_paths`, forces Human Gate on config file changes |

**Example usage:**

```python
# InputValidator — prompt injection defense
validator = InputValidator(config)
result = validator.validate(user_input)
if not result.is_safe:
    raise GuardrailViolation(result.reason)

# PathGuard — protected path blocking
guard = PathGuard(protected_paths=[".env", "config/secrets.yaml"])
guard.check(changed_files)  # Forces L2_HUMAN on violation
```

---

### Self-Healing (`src/healing/`)

**Why does this exist?** When an agent fails, it can stall the entire pipeline. Self-Healing automatically detects and recovers from agent failures to maintain system continuity.

**Components:**

| Class | Role |
|---|---|
| `AgentHealthMonitor` | Tracks agent state: HEALTHY -> DEGRADED -> UNHEALTHY -> DEAD |
| `AgentDiagnostician` | Classifies errors (8 types) + estimates root cause |
| `SelfHealer` | Executes recovery strategies: model_downgrade, agent_reinit, substitute, escalate |
| `HealthWatchdog` | asyncio background monitoring loop |

**Recovery strategies (in priority order):**

1. **model_downgrade** — Switch to a more stable model if the current one is failing.
2. **agent_reinit** — Reinitialize the agent and retry.
3. **substitute** — Replace with another agent of the same role.
4. **escalate** — If all automatic recovery fails, escalate to Human Gate (L2_HUMAN).

---

### Ollama Bridge (`src/runtime/ollama_bridge.py`)

**Why does this exist?** Not every developer has GPU workers. Ollama Bridge lets you integrate models running locally via Ollama (e.g., on a MacBook) directly into LiteLLM.

**Components:**

- `OllamaEndpoint` — model_name, base_url, tags configuration
- `health_check()` — Ollama server status check
- Auto model pull — automatically downloads models if not present
- Auto litellm config generation — zero manual configuration needed

Works together with `role_router.py` to form the vLLM -> Ollama -> default fallback chain.

---

### KubeRay (`src/runtime/kuberay.py`)

**Why does this exist?** In production environments, you need to manage Ray clusters on Kubernetes. KubeRay provides programmatic control over KubeRay CRDs (Custom Resource Definitions) to automate infrastructure management.

**Components:**

| Class | Role |
|---|---|
| `KubeRayConfig` | Cluster-wide configuration |
| `WorkerGroupConfig` | Worker group (CPU/GPU node) settings |
| `AutoScaleConfig` | Autoscaling policy |
| `KubeRayManager` | deploy / scale / delete / status operations |

---

### Hybrid Cloud (`src/runtime/hybrid.py`)

**Why does this exist?** When local GPUs are sufficient, there is no need to spend on cloud resources. But when workloads spike, you need to overflow to the cloud. Hybrid Cloud makes this decision automatically.

**Scheduling strategies:**

| Strategy | Description |
|---|---|
| `LOCAL_FIRST` | Prioritizes local GPU resources |
| `COST_OPTIMAL` | Selects the best cost-to-performance option |
| `PERFORMANCE` | Aggressively uses cloud for maximum performance |
| `BALANCED` | Balances cost and performance |

**Components:**

- `GPUResource` — local/cloud GPU resource definitions
- `HybridConfig` — daily/monthly budget limits
- `schedule_task()` — checks local GPU capacity -> overflows to cloud when exceeded

---

### Harness Features (across multiple modules)

Key features added to existing modules in Phase 3.

**GitExecutor Snapshot (`src/runtime/git_executor.py`)**

Transaction-style snapshot/rollback based on git stash. The agent saves a snapshot before modifying code, and can roll back if something goes wrong.

```python
executor = GitExecutor(repo_path)
snapshot_id = await executor.save_snapshot()  # Save current state via git stash
# ... agent modifies code ...
# If something goes wrong:
await executor.rollback_to_snapshot(snapshot_id)  # Restore to original state
```

**Compressor token_gap (`src/memory/compressor.py`)**

When an API returns a "prompt too long" error, the compressor parses the exact token overage from the error message and compresses only what is needed. This minimizes information loss compared to the previous blanket compression approach.

**BaseAgent self-correction (`src/agents/base.py`)**

On JSON parsing failure, retries once with a correction prompt included. This avoids infinite loops while significantly improving parsing success rates.

---

## Agent Role Reference

| Role | Default model | Responsibility |
|---|---|---|
| orchestrator | claude-opus-4-6 | Design, dispatch, review, Human Gate |
| reviewer | claude-sonnet-4-6 | Code review, review_score |
| backend | ollama/deepseek-v3.2:70b | API, DB, business logic |
| frontend | ollama/qwen3.5:32b | UI/UX implementation |
| tester | ollama/gemma4:14b | Test automation, coverage |
| devops | ollama/glm-5:14b | CI/CD, IaC, infrastructure |
| docs | ollama/mimo-v2:7b | Documentation, API specs |

## Hardware Strategy

### Phase 1 — MacBook Solo

All agents run on M5 Max 128 GB.

| Usage | Memory |
|---|---|
| OS + runtime overhead | ~8 GB |
| Coding agent (70B Q4) | ~40 GB |
| Lightweight agents x3 (14B Q4) | ~27 GB |
| KV cache + headroom | ~53 GB |

### Phase 2 — Multi-node

MacBook (Ray Head) + PC Worker (GPU). Connect with a single `ray.init(address="auto")`. Register GPU worker endpoints via vLLM Bridge.

### Phase 3 — Cloud Hybrid

KubeRay + on-premises + cloud burst-out. Add nodes without any code changes. Local and cloud resources are automatically distributed according to the scheduling strategy in `hybrid.py`.

## Related Docs

- [Handoff Artifact Schema](handoff-schema.md)
- [Project Registry Schema](registry-schema.md)
- [Human Gate Design](human-gate.md)
- [Quick Start Guide](quickstart.md)
