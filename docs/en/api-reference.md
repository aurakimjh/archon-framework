# API Reference

🇰🇷 [한국어](../ko/api-reference.md)

> Version: 1.0.0 | Last updated: 2026-04-24

## Table of Contents

- [agents](#agents)
- [gate — Human Gate](#gate)
- [orchestrator](#orchestrator)
- [pipeline — QA / Git / Demo](#pipeline)
- [runtime — vLLM / Cluster](#runtime)
- [memory — 3-Layer Memory](#memory)
- [router — LLM Router](#router)
- [mcp — MCP / A2A](#mcp)
- [queue — Task Scheduler](#queue)
- [notifications](#notifications)
- [errors](#errors)
- [registry](#registry)

---

## agents

Source: `src/agents/`

### BaseAgent

```python
class BaseAgent(abc.ABC):
    role: AgentRole
```

Common base class for all agents. Stateless — context is injected per task via `HandoffArtifact`.

#### `__init__(role, a2a_router=None)`

| Parameter | Type | Description |
|---|---|---|
| `role` | `AgentRole` | Agent role |
| `a2a_router` | `A2ARouter \| None` | A2A message router (optional) |

#### `execute(handoff, registry) → HandoffArtifact` `async`

Executes a task and produces the next handoff. Automatically compresses context on token overflow.

| Parameter | Type | Description |
|---|---|---|
| `handoff` | `HandoffArtifact` | Input handoff |
| `registry` | `ProjectRegistry` | Project registry |

#### `execute_streaming(handoff, registry) → AsyncIterator[str]` `async`

Streaming execution — yields text chunks. Applies `AgentModelConfig.timeout_seconds`.

#### `execute_with_streaming(handoff, registry, on_chunk=None) → HandoffArtifact` `async`

Uses streaming if `AgentModelConfig.streaming` is True, falls back to `execute()` otherwise.

#### `send_a2a(to_agent, subject, body, *, message_type, priority, project_id, task_id) → bool`

Sends an A2A message to another agent. Returns False if `a2a_router` is not configured.

#### `receive_a2a() → list[A2AMessage]`

Receives messages from this agent's mailbox.

#### `_parse_structured_output(result_text) → dict`

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

**Example**

```python
from src.agents.backend import BackendAgent
from src.mcp.a2a import A2ARouter

router = A2ARouter()
agent = BackendAgent(a2a_router=router)

result = await agent.execute(handoff, registry)
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
| `ReviewerAgent` | `agents/reviewer.py` | Code review, review_score |

All inherit `BaseAgent` and implement the abstract `_build_system_prompt(handoff, registry)` method.

---

## gate

Source: `src/gate/`

### GateDecision

```python
class GateDecision(StrEnum):
    AUTO_PASS = "auto_pass"
    L1_REWORK = "l1_rework"
    L2_HUMAN  = "l2_human"
    L3_HALT   = "l3_halt"
    L4_DEPLOY = "l4_deploy"
```

### `evaluate_gate(...)` → `GateDecision`

Synthesizes QA results and policy to determine gate_decision.

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

Decision priority: L4 > L3 > L2 (standard) > L2 (Dynamic Guardrails) > L2 (SOP) > L1 > AUTO_PASS

**Example**

```python
from src.gate.evaluator import evaluate_gate
from src.orchestrator.handoff import QualityGates
from src.registry.models import QualityPolicy

decision = evaluate_gate(
    quality=QualityGates(lint_result="passed", build_result="passed", review_score=85),
    policy=QualityPolicy(),
    changed_paths=["src/payments/checkout.py"],  # triggers Dynamic Guardrails
)
# → GateDecision.L2_HUMAN
```

---

## orchestrator

Source: `src/orchestrator/`

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

Standard JSON document for inter-agent context transfer. Full schema: [handoff-schema.md](handoff-schema.md)

#### Key Sub-models

| Model | Key fields |
|---|---|
| `Envelope` | `handoff_id`, `from_agent`, `to_agent`, `retry_count`, `parent_handoff_id` |
| `ProjectContext` | `project_id`, `git_repo`, `git_branch`, `tech_stack` |
| `Task` | `task_id`, `completed_summary`, `next_instructions`, `decisions_made`, `blockers` |
| `Artifacts` | `changed_files: list[ChangedFile]`, `generated_docs`, `dependency_changes` |
| `QualityGates` | `test_results`, `lint_result`, `build_result`, `security_scan`, `review_score`, `sop_compliance_score`, `gate_decision` |
| `HumanGatePackage` | `gate_level`, `trigger_reason`, `required_decision`, `decision_options`, `paused_agents` |
| `MemoryContext` | `relevant_past_decisions`, `known_patterns`, `error_history`, `human_feedback` |

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

#### `run(initial_handoff) → HandoffArtifact` `async`

Runs the full pipeline: agent execution → QA → Reviewer → Gate decision → commit/escalation.

#### `process_chain(handoff, registry) → list[HandoffArtifact]` `async`

Runs the task chain sequentially per `DEFAULT_TASK_CHAINS`.

```python
DEFAULT_TASK_CHAINS: dict[str, list[str]] = {
    "backend":  ["tester", "docs"],
    "frontend": ["tester", "docs"],
    "tester":   [],
    "devops":   ["tester"],
    "docs":     [],
}
```

**Example**

```python
from src.orchestrator.orchestrator import Orchestrator

orch = Orchestrator(registry=registry, notifier=composite_notifier)
result = await orch.run(initial_handoff)
```

---

## pipeline

Source: `src/pipeline/`, `src/runtime/qa.py`, `src/runtime/git_executor.py`

### QA Pipeline (`src/runtime/qa.py`)

#### `run_qa_pipeline(project_root, registry, run_id=None) → QualityGates` `async`

Runs lint, typecheck, test, build, and security scan in parallel, returning `QualityGates`. UUID-based `run_id` ensures file isolation.

#### `run_lint(project_root) → str` `async`

ruff check. Returns `"passed"` | `"failed"` | `"skipped"`.

#### `run_typecheck(project_root) → str` `async`

mypy. Returns `"passed"` | `"failed"` | `"skipped"`.

#### `run_tests(project_root, run_id=None) → TestResults` `async`

pytest + JUnit XML parsing. Returns `TestResults(unit_passed, unit_failed, coverage_percent)`.

#### `run_coverage(project_root, run_id=None) → float` `async`

pytest --cov. Returns coverage percent. Returns `0.0` on failure.

#### `run_security_scan(project_root) → SecurityScan` `async`

semgrep + JSON parsing. Returns `SecurityScan(tool, critical, high, medium, low)`.

#### `run_build(project_root) → str` `async`

Python syntax validation via `compileall`. Returns `"passed"` | `"failed"` | `"skipped"`.

**Example**

```python
from src.runtime.qa import run_qa_pipeline

quality = await run_qa_pipeline(
    project_root="/path/to/project",
    registry=registry,
)
print(quality.lint_result)                       # "passed"
print(quality.test_results.coverage_percent)     # 85.3
```

---

### GitExecutor (`src/runtime/git_executor.py`)

```python
class GitExecutor:
    def __init__(self, git_config: GitConfig)
```

#### `validate_protected_paths(handoff)` → `None`

Raises `ProtectedPathError` if any file in `handoff.artifacts.changed_files` touches `git_config.protected_paths`.

#### `auto_commit(handoff, message_template, repo_root=None) → str | None` `async`

1. Validate protected paths → 2. Create/checkout branch → 3. Stage files → 4. Commit → 5. Push.
Returns commit SHA on success, `None` if no changes.

#### `check_force_push_attempt(args) → bool` `async`

Detects `--force`, `-f`, `--force-with-lease` flags. Used to trigger L3_HALT.

---

### DemoPipeline (`src/pipeline/demo_pipeline.py`)

Mock scenario-based demo/test pipeline. Exercises the full pipeline flow without a running LLM.

```python
class DemoPipeline:
    def __init__(
        self,
        registry: ProjectRegistry,
        *,
        mock: bool = False,
        scenario: str = "auto_pass",
        dry_run: bool = False,
        on_step: StepCallback | None = None,
    )
```

#### `run(initial_handoff) → PipelineResult` `async`

Runs the full pipeline with automatic L1 retry up to `max_retry_before_escalation`.

```python
@dataclass
class PipelineResult:
    handoff: HandoffArtifact
    gate: GateDecision
    attempt: int
    committed: bool
    commit_sha: str | None
```

**Scenarios**

| Scenario | Description |
|---|---|
| `auto_pass` | AUTO_PASS on first attempt |
| `l1` | Attempt 0: lint fail → L1; attempt 1: AUTO_PASS |
| `l2` | review_score=58 → immediate L2_HUMAN |
| `l1_exhausted` | All attempts fail lint → retries exhausted → L2_HUMAN |

**Step events**: `loop`, `backend`, `backend_done`, `qa`, `qa_done`, `reviewer`, `reviewer_done`, `gate`, `l1_rework`, `l2_escalated`, `l2_human`, `l3_halt`, `l4_deploy`, `commit`

**Example**

```python
from src.pipeline.demo_pipeline import DemoPipeline

pipeline = DemoPipeline(registry=registry, mock=True, scenario="l1")
result = await pipeline.run(initial_handoff)
print(result.gate)     # GateDecision.AUTO_PASS
print(result.attempt)  # 1
```

---

## runtime

Source: `src/runtime/`

### VLLMBridge (`src/runtime/vllm_bridge.py`)

Integrates GPU worker vLLM servers into LiteLLM.

```python
class VLLMBridge:
    def __init__(self, timeout: float = 5.0)
```

#### `register(endpoint)` → `None`

Registers a `VLLMEndpoint`.

#### `unregister(name) → bool`

Unregisters an endpoint. Returns True on success.

#### `health_check(name) → bool` `async`

Health-checks a single endpoint; updates `_healthy` set.

#### `health_check_all() → dict[str, bool]` `async`

Health-checks all registered endpoints.

#### `get_litellm_config(name) → dict | None`

Returns LiteLLM completion parameters: `{"model", "api_base", "api_key", "max_tokens"}`.

#### `list_healthy() → list[VLLMEndpoint]`

Returns only healthy endpoints.

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
    tags: list[str]         # Routing tags
```

**Example**

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

### ClusterManager (`src/runtime/cluster.py`)

Manages Ray cluster worker nodes.

#### `register_worker(config) → WorkerNode`

Registers a worker. Accepts `WorkerConfig(node_id, node_type, gpu_count, memory_gb, ...)`.

#### `unregister_worker(node_id) → bool`

Unregisters a worker.

#### `heartbeat(node_id) → bool`

Updates worker heartbeat. Returns False if worker not found.

#### `mark_offline(node_id) → bool`

Transitions worker to OFFLINE.

#### `drain_worker(node_id) → bool`

Transitions worker to DRAINING (no new task allocation).

#### `get_cluster_summary() → dict`

Cluster summary: worker count, total GPUs, total memory, total tasks.

```python
WorkerType: "CPU" | "GPU" | "HYBRID"
WorkerStatus: "online" | "offline" | "degraded" | "draining"
```

---

## memory

Source: `src/memory/`

### MemoryStore (`src/memory/context_injector.py`)

3-layer memory facade. Each backend is optional; missing layers fall back to in-memory dict.

```python
class MemoryStore:
    def __init__(
        self,
        redis_scratchpad: RedisScratchpad | None = None,
        vector_store: VectorStore | None = None,
        mem0_store: Mem0Store | None = None,
    )
```

#### `set_scratch(project_id, task_id, key, value)` `async`

Saves a value to L1 Redis.

#### `get_scratch(project_id, task_id, key) → Any | None` `async`

Retrieves a value from L1 Redis.

#### `store_handoff(project_id, handoff_id, summary, metadata=None)`

Stores a handoff summary in L2 ChromaDB.

#### `search_handoffs(project_id, query, n_results=5, threshold=0.85) → list[dict]`

Searches for similar handoffs in L2 ChromaDB.

#### `store_pattern(project_id, pattern, reason="", user_id="archon")`

Stores a pattern in L3 Mem0.

#### `search_patterns(query, user_id="archon", limit=5) → list[dict]`

Searches for similar patterns in L3 Mem0 (cross-project).

#### `inject_memory_context(task_instructions, project_id) → MemoryContext` `async`

Queries L2+L3 using task instructions, assembles and returns `MemoryContext` for agent injection.

**Example**

```python
from src.memory.context_injector import MemoryStore
from src.memory.redis_scratchpad import RedisScratchpad
import redis.asyncio as aioredis

redis_client = aioredis.from_url("redis://localhost:6379/0")
store = MemoryStore(redis_scratchpad=RedisScratchpad(redis_client))

await store.set_scratch("proj-001", "task-001", "draft", {"status": "in_progress"})
ctx = await store.inject_memory_context("Payment API implementation", "proj-001")
```

---

### RedisScratchpad (`src/memory/redis_scratchpad.py`)

```python
class RedisScratchpad:
    def __init__(self, redis_client: Any, ttl: int = 86400)
```

Key format: `archon:scratch:{project_id}:{task_id}:{key}`

| Method | Description |
|---|---|
| `set(project_id, task_id, key, value, ttl=None)` | Store value (JSON-serialized) |
| `get(project_id, task_id, key) → Any \| None` | Retrieve value |
| `delete(project_id, task_id, key) → bool` | Delete value |
| `list_keys(project_id, task_id) → list[str]` | List all keys for a task |
| `clear_task(project_id, task_id) → int` | Delete all task data; returns count |

---

### VectorStore (`src/memory/vector_store.py`)

```python
class VectorStore:
    def __init__(self, chroma_client: Any, collection_prefix: str = "archon")
```

Per-project ChromaDB collection isolation. Cosine similarity vector search.

| Method | Description |
|---|---|
| `store_handoff(project_id, handoff_id, summary, metadata=None)` | Store handoff vector (upsert) |
| `search(project_id, query, n_results=5, threshold=0.85) → list[dict]` | Search similar handoffs |
| `delete_handoff(project_id, handoff_id)` | Delete a specific handoff |
| `delete_project(project_id)` | Delete entire project collection |
| `count(project_id) → int` | Number of stored handoffs |

Search result format: `{"id": str, "document": str, "metadata": dict, "similarity": float}`

---

### `compress_handoff(handoff, max_context_tokens=12000) → HandoffArtifact`

Source: `src/memory/compressor.py`

Multi-stage compression when handoff exceeds token limit.

Compression order: ① memory_context → ② completed_summary → ③ decisions_made → ④ next_instructions

#### `estimate_tokens(text) → int`

Estimates token count for mixed Korean/English text. (Korean: 2 chars = 1 token; ASCII: 4 chars = 1 token)

#### `compress_text(text, max_tokens) → str`

Truncates text while respecting sentence boundaries.

---

## router

Source: `src/router/`

### `get_model_for_role(role, registry=None) → str`

Source: `src/router/role_router.py`

Priority: `model_override` > `model` > `ROLE_MODEL_MAP` default

### `get_model_for_handoff(role, handoff, registry) → str`

Measures handoff complexity to select a model. Returns `high_complexity_model` for HIGH complexity if configured.

### `get_model_with_vllm(role, handoff, registry, vllm_bridge=None) → tuple[str, dict | None]`

Routes to vLLM if a healthy endpoint matches, otherwise falls back to standard routing. Returns `(model_name, litellm_config)`.

### `measure_complexity(handoff) → ComplexityScore`

Source: `src/router/complexity.py`

Measures complexity against 8 criteria.

```python
@dataclass
class ComplexityScore:
    level: ComplexityLevel   # LOW | MEDIUM | HIGH
    score: int               # 0–14 points
    factors: list[str]       # triggered criteria
```

| Criterion | Points |
|---|---|
| Instructions ≥ 500 chars | +2 |
| Changed files ≥ 5 | +2 |
| Past decisions ≥ 3 | +1 |
| Blocker present | +2 |
| External integration | +2 |
| Schema change | +2 |
| Priority ≥ 8 | +1 |
| Prior L2+ gate | +2 |

Levels: LOW (0–3) / MEDIUM (4–6) / HIGH (7+)

**Example**

```python
from src.router.complexity import measure_complexity

score = measure_complexity(handoff)
print(score.level)    # ComplexityLevel.HIGH
print(score.score)    # 9
print(score.factors)  # ["schema_change", "external_integration", ...]
```

---

## mcp

Source: `src/mcp/`

### MCPServer (`src/mcp/server.py`)

MCP tool server for external clients to control Archon.

```python
class MCPServer:
    def __init__(self)
```

#### `register_project(registry)` → `None`

Registers a project with the MCP server.

#### `get_tools() → list[ToolDefinition]`

Returns the list of available tools.

#### `call_tool(name, arguments) → ToolResult` `async`

Calls a tool. Returns `ToolResult(success, data, error)`.

**Available Tools**

| Tool name | Input | Description |
|---|---|---|
| `execute_task` | `project_id, task_id, agent_role, instructions` | Submit task to an agent |
| `get_status` | `project_id, task_id?` | Query project/task status |
| `list_agents` | — | List available agents |
| `get_project` | `project_id` | Project registry details |
| `list_projects` | — | List registered projects |

---

### A2ARouter (`src/mcp/a2a.py`)

Agent-to-agent message routing.

```python
class A2ARouter:
    def __init__(self)
```

#### `send(message)` → `None`

Places an `A2AMessage` into the recipient agent's mailbox.

#### `receive(agent_role) → list[A2AMessage]`

Pulls all messages from an agent's mailbox (FIFO, consumed on read).

#### `broadcast(message)` → `None`

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

**Example**

```python
from src.mcp.a2a import A2ARouter, A2AMessageType, A2APriority

router = A2ARouter()
backend_agent = BackendAgent(a2a_router=router)

backend_agent.send_a2a(
    to_agent="tester",
    subject="Test request",
    body="Unit tests needed for payment API",
    message_type=A2AMessageType.REQUEST,
    priority=A2APriority.HIGH,
)
```

---

## queue

Source: `src/queue/`

### TaskScheduler (`src/queue/scheduler.py`)

Dependency-based async task scheduler.

```python
class TaskScheduler:
    def __init__(self, concurrency: int = 3)
```

#### `add_task(task)` → `None`

Registers a `TaskSpec`. Raises `ValueError` on duplicate `task_id`.

#### `add_tasks(tasks)` → `None`

Registers multiple tasks at once.

#### `topological_sort() → list[str]`

Returns execution order by dependency. Raises `CyclicDependencyError` on cycles.

#### `get_ready_tasks() → list[TaskSpec]`

Returns tasks whose dependencies are all completed.

#### `run(executor) → dict[str, TaskSpec]` `async`

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

**Example**

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

### PriorityRanker (`src/queue/priority.py`)

Ranks tasks by composite priority across multiple projects.

```python
class PriorityRanker:
    def __init__(self, project_weights=None, max_slots=5)
```

#### `set_project_weight(weight)` → `None`

Sets `ProjectWeight(project_id, priority, deadline, pending_count)`.

#### `rank(tasks, now=None) → list[RankedTask]`

Returns tasks sorted by score descending. `score = (project_priority × 10) + task_priority + deadline_bonus`

deadline_bonus: ≤24h: +30 / ≤72h: +15 / ≤7d: +5 / overdue: +50

#### `allocate_slots(tasks, now=None) → list[TaskSpec]`

Returns top `max_slots` tasks after ranking.

---

## notifications

Source: `src/notifications/`

### GateEvent (`src/notifications/base.py`)

Notification event generated when a gate decision fires.

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

### Notifier (abstract class)

```python
class Notifier(abc.ABC):
    async def notify(self, event: GateEvent) -> bool: ...
    def should_notify(self, event: GateEvent) -> bool: ...  # AUTO_PASS suppressed by default
```

### CompositeNotifier

```python
class CompositeNotifier(Notifier):
    def __init__(self, notifiers: list[Notifier] | None = None)
    def add(self, notifier: Notifier) -> None
    async def notify(self, event: GateEvent) -> bool
```

Fan-out to all notifiers simultaneously. Returns True if any succeeds.

### TerminalNotifier (`src/notifications/terminal.py`)

rich TUI panel + macOS `osascript` desktop notifications.

### SlackNotifier (`src/notifications/slack.py`)

Slack incoming webhook. Automatic color/emoji per gate level.

**Example**

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

## errors

Source: `src/errors.py`

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
└── MemoryError
    └── VectorStoreError
```

**Example**

```python
from src.errors import ProtectedPathError, GitCommandError

try:
    await git_executor.auto_commit(handoff, template)
except ProtectedPathError as e:
    print(f"Protected path blocked: {e}")
except GitCommandError as e:
    print(f"Git command failed: {e.command} — {e.stderr}")
```

---

## registry

Source: `src/registry/`

### ProjectRegistry (`src/registry/models.py`)

Central configuration store for a project. Full schema: [registry-schema.md](registry-schema.md)

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

#### `get_model_for_role(role) → str`

Returns LLM model name for a role. `model_override` takes precedence.

### RegistryStore (`src/registry/store.py`)

JSON file-based registry persistence. Location: `.harness/registry/{project_id}.json`

#### `load(project_id) → ProjectRegistry`

Loads a registry. Raises `ProjectNotFoundError` if file not found.

#### `save(registry)` → `None`

Persists registry as JSON.

#### `update_metrics(project_id, delta)` → `None`

Accumulates metric deltas.

#### `update_work_queue(project_id, work_queue)` → `None`

Replaces work_queue state.

**Example**

```python
from src.registry.store import RegistryStore

store = RegistryStore(base_path=".harness/registry")
registry = store.load("proj-001")
registry.metrics.auto_commit_count += 1
store.save(registry)
```
