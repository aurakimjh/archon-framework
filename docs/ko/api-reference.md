# API Reference

🇺🇸 [English](../en/api-reference.md)

> 버전: 1.0.0 | 최종 수정: 2026-04-24

## 목차

- [agents — 에이전트](#agents)
- [gate — Human Gate](#gate)
- [orchestrator — 오케스트레이터](#orchestrator)
- [pipeline — QA / Git / 데모](#pipeline)
- [runtime — vLLM / 클러스터](#runtime)
- [memory — 3계층 메모리](#memory)
- [router — LLM 라우터](#router)
- [mcp — MCP / A2A](#mcp)
- [queue — 태스크 스케줄러](#queue)
- [notifications — 알림](#notifications)
- [errors — 예외](#errors)
- [registry — 레지스트리](#registry)

---

## agents

소스: `src/agents/`

### BaseAgent

```python
class BaseAgent(abc.ABC):
    role: AgentRole
```

모든 에이전트의 공통 베이스 클래스. 무상태로 동작하며, 태스크마다 `HandoffArtifact`로 컨텍스트를 주입받는다.

#### `__init__(role, a2a_router=None)`

| 파라미터 | 타입 | 설명 |
|---|---|---|
| `role` | `AgentRole` | 에이전트 역할 |
| `a2a_router` | `A2ARouter \| None` | A2A 메시지 라우터 (선택) |

#### `execute(handoff, registry) → HandoffArtifact` `async`

태스크를 실행하고 다음 핸드오프를 생성한다. 토큰 초과 시 자동으로 컨텍스트를 압축한다.

| 파라미터 | 타입 | 설명 |
|---|---|---|
| `handoff` | `HandoffArtifact` | 입력 핸드오프 |
| `registry` | `ProjectRegistry` | 프로젝트 레지스트리 |

#### `execute_streaming(handoff, registry) → AsyncIterator[str]` `async`

스트리밍 모드로 실행. 청크 단위로 텍스트를 yield한다. `AgentModelConfig.timeout_seconds` 타임아웃 적용.

#### `execute_with_streaming(handoff, registry, on_chunk=None) → HandoffArtifact` `async`

`AgentModelConfig.streaming`이 True면 스트리밍, 아니면 `execute()`로 폴백.

#### `send_a2a(to_agent, subject, body, *, message_type, priority, project_id, task_id) → bool`

다른 에이전트에게 A2A 메시지를 전송한다. `a2a_router` 미설정 시 False 반환.

#### `receive_a2a() → list[A2AMessage]`

이 에이전트의 mailbox에서 메시지를 수신한다.

#### `_parse_structured_output(result_text) → dict`

LLM 출력에서 `<archon-output>...</archon-output>` JSON 블록을 파싱한다.

```python
# LLM이 반환하는 구조화 출력 형식
"""
<archon-output>
{
  "summary": "작업 요약",
  "changed_files": [{"path": "src/foo.py", "change_type": "added", "reason": "..."}],
  "decisions": [{"decision": "결정 내용", "reason": "이유"}]
}
</archon-output>
"""
```

**예시**

```python
from src.agents.backend import BackendAgent
from src.mcp.a2a import A2ARouter

router = A2ARouter()
agent = BackendAgent(a2a_router=router)

result = await agent.execute(handoff, registry)
```

---

### 역할별 에이전트

| 클래스 | 파일 | 역할 |
|---|---|---|
| `BackendAgent` | `agents/backend.py` | API, DB, 비즈니스 로직 |
| `FrontendAgent` | `agents/frontend.py` | UI/UX 구현 |
| `TesterAgent` | `agents/tester.py` | 테스트 자동화, 커버리지 |
| `DevOpsAgent` | `agents/devops.py` | CI/CD, IaC, 인프라 |
| `DocsAgent` | `agents/docs.py` | 문서화, API 스펙 |
| `ReviewerAgent` | `agents/reviewer.py` | 코드 리뷰, review_score 산출 |

모두 `BaseAgent`를 상속하며 `_build_system_prompt(handoff, registry)` 추상 메서드를 구현한다.

---

## gate

소스: `src/gate/`

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

QA 결과와 정책을 종합해 gate_decision을 판정한다.

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

판정 우선순위: L4 > L3 > L2 (일반) > L2 (Dynamic Guardrails) > L2 (SOP) > L1 > AUTO_PASS

**예시**

```python
from src.gate.evaluator import evaluate_gate
from src.orchestrator.handoff import QualityGates
from src.registry.models import QualityPolicy

decision = evaluate_gate(
    quality=QualityGates(lint_result="passed", build_result="passed", review_score=85),
    policy=QualityPolicy(),
    changed_paths=["src/payments/checkout.py"],  # Dynamic Guardrails 트리거
)
# → GateDecision.L2_HUMAN
```

---

## orchestrator

소스: `src/orchestrator/`

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

에이전트 간 컨텍스트를 전달하는 표준 JSON 문서. 전체 스키마: [handoff-schema.md](handoff-schema.md)

#### 주요 서브 모델

| 모델 | 주요 필드 |
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

전체 파이프라인을 실행한다. 에이전트 실행 → QA → Reviewer → Gate 판정 → 커밋/에스컬레이션.

#### `process_chain(handoff, registry) → list[HandoffArtifact]` `async`

태스크 체인을 순차 실행한다. `DEFAULT_TASK_CHAINS`에 따라 연쇄 에이전트를 실행한다.

```python
DEFAULT_TASK_CHAINS: dict[str, list[str]] = {
    "backend":  ["tester", "docs"],
    "frontend": ["tester", "docs"],
    "tester":   [],
    "devops":   ["tester"],
    "docs":     [],
}
```

**예시**

```python
from src.orchestrator.orchestrator import Orchestrator

orch = Orchestrator(registry=registry, notifier=composite_notifier)
result = await orch.run(initial_handoff)
```

---

## pipeline

소스: `src/pipeline/`, `src/runtime/qa.py`, `src/runtime/git_executor.py`

### QA Pipeline (`src/runtime/qa.py`)

#### `run_qa_pipeline(project_root, registry, run_id=None) → QualityGates` `async`

lint, typecheck, test, build, security 스캔을 모두 병렬로 실행해 `QualityGates`를 반환한다. UUID 기반 `run_id`로 파일 격리를 보장한다.

#### `run_lint(project_root) → str` `async`

ruff check 실행. `"passed"` | `"failed"` | `"skipped"` 반환.

#### `run_typecheck(project_root) → str` `async`

mypy 실행. `"passed"` | `"failed"` | `"skipped"` 반환.

#### `run_tests(project_root, run_id=None) → TestResults` `async`

pytest 실행 + JUnit XML 파싱. `TestResults(unit_passed, unit_failed, coverage_percent)` 반환.

#### `run_coverage(project_root, run_id=None) → float` `async`

pytest --cov 실행. 커버리지 퍼센트 반환. 실패 시 `0.0`.

#### `run_security_scan(project_root) → SecurityScan` `async`

semgrep 실행 + JSON 파싱. `SecurityScan(tool, critical, high, medium, low)` 반환.

#### `run_build(project_root) → str` `async`

`compileall`로 Python 문법 검증. `"passed"` | `"failed"` | `"skipped"` 반환.

**예시**

```python
from src.runtime.qa import run_qa_pipeline

quality = await run_qa_pipeline(
    project_root="/path/to/project",
    registry=registry,
)
print(quality.lint_result)         # "passed"
print(quality.test_results.coverage_percent)  # 85.3
```

---

### GitExecutor (`src/runtime/git_executor.py`)

```python
class GitExecutor:
    def __init__(self, git_config: GitConfig)
```

#### `validate_protected_paths(handoff)` → `None`

`handoff.artifacts.changed_files`가 `git_config.protected_paths`를 침범하면 `ProtectedPathError`를 발생시킨다.

#### `auto_commit(handoff, message_template, repo_root=None) → str | None` `async`

1. protected_paths 검증 → 2. 브랜치 생성/체크아웃 → 3. 파일 스테이징 → 4. 커밋 → 5. 푸시.
변경사항 없으면 `None` 반환. 성공 시 커밋 SHA 반환.

#### `check_force_push_attempt(args) → bool` `async`

`--force`, `-f`, `--force-with-lease` 플래그 포함 여부 감지. L3_HALT 트리거용.

---

### DemoPipeline (`src/pipeline/demo_pipeline.py`)

Mock 시나리오 기반 데모/테스트 파이프라인. LLM 없이 전체 파이프라인 흐름을 테스트할 수 있다.

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

파이프라인 전체 실행. L1 시 최대 `max_retry_before_escalation`회 재시도.

```python
@dataclass
class PipelineResult:
    handoff: HandoffArtifact
    gate: GateDecision
    attempt: int
    committed: bool
    commit_sha: str | None
```

**시나리오**

| 시나리오 | 설명 |
|---|---|
| `auto_pass` | 첫 시도 AUTO_PASS |
| `l1` | 시도 0: 린트 실패 → L1, 시도 1: AUTO_PASS |
| `l2` | review_score=58 → 즉시 L2_HUMAN |
| `l1_exhausted` | 모든 시도 린트 실패 → max_retry 소진 → L2_HUMAN |

**step 이벤트**: `loop`, `backend`, `backend_done`, `qa`, `qa_done`, `reviewer`, `reviewer_done`, `gate`, `l1_rework`, `l2_escalated`, `l2_human`, `l3_halt`, `l4_deploy`, `commit`

**예시**

```python
from src.pipeline.demo_pipeline import DemoPipeline

pipeline = DemoPipeline(registry=registry, mock=True, scenario="l1")
result = await pipeline.run(initial_handoff)
print(result.gate)     # GateDecision.AUTO_PASS
print(result.attempt)  # 1
```

---

## runtime

소스: `src/runtime/`

### VLLMBridge (`src/runtime/vllm_bridge.py`)

GPU 워커 vLLM 서버를 LiteLLM에 통합한다.

```python
class VLLMBridge:
    def __init__(self, timeout: float = 5.0)
```

#### `register(endpoint)` → `None`

`VLLMEndpoint`를 등록한다.

#### `unregister(name) → bool`

등록 해제. 성공 시 True.

#### `health_check(name) → bool` `async`

단일 엔드포인트 헬스체크. 결과를 `_healthy` set에 반영.

#### `health_check_all() → dict[str, bool]` `async`

모든 엔드포인트 헬스체크.

#### `get_litellm_config(name) → dict | None`

LiteLLM completion 파라미터 dict 반환. `{"model", "api_base", "api_key", "max_tokens"}`.

#### `list_healthy() → list[VLLMEndpoint]`

정상 상태 엔드포인트만 반환.

#### VLLMEndpoint

```python
@dataclass
class VLLMEndpoint:
    name: str               # LiteLLM 모델 이름 (e.g. "vllm/qwen-27b")
    base_url: str           # vLLM 서버 URL (e.g. "http://gpu-node:8000")
    model_name: str         # vLLM에 로드된 실제 모델명
    api_key: str = "EMPTY"
    max_tokens: int = 4096
    gpu_memory_utilization: float = 0.9
    tensor_parallel_size: int = 1
    tags: list[str]         # 라우팅 태그
```

**예시**

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

Ray 클러스터 워커 노드를 관리한다.

#### `register_worker(config) → WorkerNode`

워커 등록. `WorkerConfig(node_id, node_type, gpu_count, memory_gb, ...)` 수신.

#### `unregister_worker(node_id) → bool`

워커 등록 해제.

#### `heartbeat(node_id) → bool`

워커 heartbeat 갱신. 존재하지 않으면 False.

#### `mark_offline(node_id) → bool`

워커를 OFFLINE으로 전환.

#### `drain_worker(node_id) → bool`

워커를 DRAINING 상태로 전환 (새 태스크 비할당).

#### `get_cluster_summary() → dict`

클러스터 요약: 워커 수, GPU 합계, 메모리 합계, 태스크 합계.

```python
WorkerType: "CPU" | "GPU" | "HYBRID"
WorkerStatus: "online" | "offline" | "degraded" | "draining"
```

---

## memory

소스: `src/memory/`

### MemoryStore (`src/memory/context_injector.py`)

3계층 메모리 파사드. 각 백엔드는 선택적으로 주입하며, None이면 인메모리 폴백.

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

L1 Redis에 스크래치 값 저장.

#### `get_scratch(project_id, task_id, key) → Any | None` `async`

L1 Redis에서 스크래치 값 조회.

#### `store_handoff(project_id, handoff_id, summary, metadata=None)`

L2 ChromaDB에 핸드오프 요약 저장.

#### `search_handoffs(project_id, query, n_results=5, threshold=0.85) → list[dict]`

L2 ChromaDB에서 유사 핸드오프 검색.

#### `store_pattern(project_id, pattern, reason="", user_id="archon")`

L3 Mem0에 패턴 저장.

#### `search_patterns(query, user_id="archon", limit=5) → list[dict]`

L3 Mem0에서 유사 패턴 검색 (크로스 프로젝트).

#### `inject_memory_context(task_instructions, project_id) → MemoryContext` `async`

L2+L3에서 관련 컨텍스트를 검색해 `MemoryContext`로 조합한다.

**예시**

```python
from src.memory.context_injector import MemoryStore
from src.memory.redis_scratchpad import RedisScratchpad
import redis.asyncio as aioredis

redis_client = aioredis.from_url("redis://localhost:6379/0")
store = MemoryStore(redis_scratchpad=RedisScratchpad(redis_client))

await store.set_scratch("proj-001", "task-001", "draft", {"status": "in_progress"})
ctx = await store.inject_memory_context("결제 API 구현", "proj-001")
```

---

### RedisScratchpad (`src/memory/redis_scratchpad.py`)

```python
class RedisScratchpad:
    def __init__(self, redis_client: Any, ttl: int = 86400)
```

키 형식: `archon:scratch:{project_id}:{task_id}:{key}`

| 메서드 | 설명 |
|---|---|
| `set(project_id, task_id, key, value, ttl=None)` | 값 저장 (JSON 직렬화) |
| `get(project_id, task_id, key) → Any \| None` | 값 조회 |
| `delete(project_id, task_id, key) → bool` | 값 삭제 |
| `list_keys(project_id, task_id) → list[str]` | 태스크의 모든 키 목록 |
| `clear_task(project_id, task_id) → int` | 태스크 데이터 전체 삭제. 삭제된 키 수 반환 |

---

### VectorStore (`src/memory/vector_store.py`)

```python
class VectorStore:
    def __init__(self, chroma_client: Any, collection_prefix: str = "archon")
```

프로젝트별 ChromaDB 컬렉션 격리. cosine similarity 기반 벡터 검색.

| 메서드 | 설명 |
|---|---|
| `store_handoff(project_id, handoff_id, summary, metadata=None)` | 핸드오프 벡터 저장 (upsert) |
| `search(project_id, query, n_results=5, threshold=0.85) → list[dict]` | 유사 핸드오프 검색 |
| `delete_handoff(project_id, handoff_id)` | 특정 핸드오프 삭제 |
| `delete_project(project_id)` | 프로젝트 컬렉션 전체 삭제 |
| `count(project_id) → int` | 저장된 핸드오프 수 |

검색 결과 형식: `{"id": str, "document": str, "metadata": dict, "similarity": float}`

---

### `compress_handoff(handoff, max_context_tokens=12000) → HandoffArtifact`

소스: `src/memory/compressor.py`

핸드오프가 토큰 한도를 초과하면 다단계 압축을 수행한다.

압축 순서: ① memory_context → ② completed_summary → ③ decisions_made → ④ next_instructions

#### `estimate_tokens(text) → int`

한영 혼합 텍스트의 토큰 수를 추정한다. (한글 2자 = 1토큰, ASCII 4자 = 1토큰)

#### `compress_text(text, max_tokens) → str`

문장 경계를 존중하며 텍스트를 truncate한다.

---

## router

소스: `src/router/`

### `get_model_for_role(role, registry=None) → str`

소스: `src/router/role_router.py`

우선순위: `model_override` > `model` > `ROLE_MODEL_MAP` 기본값

### `get_model_for_handoff(role, handoff, registry) → str`

핸드오프의 복잡도를 측정해 모델을 선택한다. HIGH 복잡도이고 `high_complexity_model` 설정 시 해당 모델 반환.

### `get_model_with_vllm(role, handoff, registry, vllm_bridge=None) → tuple[str, dict | None]`

vLLM healthy 워커 매칭 시 vLLM으로 라우팅, 아니면 기본 라우팅으로 폴백. `(model_name, litellm_config)` 튜플 반환.

### `measure_complexity(handoff) → ComplexityScore`

소스: `src/router/complexity.py`

8개 기준으로 복잡도를 측정한다.

```python
@dataclass
class ComplexityScore:
    level: ComplexityLevel   # LOW | MEDIUM | HIGH
    score: int               # 0~14점
    factors: list[str]       # 트리거된 기준 목록
```

| 기준 | 점수 |
|---|---|
| 지시사항 ≥ 500자 | +2 |
| 변경 파일 ≥ 5개 | +2 |
| 과거 결정 ≥ 3개 | +1 |
| 블로커 존재 | +2 |
| 외부 통합 | +2 |
| 스키마 변경 | +2 |
| 우선순위 ≥ 8 | +1 |
| 이전 L2+ gate | +2 |

레벨: LOW (0~3) / MEDIUM (4~6) / HIGH (7+)

**예시**

```python
from src.router.complexity import measure_complexity

score = measure_complexity(handoff)
print(score.level)    # ComplexityLevel.HIGH
print(score.score)    # 9
print(score.factors)  # ["schema_change", "external_integration", ...]
```

---

## mcp

소스: `src/mcp/`

### MCPServer (`src/mcp/server.py`)

외부 클라이언트가 Archon을 제어하는 MCP 도구 서버.

```python
class MCPServer:
    def __init__(self)
```

#### `register_project(registry)` → `None`

프로젝트를 MCP 서버에 등록한다.

#### `get_tools() → list[ToolDefinition]`

사용 가능한 도구 목록 반환.

#### `call_tool(name, arguments) → ToolResult` `async`

도구를 호출한다. 결과: `ToolResult(success, data, error)`.

**제공 도구**

| 도구명 | 입력 | 설명 |
|---|---|---|
| `execute_task` | `project_id, task_id, agent_role, instructions` | 태스크를 에이전트에게 제출 |
| `get_status` | `project_id, task_id?` | 프로젝트/태스크 상태 조회 |
| `list_agents` | — | 사용 가능한 에이전트 목록 |
| `get_project` | `project_id` | 프로젝트 레지스트리 상세 |
| `list_projects` | — | 등록된 프로젝트 목록 |

---

### A2ARouter (`src/mcp/a2a.py`)

에이전트 간 메시지 라우팅.

```python
class A2ARouter:
    def __init__(self)
```

#### `send(message) → None`

`A2AMessage`를 수신 에이전트의 mailbox에 넣는다.

#### `receive(agent_role) → list[A2AMessage]`

에이전트의 mailbox에서 모든 메시지를 꺼낸다 (FIFO, 수신 후 삭제).

#### `broadcast(message) → None`

모든 에이전트 mailbox에 메시지를 브로드캐스트한다.

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
    created_at: datetime           # 자동 생성
```

**예시**

```python
from src.mcp.a2a import A2ARouter, A2AMessage, A2AMessageType, A2APriority

router = A2ARouter()
backend_agent = BackendAgent(a2a_router=router)

backend_agent.send_a2a(
    to_agent="tester",
    subject="테스트 요청",
    body="결제 API 단위 테스트 작성 필요",
    message_type=A2AMessageType.REQUEST,
    priority=A2APriority.HIGH,
)
```

---

## queue

소스: `src/queue/`

### TaskScheduler (`src/queue/scheduler.py`)

의존성 기반 비동기 태스크 스케줄러.

```python
class TaskScheduler:
    def __init__(self, concurrency: int = 3)
```

#### `add_task(task)` → `None`

`TaskSpec`을 등록한다. 중복 `task_id`는 `ValueError` 발생.

#### `add_tasks(tasks)` → `None`

여러 태스크를 한 번에 등록.

#### `topological_sort() → list[str]`

의존성 기반 실행 순서 반환. 순환 의존성 시 `CyclicDependencyError` 발생.

#### `get_ready_tasks() → list[TaskSpec]`

현재 실행 가능한(의존성 모두 완료된) 태스크 목록.

#### `run(executor) → dict[str, TaskSpec]` `async`

모든 태스크를 비동기 실행. Semaphore로 최대 `concurrency`개 동시 실행.

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

**예시**

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

멀티 프로젝트 환경에서 태스크를 종합 우선순위로 정렬한다.

```python
class PriorityRanker:
    def __init__(self, project_weights=None, max_slots=5)
```

#### `set_project_weight(weight)` → `None`

`ProjectWeight(project_id, priority, deadline, pending_count)` 설정.

#### `rank(tasks, now=None) → list[RankedTask]`

score 내림차순 정렬. `score = (project_priority × 10) + task_priority + deadline_bonus`

deadline_bonus: 24h이내 +30 / 72h이내 +15 / 7일이내 +5 / 지남 +50

#### `allocate_slots(tasks, now=None) → list[TaskSpec]`

랭킹 후 `max_slots`개만 반환.

---

## notifications

소스: `src/notifications/`

### GateEvent (`src/notifications/base.py`)

Gate 판정 발생 시 생성되는 알림 이벤트.

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

프로퍼티: `.severity` (`"info"` | `"warning"` | `"error"` | `"critical"`), `.title`, `.summary`

### Notifier (추상 클래스)

```python
class Notifier(abc.ABC):
    async def notify(self, event: GateEvent) -> bool: ...
    def should_notify(self, event: GateEvent) -> bool: ...  # AUTO_PASS는 기본 미전송
```

### CompositeNotifier

```python
class CompositeNotifier(Notifier):
    def __init__(self, notifiers: list[Notifier] | None = None)
    def add(self, notifier: Notifier) -> None
    async def notify(self, event: GateEvent) -> bool
```

여러 Notifier에 동시 전송. 하나라도 성공하면 True.

### TerminalNotifier (`src/notifications/terminal.py`)

rich 라이브러리 TUI 패널 + macOS `osascript` 데스크탑 알림.

### SlackNotifier (`src/notifications/slack.py`)

Slack incoming webhook 알림. Gate 레벨별 색상/이모지 자동 적용.

**예시**

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

소스: `src/errors.py`

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

**예시**

```python
from src.errors import ProtectedPathError, GitCommandError

try:
    await git_executor.auto_commit(handoff, template)
except ProtectedPathError as e:
    print(f"보호 경로 접근 차단: {e}")
except GitCommandError as e:
    print(f"Git 명령 실패: {e.command} — {e.stderr}")
```

---

## registry

소스: `src/registry/`

### ProjectRegistry (`src/registry/models.py`)

프로젝트별 전체 설정을 담는 중앙 레지스트리. 전체 스키마: [registry-schema.md](registry-schema.md)

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

역할에 해당하는 LLM 모델명 반환. `model_override` 우선.

### RegistryStore (`src/registry/store.py`)

JSON 파일 기반 레지스트리 영속성. 저장 위치: `.harness/registry/{project_id}.json`

#### `load(project_id) → ProjectRegistry`

레지스트리를 로드한다. 파일 없으면 `ProjectNotFoundError` 발생.

#### `save(registry)` → `None`

레지스트리를 JSON으로 저장한다.

#### `update_metrics(project_id, delta)` → `None`

메트릭을 delta 누적 업데이트한다.

#### `update_work_queue(project_id, work_queue)` → `None`

work_queue 상태를 교체한다.

**예시**

```python
from src.registry.store import RegistryStore

store = RegistryStore(base_path=".harness/registry")
registry = store.load("proj-001")
registry.metrics.auto_commit_count += 1
store.save(registry)
```
