# API Reference

[한국어](../ko/api-reference.md)

> Version: 2.0.0 | Last updated: 2026-04-24

## Table of Contents

- [agents — Agents](#agents)
- [gate — Human Gate](#gate)
- [orchestrator — Orchestrator](#orchestrator)
- [router — LLM Router](#router)
- [runtime — Git / vLLM / Ollama / Cluster / KubeRay / Hybrid Cloud](#runtime)
- [memory — 3-Layer Memory](#memory)
- [guardrails — Input/Output Validation & Budget](#guardrails)
- [observability — Tracing & Telemetry](#observability)
- [benchmark — Model Benchmarking](#benchmark)
- [evolution — Self-Tuning Pipeline](#evolution)
- [dashboard — Web Dashboard & WebSocket](#dashboard)
- [healing — Self-Healing & Diagnostics](#healing)
- [notifications — Notifications](#notifications)
- [mcp — MCP / A2A](#mcp)
- [queue — Task Scheduler](#queue)
- [errors — Exceptions](#errors)
- [registry — Registry](#registry)

---

## agents

Source: `src/agents/`

Agents are the core execution units. Each agent receives a `HandoffArtifact`, performs work (code generation, testing, review, etc.), and produces a new `HandoffArtifact` for the next stage. All agents are stateless -- context comes entirely from the handoff.

### BaseAgent

```python
class BaseAgent(abc.ABC):
    role: AgentRole
```

Common base class for all agents. Stateless -- context is injected per task via `HandoffArtifact`.

#### `__init__(role, a2a_router=None)`

| Parameter | Type | Description |
|---|---|---|
| `role` | `AgentRole` | Agent role enum value |
| `a2a_router` | `A2ARouter \| None` | A2A message router (optional) |

#### `execute(handoff, registry) -> HandoffArtifact` `async`

Executes a task and produces the next handoff. Automatically compresses context when token limits are exceeded.

| Parameter | Type | Description |
|---|---|---|
| `handoff` | `HandoffArtifact` | Input handoff containing task and context |
| `registry` | `ProjectRegistry` | Project configuration registry |

**Returns:** A new `HandoffArtifact` with completed work and next instructions.

```python
from src.agents.backend import BackendAgent

agent = BackendAgent()
result = await agent.execute(handoff, registry)
print(result.task.completed_summary)
```

#### `execute_streaming(handoff, registry) -> AsyncIterator[str]` `async`

Streaming execution -- yields text chunks as the LLM generates them. Applies `AgentModelConfig.timeout_seconds` as a deadline.

Use this when you need real-time output display (e.g., terminal UI, dashboard streaming).

```python
async for chunk in agent.execute_streaming(handoff, registry):
    print(chunk, end="", flush=True)
```

#### `execute_with_streaming(handoff, registry, on_chunk=None) -> HandoffArtifact` `async`

Adaptive execution: uses streaming if `AgentModelConfig.streaming` is True, otherwise falls back to `execute()`. The optional `on_chunk` callback receives each text chunk during streaming.

| Parameter | Type | Description |
|---|---|---|
| `handoff` | `HandoffArtifact` | Input handoff |
| `registry` | `ProjectRegistry` | Project registry |
| `on_chunk` | `Callable[[str], None] \| None` | Callback for each streamed chunk |

#### `_self_correct_output(result_text, handoff) -> str` `async`

*Phase 3.* When `_parse_structured_output()` fails, this method sends the malformed output back to the LLM with correction instructions. Retries up to 2 times before raising `AgentParsingError`.

Use case: improves reliability when LLMs occasionally produce invalid JSON in `<archon-output>` blocks.

#### `_build_handoff_from_parsed(parsed, handoff) -> HandoffArtifact`

*Phase 3.* Converts the parsed dict from `_parse_structured_output()` into a proper `HandoffArtifact`. Handles field mapping, default values, and envelope generation.

| Parameter | Type | Description |
|---|---|---|
| `parsed` | `dict` | Parsed structured output dictionary |
| `handoff` | `HandoffArtifact` | Original input handoff (for context copying) |

#### `_extract_structured_fields(result_text) -> dict`

*Phase 3.* Fallback extraction when `<archon-output>` blocks are missing. Attempts to extract summary, changed_files, and decisions from free-form LLM text using pattern matching.

#### `send_a2a(to_agent, subject, body, *, message_type, priority, project_id, task_id) -> bool`

Sends an A2A message to another agent. Returns False if `a2a_router` is not configured.

#### `receive_a2a() -> list[A2AMessage]`

Receives messages from this agent's mailbox.

#### `_parse_structured_output(result_text) -> dict`

Parses `<archon-output>...</archon-output>` JSON blocks from LLM output.

```python
# Expected LLM structured output format
"""
<archon-output>
{
  "summary": "Task summary",
  "changed_files": [{"path": "src/foo.py", "change_type": "added", "reason": "..."}],
  "decisions": [{"decision": "Decision text", "reason": "Reason"}]
}
</archon-output>
"""
```

---

### Role-specific Agents

| Class | File | Responsibility |
|---|---|---|
| `BackendAgent` | `agents/backend.py` | API, DB, business logic |
| `FrontendAgent` | `agents/frontend.py` | UI/UX implementation |
| `TesterAgent` | `agents/tester.py` | Test automation, coverage |
| `DevOpsAgent` | `agents/devops.py` | CI/CD, IaC, infrastructure |
| `DocsAgent` | `agents/docs.py` | Documentation, API specs |
| `ReviewerAgent` | `agents/reviewer.py` | Code review, review_score calculation |

All inherit `BaseAgent` and implement the abstract `_build_system_prompt(handoff, registry)` method. Each agent builds a role-specific system prompt that includes project context, tech stack, and coding guidelines from the registry.

```python
from src.agents.backend import BackendAgent
from src.agents.tester import TesterAgent
from src.mcp.a2a import A2ARouter

router = A2ARouter()
backend = BackendAgent(a2a_router=router)
tester = TesterAgent(a2a_router=router)

# Execute backend work, then hand off to tester
result = await backend.execute(handoff, registry)
test_result = await tester.execute(result, registry)
```

---

## gate

Source: `src/gate/`

The Gate module decides what happens after QA: auto-pass, rework, escalate to a human, halt, or deploy. It is the safety net that prevents bad code from shipping.

### GateDecision

```python
class GateDecision(StrEnum):
    AUTO_PASS = "auto_pass"
    L1_REWORK = "l1_rework"
    L2_HUMAN  = "l2_human"
    L3_HALT   = "l3_halt"
    L4_DEPLOY = "l4_deploy"
```

| Value | Meaning | What happens |
|---|---|---|
| `AUTO_PASS` | All checks passed | Auto-commit and proceed |
| `L1_REWORK` | Minor issue (lint, test) | Agent retries automatically |
| `L2_HUMAN` | Needs human review | Pauses and notifies human |
| `L3_HALT` | Critical issue detected | Halts entire pipeline |
| `L4_DEPLOY` | Deploy request | Requires explicit human approval |

### `evaluate_gate(...)` -> `GateDecision`

Evaluates QA results and policy to produce a gate decision. This is the central decision function with a 7-step priority chain.

```python
def evaluate_gate(
    quality: QualityGates,
    policy: QualityPolicy,
    has_schema_change: bool = False,
    has_external_integration: bool = False,
    is_deploy_request: bool = False,
    retry_count: int = 0,
    changed_paths: list[str] | None = None,
    task_instructions: str = "",
) -> GateDecision
```

| Parameter | Type | Description |
|---|---|---|
| `quality` | `QualityGates` | QA pipeline results (lint, test, build, review_score, etc.) |
| `policy` | `QualityPolicy` | Thresholds and rules from the project registry |
| `has_schema_change` | `bool` | Whether DB schema was modified |
| `has_external_integration` | `bool` | Whether external APIs are involved |
| `is_deploy_request` | `bool` | Whether this is a deploy action |
| `retry_count` | `int` | Number of L1 retries so far |
| `changed_paths` | `list[str] \| None` | File paths changed (for Dynamic Guardrails) |
| `task_instructions` | `str` | Original task instructions (for SOP matching) |

**7-step decision priority:** L4 > L3 > L2 (standard) > L2 (Dynamic Guardrails) > L2 (SOP) > L1 > AUTO_PASS

**Returns:** `GateDecision`

```python
from src.gate.evaluator import evaluate_gate
from src.orchestrator.handoff import QualityGates
from src.registry.models import QualityPolicy

decision = evaluate_gate(
    quality=QualityGates(lint_result="passed", build_result="passed", review_score=85),
    policy=QualityPolicy(),
    changed_paths=["src/payments/checkout.py"],  # triggers Dynamic Guardrails
)
# -> GateDecision.L2_HUMAN
```

---

## orchestrator

Source: `src/orchestrator/`

The Orchestrator drives the end-to-end pipeline: it picks an agent, runs it, feeds the output through QA, invokes the reviewer, evaluates the gate, and either commits or escalates.

### HandoffArtifact

```python
class HandoffArtifact(BaseModel):
    envelope: Envelope
    project_context: ProjectContext
    task: Task
    artifacts: Artifacts
    quality_gates: QualityGates
    human_gate_package: HumanGatePackage | None = None
    memory_context: MemoryContext | None = None
```

Standard JSON document for inter-agent context transfer. Every agent receives one and produces one. Full schema: [handoff-schema.md](handoff-schema.md)

#### Sub-models

| Model | Key fields | Purpose |
|---|---|---|
| `Envelope` | `handoff_id`, `from_agent`, `to_agent`, `retry_count`, `parent_handoff_id` | Routing metadata |
| `ProjectContext` | `project_id`, `git_repo`, `git_branch`, `tech_stack` | Project info |
| `Task` | `task_id`, `completed_summary`, `next_instructions`, `decisions_made`, `blockers` | Task state |
| `Artifacts` | `changed_files: list[ChangedFile]`, `generated_docs`, `dependency_changes` | Work output |
| `QualityGates` | `test_results`, `lint_result`, `build_result`, `security_scan`, `review_score`, `sop_compliance_score`, `gate_decision` | QA results |
| `HumanGatePackage` | `gate_level`, `trigger_reason`, `required_decision`, `decision_options`, `paused_agents` | Human review info |
| `MemoryContext` | `relevant_past_decisions`, `known_patterns`, `error_history`, `human_feedback` | Injected memory |

### Orchestrator

```python
class Orchestrator:
    def __init__(
        self,
        registry: ProjectRegistry,
        notifier: Notifier | None = None,
        vllm_bridge: VLLMBridge | None = None,
        a2a_router: A2ARouter | None = None,
    )
```

| Parameter | Type | Description |
|---|---|---|
| `registry` | `ProjectRegistry` | Project configuration |
| `notifier` | `Notifier \| None` | Gate event notifier (Slack, terminal, etc.) |
| `vllm_bridge` | `VLLMBridge \| None` | vLLM integration for GPU routing |
| `a2a_router` | `A2ARouter \| None` | Agent-to-agent messaging |

#### `run(initial_handoff) -> HandoffArtifact` `async`

Runs the full pipeline: agent execution -> QA -> Reviewer -> Gate decision -> commit/escalation. Handles L1 retries automatically.

#### `process_handoff(handoff) -> HandoffArtifact` `async`

Processes a single handoff through one agent cycle. Does not loop on L1 -- use `run()` for the full loop.

#### `process_chain(handoff, registry) -> list[HandoffArtifact]` `async`

Runs a task chain sequentially per `DEFAULT_TASK_CHAINS`. For example, after a backend task completes, it automatically runs tester then docs.

```python
DEFAULT_TASK_CHAINS: dict[str, list[str]] = {
    "backend":  ["tester", "docs"],
    "frontend": ["tester", "docs"],
    "tester":   [],
    "devops":   ["tester"],
    "docs":     [],
}
```

```python
from src.orchestrator.orchestrator import Orchestrator

orch = Orchestrator(registry=registry, notifier=composite_notifier)
result = await orch.run(initial_handoff)
print(result.quality_gates.gate_decision)  # "auto_pass"
```

---

## router

Source: `src/router/`

The Router selects which LLM model to use for each agent call. It considers the agent's role, task complexity, available GPU workers, and provider preferences.

### role_router.py

#### `get_model_for_role(role, registry=None) -> str`

Returns the configured model for a role. Priority: `model_override` > `model` > `ROLE_MODEL_MAP` default.

| Parameter | Type | Description |
|---|---|---|
| `role` | `str` | Agent role (e.g., "backend", "tester") |
| `registry` | `ProjectRegistry \| None` | Registry with agent_config |

#### `get_model_for_handoff(role, handoff, registry) -> str`

Measures handoff complexity and selects a model. If complexity is HIGH and `high_complexity_model` is configured, returns that model instead of the default.

| Parameter | Type | Description |
|---|---|---|
| `role` | `str` | Agent role |
| `handoff` | `HandoffArtifact` | Current handoff (used for complexity measurement) |
| `registry` | `ProjectRegistry` | Project registry |

#### `get_model_with_vllm(role, handoff, registry, vllm_bridge=None) -> tuple[str, dict | None]`

Routes to a vLLM GPU worker if a healthy endpoint matches the role, otherwise falls back to standard routing. Returns `(model_name, litellm_config)` where `litellm_config` is None for non-vLLM models.

#### `get_model_with_ollama(role, handoff, registry, ollama_bridge=None) -> tuple[str, dict | None]`

*Phase 3.* Routes to a local Ollama instance if available and the role matches. Useful for development and low-latency tasks. Returns `(model_name, litellm_config)`.

#### `get_model_with_provider(role, handoff, registry, vllm_bridge=None, ollama_bridge=None) -> tuple[str, dict | None]`

*Phase 3.* Unified routing function that tries vLLM first, then Ollama, then falls back to cloud API. This is the recommended entry point for model selection.

```python
from src.router.role_router import get_model_with_provider

model, config = get_model_with_provider(
    role="backend",
    handoff=handoff,
    registry=registry,
    vllm_bridge=vllm_bridge,
    ollama_bridge=ollama_bridge,
)
```

### complexity.py

#### `measure_complexity(handoff) -> ComplexityScore`

Scores handoff complexity against 8 criteria. Used by the router to decide whether to use a more capable (and expensive) model.

```python
@dataclass
class ComplexityScore:
    level: ComplexityLevel   # LOW | MEDIUM | HIGH
    score: int               # 0-14 points
    factors: list[str]       # triggered criteria
```

| Criterion | Points |
|---|---|
| Instructions >= 500 chars | +2 |
| Changed files >= 5 | +2 |
| Past decisions >= 3 | +1 |
| Blocker present | +2 |
| External integration | +2 |
| Schema change | +2 |
| Priority >= 8 | +1 |
| Prior L2+ gate | +2 |

Levels: LOW (0-3) / MEDIUM (4-6) / HIGH (7+)

#### `select_model_by_complexity(score, agent_config) -> str`

*Phase 3.* Given a `ComplexityScore` and an `AgentModelConfig`, returns the appropriate model name. HIGH complexity -> `high_complexity_model`, otherwise -> default model.

```python
from src.router.complexity import measure_complexity, select_model_by_complexity

score = measure_complexity(handoff)
model = select_model_by_complexity(score, registry.agent_config["backend"])
print(f"Using {model} for {score.level} complexity (score={score.score})")
```

---

## runtime

Source: `src/runtime/`

The Runtime module provides infrastructure integration: Git operations, GPU server bridges, cluster management, and hybrid cloud scheduling.

### GitExecutor (`src/runtime/git_executor.py`)

Handles all Git operations with safety guardrails (protected paths, force-push detection).

```python
class GitExecutor:
    def __init__(self, git_config: GitConfig)
```

#### `auto_commit(handoff, message_template, repo_root=None) -> str | None` `async`

Full commit workflow: 1) validate protected paths -> 2) create/checkout branch -> 3) stage files -> 4) commit -> 5) push. Returns commit SHA on success, `None` if no changes.

| Parameter | Type | Description |
|---|---|---|
| `handoff` | `HandoffArtifact` | Handoff with changed files |
| `message_template` | `str` | Commit message template |
| `repo_root` | `str \| None` | Git repo root (defaults to git_config) |

#### `validate_protected_paths(handoff) -> None`

Raises `ProtectedPathError` if any changed file touches `git_config.protected_paths`.

#### `save_snapshot(repo_root=None) -> Snapshot`

*Phase 3.* Captures the current HEAD commit as a named snapshot for later rollback.

```python
@dataclass
class Snapshot:
    snapshot_id: str
    commit_sha: str
    branch: str
    timestamp: datetime
    label: str
```

#### `rollback_to_snapshot(snapshot, repo_root=None) -> bool` `async`

*Phase 3.* Hard-resets the working tree to a previously saved snapshot. Returns True on success. Use with caution -- this discards uncommitted changes.

#### `list_snapshots() -> list[Snapshot]`

*Phase 3.* Returns all saved snapshots, newest first.

#### `clear_snapshots() -> None`

*Phase 3.* Removes all saved snapshots from memory.

```python
from src.runtime.git_executor import GitExecutor

git = GitExecutor(git_config=registry.git_config)

# Save before risky operation
snapshot = git.save_snapshot()

# Do work...
sha = await git.auto_commit(handoff, "feat(backend): add payment API")

# If something goes wrong
await git.rollback_to_snapshot(snapshot)
```

---

### VLLMBridge (`src/runtime/vllm_bridge.py`)

Integrates self-hosted vLLM GPU servers into LiteLLM. Register endpoints, health-check them, and get LiteLLM-compatible configs for completion calls.

```python
class VLLMBridge:
    def __init__(self, timeout: float = 5.0)
```

| Parameter | Type | Description |
|---|---|---|
| `timeout` | `float` | HTTP timeout for health checks (seconds) |

#### `register(endpoint) -> None`

Registers a `VLLMEndpoint`.

#### `health_check(name) -> bool` `async`

Health-checks a single endpoint by name. Updates internal healthy/unhealthy tracking.

#### `get_litellm_config(name) -> dict | None`

Returns LiteLLM completion parameters: `{"model", "api_base", "api_key", "max_tokens"}`. Returns None if endpoint not found.

#### VLLMEndpoint

```python
@dataclass
class VLLMEndpoint:
    name: str               # LiteLLM model name (e.g. "vllm/qwen-27b")
    base_url: str           # vLLM server URL (e.g. "http://gpu-node:8000")
    model_name: str         # Actual model loaded in vLLM
    api_key: str = "EMPTY"
    max_tokens: int = 4096
    gpu_memory_utilization: float = 0.9
    tensor_parallel_size: int = 1
    tags: list[str]         # Routing tags (e.g. ["backend", "tester"])
```

```python
from src.runtime.vllm_bridge import VLLMBridge, VLLMEndpoint

bridge = VLLMBridge()
bridge.register(VLLMEndpoint(
    name="vllm/qwen-27b",
    base_url="http://gpu-node:8000",
    model_name="Qwen/Qwen2.5-27B",
    tags=["backend"],
))
await bridge.health_check_all()
config = bridge.get_litellm_config("vllm/qwen-27b")
```

---

### OllamaBridge (`src/runtime/ollama_bridge.py`)

*Phase 3.* Integrates local Ollama instances for development and low-latency inference. Similar to VLLMBridge but for Ollama's REST API.

```python
class OllamaBridge:
    def __init__(self, base_url: str = "http://localhost:11434", timeout: float = 5.0)
```

| Parameter | Type | Description |
|---|---|---|
| `base_url` | `str` | Ollama server URL |
| `timeout` | `float` | HTTP timeout (seconds) |

#### `register(model_name, tags=None) -> None`

Registers a model for routing.

#### `health_check() -> bool` `async`

Checks if the Ollama server is responding.

#### `pull_model(model_name) -> bool` `async`

Pulls a model from the Ollama registry. Returns True when complete.

#### `list_models() -> list[str]` `async`

Lists all locally available models.

#### `get_litellm_config(model_name) -> dict | None`

Returns LiteLLM-compatible config for the specified model.

```python
from src.runtime.ollama_bridge import OllamaBridge

ollama = OllamaBridge()
if await ollama.health_check():
    await ollama.pull_model("qwen2.5:14b")
    config = ollama.get_litellm_config("qwen2.5:14b")
```

---

### ClusterManager (`src/runtime/cluster.py`)

Manages Ray cluster worker nodes. Tracks worker status, GPU allocation, and provides cluster-wide summaries.

```python
class ClusterManager:
    def __init__(self)
```

#### `register_worker(config) -> WorkerNode`

Registers a worker. Accepts `WorkerConfig(node_id, node_type, gpu_count, memory_gb, ...)`.

#### `heartbeat(node_id) -> bool`

Updates worker heartbeat timestamp. Returns False if worker not found.

#### `get_cluster_summary() -> dict`

Returns cluster summary: worker count, total GPUs, total memory, total tasks.

```python
WorkerType: "CPU" | "GPU" | "HYBRID"
WorkerStatus: "online" | "offline" | "degraded" | "draining"
```

---

### KubeRayManager (`src/runtime/kuberay_manager.py`)

*Phase 3.* Manages Ray clusters on Kubernetes via KubeRay operator. Generates YAML manifests and manages cluster lifecycle.

```python
class KubeRayManager:
    def __init__(self, namespace: str = "default", kubeconfig: str | None = None)
```

| Parameter | Type | Description |
|---|---|---|
| `namespace` | `str` | Kubernetes namespace for Ray clusters |
| `kubeconfig` | `str \| None` | Path to kubeconfig file (defaults to in-cluster) |

#### `deploy_cluster(config) -> dict` `async`

Deploys a new Ray cluster. Returns cluster status dict with endpoint URL.

#### `scale_workers(cluster_name, replicas) -> dict` `async`

Scales worker pods for an existing cluster.

| Parameter | Type | Description |
|---|---|---|
| `cluster_name` | `str` | Name of the Ray cluster |
| `replicas` | `int` | Target number of worker replicas |

#### `get_cluster_status(cluster_name) -> dict` `async`

Returns current cluster status: phase, ready workers, head node endpoint.

#### `delete_cluster(cluster_name) -> bool` `async`

Deletes a Ray cluster and all associated resources.

#### `generate_manifests(config) -> str`

Generates KubeRay YAML manifests without applying them. Useful for review before deployment.

```python
from src.runtime.kuberay_manager import KubeRayManager

kuberay = KubeRayManager(namespace="archon-prod")
status = await kuberay.deploy_cluster(config)
print(status["endpoint"])  # "ray://ray-head.archon-prod:10001"

await kuberay.scale_workers("archon-cluster", replicas=4)
```

---

### HybridCloudManager (`src/runtime/hybrid_cloud.py`)

*Phase 3.* Schedules tasks across on-premise GPU nodes and cloud providers based on cost, availability, and budget constraints.

```python
class HybridCloudManager:
    def __init__(self, budget_limit: float | None = None)
```

| Parameter | Type | Description |
|---|---|---|
| `budget_limit` | `float \| None` | Monthly cost budget in USD (None = unlimited) |

#### `register_resource(resource) -> None`

Registers a compute resource (on-prem GPU, cloud instance, etc.).

#### `schedule_task(task, preference="cost") -> str`

Schedules a task to the best available resource. Returns the resource ID.

| Parameter | Type | Description |
|---|---|---|
| `task` | `dict` | Task descriptor with requirements |
| `preference` | `str` | Scheduling preference: `"cost"`, `"speed"`, or `"locality"` |

#### `check_budget() -> dict`

Returns current budget status: spent, remaining, utilization percentage.

#### `get_summary() -> dict`

Returns overview of all registered resources and their utilization.

```python
from src.runtime.hybrid_cloud import HybridCloudManager

hcm = HybridCloudManager(budget_limit=500.0)
hcm.register_resource(on_prem_gpu)
hcm.register_resource(cloud_gpu)

resource_id = hcm.schedule_task({"role": "backend", "complexity": "HIGH"}, preference="cost")
budget = hcm.check_budget()
print(f"Budget: ${budget['remaining']:.2f} remaining")
```

---

## memory

Source: `src/memory/`

The Memory module provides a 3-layer architecture: L1 (Redis scratchpad for fast ephemeral data), L2 (ChromaDB vector store for handoff history), and L3 (Mem0 for cross-project patterns). Each layer is optional -- missing backends fall back to in-memory dicts.

### MemoryStore (`src/memory/context_injector.py`)

3-layer memory facade. This is the primary entry point for memory operations.

```python
class MemoryStore:
    def __init__(
        self,
        redis_scratchpad: RedisScratchpad | None = None,
        vector_store: VectorStore | None = None,
        mem0_store: Mem0Store | None = None,
    )
```

#### `inject_memory_context(task_instructions, project_id) -> MemoryContext` `async`

Queries L2 (vector search) and L3 (pattern search) using task instructions, assembles relevant context for agent injection. This is the method the orchestrator calls before every agent execution.

| Parameter | Type | Description |
|---|---|---|
| `task_instructions` | `str` | Current task instructions (used as search query) |
| `project_id` | `str` | Project ID for scoping L2 search |

**Returns:** `MemoryContext` with `relevant_past_decisions`, `known_patterns`, `error_history`, `human_feedback`.

```python
from src.memory.context_injector import MemoryStore

store = MemoryStore(redis_scratchpad=scratchpad, vector_store=vs, mem0_store=mem0)
ctx = await store.inject_memory_context("Payment API implementation", "proj-001")
print(ctx.known_patterns)  # ["Always validate currency codes", ...]
```

#### Other MemoryStore methods

| Method | Layer | Description |
|---|---|---|
| `set_scratch(project_id, task_id, key, value)` | L1 | Save ephemeral value to Redis |
| `get_scratch(project_id, task_id, key) -> Any \| None` | L1 | Retrieve value from Redis |
| `store_handoff(project_id, handoff_id, summary, metadata=None)` | L2 | Store handoff summary vector |
| `search_handoffs(project_id, query, n_results=5, threshold=0.85) -> list[dict]` | L2 | Search similar handoffs |
| `store_pattern(project_id, pattern, reason="", user_id="archon")` | L3 | Store cross-project pattern |
| `search_patterns(query, user_id="archon", limit=5) -> list[dict]` | L3 | Search patterns |

---

### RedisScratchpad (`src/memory/redis_scratchpad.py`)

Fast ephemeral storage for in-progress task data. Data is automatically expired via TTL.

```python
class RedisScratchpad:
    def __init__(self, redis_client: Any, ttl: int = 86400)
```

Key format: `archon:scratch:{project_id}:{task_id}:{key}`

| Method | Signature | Description |
|---|---|---|
| `set` | `(project_id, task_id, key, value, ttl=None)` | Store value (JSON-serialized) |
| `get` | `(project_id, task_id, key) -> Any \| None` | Retrieve value |
| `delete` | `(project_id, task_id, key) -> bool` | Delete value |
| `list_keys` | `(project_id, task_id) -> list[str]` | List all keys for a task |
| `clear_task` | `(project_id, task_id) -> int` | Delete all task data; returns count |

---

### VectorStore (`src/memory/vector_store.py`)

Persistent vector storage using ChromaDB. Each project gets its own collection for isolation.

```python
class VectorStore:
    def __init__(self, chroma_client: Any, collection_prefix: str = "archon")
```

| Method | Signature | Description |
|---|---|---|
| `store` | `(project_id, handoff_id, summary, metadata=None)` | Store handoff vector (upsert) |
| `search` | `(project_id, query, n_results=5, threshold=0.85) -> list[dict]` | Cosine similarity search |
| `delete` | `(project_id, handoff_id)` | Delete specific handoff |
| `delete_project` | `(project_id)` | Delete entire project collection |
| `count` | `(project_id) -> int` | Number of stored handoffs |

Search result format: `{"id": str, "document": str, "metadata": dict, "similarity": float}`

---

### Mem0Store (`src/memory/mem0_store.py`)

Long-term cross-project memory using Mem0. Stores patterns, preferences, and lessons learned that apply across all projects.

```python
class Mem0Store:
    def __init__(self, mem0_client: Any)
```

#### `add_memory(text, user_id="archon", metadata=None) -> str`

Stores a memory. Returns the memory ID.

#### `search_memories(query, user_id="archon", limit=5) -> list[dict]`

Searches memories by semantic similarity. Returns list of `{"id", "text", "metadata", "score"}`.

```python
from src.memory.mem0_store import Mem0Store

mem0 = Mem0Store(client)
mem0.add_memory("Always use UTC timestamps in API responses", user_id="archon")
results = mem0.search_memories("timestamp formatting", limit=3)
```

---

### compressor (`src/memory/compressor.py`)

When a handoff exceeds token limits, the compressor reduces it to fit. Used automatically by `BaseAgent.execute()`.

#### `compress_handoff(handoff, token_gap) -> HandoffArtifact`

*Phase 3 signature update.* Compresses a handoff to free up `token_gap` tokens. Compresses fields in priority order: memory_context -> completed_summary -> decisions_made -> next_instructions.

| Parameter | Type | Description |
|---|---|---|
| `handoff` | `HandoffArtifact` | Handoff to compress |
| `token_gap` | `int` | Number of tokens to free |

#### `estimate_tokens(text) -> int`

Estimates token count for mixed Korean/English text. (Korean: 2 chars = 1 token; ASCII: 4 chars = 1 token)

#### `compress_text(text, max_tokens) -> str`

Truncates text while respecting sentence boundaries.

#### `summarize_text(text, max_tokens) -> str` `async`

*Phase 3.* Uses an LLM to intelligently summarize text rather than truncating. Produces a more coherent compressed result but requires an API call.

---

## guardrails

Source: `src/guardrails/`

*Phase 3.* The Guardrails module validates inputs before agent execution and outputs after, tracks token budgets, and enforces path-based access policies.

### GuardrailPolicy

```python
class GuardrailPolicy(BaseModel):
    max_input_tokens: int = 8000
    max_output_tokens: int = 16000
    blocked_patterns: list[str] = []
    required_output_fields: list[str] = ["summary", "changed_files"]
    token_budget_per_task: int = 100000
    token_budget_per_project: int = 1000000
    protected_path_patterns: list[str] = []
    allow_self_correction: bool = True
```

A single policy object controls all guardrail behavior. Stored in the project registry.

---

### InputValidator (`src/guardrails/input_validator.py`)

Validates handoff inputs before an agent executes. Catches issues early -- before spending tokens on LLM calls.

```python
class InputValidator:
    def __init__(self, policy: GuardrailPolicy)
```

#### `validate(handoff) -> InputValidationResult`

| Check | What it does |
|---|---|
| Token count | Rejects inputs exceeding `max_input_tokens` |
| Blocked patterns | Scans for disallowed patterns (secrets, SQL injection, etc.) |
| Required fields | Ensures `task.next_instructions` is not empty |

```python
class InputValidationResult(BaseModel):
    valid: bool
    errors: list[str]
    warnings: list[str]
    token_count: int
```

```python
from src.guardrails.input_validator import InputValidator

validator = InputValidator(policy)
result = validator.validate(handoff)
if not result.valid:
    raise InputValidationError(result.errors)
```

---

### OutputValidator (`src/guardrails/output_validator.py`)

Validates agent output before it becomes the next handoff. Ensures structured output integrity.

```python
class OutputValidator:
    def __init__(self, policy: GuardrailPolicy)
```

#### `validate(result_handoff) -> OutputValidationResult`

| Check | What it does |
|---|---|
| Required fields | Ensures `required_output_fields` are present |
| Token count | Warns if output exceeds `max_output_tokens` |
| File path safety | Detects suspicious paths (e.g., `/etc/passwd`, `~/.ssh/`) |

```python
class OutputValidationResult(BaseModel):
    valid: bool
    errors: list[str]
    warnings: list[str]
    token_count: int
    missing_fields: list[str]
```

---

### TokenBudgetTracker (`src/guardrails/token_budget.py`)

Tracks cumulative token usage per task and per project. Prevents runaway costs from infinite retry loops.

```python
class TokenBudgetTracker:
    def __init__(self, policy: GuardrailPolicy)
```

#### `record(project_id, task_id, tokens_used) -> None`

Records token usage for a task.

#### `check_before_call(project_id, task_id, estimated_tokens) -> bool`

Returns True if the estimated call would stay within budget. Returns False if it would exceed the limit.

#### `get_status(project_id, task_id=None) -> dict`

Returns budget status: `{"used", "limit", "remaining", "utilization_pct"}`. Pass `task_id` for task-level, omit for project-level.

```python
from src.guardrails.token_budget import TokenBudgetTracker

tracker = TokenBudgetTracker(policy)
if tracker.check_before_call("proj-001", "task-001", estimated_tokens=4000):
    result = await agent.execute(handoff, registry)
    tracker.record("proj-001", "task-001", actual_tokens)
else:
    raise TokenBudgetExceededError("Task token budget exhausted")
```

---

### PathGuard (`src/guardrails/path_guard.py`)

Enforces file path access policies. Prevents agents from modifying files outside their allowed scope.

```python
class PathGuard:
    def __init__(self, policy: GuardrailPolicy)
```

#### `check_handoff(handoff) -> list[str]`

Returns list of violation messages for any changed files that match `protected_path_patterns`. Empty list means all paths are allowed.

#### `check_paths(paths) -> list[str]`

Checks a raw list of file paths against the policy. Useful for pre-validation before agent execution.

```python
from src.guardrails.path_guard import PathGuard

guard = PathGuard(policy)
violations = guard.check_handoff(handoff)
if violations:
    raise PathGuardError(f"Blocked paths: {violations}")
```

---

## observability

Source: `src/observability/`

*Phase 3.* Distributed tracing and telemetry for the entire pipeline. Supports multiple backends (AITOP, OpenTelemetry, etc.) and sampling.

### Configuration

```python
class TracingBackend(StrEnum):
    NOOP = "noop"
    AITOP = "aitop"
    COMPOSITE = "composite"

class TracingConfig(BaseModel):
    enabled: bool = False
    backend: TracingBackend = TracingBackend.NOOP
    sample_rate: float = 1.0
    aitop_endpoint: str | None = None
    export_interval_seconds: int = 30
```

### ArchonTracer (ABC)

Abstract base class for all tracers.

```python
class ArchonTracer(abc.ABC):
    def start_trace(self, trace_id: str, metadata: dict | None = None) -> SpanContext: ...
    def start_span(self, name: str, parent: SpanContext | None = None) -> SpanContext: ...
    def end_span(self, span: SpanContext, status: str = "ok", metadata: dict | None = None) -> None: ...
    def record_llm_call(self, span: SpanContext, record: LLMCallRecord) -> None: ...
```

#### SpanContext

```python
@dataclass
class SpanContext:
    trace_id: str
    span_id: str
    parent_span_id: str | None
    name: str
    start_time: datetime
    metadata: dict
```

#### LLMCallRecord

```python
@dataclass
class LLMCallRecord:
    model: str
    provider: str
    input_tokens: int
    output_tokens: int
    latency_ms: float
    cost_usd: float
    status: str          # "success" | "error" | "timeout"
    error_message: str | None = None
```

### Tracer Implementations

| Class | Description |
|---|---|
| `NoOpTracer` | Does nothing. Default when tracing is disabled. |
| `CompositeTracer` | Fans out to multiple child tracers. |
| `SamplingTracer` | Wraps another tracer and samples at a configurable rate. |
| `AitopTracer` | Sends traces to an AITOP backend for visualization. |

### TracingMiddleware (`src/observability/middleware.py`)

High-level helper that integrates tracing into the orchestrator pipeline.

```python
class TracingMiddleware:
    def __init__(self, tracer: ArchonTracer)
```

#### `start_pipeline_trace(handoff) -> SpanContext`

Starts a root trace for a pipeline execution.

#### `start_agent_span(parent, agent_role) -> SpanContext`

Starts a child span for an agent execution within a pipeline trace.

#### `record_llm_call(span, record) -> None`

Records an LLM call within a span.

### `create_tracer_from_config(config) -> ArchonTracer`

Factory function that creates the appropriate tracer from a `TracingConfig`.

```python
from src.observability import create_tracer_from_config, TracingConfig

config = TracingConfig(enabled=True, backend="aitop", sample_rate=0.5)
tracer = create_tracer_from_config(config)

span = tracer.start_trace("pipeline-001")
agent_span = tracer.start_span("backend-agent", parent=span)
tracer.record_llm_call(agent_span, LLMCallRecord(
    model="gpt-4o", provider="openai",
    input_tokens=3000, output_tokens=1500,
    latency_ms=2300, cost_usd=0.045, status="success",
))
tracer.end_span(agent_span)
tracer.end_span(span)
```

---

## benchmark

Source: `src/benchmark/`

*Phase 3.* Benchmarks LLM models against role-specific tasks and recommends optimal model assignments per role.

### Data Models

```python
@dataclass
class BenchmarkTask:
    task_id: str
    role: str                   # "backend", "tester", etc.
    instructions: str
    expected_output: dict       # ground truth for scoring
    complexity: str             # "LOW" | "MEDIUM" | "HIGH"

@dataclass
class BenchmarkResult:
    task_id: str
    model: str
    output: str
    latency_ms: float
    input_tokens: int
    output_tokens: int
    cost_usd: float
    success: bool

@dataclass
class ModelScore:
    model: str
    role: str
    quality_score: float        # 0-100
    speed_score: float          # 0-100
    cost_score: float           # 0-100
    composite_score: float      # weighted average

@dataclass
class ModelRanking:
    role: str
    rankings: list[ModelScore]  # sorted by composite_score desc
    recommended: str            # top model name
```

### BenchmarkRunner

```python
class BenchmarkRunner:
    def __init__(self, models: list[str], timeout: float = 60.0)
```

#### `run_task(task, model) -> BenchmarkResult` `async`

Runs a single benchmark task against a model.

#### `run_suite(tasks) -> list[BenchmarkResult]` `async`

Runs all tasks against all registered models. Returns the full result matrix.

```python
from src.benchmark.runner import BenchmarkRunner

runner = BenchmarkRunner(models=["gpt-4o", "claude-sonnet-4-20250514", "qwen2.5-72b"])
results = await runner.run_suite(tasks)
```

### BenchmarkScorer

```python
class BenchmarkScorer:
    def __init__(self, quality_weight=0.5, speed_weight=0.3, cost_weight=0.2)
```

#### `score_results(results, tasks) -> list[ModelScore]`

Scores benchmark results by comparing outputs to expected outputs. Returns per-model, per-role scores.

### ModelRecommender

```python
class ModelRecommender:
    def __init__(self, scorer: BenchmarkScorer)
```

#### `rank_models(scores, role) -> ModelRanking`

Ranks models for a specific role based on composite scores.

#### `recommend_all_roles(scores) -> dict[str, ModelRanking]`

Returns rankings for all roles at once.

#### `apply_recommendations(rankings, registry) -> ProjectRegistry`

Updates the project registry's `agent_config` with recommended models.

```python
from src.benchmark.scorer import BenchmarkScorer
from src.benchmark.recommender import ModelRecommender

scorer = BenchmarkScorer(quality_weight=0.6, speed_weight=0.2, cost_weight=0.2)
scores = scorer.score_results(results, tasks)

recommender = ModelRecommender(scorer)
rankings = recommender.recommend_all_roles(scores)
print(rankings["backend"].recommended)  # "claude-sonnet-4-20250514"

updated_registry = recommender.apply_recommendations(rankings, registry)
```

---

## evolution

Source: `src/evolution/`

*Phase 3.* Self-tuning pipeline that analyzes execution patterns, identifies bottlenecks, and automatically adjusts quality thresholds and agent configurations.

### Data Models

```python
@dataclass
class PipelineExecution:
    pipeline_id: str
    handoffs: list[HandoffArtifact]
    gate_decisions: list[GateDecision]
    total_duration_ms: float
    total_tokens: int
    total_cost_usd: float

@dataclass
class AgentMetrics:
    role: str
    avg_latency_ms: float
    avg_tokens: int
    success_rate: float
    rework_rate: float

@dataclass
class PipelineMetrics:
    total_executions: int
    auto_pass_rate: float
    l1_rate: float
    l2_rate: float
    avg_duration_ms: float
    agent_metrics: dict[str, AgentMetrics]

@dataclass
class TuningAction:
    action_type: str            # "adjust_threshold", "change_model", "modify_retry"
    target: str                 # field or config key
    current_value: Any
    proposed_value: Any
    reason: str

class EvolutionConfig(BaseModel):
    enabled: bool = False
    min_executions: int = 20    # minimum data before tuning
    cycle_interval_seconds: int = 3600
    auto_apply: bool = False    # require human approval by default
```

### MetricsCollector

```python
class MetricsCollector:
    def __init__(self)
```

#### `record(execution) -> None`

Records a completed pipeline execution for later analysis.

#### `get_metrics(window_hours=24) -> PipelineMetrics`

Returns aggregated pipeline metrics for the given time window.

#### `get_agent_metrics(role, window_hours=24) -> AgentMetrics`

Returns metrics for a specific agent role.

### PatternAnalyzer

```python
class PatternAnalyzer:
    def __init__(self, collector: MetricsCollector)
```

#### `analyze() -> list[TuningAction]`

Analyzes collected metrics and proposes tuning actions. Examples: "review_score threshold too strict (L2 rate 45%)", "backend agent rework rate high -- suggest model upgrade".

### ThresholdTuner

```python
class ThresholdTuner:
    def __init__(self, config: EvolutionConfig)
```

#### `evaluate_actions(actions) -> list[TuningAction]`

Filters proposed actions by safety bounds. Rejects actions that would reduce quality below minimum thresholds.

#### `safe_adjust(current, proposed, max_delta) -> Any`

Applies a bounded adjustment. Ensures changes are gradual (max_delta per cycle).

#### `apply_to_policy(actions, policy) -> QualityPolicy`

Applies approved tuning actions to a quality policy and returns the updated policy.

### EvolutionLoop

```python
class EvolutionLoop:
    def __init__(
        self,
        config: EvolutionConfig,
        collector: MetricsCollector,
        analyzer: PatternAnalyzer,
        tuner: ThresholdTuner,
    )
```

#### `run_cycle() -> list[TuningAction]` `async`

Runs one evolution cycle: collect -> analyze -> propose -> (optionally) apply.

#### `start_background() -> None` `async`

Starts the evolution loop as a background task, running every `cycle_interval_seconds`.

#### `stop() -> None`

Stops the background evolution loop.

```python
from src.evolution.loop import EvolutionLoop
from src.evolution.config import EvolutionConfig

config = EvolutionConfig(enabled=True, auto_apply=False, cycle_interval_seconds=3600)
loop = EvolutionLoop(config, collector, analyzer, tuner)

# Manual cycle
actions = await loop.run_cycle()
for a in actions:
    print(f"{a.action_type}: {a.target} {a.current_value} -> {a.proposed_value} ({a.reason})")

# Or run in background
await loop.start_background()
```

---

## dashboard

Source: `src/dashboard/`

*Phase 3.* Real-time web dashboard for monitoring pipeline execution, agent status, costs, and gate queue. Built with FastAPI + WebSocket.

### DashboardApp

```python
class DashboardApp:
    def __init__(self, registry_store: RegistryStore, collector: MetricsCollector | None = None)
```

#### `create_app() -> FastAPI`

Creates and returns the FastAPI application with all routes and WebSocket endpoints configured.

```python
from src.dashboard.app import DashboardApp

dashboard = DashboardApp(registry_store=store, collector=collector)
app = dashboard.create_app()

# Run with uvicorn
import uvicorn
uvicorn.run(app, host="0.0.0.0", port=8080)
```

### DashboardRoutes

Handles all HTTP and WebSocket endpoints.

| Endpoint | Method | Description |
|---|---|---|
| `/api/projects` | GET | List all projects |
| `/api/projects/{id}` | GET | Project details |
| `/api/projects/{id}/agents` | GET | Agent statuses for a project |
| `/api/projects/{id}/metrics` | GET | Pipeline metrics |
| `/api/projects/{id}/costs` | GET | Cost breakdown |
| `/api/projects/{id}/gate-queue` | GET | Pending human gate items |
| `/api/projects/{id}/gate-queue/{item_id}` | POST | Approve/reject gate item |
| `/api/projects/{id}/handoffs` | GET | Recent handoff history |
| `/api/projects/{id}/evolution` | GET | Evolution status and proposals |
| `/api/health` | GET | Health check |
| `/ws/events` | WebSocket | Real-time pipeline events |

### WebSocketManager

```python
class WebSocketManager:
    def __init__(self)
```

#### `connect(websocket) -> None` `async`

Registers a WebSocket client for real-time event streaming.

#### `broadcast(event) -> None` `async`

Sends an event to all connected WebSocket clients. Events include gate decisions, agent completions, error alerts, and cost updates.

### API Models

```python
class ProjectSummary(BaseModel):
    project_id: str
    project_name: str
    status: str
    agent_count: int
    pending_gates: int

class AgentStatusResponse(BaseModel):
    role: str
    model: str
    status: str                 # "idle" | "running" | "error"
    last_execution_ms: float | None
    success_rate: float

class CostSummary(BaseModel):
    total_cost_usd: float
    cost_by_model: dict[str, float]
    cost_by_role: dict[str, float]
    budget_remaining: float | None

class GateQueueItem(BaseModel):
    item_id: str
    task_id: str
    gate_level: str
    trigger_reason: str
    agent_role: str
    created_at: datetime
    decision_options: list[str]
```

---

## healing

Source: `src/healing/`

*Phase 3.* Self-healing infrastructure that monitors agent health, diagnoses failures, and automatically recovers from common error patterns.

### AgentHealthStatus

```python
class AgentHealthStatus(StrEnum):
    HEALTHY   = "healthy"
    DEGRADED  = "degraded"
    UNHEALTHY = "unhealthy"
    DEAD      = "dead"
```

| Status | Meaning |
|---|---|
| `HEALTHY` | Agent operating normally |
| `DEGRADED` | Elevated error rate or latency |
| `UNHEALTHY` | Consistently failing, needs intervention |
| `DEAD` | Not responding at all |

### AgentHealthMonitor

Tracks per-agent health using a sliding window of success/failure signals.

```python
class AgentHealthMonitor:
    def __init__(self, window_size: int = 20, degraded_threshold: float = 0.7, unhealthy_threshold: float = 0.4)
```

#### `record_success(role) -> AgentHealthStatus`

Records a successful execution. Returns updated health status.

#### `record_failure(role, error) -> AgentHealthStatus`

Records a failed execution. Returns updated health status.

#### `record_circuit_open(role) -> AgentHealthStatus`

Records a circuit breaker open event. Transitions to DEAD status.

### HealthMonitorRegistry

Manages multiple `AgentHealthMonitor` instances -- one per agent role.

### DiagnosticRegistry

Manages multiple `AgentDiagnostician` instances for centralized diagnostics.

### AgentDiagnostician

Analyzes error patterns to determine root causes and suggest fixes.

```python
class AgentDiagnostician:
    def __init__(self, role: str, max_history: int = 50)
```

#### `record_error(error, context=None) -> None`

Records an error with optional context for pattern analysis.

#### `generate_report() -> dict`

Generates a diagnostic report: error frequency by category, most common root causes, and recommended recovery actions.

### ErrorCategory

```python
class ErrorCategory(StrEnum):
    TIMEOUT       = "timeout"
    PARSING       = "parsing"
    RATE_LIMIT    = "rate_limit"
    AUTH          = "auth"
    CONTEXT_OVERFLOW = "context_overflow"
    MODEL_ERROR   = "model_error"
    NETWORK       = "network"
    UNKNOWN       = "unknown"
```

### RootCause

```python
class RootCause(StrEnum):
    MODEL_OVERLOADED   = "model_overloaded"
    TOKEN_LIMIT        = "token_limit"
    INVALID_PROMPT     = "invalid_prompt"
    API_KEY_EXPIRED    = "api_key_expired"
    RATE_LIMIT_HIT     = "rate_limit_hit"
    NETWORK_UNSTABLE   = "network_unstable"
    MODEL_DEGRADED     = "model_degraded"
    UNKNOWN            = "unknown"
```

### SelfHealer

Automatically applies recovery actions based on diagnostics.

```python
class SelfHealer:
    def __init__(self, registry: ProjectRegistry)
```

#### `heal(role, report) -> RecoveryAction` `async`

Selects and executes a recovery action based on the diagnostic report.

#### `select_action(report) -> RecoveryAction`

Chooses the best recovery action without executing it.

### RecoveryAction

```python
class RecoveryAction(StrEnum):
    RETRY           = "retry"
    SWITCH_MODEL    = "switch_model"
    REDUCE_CONTEXT  = "reduce_context"
    COOL_DOWN       = "cool_down"
    REFRESH_AUTH    = "refresh_auth"
    ESCALATE        = "escalate"
```

### HealthWatchdog

Background service that periodically checks all agent health and triggers healing when needed.

```python
class HealthWatchdog:
    def __init__(
        self,
        monitor_registry: HealthMonitorRegistry,
        diagnostic_registry: DiagnosticRegistry,
        healer: SelfHealer,
        check_interval: int = 30,
    )
```

#### `start() -> None` `async`

Starts the watchdog as a background task.

#### `stop() -> None`

Stops the watchdog.

#### `check_once() -> dict[str, AgentHealthStatus]` `async`

Runs a single health check cycle and returns all agent statuses.

```python
from src.healing.watchdog import HealthWatchdog
from src.healing.monitor import HealthMonitorRegistry
from src.healing.diagnostician import DiagnosticRegistry
from src.healing.healer import SelfHealer

monitors = HealthMonitorRegistry()
diagnostics = DiagnosticRegistry()
healer = SelfHealer(registry)

watchdog = HealthWatchdog(monitors, diagnostics, healer, check_interval=30)
await watchdog.start()

# Manual check
statuses = await watchdog.check_once()
for role, status in statuses.items():
    print(f"{role}: {status}")
```

---

## notifications

Source: `src/notifications/`

Sends notifications when gate decisions fire. Supports multiple backends (Slack, terminal) with fan-out.

### GateEvent (`src/notifications/base.py`)

```python
class GateEvent(BaseModel):
    project_id: str
    project_name: str
    task_id: str
    gate_decision: GateDecision
    trigger_reason: str
    agent_role: str
    review_score: int = 0
    retry_count: int = 0
    timestamp: datetime
```

Properties: `.severity` (`"info"` | `"warning"` | `"error"` | `"critical"`), `.title`, `.summary`

### Notifier (ABC)

```python
class Notifier(abc.ABC):
    async def notify(self, event: GateEvent) -> bool: ...
    def should_notify(self, event: GateEvent) -> bool: ...  # AUTO_PASS suppressed by default
```

### CompositeNotifier

Fan-out to multiple notifiers simultaneously. Returns True if any succeeds.

```python
class CompositeNotifier(Notifier):
    def __init__(self, notifiers: list[Notifier] | None = None)
    def add(self, notifier: Notifier) -> None
    async def notify(self, event: GateEvent) -> bool
```

### SlackNotifier (`src/notifications/slack.py`)

Slack incoming webhook. Automatic color/emoji per gate level.

```python
class SlackNotifier(Notifier):
    def __init__(self, webhook_url: str)
```

### TerminalNotifier (`src/notifications/terminal.py`)

rich TUI panel + macOS `osascript` desktop notifications.

```python
class TerminalNotifier(Notifier):
    def __init__(self)
```

```python
from src.notifications.base import CompositeNotifier, GateEvent
from src.notifications.slack import SlackNotifier
from src.notifications.terminal import TerminalNotifier

notifier = CompositeNotifier([
    SlackNotifier(webhook_url="https://hooks.slack.com/..."),
    TerminalNotifier(),
])

event = GateEvent(
    project_id="proj-001",
    project_name="My Project",
    task_id="task-001",
    gate_decision=GateDecision.L2_HUMAN,
    trigger_reason="review_score 58 < 70",
    agent_role="backend",
)
await notifier.notify(event)
```

---

## mcp

Source: `src/mcp/`

MCP (Model Context Protocol) server for external tool integration and A2A (Agent-to-Agent) messaging.

### MCPServer (`src/mcp/server.py`)

MCP tool server for external clients to control Archon.

```python
class MCPServer:
    def __init__(self)
```

#### `register_project(registry) -> None`

Registers a project with the MCP server.

#### `get_tools() -> list[ToolDefinition]`

Returns available tools.

#### `call_tool(name, arguments) -> ToolResult` `async`

Calls a tool. Returns `ToolResult(success, data, error)`.

**Available Tools**

| Tool name | Input | Description |
|---|---|---|
| `execute_task` | `project_id, task_id, agent_role, instructions` | Submit task to an agent |
| `get_status` | `project_id, task_id?` | Query project/task status |
| `list_agents` | -- | List available agents |
| `get_project` | `project_id` | Project registry details |
| `list_projects` | -- | List registered projects |

### A2ARouter (`src/mcp/a2a.py`)

Agent-to-agent message routing.

```python
class A2ARouter:
    def __init__(self)
```

#### `send(message) -> None`

Places an `A2AMessage` into the recipient agent's mailbox.

#### `receive(agent_role) -> list[A2AMessage]`

Pulls all messages from an agent's mailbox (FIFO, consumed on read).

#### `broadcast(message) -> None`

Broadcasts a message to all agent mailboxes.

#### A2AMessage

```python
@dataclass
class A2AMessage:
    message_id: str
    from_agent: str
    to_agent: str
    message_type: A2AMessageType   # REQUEST | RESPONSE | BROADCAST | NOTIFY
    priority: A2APriority          # LOW | NORMAL | HIGH | URGENT
    subject: str
    body: str
    project_id: str | None = None
    task_id: str | None = None
    created_at: datetime           # auto-generated
```

---

## queue

Source: `src/queue/`

Dependency-based async task scheduling with multi-project priority ranking.

### TaskScheduler (`src/queue/scheduler.py`)

```python
class TaskScheduler:
    def __init__(self, concurrency: int = 3)
```

#### `add_task(task) -> None`

Registers a `TaskSpec`. Raises `ValueError` on duplicate `task_id`.

#### `add_tasks(tasks) -> None`

Registers multiple tasks at once.

#### `topological_sort() -> list[str]`

Returns execution order by dependency. Raises `CyclicDependencyError` on cycles.

#### `get_ready_tasks() -> list[TaskSpec]`

Returns tasks whose dependencies are all completed.

#### `run(executor) -> dict[str, TaskSpec]` `async`

Runs all tasks async with Semaphore limiting to `concurrency` concurrent executions.

#### TaskSpec

```python
@dataclass
class TaskSpec:
    task_id: str
    agent_role: str
    project_id: str
    depends_on: list[str] = field(default_factory=list)
    priority: int = 1
    payload: dict[str, Any] = field(default_factory=dict)
    status: TaskStatus = TaskStatus.PENDING
    result: Any = None
    error: str | None = None
```

`TaskStatus`: `PENDING | READY | RUNNING | COMPLETED | FAILED`

### PriorityRanker (`src/queue/priority.py`)

Ranks tasks by composite priority across multiple projects.

```python
class PriorityRanker:
    def __init__(self, project_weights=None, max_slots=5)
```

#### `set_project_weight(weight) -> None`

Sets `ProjectWeight(project_id, priority, deadline, pending_count)`.

#### `rank(tasks, now=None) -> list[RankedTask]`

Returns tasks sorted by score descending. `score = (project_priority x 10) + task_priority + deadline_bonus`

deadline_bonus: <=24h: +30 / <=72h: +15 / <=7d: +5 / overdue: +50

#### `allocate_slots(tasks, now=None) -> list[TaskSpec]`

Returns top `max_slots` tasks after ranking.

```python
from src.queue.scheduler import TaskScheduler, TaskSpec

scheduler = TaskScheduler(concurrency=3)
scheduler.add_tasks([
    TaskSpec("build", "backend", "proj-001", priority=10),
    TaskSpec("test", "tester", "proj-001", depends_on=["build"]),
])

async def executor(task):
    return await run_agent(task)

results = await scheduler.run(executor)
```

---

## errors

Source: `src/errors.py`

All Archon exceptions inherit from `ArchonError`. Catch specific subclasses for targeted error handling.

```
ArchonError
├── GitError
│   ├── GitCommandError(command, stderr)
│   ├── ProtectedPathError
│   └── ForcePushError
├── AgentError
│   ├── AgentTimeoutError
│   └── AgentParsingError
├── RuntimeSetupError
│   ├── VLLMConnectionError(endpoint, detail)
│   └── ClusterError
├── PipelineError
│   ├── QAError
│   └── GateEvaluationError
├── RegistryError
│   └── ProjectNotFoundError
├── MemoryError
│   └── VectorStoreError
├── InputValidationError                    # Phase 3
├── OutputValidationError                   # Phase 3
├── TokenBudgetExceededError                # Phase 3
├── PathGuardError                          # Phase 3
├── ObservabilityError                      # Phase 3
│   └── TracingBackendError
└── BenchmarkError                          # Phase 3
```

Each exception carries structured context for diagnostics:

```python
from src.errors import ProtectedPathError, TokenBudgetExceededError

try:
    await git_executor.auto_commit(handoff, template)
except ProtectedPathError as e:
    print(f"Protected path blocked: {e}")
except TokenBudgetExceededError as e:
    print(f"Budget exceeded: {e}")
```

---

## registry

Source: `src/registry/`

The Registry is the central configuration store for each project. It defines models, quality policies, Git settings, and runtime configuration.

### ProjectRegistry (`src/registry/models.py`)

```python
class ProjectRegistry(BaseModel):
    project_meta: ProjectMeta
    git_config: GitConfig
    agent_config: dict[str, AgentModelConfig] = {}
    quality_policy: QualityPolicy
    work_queue: WorkQueue
    memory_config: MemoryConfig | None = None
    metrics: ProjectMetrics
    human_gate_history: HumanGateHistory
```

#### Sub-models

| Model | Key fields | Purpose |
|---|---|---|
| `ProjectMeta` | `project_id`, `name`, `description`, `tech_stack` | Project identity |
| `GitConfig` | `repo`, `branch`, `protected_paths`, `auto_push` | Git settings |
| `AgentModelConfig` | `model`, `model_override`, `high_complexity_model`, `streaming`, `timeout_seconds`, `max_tokens` | Per-role LLM config |
| `QualityPolicy` | `min_review_score`, `min_coverage`, `max_retry_before_escalation`, `require_human_for_schema`, `require_human_for_external`, `sop_paths`, `dynamic_guardrail_paths` | Quality thresholds |
| `WorkQueue` | `pending_tasks`, `active_tasks`, `completed_tasks` | Task tracking |
| `MemoryConfig` | `redis_url`, `chroma_path`, `mem0_api_key` | Memory backend config |
| `ProjectMetrics` | `total_tasks`, `auto_commit_count`, `l1_count`, `l2_count`, `total_tokens`, `total_cost_usd` | Cumulative metrics |
| `HumanGateHistory` | `decisions: list[HumanGateDecision]` | Human review audit trail |

#### `get_model_for_role(role) -> str`

Returns LLM model name for a role. `model_override` takes precedence.

### RegistryStore (`src/registry/store.py`)

JSON file-based registry persistence. Location: `.harness/registry/{project_id}.json`

#### `load(project_id) -> ProjectRegistry`

Loads a registry. Raises `ProjectNotFoundError` if file not found.

#### `save(registry) -> None`

Persists registry as JSON.

#### `update_metrics(project_id, delta) -> None`

Accumulates metric deltas.

#### `update_work_queue(project_id, work_queue) -> None`

Replaces work_queue state.

```python
from src.registry.store import RegistryStore

store = RegistryStore(base_path=".harness/registry")
registry = store.load("proj-001")
registry.metrics.auto_commit_count += 1
store.save(registry)
```
