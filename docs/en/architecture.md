# Archon System Architecture

🇰🇷 [한국어](../ko/architecture.md)

> Version: 1.1.0 | Last updated: 2026-04-23

## Overview

Archon is a multi-agent AI development platform built around a 7-layer architecture. It uses the Claude API as the master orchestrator and open-source LLMs as specialized agents, enabling a solo developer to achieve team-level productivity.

## Core Design Principles

| Principle | Description |
|---|---|
| P1. Agents are stateless | No project affinity — `project_context` is injected per task |
| P2. Structure is open, soul is private | Schema/design is open-source; prompts/SOPs stay private |
| P3. Scale-out without code changes | Ray-based — linear scaling by adding nodes |
| P4. Work never stops | Only the affected project pauses on Human Gate trigger |
| P5. Models are always swappable | Role-based model YAML swap via LiteLLM Proxy |
| P6. High-risk areas always get human eyes | Dynamic Guardrails — payment/auth/infra auto-escalate to L2 |

## 7-Layer Structure

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
  LiteLLM Proxy (localhost:4000)
          │
          ▼
Layer 4 — Specialized Agent Pool
  src/agents/base.py           — BaseAgent (streaming, A2A, structured output)
  src/agents/{backend,frontend,tester,devops,docs}.py
  (stateless · context injected · shared pool)
          │
          ▼
Layer 5 — QA Pipeline + Human Gate
  src/pipeline/qa.py           — parallel lint/build/test/security
  src/pipeline/git_executor.py — auto-commit, protected_paths validation
  src/gate/evaluator.py        — 5-level gate decision
  src/notifications/           — Slack · Terminal notifications
          │
          ▼
Layer 6 — Shared Memory & Context Store
  src/memory/context_injector.py   — 3-layer facade (MemoryStore)
  src/memory/redis_scratchpad.py   — L1: Redis (TTL 24h)
  src/memory/vector_store.py       — L2: ChromaDB vector search
  src/memory/mem0_store.py         — L3: Mem0 cross-project patterns
  src/memory/compressor.py         — large handoff compression
          │
          ▼
Layer 7 — LLM Runtime
  src/runtime/vllm_bridge.py  — vLLM endpoint management
  src/runtime/cluster.py      — Ray cluster
  MLX (Apple Silicon) · Ollama · vLLM · Claude API
```

## Module Details

### Orchestrator (`src/orchestrator/`)

`orchestrator.py` — drives the entire pipeline.

- **6-agent pool**: `backend`, `frontend`, `tester`, `devops`, `docs`, `reviewer`
- **Task Chain**: sequential execution after agent completion. Defaults:
  - `backend` → tester → docs
  - `frontend` → tester → docs
  - `devops` → tester
- **`process_chain()`**: runs the chain sequentially, returning each handoff
- **Notifications**: sends gate events to Slack/Terminal via `CompositeNotifier`

`handoff.py` — inter-agent context transfer standard.

7-section Pydantic model: `Envelope` · `ProjectContext` · `Task` · `Artifacts` · `QualityGates` · `HumanGatePackage` · `MemoryContext`

---

### BaseAgent (`src/agents/base.py`)

Common base class for all agents.

- **Stateless**: agent instances remember nothing. Context is injected via `HandoffArtifact` per task.
- **3 execution modes**:
  - `execute()` — standard synchronous LLM call
  - `execute_streaming()` — chunk-by-chunk streaming (`AsyncIterator[str]`)
  - `execute_with_streaming()` — uses streaming if `AgentModelConfig.streaming` is True, falls back otherwise
- **Auto-compression**: `compress_handoff()` on token overflow
- **Structured output**: parses `changed_files`, `decisions`, etc. from `<archon-output>JSON</archon-output>` tags
- **A2A messaging**: `send_a2a()`, `receive_a2a()` for direct inter-agent communication

---

### Human Gate (`src/gate/`)

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

Measures task complexity to dynamically select LLM models.

**8 scoring criteria**:
1. Instruction length (≥500 chars → +2)
2. Changed file count (≥5 files → +2)
3. Past decision count (≥3 → +1)
4. Blocker presence (+2)
5. External integration flag (`has_external_integration` → +2)
6. Schema change flag (`has_schema_change` → +2)
7. High priority (priority ≥ 8 → +1)
8. Prior L2+ gate history (`gate_decision` L2/L3/L4 → +2)

**Level thresholds**: LOW (0–3) / MEDIUM (4–6) / HIGH (7+)

`select_model_by_complexity()` returns `AgentModelConfig.high_complexity_model` for HIGH tasks.

---

### 3-Layer Memory (`src/memory/`)

| Class | Layer | Backend | TTL |
|---|---|---|---|
| `RedisScratchpad` | L1 short-term | Redis | 24h (`redis_ttl`) |
| `VectorStore` | L2 mid-term | ChromaDB | unlimited |
| `Mem0Store` | L3 long-term | Mem0 API | unlimited |
| `MemoryStore` | Facade | all layers | — |

`MemoryStore.inject_memory_context()` — queries L2+L3 with task instructions as a search key, assembles a `MemoryContext` for injection into the agent.

Each layer falls back to an in-memory dict if not connected, so the system works without any infrastructure.

---

### Task Scheduler (`src/queue/scheduler.py`)

Dependency-based async task scheduler.

1. `add_task(TaskSpec)` — register a task (task_id, agent_role, depends_on, priority)
2. `topological_sort()` — Kahn's algorithm for execution order; detects cyclic dependencies
3. `run(executor)` — asyncio Semaphore limits concurrency (`concurrency=3` default)

---

### MCP Server (`src/mcp/server.py`)

5 MCP tools for external clients (IDE, CLI) to control Archon.

| Tool | Description |
|---|---|
| `execute_task` | Submit a task to a specific agent |
| `get_status` | Query project/task status |
| `list_agents` | List available agents |
| `get_project` | Get project registry details |
| `list_projects` | List registered projects |

Transport layer (stdio/SSE) wired via MCP SDK in Phase 3.

---

### A2A Messaging (`src/mcp/a2a.py`)

Direct agent-to-agent communication (based on Google A2A protocol).

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

Integrates GPU worker vLLM servers into LiteLLM.

```python
bridge = VLLMBridge()
bridge.register(VLLMEndpoint(
    name="vllm/qwen-27b",
    base_url="http://gpu-node:8000",
    model_name="Qwen/Qwen2.5-27B",
))
await bridge.health_check("vllm/qwen-27b")
config = bridge.get_litellm_config("vllm/qwen-27b")
# → {"model": "openai/Qwen2.5-27B", "api_base": "http://gpu-node:8000/v1", ...}
```

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
| Lightweight agents ×3 (14B Q4) | ~27 GB |
| KV cache + headroom | ~53 GB |

### Phase 2 — Multi-node

MacBook (Ray Head) + PC Worker (GPU). Connect with a single `ray.init(address="auto")`. Register GPU worker endpoints via vLLM Bridge.

### Phase 3 — Cloud Hybrid

KubeRay + on-premises + cloud burst-out. Add nodes without any code changes.

## Related Docs

- [Handoff Artifact Schema](handoff-schema.md)
- [Project Registry Schema](registry-schema.md)
- [Human Gate Design](human-gate.md)
- [Quick Start Guide](quickstart.md)
