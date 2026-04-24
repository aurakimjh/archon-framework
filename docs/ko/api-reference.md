# API Reference

[English](../en/api-reference.md)

> 버전: 2.0.0 | 최종 수정: 2026-04-24

## 목차

- [agents — 에이전트](#agents)
- [gate — Human Gate](#gate)
- [orchestrator — 오케스트레이터](#orchestrator)
- [router — LLM 라우터](#router)
- [runtime — Git / vLLM / Ollama / 클러스터 / KubeRay / 하이브리드 클라우드](#runtime)
- [memory — 3계층 메모리](#memory)
- [guardrails — 입출력 검증 및 예산 관리](#guardrails)
- [observability — 트레이싱 및 텔레메트리](#observability)
- [benchmark — 모델 벤치마크](#benchmark)
- [evolution — 자가 튜닝 파이프라인](#evolution)
- [dashboard — 웹 대시보드 및 WebSocket](#dashboard)
- [healing — 자가 복구 및 진단](#healing)
- [notifications — 알림](#notifications)
- [mcp — MCP / A2A](#mcp)
- [queue — 태스크 스케줄러](#queue)
- [errors — 예외](#errors)
- [registry — 레지스트리](#registry)

---

## agents

소스: `src/agents/`

에이전트는 Archon의 핵심 실행 단위입니다. 각 에이전트는 `HandoffArtifact`를 입력받아 작업(코드 생성, 테스트, 리뷰 등)을 수행하고, 다음 단계를 위한 새로운 `HandoffArtifact`를 생성합니다. 모든 에이전트는 무상태(stateless)로 동작하며, 컨텍스트는 핸드오프를 통해서만 전달됩니다.

### BaseAgent

```python
class BaseAgent(abc.ABC):
    role: AgentRole
```

모든 에이전트의 공통 베이스 클래스입니다. 무상태로 동작하며, 태스크마다 `HandoffArtifact`로 컨텍스트를 주입받습니다.

#### `__init__(role, a2a_router=None)`

| 파라미터 | 타입 | 설명 |
|---|---|---|
| `role` | `AgentRole` | 에이전트 역할 enum 값 |
| `a2a_router` | `A2ARouter \| None` | A2A 메시지 라우터 (선택) |

#### `execute(handoff, registry) -> HandoffArtifact` `async`

태스크를 실행하고 다음 핸드오프를 생성합니다. 토큰 한도를 초과하면 자동으로 컨텍스트를 압축합니다.

| 파라미터 | 타입 | 설명 |
|---|---|---|
| `handoff` | `HandoffArtifact` | 태스크와 컨텍스트가 담긴 입력 핸드오프 |
| `registry` | `ProjectRegistry` | 프로젝트 설정 레지스트리 |

**반환값:** 완료된 작업과 다음 지시사항이 담긴 새로운 `HandoffArtifact`.

```python
from src.agents.backend import BackendAgent

agent = BackendAgent()
result = await agent.execute(handoff, registry)
print(result.task.completed_summary)
```

#### `execute_streaming(handoff, registry) -> AsyncIterator[str]` `async`

스트리밍 모드로 실행합니다. LLM이 생성하는 텍스트를 청크 단위로 yield합니다. `AgentModelConfig.timeout_seconds` 타임아웃이 적용됩니다.

실시간 출력이 필요한 경우(터미널 UI, 대시보드 스트리밍 등)에 사용하세요.

```python
async for chunk in agent.execute_streaming(handoff, registry):
    print(chunk, end="", flush=True)
```

#### `execute_with_streaming(handoff, registry, on_chunk=None) -> HandoffArtifact` `async`

적응형 실행: `AgentModelConfig.streaming`이 True이면 스트리밍, 아니면 `execute()`로 폴백합니다. 선택적 `on_chunk` 콜백으로 각 청크를 수신할 수 있습니다.

| 파라미터 | 타입 | 설명 |
|---|---|---|
| `handoff` | `HandoffArtifact` | 입력 핸드오프 |
| `registry` | `ProjectRegistry` | 프로젝트 레지스트리 |
| `on_chunk` | `Callable[[str], None] \| None` | 스트리밍 청크 콜백 |

#### `_self_correct_output(result_text, handoff) -> str` `async`

*Phase 3.* `_parse_structured_output()`이 실패했을 때, 잘못된 출력을 LLM에 다시 보내 수정을 요청합니다. 최대 2회 재시도 후 `AgentParsingError`를 발생시킵니다.

활용 사례: LLM이 간헐적으로 `<archon-output>` 블록에 잘못된 JSON을 생성할 때 안정성을 향상시킵니다.

#### `_build_handoff_from_parsed(parsed, handoff) -> HandoffArtifact`

*Phase 3.* `_parse_structured_output()`에서 파싱된 dict를 적절한 `HandoffArtifact`로 변환합니다. 필드 매핑, 기본값 설정, 봉투(envelope) 생성을 처리합니다.

| 파라미터 | 타입 | 설명 |
|---|---|---|
| `parsed` | `dict` | 파싱된 구조화 출력 딕셔너리 |
| `handoff` | `HandoffArtifact` | 원본 입력 핸드오프 (컨텍스트 복사용) |

#### `_extract_structured_fields(result_text) -> dict`

*Phase 3.* `<archon-output>` 블록이 없을 때의 폴백 추출 메서드입니다. 자유형 LLM 텍스트에서 패턴 매칭을 사용하여 summary, changed_files, decisions를 추출합니다.

#### `send_a2a(to_agent, subject, body, *, message_type, priority, project_id, task_id) -> bool`

다른 에이전트에게 A2A 메시지를 전송합니다. `a2a_router` 미설정 시 False를 반환합니다.

#### `receive_a2a() -> list[A2AMessage]`

이 에이전트의 mailbox에서 메시지를 수신합니다.

#### `_parse_structured_output(result_text) -> dict`

LLM 출력에서 `<archon-output>...</archon-output>` JSON 블록을 파싱합니다.

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

모두 `BaseAgent`를 상속하며 `_build_system_prompt(handoff, registry)` 추상 메서드를 구현합니다. 각 에이전트는 레지스트리에서 프로젝트 컨텍스트, 기술 스택, 코딩 가이드라인을 포함한 역할별 시스템 프롬프트를 구성합니다.

```python
from src.agents.backend import BackendAgent
from src.agents.tester import TesterAgent
from src.mcp.a2a import A2ARouter

router = A2ARouter()
backend = BackendAgent(a2a_router=router)
tester = TesterAgent(a2a_router=router)

# 백엔드 작업 실행 후 테스터에게 핸드오프
result = await backend.execute(handoff, registry)
test_result = await tester.execute(result, registry)
```

---

## gate

소스: `src/gate/`

Gate 모듈은 QA 이후의 분기를 결정합니다: 자동 통과, 재작업, 인간 에스컬레이션, 중지, 또는 배포. 문제 있는 코드가 배포되는 것을 방지하는 안전장치입니다.

### GateDecision

```python
class GateDecision(StrEnum):
    AUTO_PASS = "auto_pass"
    L1_REWORK = "l1_rework"
    L2_HUMAN  = "l2_human"
    L3_HALT   = "l3_halt"
    L4_DEPLOY = "l4_deploy"
```

| 값 | 의미 | 동작 |
|---|---|---|
| `AUTO_PASS` | 모든 검사 통과 | 자동 커밋 후 진행 |
| `L1_REWORK` | 경미한 문제 (린트, 테스트) | 에이전트가 자동 재시도 |
| `L2_HUMAN` | 인간 리뷰 필요 | 파이프라인 일시정지 후 알림 |
| `L3_HALT` | 심각한 문제 감지 | 전체 파이프라인 중지 |
| `L4_DEPLOY` | 배포 요청 | 인간의 명시적 승인 필요 |

### `evaluate_gate(...)` -> `GateDecision`

QA 결과와 정책을 종합해 gate 판정을 내리는 핵심 함수입니다. 7단계 우선순위 체인으로 동작합니다.

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

| 파라미터 | 타입 | 설명 |
|---|---|---|
| `quality` | `QualityGates` | QA 파이프라인 결과 (린트, 테스트, 빌드, review_score 등) |
| `policy` | `QualityPolicy` | 프로젝트 레지스트리의 품질 임계값과 규칙 |
| `has_schema_change` | `bool` | DB 스키마 변경 여부 |
| `has_external_integration` | `bool` | 외부 API 관련 여부 |
| `is_deploy_request` | `bool` | 배포 작업 여부 |
| `retry_count` | `int` | L1 재시도 횟수 |
| `changed_paths` | `list[str] \| None` | 변경된 파일 경로 (Dynamic Guardrails용) |
| `task_instructions` | `str` | 원본 태스크 지시사항 (SOP 매칭용) |

**7단계 판정 우선순위:** L4 > L3 > L2 (일반) > L2 (Dynamic Guardrails) > L2 (SOP) > L1 > AUTO_PASS

**반환값:** `GateDecision`

```python
from src.gate.evaluator import evaluate_gate
from src.orchestrator.handoff import QualityGates
from src.registry.models import QualityPolicy

decision = evaluate_gate(
    quality=QualityGates(lint_result="passed", build_result="passed", review_score=85),
    policy=QualityPolicy(),
    changed_paths=["src/payments/checkout.py"],  # Dynamic Guardrails 트리거
)
# -> GateDecision.L2_HUMAN
```

---

## orchestrator

소스: `src/orchestrator/`

오케스트레이터는 전체 파이프라인을 구동합니다: 에이전트를 선택하고, 실행하고, QA를 거치고, 리뷰어를 호출하고, Gate를 평가한 후 커밋하거나 에스컬레이션합니다.

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

에이전트 간 컨텍스트를 전달하는 표준 JSON 문서입니다. 모든 에이전트가 하나를 받고 하나를 생성합니다. 전체 스키마: [handoff-schema.md](handoff-schema.md)

#### 서브 모델

| 모델 | 주요 필드 | 용도 |
|---|---|---|
| `Envelope` | `handoff_id`, `from_agent`, `to_agent`, `retry_count`, `parent_handoff_id` | 라우팅 메타데이터 |
| `ProjectContext` | `project_id`, `git_repo`, `git_branch`, `tech_stack` | 프로젝트 정보 |
| `Task` | `task_id`, `completed_summary`, `next_instructions`, `decisions_made`, `blockers` | 태스크 상태 |
| `Artifacts` | `changed_files: list[ChangedFile]`, `generated_docs`, `dependency_changes` | 작업 산출물 |
| `QualityGates` | `test_results`, `lint_result`, `build_result`, `security_scan`, `review_score`, `sop_compliance_score`, `gate_decision` | QA 결과 |
| `HumanGatePackage` | `gate_level`, `trigger_reason`, `required_decision`, `decision_options`, `paused_agents` | 인간 리뷰 정보 |
| `MemoryContext` | `relevant_past_decisions`, `known_patterns`, `error_history`, `human_feedback` | 주입된 메모리 |

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

| 파라미터 | 타입 | 설명 |
|---|---|---|
| `registry` | `ProjectRegistry` | 프로젝트 설정 |
| `notifier` | `Notifier \| None` | Gate 이벤트 알림기 (Slack, 터미널 등) |
| `vllm_bridge` | `VLLMBridge \| None` | GPU 라우팅을 위한 vLLM 통합 |
| `a2a_router` | `A2ARouter \| None` | 에이전트 간 메시징 |

#### `run(initial_handoff) -> HandoffArtifact` `async`

전체 파이프라인을 실행합니다: 에이전트 실행 -> QA -> 리뷰어 -> Gate 판정 -> 커밋/에스컬레이션. L1 재시도를 자동으로 처리합니다.

#### `process_handoff(handoff) -> HandoffArtifact` `async`

단일 핸드오프를 하나의 에이전트 사이클을 통해 처리합니다. L1 루프를 돌지 않습니다 -- 전체 루프는 `run()`을 사용하세요.

#### `process_chain(handoff, registry) -> list[HandoffArtifact]` `async`

`DEFAULT_TASK_CHAINS`에 따라 태스크 체인을 순차 실행합니다. 예를 들어, 백엔드 태스크 완료 후 자동으로 테스터와 문서 에이전트를 실행합니다.

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

소스: `src/router/`

라우터는 각 에이전트 호출에 사용할 LLM 모델을 선택합니다. 에이전트 역할, 태스크 복잡도, 사용 가능한 GPU 워커, 프로바이더 설정을 고려합니다.

### role_router.py

#### `get_model_for_role(role, registry=None) -> str`

역할에 대해 설정된 모델을 반환합니다. 우선순위: `model_override` > `model` > `ROLE_MODEL_MAP` 기본값

| 파라미터 | 타입 | 설명 |
|---|---|---|
| `role` | `str` | 에이전트 역할 (예: "backend", "tester") |
| `registry` | `ProjectRegistry \| None` | agent_config가 포함된 레지스트리 |

#### `get_model_for_handoff(role, handoff, registry) -> str`

핸드오프의 복잡도를 측정하여 모델을 선택합니다. 복잡도가 HIGH이고 `high_complexity_model`이 설정되어 있으면 해당 모델을 반환합니다.

| 파라미터 | 타입 | 설명 |
|---|---|---|
| `role` | `str` | 에이전트 역할 |
| `handoff` | `HandoffArtifact` | 현재 핸드오프 (복잡도 측정용) |
| `registry` | `ProjectRegistry` | 프로젝트 레지스트리 |

#### `get_model_with_vllm(role, handoff, registry, vllm_bridge=None) -> tuple[str, dict | None]`

정상 상태의 vLLM 엔드포인트가 역할과 매칭되면 vLLM으로 라우팅하고, 아니면 기본 라우팅으로 폴백합니다. `(model_name, litellm_config)` 튜플을 반환합니다. 비-vLLM 모델의 경우 `litellm_config`는 None입니다.

#### `get_model_with_ollama(role, handoff, registry, ollama_bridge=None) -> tuple[str, dict | None]`

*Phase 3.* 사용 가능한 로컬 Ollama 인스턴스가 있고 역할이 매칭되면 해당 인스턴스로 라우팅합니다. 개발 환경이나 저지연 태스크에 유용합니다. `(model_name, litellm_config)` 반환.

#### `get_model_with_provider(role, handoff, registry, vllm_bridge=None, ollama_bridge=None) -> tuple[str, dict | None]`

*Phase 3.* 통합 라우팅 함수로, vLLM -> Ollama -> 클라우드 API 순서로 시도합니다. 모델 선택을 위한 권장 진입점입니다.

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

8개 기준으로 핸드오프 복잡도를 측정합니다. 라우터가 더 성능 좋은(그리고 비싼) 모델을 사용할지 결정하는 데 사용됩니다.

```python
@dataclass
class ComplexityScore:
    level: ComplexityLevel   # LOW | MEDIUM | HIGH
    score: int               # 0~14점
    factors: list[str]       # 트리거된 기준 목록
```

| 기준 | 점수 |
|---|---|
| 지시사항 >= 500자 | +2 |
| 변경 파일 >= 5개 | +2 |
| 과거 결정 >= 3개 | +1 |
| 블로커 존재 | +2 |
| 외부 통합 | +2 |
| 스키마 변경 | +2 |
| 우선순위 >= 8 | +1 |
| 이전 L2+ gate | +2 |

레벨: LOW (0~3) / MEDIUM (4~6) / HIGH (7+)

#### `select_model_by_complexity(score, agent_config) -> str`

*Phase 3.* `ComplexityScore`와 `AgentModelConfig`를 받아 적절한 모델명을 반환합니다. HIGH 복잡도 -> `high_complexity_model`, 그 외 -> 기본 모델.

```python
from src.router.complexity import measure_complexity, select_model_by_complexity

score = measure_complexity(handoff)
model = select_model_by_complexity(score, registry.agent_config["backend"])
print(f"{score.level} 복잡도(score={score.score})에 대해 {model} 사용")
```

---

## runtime

소스: `src/runtime/`

런타임 모듈은 인프라 통합을 제공합니다: Git 작업, GPU 서버 브릿지, 클러스터 관리, 하이브리드 클라우드 스케줄링.

### GitExecutor (`src/runtime/git_executor.py`)

안전 가드레일(보호 경로, force-push 감지)과 함께 모든 Git 작업을 처리합니다.

```python
class GitExecutor:
    def __init__(self, git_config: GitConfig)
```

#### `auto_commit(handoff, message_template, repo_root=None) -> str | None` `async`

전체 커밋 워크플로우: 1) 보호 경로 검증 -> 2) 브랜치 생성/체크아웃 -> 3) 파일 스테이징 -> 4) 커밋 -> 5) 푸시. 성공 시 커밋 SHA를 반환하고, 변경사항이 없으면 `None`을 반환합니다.

| 파라미터 | 타입 | 설명 |
|---|---|---|
| `handoff` | `HandoffArtifact` | 변경 파일이 담긴 핸드오프 |
| `message_template` | `str` | 커밋 메시지 템플릿 |
| `repo_root` | `str \| None` | Git 저장소 루트 (기본값: git_config) |

#### `validate_protected_paths(handoff) -> None`

`handoff.artifacts.changed_files`가 `git_config.protected_paths`를 침범하면 `ProtectedPathError`를 발생시킵니다.

#### `save_snapshot(repo_root=None) -> Snapshot`

*Phase 3.* 현재 HEAD 커밋을 이름이 지정된 스냅샷으로 캡처합니다. 나중에 롤백할 때 사용합니다.

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

*Phase 3.* 작업 트리를 이전에 저장한 스냅샷으로 하드 리셋합니다. 성공 시 True를 반환합니다. 커밋되지 않은 변경사항이 삭제되므로 주의하세요.

#### `list_snapshots() -> list[Snapshot]`

*Phase 3.* 저장된 모든 스냅샷을 최신순으로 반환합니다.

#### `clear_snapshots() -> None`

*Phase 3.* 메모리에서 저장된 모든 스냅샷을 제거합니다.

```python
from src.runtime.git_executor import GitExecutor

git = GitExecutor(git_config=registry.git_config)

# 위험한 작업 전에 스냅샷 저장
snapshot = git.save_snapshot()

# 작업 수행...
sha = await git.auto_commit(handoff, "feat(backend): 결제 API 추가")

# 문제 발생 시 롤백
await git.rollback_to_snapshot(snapshot)
```

---

### VLLMBridge (`src/runtime/vllm_bridge.py`)

자체 호스팅 vLLM GPU 서버를 LiteLLM에 통합합니다. 엔드포인트를 등록하고, 헬스체크를 수행하고, LiteLLM 호환 설정을 가져옵니다.

```python
class VLLMBridge:
    def __init__(self, timeout: float = 5.0)
```

| 파라미터 | 타입 | 설명 |
|---|---|---|
| `timeout` | `float` | 헬스체크 HTTP 타임아웃 (초) |

#### `register(endpoint) -> None`

`VLLMEndpoint`를 등록합니다.

#### `health_check(name) -> bool` `async`

이름으로 단일 엔드포인트를 헬스체크합니다. 내부 정상/비정상 상태를 업데이트합니다.

#### `get_litellm_config(name) -> dict | None`

LiteLLM completion 파라미터를 반환합니다: `{"model", "api_base", "api_key", "max_tokens"}`. 엔드포인트가 없으면 None을 반환합니다.

#### VLLMEndpoint

```python
@dataclass
class VLLMEndpoint:
    name: str               # LiteLLM 모델 이름 (예: "vllm/qwen-27b")
    base_url: str           # vLLM 서버 URL (예: "http://gpu-node:8000")
    model_name: str         # vLLM에 로드된 실제 모델명
    api_key: str = "EMPTY"
    max_tokens: int = 4096
    gpu_memory_utilization: float = 0.9
    tensor_parallel_size: int = 1
    tags: list[str]         # 라우팅 태그 (예: ["backend", "tester"])
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

*Phase 3.* 개발 환경 및 저지연 추론을 위한 로컬 Ollama 인스턴스 통합입니다. VLLMBridge와 유사하지만 Ollama의 REST API를 사용합니다.

```python
class OllamaBridge:
    def __init__(self, base_url: str = "http://localhost:11434", timeout: float = 5.0)
```

| 파라미터 | 타입 | 설명 |
|---|---|---|
| `base_url` | `str` | Ollama 서버 URL |
| `timeout` | `float` | HTTP 타임아웃 (초) |

#### `register(model_name, tags=None) -> None`

라우팅을 위한 모델을 등록합니다.

#### `health_check() -> bool` `async`

Ollama 서버가 응답하는지 확인합니다.

#### `pull_model(model_name) -> bool` `async`

Ollama 레지스트리에서 모델을 풀(pull)합니다. 완료 시 True를 반환합니다.

#### `list_models() -> list[str]` `async`

로컬에서 사용 가능한 모든 모델 목록을 반환합니다.

#### `get_litellm_config(model_name) -> dict | None`

지정된 모델에 대한 LiteLLM 호환 설정을 반환합니다.

```python
from src.runtime.ollama_bridge import OllamaBridge

ollama = OllamaBridge()
if await ollama.health_check():
    await ollama.pull_model("qwen2.5:14b")
    config = ollama.get_litellm_config("qwen2.5:14b")
```

---

### ClusterManager (`src/runtime/cluster.py`)

Ray 클러스터 워커 노드를 관리합니다. 워커 상태, GPU 할당을 추적하고 클러스터 요약을 제공합니다.

```python
class ClusterManager:
    def __init__(self)
```

#### `register_worker(config) -> WorkerNode`

워커를 등록합니다. `WorkerConfig(node_id, node_type, gpu_count, memory_gb, ...)` 수신.

#### `heartbeat(node_id) -> bool`

워커 heartbeat 타임스탬프를 갱신합니다. 워커가 없으면 False를 반환합니다.

#### `get_cluster_summary() -> dict`

클러스터 요약을 반환합니다: 워커 수, GPU 합계, 메모리 합계, 태스크 합계.

```python
WorkerType: "CPU" | "GPU" | "HYBRID"
WorkerStatus: "online" | "offline" | "degraded" | "draining"
```

---

### KubeRayManager (`src/runtime/kuberay_manager.py`)

*Phase 3.* KubeRay 오퍼레이터를 통해 Kubernetes에서 Ray 클러스터를 관리합니다. YAML 매니페스트를 생성하고 클러스터 라이프사이클을 관리합니다.

```python
class KubeRayManager:
    def __init__(self, namespace: str = "default", kubeconfig: str | None = None)
```

| 파라미터 | 타입 | 설명 |
|---|---|---|
| `namespace` | `str` | Ray 클러스터용 Kubernetes 네임스페이스 |
| `kubeconfig` | `str \| None` | kubeconfig 파일 경로 (기본값: 인-클러스터) |

#### `deploy_cluster(config) -> dict` `async`

새 Ray 클러스터를 배포합니다. 엔드포인트 URL이 포함된 클러스터 상태 dict를 반환합니다.

#### `scale_workers(cluster_name, replicas) -> dict` `async`

기존 클러스터의 워커 Pod를 스케일링합니다.

| 파라미터 | 타입 | 설명 |
|---|---|---|
| `cluster_name` | `str` | Ray 클러스터 이름 |
| `replicas` | `int` | 목표 워커 레플리카 수 |

#### `get_cluster_status(cluster_name) -> dict` `async`

현재 클러스터 상태를 반환합니다: 단계, 준비된 워커, 헤드 노드 엔드포인트.

#### `delete_cluster(cluster_name) -> bool` `async`

Ray 클러스터와 관련된 모든 리소스를 삭제합니다.

#### `generate_manifests(config) -> str`

적용하지 않고 KubeRay YAML 매니페스트를 생성합니다. 배포 전 리뷰에 유용합니다.

```python
from src.runtime.kuberay_manager import KubeRayManager

kuberay = KubeRayManager(namespace="archon-prod")
status = await kuberay.deploy_cluster(config)
print(status["endpoint"])  # "ray://ray-head.archon-prod:10001"

await kuberay.scale_workers("archon-cluster", replicas=4)
```

---

### HybridCloudManager (`src/runtime/hybrid_cloud.py`)

*Phase 3.* 비용, 가용성, 예산 제약에 따라 온프레미스 GPU 노드와 클라우드 프로바이더에 걸쳐 태스크를 스케줄링합니다.

```python
class HybridCloudManager:
    def __init__(self, budget_limit: float | None = None)
```

| 파라미터 | 타입 | 설명 |
|---|---|---|
| `budget_limit` | `float \| None` | 월간 비용 예산 (USD, None = 무제한) |

#### `register_resource(resource) -> None`

컴퓨트 리소스(온프레미스 GPU, 클라우드 인스턴스 등)를 등록합니다.

#### `schedule_task(task, preference="cost") -> str`

최적의 사용 가능한 리소스에 태스크를 스케줄링합니다. 리소스 ID를 반환합니다.

| 파라미터 | 타입 | 설명 |
|---|---|---|
| `task` | `dict` | 요구사항이 포함된 태스크 명세 |
| `preference` | `str` | 스케줄링 선호: `"cost"`, `"speed"`, 또는 `"locality"` |

#### `check_budget() -> dict`

현재 예산 상태를 반환합니다: 사용액, 잔액, 사용률.

#### `get_summary() -> dict`

등록된 모든 리소스와 활용률 개요를 반환합니다.

```python
from src.runtime.hybrid_cloud import HybridCloudManager

hcm = HybridCloudManager(budget_limit=500.0)
hcm.register_resource(on_prem_gpu)
hcm.register_resource(cloud_gpu)

resource_id = hcm.schedule_task({"role": "backend", "complexity": "HIGH"}, preference="cost")
budget = hcm.check_budget()
print(f"예산: ${budget['remaining']:.2f} 남음")
```

---

## memory

소스: `src/memory/`

메모리 모듈은 3계층 아키텍처를 제공합니다: L1 (Redis 스크래치패드, 빠른 임시 데이터), L2 (ChromaDB 벡터 스토어, 핸드오프 이력), L3 (Mem0, 크로스 프로젝트 패턴). 각 계층은 선택적이며, 백엔드가 없으면 인메모리 dict로 폴백합니다.

### MemoryStore (`src/memory/context_injector.py`)

3계층 메모리 파사드입니다. 메모리 작업을 위한 주요 진입점입니다.

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

L2(벡터 검색)와 L3(패턴 검색)에서 태스크 지시사항을 쿼리하여 에이전트 주입용 관련 컨텍스트를 조합합니다. 오케스트레이터가 매 에이전트 실행 전에 호출하는 메서드입니다.

| 파라미터 | 타입 | 설명 |
|---|---|---|
| `task_instructions` | `str` | 현재 태스크 지시사항 (검색 쿼리로 사용) |
| `project_id` | `str` | L2 검색 범위를 지정하는 프로젝트 ID |

**반환값:** `relevant_past_decisions`, `known_patterns`, `error_history`, `human_feedback`가 포함된 `MemoryContext`.

```python
from src.memory.context_injector import MemoryStore

store = MemoryStore(redis_scratchpad=scratchpad, vector_store=vs, mem0_store=mem0)
ctx = await store.inject_memory_context("결제 API 구현", "proj-001")
print(ctx.known_patterns)  # ["항상 통화 코드를 검증할 것", ...]
```

#### 기타 MemoryStore 메서드

| 메서드 | 계층 | 설명 |
|---|---|---|
| `set_scratch(project_id, task_id, key, value)` | L1 | Redis에 임시 값 저장 |
| `get_scratch(project_id, task_id, key) -> Any \| None` | L1 | Redis에서 값 조회 |
| `store_handoff(project_id, handoff_id, summary, metadata=None)` | L2 | 핸드오프 요약 벡터 저장 |
| `search_handoffs(project_id, query, n_results=5, threshold=0.85) -> list[dict]` | L2 | 유사 핸드오프 검색 |
| `store_pattern(project_id, pattern, reason="", user_id="archon")` | L3 | 크로스 프로젝트 패턴 저장 |
| `search_patterns(query, user_id="archon", limit=5) -> list[dict]` | L3 | 패턴 검색 |

---

### RedisScratchpad (`src/memory/redis_scratchpad.py`)

진행 중인 태스크 데이터를 위한 고속 임시 저장소입니다. TTL로 데이터가 자동 만료됩니다.

```python
class RedisScratchpad:
    def __init__(self, redis_client: Any, ttl: int = 86400)
```

키 형식: `archon:scratch:{project_id}:{task_id}:{key}`

| 메서드 | 시그니처 | 설명 |
|---|---|---|
| `set` | `(project_id, task_id, key, value, ttl=None)` | 값 저장 (JSON 직렬화) |
| `get` | `(project_id, task_id, key) -> Any \| None` | 값 조회 |
| `delete` | `(project_id, task_id, key) -> bool` | 값 삭제 |
| `list_keys` | `(project_id, task_id) -> list[str]` | 태스크의 모든 키 목록 |
| `clear_task` | `(project_id, task_id) -> int` | 태스크 데이터 전체 삭제; 삭제된 키 수 반환 |

---

### VectorStore (`src/memory/vector_store.py`)

ChromaDB를 사용한 영구 벡터 저장소입니다. 각 프로젝트는 격리를 위해 자체 컬렉션을 갖습니다.

```python
class VectorStore:
    def __init__(self, chroma_client: Any, collection_prefix: str = "archon")
```

| 메서드 | 시그니처 | 설명 |
|---|---|---|
| `store` | `(project_id, handoff_id, summary, metadata=None)` | 핸드오프 벡터 저장 (upsert) |
| `search` | `(project_id, query, n_results=5, threshold=0.85) -> list[dict]` | 코사인 유사도 검색 |
| `delete` | `(project_id, handoff_id)` | 특정 핸드오프 삭제 |
| `delete_project` | `(project_id)` | 프로젝트 컬렉션 전체 삭제 |
| `count` | `(project_id) -> int` | 저장된 핸드오프 수 |

검색 결과 형식: `{"id": str, "document": str, "metadata": dict, "similarity": float}`

---

### Mem0Store (`src/memory/mem0_store.py`)

Mem0를 사용한 장기 크로스 프로젝트 메모리입니다. 모든 프로젝트에 적용되는 패턴, 선호사항, 학습 내용을 저장합니다.

```python
class Mem0Store:
    def __init__(self, mem0_client: Any)
```

#### `add_memory(text, user_id="archon", metadata=None) -> str`

메모리를 저장합니다. 메모리 ID를 반환합니다.

#### `search_memories(query, user_id="archon", limit=5) -> list[dict]`

시맨틱 유사도로 메모리를 검색합니다. `{"id", "text", "metadata", "score"}` 리스트를 반환합니다.

```python
from src.memory.mem0_store import Mem0Store

mem0 = Mem0Store(client)
mem0.add_memory("API 응답에는 항상 UTC 타임스탬프를 사용할 것", user_id="archon")
results = mem0.search_memories("타임스탬프 형식", limit=3)
```

---

### compressor (`src/memory/compressor.py`)

핸드오프가 토큰 한도를 초과하면 압축합니다. `BaseAgent.execute()`에서 자동으로 사용됩니다.

#### `compress_handoff(handoff, token_gap) -> HandoffArtifact`

*Phase 3 시그니처 업데이트.* `token_gap`만큼의 토큰을 확보하기 위해 핸드오프를 압축합니다. 우선순위 순서로 필드를 압축합니다: memory_context -> completed_summary -> decisions_made -> next_instructions.

| 파라미터 | 타입 | 설명 |
|---|---|---|
| `handoff` | `HandoffArtifact` | 압축할 핸드오프 |
| `token_gap` | `int` | 확보할 토큰 수 |

#### `estimate_tokens(text) -> int`

한영 혼합 텍스트의 토큰 수를 추정합니다. (한글 2자 = 1토큰, ASCII 4자 = 1토큰)

#### `compress_text(text, max_tokens) -> str`

문장 경계를 존중하며 텍스트를 잘라냅니다.

#### `summarize_text(text, max_tokens) -> str` `async`

*Phase 3.* 단순 잘라내기 대신 LLM을 사용하여 텍스트를 지능적으로 요약합니다. 더 일관성 있는 압축 결과를 생성하지만 API 호출이 필요합니다.

---

## guardrails

소스: `src/guardrails/`

*Phase 3.* Guardrails 모듈은 에이전트 실행 전 입력 검증, 실행 후 출력 검증, 토큰 예산 추적, 경로 기반 접근 정책 적용을 담당합니다.

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

모든 가드레일 동작을 제어하는 단일 정책 객체입니다. 프로젝트 레지스트리에 저장됩니다.

---

### InputValidator (`src/guardrails/input_validator.py`)

에이전트 실행 전에 핸드오프 입력을 검증합니다. LLM 호출에 토큰을 소비하기 전에 문제를 조기에 감지합니다.

```python
class InputValidator:
    def __init__(self, policy: GuardrailPolicy)
```

#### `validate(handoff) -> InputValidationResult`

| 검사 항목 | 수행 내용 |
|---|---|
| 토큰 수 | `max_input_tokens` 초과 입력 거부 |
| 차단 패턴 | 금지된 패턴 스캔 (시크릿, SQL 인젝션 등) |
| 필수 필드 | `task.next_instructions`가 비어있지 않은지 확인 |

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

에이전트 출력이 다음 핸드오프가 되기 전에 검증합니다. 구조화 출력의 무결성을 보장합니다.

```python
class OutputValidator:
    def __init__(self, policy: GuardrailPolicy)
```

#### `validate(result_handoff) -> OutputValidationResult`

| 검사 항목 | 수행 내용 |
|---|---|
| 필수 필드 | `required_output_fields`가 존재하는지 확인 |
| 토큰 수 | 출력이 `max_output_tokens`를 초과하면 경고 |
| 파일 경로 안전성 | 의심스러운 경로 감지 (예: `/etc/passwd`, `~/.ssh/`) |

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

태스크별, 프로젝트별 누적 토큰 사용량을 추적합니다. 무한 재시도 루프로 인한 비용 폭주를 방지합니다.

```python
class TokenBudgetTracker:
    def __init__(self, policy: GuardrailPolicy)
```

#### `record(project_id, task_id, tokens_used) -> None`

태스크의 토큰 사용량을 기록합니다.

#### `check_before_call(project_id, task_id, estimated_tokens) -> bool`

예상 호출이 예산 내에 있으면 True를 반환합니다. 한도를 초과하면 False를 반환합니다.

#### `get_status(project_id, task_id=None) -> dict`

예산 상태를 반환합니다: `{"used", "limit", "remaining", "utilization_pct"}`. `task_id`를 전달하면 태스크 수준, 생략하면 프로젝트 수준의 상태를 반환합니다.

```python
from src.guardrails.token_budget import TokenBudgetTracker

tracker = TokenBudgetTracker(policy)
if tracker.check_before_call("proj-001", "task-001", estimated_tokens=4000):
    result = await agent.execute(handoff, registry)
    tracker.record("proj-001", "task-001", actual_tokens)
else:
    raise TokenBudgetExceededError("태스크 토큰 예산 소진")
```

---

### PathGuard (`src/guardrails/path_guard.py`)

파일 경로 접근 정책을 적용합니다. 에이전트가 허용된 범위 밖의 파일을 수정하는 것을 방지합니다.

```python
class PathGuard:
    def __init__(self, policy: GuardrailPolicy)
```

#### `check_handoff(handoff) -> list[str]`

`protected_path_patterns`에 매칭되는 변경 파일에 대한 위반 메시지 목록을 반환합니다. 빈 목록이면 모든 경로가 허용된 것입니다.

#### `check_paths(paths) -> list[str]`

원시 파일 경로 목록을 정책에 대해 검사합니다. 에이전트 실행 전 사전 검증에 유용합니다.

```python
from src.guardrails.path_guard import PathGuard

guard = PathGuard(policy)
violations = guard.check_handoff(handoff)
if violations:
    raise PathGuardError(f"차단된 경로: {violations}")
```

---

## observability

소스: `src/observability/`

*Phase 3.* 전체 파이프라인에 대한 분산 트레이싱 및 텔레메트리를 제공합니다. 여러 백엔드(AITOP, OpenTelemetry 등)와 샘플링을 지원합니다.

### 설정

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

모든 트레이서의 추상 베이스 클래스입니다.

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

### 트레이서 구현체

| 클래스 | 설명 |
|---|---|
| `NoOpTracer` | 아무 동작도 하지 않습니다. 트레이싱 비활성화 시 기본값입니다. |
| `CompositeTracer` | 여러 자식 트레이서에 팬아웃합니다. |
| `SamplingTracer` | 다른 트레이서를 래핑하고 설정된 비율로 샘플링합니다. |
| `AitopTracer` | AITOP 백엔드로 트레이스를 전송하여 시각화합니다. |

### TracingMiddleware (`src/observability/middleware.py`)

오케스트레이터 파이프라인에 트레이싱을 통합하는 고수준 헬퍼입니다.

```python
class TracingMiddleware:
    def __init__(self, tracer: ArchonTracer)
```

#### `start_pipeline_trace(handoff) -> SpanContext`

파이프라인 실행에 대한 루트 트레이스를 시작합니다.

#### `start_agent_span(parent, agent_role) -> SpanContext`

파이프라인 트레이스 내에서 에이전트 실행에 대한 자식 스팬을 시작합니다.

#### `record_llm_call(span, record) -> None`

스팬 내에서 LLM 호출을 기록합니다.

### `create_tracer_from_config(config) -> ArchonTracer`

`TracingConfig`에서 적절한 트레이서를 생성하는 팩토리 함수입니다.

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

소스: `src/benchmark/`

*Phase 3.* 역할별 태스크에 대해 LLM 모델을 벤치마크하고 역할별 최적 모델 배정을 추천합니다.

### 데이터 모델

```python
@dataclass
class BenchmarkTask:
    task_id: str
    role: str                   # "backend", "tester" 등
    instructions: str
    expected_output: dict       # 점수 산정용 정답
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
    quality_score: float        # 0~100
    speed_score: float          # 0~100
    cost_score: float           # 0~100
    composite_score: float      # 가중 평균

@dataclass
class ModelRanking:
    role: str
    rankings: list[ModelScore]  # composite_score 내림차순 정렬
    recommended: str            # 최상위 모델명
```

### BenchmarkRunner

```python
class BenchmarkRunner:
    def __init__(self, models: list[str], timeout: float = 60.0)
```

#### `run_task(task, model) -> BenchmarkResult` `async`

단일 벤치마크 태스크를 모델에 대해 실행합니다.

#### `run_suite(tasks) -> list[BenchmarkResult]` `async`

모든 태스크를 등록된 모든 모델에 대해 실행합니다. 전체 결과 매트릭스를 반환합니다.

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

벤치마크 결과를 기대 출력과 비교하여 점수를 산정합니다. 모델별, 역할별 점수를 반환합니다.

### ModelRecommender

```python
class ModelRecommender:
    def __init__(self, scorer: BenchmarkScorer)
```

#### `rank_models(scores, role) -> ModelRanking`

특정 역할에 대해 종합 점수 기반으로 모델을 랭킹합니다.

#### `recommend_all_roles(scores) -> dict[str, ModelRanking]`

모든 역할에 대한 랭킹을 한 번에 반환합니다.

#### `apply_recommendations(rankings, registry) -> ProjectRegistry`

추천된 모델로 프로젝트 레지스트리의 `agent_config`를 업데이트합니다.

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

소스: `src/evolution/`

*Phase 3.* 실행 패턴을 분석하고, 병목을 식별하고, 품질 임계값과 에이전트 설정을 자동으로 조정하는 자가 튜닝 파이프라인입니다.

### 데이터 모델

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
    target: str                 # 필드 또는 설정 키
    current_value: Any
    proposed_value: Any
    reason: str

class EvolutionConfig(BaseModel):
    enabled: bool = False
    min_executions: int = 20    # 튜닝 전 최소 데이터 수
    cycle_interval_seconds: int = 3600
    auto_apply: bool = False    # 기본적으로 인간 승인 필요
```

### MetricsCollector

```python
class MetricsCollector:
    def __init__(self)
```

#### `record(execution) -> None`

완료된 파이프라인 실행을 기록하여 나중에 분석합니다.

#### `get_metrics(window_hours=24) -> PipelineMetrics`

주어진 시간 창에 대한 집계된 파이프라인 메트릭을 반환합니다.

#### `get_agent_metrics(role, window_hours=24) -> AgentMetrics`

특정 에이전트 역할에 대한 메트릭을 반환합니다.

### PatternAnalyzer

```python
class PatternAnalyzer:
    def __init__(self, collector: MetricsCollector)
```

#### `analyze() -> list[TuningAction]`

수집된 메트릭을 분석하고 튜닝 액션을 제안합니다. 예시: "review_score 임계값이 너무 엄격함 (L2 비율 45%)", "백엔드 에이전트 재작업 비율이 높음 -- 모델 업그레이드 제안".

### ThresholdTuner

```python
class ThresholdTuner:
    def __init__(self, config: EvolutionConfig)
```

#### `evaluate_actions(actions) -> list[TuningAction]`

안전 범위 내에서 제안된 액션을 필터링합니다. 최소 품질 임계값 아래로 낮추는 액션은 거부합니다.

#### `safe_adjust(current, proposed, max_delta) -> Any`

범위가 제한된 조정을 적용합니다. 사이클당 변경이 점진적(max_delta)으로 이루어지도록 보장합니다.

#### `apply_to_policy(actions, policy) -> QualityPolicy`

승인된 튜닝 액션을 품질 정책에 적용하고 업데이트된 정책을 반환합니다.

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

한 번의 진화 사이클을 실행합니다: 수집 -> 분석 -> 제안 -> (선택적) 적용.

#### `start_background() -> None` `async`

`cycle_interval_seconds`마다 실행되는 백그라운드 태스크로 진화 루프를 시작합니다.

#### `stop() -> None`

백그라운드 진화 루프를 중지합니다.

```python
from src.evolution.loop import EvolutionLoop
from src.evolution.config import EvolutionConfig

config = EvolutionConfig(enabled=True, auto_apply=False, cycle_interval_seconds=3600)
loop = EvolutionLoop(config, collector, analyzer, tuner)

# 수동 사이클
actions = await loop.run_cycle()
for a in actions:
    print(f"{a.action_type}: {a.target} {a.current_value} -> {a.proposed_value} ({a.reason})")

# 또는 백그라운드 실행
await loop.start_background()
```

---

## dashboard

소스: `src/dashboard/`

*Phase 3.* 파이프라인 실행, 에이전트 상태, 비용, Gate 대기열을 모니터링하는 실시간 웹 대시보드입니다. FastAPI + WebSocket으로 구축되었습니다.

### DashboardApp

```python
class DashboardApp:
    def __init__(self, registry_store: RegistryStore, collector: MetricsCollector | None = None)
```

#### `create_app() -> FastAPI`

모든 라우트와 WebSocket 엔드포인트가 설정된 FastAPI 애플리케이션을 생성하여 반환합니다.

```python
from src.dashboard.app import DashboardApp

dashboard = DashboardApp(registry_store=store, collector=collector)
app = dashboard.create_app()

# uvicorn으로 실행
import uvicorn
uvicorn.run(app, host="0.0.0.0", port=8080)
```

### DashboardRoutes

모든 HTTP 및 WebSocket 엔드포인트를 처리합니다.

| 엔드포인트 | 메서드 | 설명 |
|---|---|---|
| `/api/projects` | GET | 모든 프로젝트 목록 |
| `/api/projects/{id}` | GET | 프로젝트 상세 정보 |
| `/api/projects/{id}/agents` | GET | 프로젝트의 에이전트 상태 |
| `/api/projects/{id}/metrics` | GET | 파이프라인 메트릭 |
| `/api/projects/{id}/costs` | GET | 비용 내역 |
| `/api/projects/{id}/gate-queue` | GET | 대기 중인 Human Gate 항목 |
| `/api/projects/{id}/gate-queue/{item_id}` | POST | Gate 항목 승인/거부 |
| `/api/projects/{id}/handoffs` | GET | 최근 핸드오프 이력 |
| `/api/projects/{id}/evolution` | GET | 진화 상태 및 제안 |
| `/api/health` | GET | 헬스 체크 |
| `/ws/events` | WebSocket | 실시간 파이프라인 이벤트 |

### WebSocketManager

```python
class WebSocketManager:
    def __init__(self)
```

#### `connect(websocket) -> None` `async`

실시간 이벤트 스트리밍을 위한 WebSocket 클라이언트를 등록합니다.

#### `broadcast(event) -> None` `async`

연결된 모든 WebSocket 클라이언트에 이벤트를 전송합니다. Gate 판정, 에이전트 완료, 오류 알림, 비용 업데이트 이벤트를 포함합니다.

### API 모델

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

소스: `src/healing/`

*Phase 3.* 에이전트 상태를 모니터링하고, 장애를 진단하고, 일반적인 오류 패턴에서 자동으로 복구하는 자가 복구 인프라입니다.

### AgentHealthStatus

```python
class AgentHealthStatus(StrEnum):
    HEALTHY   = "healthy"
    DEGRADED  = "degraded"
    UNHEALTHY = "unhealthy"
    DEAD      = "dead"
```

| 상태 | 의미 |
|---|---|
| `HEALTHY` | 에이전트가 정상적으로 동작 중 |
| `DEGRADED` | 오류율 또는 지연 시간 상승 |
| `UNHEALTHY` | 지속적으로 실패, 개입 필요 |
| `DEAD` | 전혀 응답하지 않음 |

### AgentHealthMonitor

슬라이딩 윈도우 방식으로 에이전트별 성공/실패 신호를 추적합니다.

```python
class AgentHealthMonitor:
    def __init__(self, window_size: int = 20, degraded_threshold: float = 0.7, unhealthy_threshold: float = 0.4)
```

#### `record_success(role) -> AgentHealthStatus`

성공한 실행을 기록합니다. 업데이트된 상태를 반환합니다.

#### `record_failure(role, error) -> AgentHealthStatus`

실패한 실행을 기록합니다. 업데이트된 상태를 반환합니다.

#### `record_circuit_open(role) -> AgentHealthStatus`

서킷 브레이커 개방 이벤트를 기록합니다. DEAD 상태로 전환됩니다.

### HealthMonitorRegistry

여러 `AgentHealthMonitor` 인스턴스를 관리합니다 -- 에이전트 역할별로 하나씩.

### DiagnosticRegistry

중앙 집중식 진단을 위해 여러 `AgentDiagnostician` 인스턴스를 관리합니다.

### AgentDiagnostician

오류 패턴을 분석하여 근본 원인을 파악하고 수정 방법을 제안합니다.

```python
class AgentDiagnostician:
    def __init__(self, role: str, max_history: int = 50)
```

#### `record_error(error, context=None) -> None`

패턴 분석을 위해 선택적 컨텍스트와 함께 오류를 기록합니다.

#### `generate_report() -> dict`

진단 보고서를 생성합니다: 카테고리별 오류 빈도, 가장 일반적인 근본 원인, 권장 복구 액션.

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

진단 결과를 기반으로 복구 액션을 자동 적용합니다.

```python
class SelfHealer:
    def __init__(self, registry: ProjectRegistry)
```

#### `heal(role, report) -> RecoveryAction` `async`

진단 보고서를 기반으로 복구 액션을 선택하고 실행합니다.

#### `select_action(report) -> RecoveryAction`

실행하지 않고 최적의 복구 액션을 선택합니다.

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

주기적으로 모든 에이전트 상태를 점검하고 필요 시 복구를 트리거하는 백그라운드 서비스입니다.

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

백그라운드 태스크로 워치독을 시작합니다.

#### `stop() -> None`

워치독을 중지합니다.

#### `check_once() -> dict[str, AgentHealthStatus]` `async`

한 번의 상태 점검 사이클을 실행하고 모든 에이전트 상태를 반환합니다.

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

# 수동 점검
statuses = await watchdog.check_once()
for role, status in statuses.items():
    print(f"{role}: {status}")
```

---

## notifications

소스: `src/notifications/`

Gate 판정이 발생할 때 알림을 전송합니다. 여러 백엔드(Slack, 터미널)를 지원하며 팬아웃 방식으로 동작합니다.

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

프로퍼티: `.severity` (`"info"` | `"warning"` | `"error"` | `"critical"`), `.title`, `.summary`

### Notifier (ABC)

```python
class Notifier(abc.ABC):
    async def notify(self, event: GateEvent) -> bool: ...
    def should_notify(self, event: GateEvent) -> bool: ...  # AUTO_PASS는 기본 미전송
```

### CompositeNotifier

여러 Notifier에 동시 전송합니다. 하나라도 성공하면 True를 반환합니다.

```python
class CompositeNotifier(Notifier):
    def __init__(self, notifiers: list[Notifier] | None = None)
    def add(self, notifier: Notifier) -> None
    async def notify(self, event: GateEvent) -> bool
```

### SlackNotifier (`src/notifications/slack.py`)

Slack incoming webhook 알림입니다. Gate 레벨별 색상/이모지가 자동 적용됩니다.

```python
class SlackNotifier(Notifier):
    def __init__(self, webhook_url: str)
```

### TerminalNotifier (`src/notifications/terminal.py`)

rich 라이브러리 TUI 패널 + macOS `osascript` 데스크탑 알림입니다.

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

소스: `src/mcp/`

외부 도구 통합을 위한 MCP(Model Context Protocol) 서버와 A2A(Agent-to-Agent) 메시징입니다.

### MCPServer (`src/mcp/server.py`)

외부 클라이언트가 Archon을 제어하는 MCP 도구 서버입니다.

```python
class MCPServer:
    def __init__(self)
```

#### `register_project(registry) -> None`

프로젝트를 MCP 서버에 등록합니다.

#### `get_tools() -> list[ToolDefinition]`

사용 가능한 도구 목록을 반환합니다.

#### `call_tool(name, arguments) -> ToolResult` `async`

도구를 호출합니다. 결과: `ToolResult(success, data, error)`.

**제공 도구**

| 도구명 | 입력 | 설명 |
|---|---|---|
| `execute_task` | `project_id, task_id, agent_role, instructions` | 에이전트에게 태스크 제출 |
| `get_status` | `project_id, task_id?` | 프로젝트/태스크 상태 조회 |
| `list_agents` | -- | 사용 가능한 에이전트 목록 |
| `get_project` | `project_id` | 프로젝트 레지스트리 상세 |
| `list_projects` | -- | 등록된 프로젝트 목록 |

### A2ARouter (`src/mcp/a2a.py`)

에이전트 간 메시지 라우팅입니다.

```python
class A2ARouter:
    def __init__(self)
```

#### `send(message) -> None`

`A2AMessage`를 수신 에이전트의 mailbox에 넣습니다.

#### `receive(agent_role) -> list[A2AMessage]`

에이전트의 mailbox에서 모든 메시지를 꺼냅니다 (FIFO, 수신 후 삭제).

#### `broadcast(message) -> None`

모든 에이전트 mailbox에 메시지를 브로드캐스트합니다.

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

---

## queue

소스: `src/queue/`

의존성 기반 비동기 태스크 스케줄링과 멀티 프로젝트 우선순위 랭킹을 제공합니다.

### TaskScheduler (`src/queue/scheduler.py`)

```python
class TaskScheduler:
    def __init__(self, concurrency: int = 3)
```

#### `add_task(task) -> None`

`TaskSpec`을 등록합니다. 중복 `task_id`는 `ValueError`를 발생시킵니다.

#### `add_tasks(tasks) -> None`

여러 태스크를 한 번에 등록합니다.

#### `topological_sort() -> list[str]`

의존성 기반 실행 순서를 반환합니다. 순환 의존성 시 `CyclicDependencyError`를 발생시킵니다.

#### `get_ready_tasks() -> list[TaskSpec]`

의존성이 모두 완료된 실행 가능한 태스크 목록을 반환합니다.

#### `run(executor) -> dict[str, TaskSpec]` `async`

모든 태스크를 비동기로 실행합니다. Semaphore로 최대 `concurrency`개 동시 실행을 제한합니다.

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

멀티 프로젝트 환경에서 태스크를 종합 우선순위로 정렬합니다.

```python
class PriorityRanker:
    def __init__(self, project_weights=None, max_slots=5)
```

#### `set_project_weight(weight) -> None`

`ProjectWeight(project_id, priority, deadline, pending_count)`를 설정합니다.

#### `rank(tasks, now=None) -> list[RankedTask]`

score 내림차순으로 태스크를 정렬합니다. `score = (project_priority x 10) + task_priority + deadline_bonus`

deadline_bonus: 24시간 이내 +30 / 72시간 이내 +15 / 7일 이내 +5 / 지남 +50

#### `allocate_slots(tasks, now=None) -> list[TaskSpec]`

랭킹 후 `max_slots`개만 반환합니다.

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

소스: `src/errors.py`

모든 Archon 예외는 `ArchonError`를 상속합니다. 세부적인 오류 처리를 위해 특정 하위 클래스를 catch하세요.

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

각 예외는 진단을 위한 구조화된 컨텍스트를 포함합니다:

```python
from src.errors import ProtectedPathError, TokenBudgetExceededError

try:
    await git_executor.auto_commit(handoff, template)
except ProtectedPathError as e:
    print(f"보호 경로 접근 차단: {e}")
except TokenBudgetExceededError as e:
    print(f"예산 초과: {e}")
```

---

## registry

소스: `src/registry/`

레지스트리는 각 프로젝트의 중앙 설정 저장소입니다. 모델, 품질 정책, Git 설정, 런타임 구성을 정의합니다.

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

#### 서브 모델

| 모델 | 주요 필드 | 용도 |
|---|---|---|
| `ProjectMeta` | `project_id`, `name`, `description`, `tech_stack` | 프로젝트 정체성 |
| `GitConfig` | `repo`, `branch`, `protected_paths`, `auto_push` | Git 설정 |
| `AgentModelConfig` | `model`, `model_override`, `high_complexity_model`, `streaming`, `timeout_seconds`, `max_tokens` | 역할별 LLM 설정 |
| `QualityPolicy` | `min_review_score`, `min_coverage`, `max_retry_before_escalation`, `require_human_for_schema`, `require_human_for_external`, `sop_paths`, `dynamic_guardrail_paths` | 품질 임계값 |
| `WorkQueue` | `pending_tasks`, `active_tasks`, `completed_tasks` | 태스크 추적 |
| `MemoryConfig` | `redis_url`, `chroma_path`, `mem0_api_key` | 메모리 백엔드 설정 |
| `ProjectMetrics` | `total_tasks`, `auto_commit_count`, `l1_count`, `l2_count`, `total_tokens`, `total_cost_usd` | 누적 메트릭 |
| `HumanGateHistory` | `decisions: list[HumanGateDecision]` | 인간 리뷰 감사 추적 |

#### `get_model_for_role(role) -> str`

역할에 해당하는 LLM 모델명을 반환합니다. `model_override`가 우선합니다.

### RegistryStore (`src/registry/store.py`)

JSON 파일 기반 레지스트리 영속성입니다. 저장 위치: `.harness/registry/{project_id}.json`

#### `load(project_id) -> ProjectRegistry`

레지스트리를 로드합니다. 파일이 없으면 `ProjectNotFoundError`를 발생시킵니다.

#### `save(registry) -> None`

레지스트리를 JSON으로 저장합니다.

#### `update_metrics(project_id, delta) -> None`

메트릭을 delta 누적 업데이트합니다.

#### `update_work_queue(project_id, work_queue) -> None`

work_queue 상태를 교체합니다.

```python
from src.registry.store import RegistryStore

store = RegistryStore(base_path=".harness/registry")
registry = store.load("proj-001")
registry.metrics.auto_commit_count += 1
store.save(registry)
```
