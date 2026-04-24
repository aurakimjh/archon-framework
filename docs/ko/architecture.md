# Archon 시스템 아키텍처

🇺🇸 [English](../en/architecture.md)

> 버전: 2.0.0 | 최종 수정: 2026-04-24

## 개요

Archon은 **7계층 아키텍처**로 구성된 멀티 에이전트 AI 개발 플랫폼입니다. Claude API를 마스터 오케스트레이터로, 오픈소스 LLM들을 전문 에이전트로 활용하여 1인 개발자가 팀급 생산성을 달성할 수 있도록 설계되었습니다.

이 문서는 Archon의 전체 구조를 설명합니다. 각 계층이 무엇을 하는지, 왜 그렇게 설계되었는지를 중심으로 서술하였으므로, 처음 접하시는 분도 전체 흐름을 이해하실 수 있습니다.

## 핵심 설계 원칙

| 원칙 | 설명 |
|---|---|
| P1. 에이전트는 무상태 | 프로젝트에 종속되지 않습니다. 태스크마다 `project_context`가 주입됩니다. |
| P2. 구조는 공개, 영혼은 비공개 | 스키마·설계는 오픈소스로, 프롬프트·SOP는 비공개로 관리합니다. |
| P3. 코드 변경 없이 스케일아웃 | Ray 기반으로 노드를 추가하는 것만으로 선형 확장이 가능합니다. |
| P4. 작업은 멈추지 않는다 | Human Gate가 발동되어도 해당 프로젝트만 일시정지되며, 다른 프로젝트는 계속 진행됩니다. |
| P5. 모델은 항상 교체 가능 | LiteLLM Proxy를 통해 역할별 모델을 YAML 한 줄로 교체할 수 있습니다. |
| P6. 고위험 영역은 반드시 인간이 본다 | Dynamic Guardrails로 결제·인증·인프라 변경은 자동으로 L2 상향됩니다. |
| P7. 모든 것은 추적된다 | Observability 트레이싱을 통해 모든 LLM 호출, 비용, 레이턴시가 전수 기록됩니다. |
| P8. 시스템은 스스로 진화한다 | Evolution Loop가 품질 메트릭을 모니터링하고 임계값을 자동으로 조정합니다. |

## 7계층 구조

아래 다이어그램은 Archon의 전체 데이터 흐름을 보여줍니다. 개발자의 요청이 최상위(Layer 0)에서 시작되어 각 계층을 거치며 처리됩니다.

```
Layer 0 — Human in the Loop
  개발자: 아이디어 입력 · 설계 검토 · 실 테스트 · 최종 승인
          │
          │ Human Gate (양방향)
          ▼
Layer 1 — Orchestrator (Claude API)
  src/orchestrator/orchestrator.py
  마스터 아키텍트 · 코드 리뷰어 · Human Gate 관리
  모델: Claude Opus 4.6 (설계) / Claude Sonnet 4.6 (리뷰)
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
  src/router/complexity.py     — 8기준 복잡도 측정, 동적 라우팅
  src/router/role_router.py    — vLLM → Ollama → default 라우팅 체인
  LiteLLM Proxy (localhost:4000)
          │
          ▼
Layer 4 — Specialized Agent Pool
  src/agents/base.py           — BaseAgent (streaming, A2A, 구조화 출력)
  src/agents/{backend,frontend,tester,devops,docs}.py
  src/guardrails/              — 입출력 검증, 토큰 예산, 경로 보호
  BaseAgent: 자가 교정(self-correction), 구조화 출력 파싱
  (무상태 · 컨텍스트 주입 · 풀 공유)
          │
          ▼
Layer 5 — QA Pipeline + Human Gate
  src/runtime/qa.py            — 병렬 lint/build/test/security
  src/runtime/git_executor.py  — 자동 커밋 + 트랜잭션 스냅샷/롤백
  src/gate/evaluator.py        — 5-레벨 gate decision
  src/notifications/           — Slack · Terminal 알림
          │
          ▼
Layer 6 — Shared Memory & Context Store
  src/memory/context_injector.py   — 3계층 파사드 (MemoryStore)
  src/memory/redis_scratchpad.py   — L1: Redis (TTL 24h)
  src/memory/vector_store.py       — L2: ChromaDB 벡터 검색
  src/memory/mem0_store.py         — L3: Mem0 크로스 프로젝트
  src/memory/compressor.py         — 대형 핸드오프 압축 + token_gap 정밀 타격
          │
          ▼
Layer 7 — LLM Runtime
  src/runtime/vllm_bridge.py   — vLLM 엔드포인트 관리
  src/runtime/ollama_bridge.py — Ollama 로컬 LLM 통합
  src/runtime/cluster.py       — Ray 클러스터
  src/runtime/kuberay.py       — KubeRay CRD 관리
  src/runtime/hybrid.py        — 클라우드 하이브리드 스케줄링
  MLX (Apple Silicon) · Ollama · vLLM · Claude API
```

---

## 모듈별 역할

### Orchestrator (`src/orchestrator/`)

오케스트레이터는 Archon의 두뇌에 해당합니다. 개발자의 요청을 받아 어떤 에이전트에게 어떤 순서로 작업을 맡길지 결정하고, 결과물의 품질을 검증합니다.

`orchestrator.py` — 전체 파이프라인을 지휘합니다.

- **6개 에이전트 풀**: `backend`, `frontend`, `tester`, `devops`, `docs`, `reviewer`
- **Task Chain**: 에이전트 완료 후 연쇄 실행됩니다. 기본값은 다음과 같습니다:
  - `backend` → tester → docs
  - `frontend` → tester → docs
  - `devops` → tester
- **`process_chain()`**: 체인을 순차 실행하며 각 핸드오프를 반환합니다.
- **알림**: Gate 판정 후 `CompositeNotifier`로 Slack/Terminal에 이벤트를 전송합니다.

`handoff.py` — 에이전트 간 컨텍스트 전달 표준입니다.

7섹션 Pydantic 모델: `Envelope` · `ProjectContext` · `Task` · `Artifacts` · `QualityGates` · `HumanGatePackage` · `MemoryContext`

---

### BaseAgent (`src/agents/base.py`)

BaseAgent는 모든 전문 에이전트가 상속하는 공통 베이스 클래스입니다. 에이전트의 공통 기능(LLM 호출, 컨텍스트 관리, 통신)을 한 곳에 모아 중복을 없앴습니다.

**핵심 특징:**

- **무상태**: 에이전트 인스턴스는 아무것도 기억하지 않습니다. 매 태스크마다 `HandoffArtifact`로 컨텍스트가 주입됩니다.
- **3가지 실행 모드**:
  - `execute()` — 일반 동기식 LLM 호출
  - `execute_streaming()` — 청크 단위 스트리밍 (`AsyncIterator[str]`)
  - `execute_with_streaming()` — `AgentModelConfig.streaming`이 True면 스트리밍, 아니면 일반 폴백
- **자동 압축**: 토큰 초과 시 `compress_handoff()`로 자동 컨텍스트 압축
- **구조화 출력**: LLM이 `<archon-output>JSON</archon-output>` 태그로 반환하면 `changed_files`, `decisions` 등을 파싱합니다.
- **A2A 메시지**: `send_a2a()`, `receive_a2a()`로 에이전트 간 직접 통신이 가능합니다.

**Phase 3에서 추가된 기능:**

- **자가 교정(Self-Correction)**: LLM 응답의 JSON 파싱이 실패하면 교정 프롬프트를 포함하여 1회 재시도합니다. 이를 통해 구조화 출력의 성공률이 크게 향상됩니다.

  ```python
  # BaseAgent 내부 동작 (개념적)
  result = await self.call_llm(prompt)
  parsed = try_parse_structured(result)
  if parsed is None:
      # 교정 프롬프트와 함께 1회 재시도
      result = await self.call_llm(correction_prompt + result)
      parsed = try_parse_structured(result)
  ```

- **가드레일 통합**: 모든 `execute()` 호출에서 입력/출력 검증, 토큰 예산 차감, 경로 보호가 자동으로 적용됩니다.
- **트레이싱 통합**: `TracingMiddleware`가 모든 LLM 호출의 레이턴시, 토큰 수, 비용을 자동으로 기록합니다.
- **헬스 모니터링**: `AgentHealthMonitor`가 에이전트 상태를 추적하고, 이상 감지 시 자가 치유를 트리거합니다.

---

### Human Gate (`src/gate/`)

Human Gate는 "위험한 작업은 반드시 사람이 확인한다"는 원칙을 구현한 안전장치입니다. AI가 자율적으로 동작하되, 고위험 작업에서는 개발자의 승인을 요구합니다.

`evaluator.py`의 `evaluate_gate()` 함수가 5-레벨을 결정합니다.

**판정 순서** (높은 우선순위 먼저):

1. `L4_DEPLOY` — `is_deploy_request=True`이면 무조건
2. `L3_HALT` — 빌드 실패, Critical/High 보안 취약점
3. `L2_HUMAN` — review_score 미달, 스키마/외부 연동, 재작업 소진
4. `L2_HUMAN` (Dynamic Guardrails) — 고위험 경로/키워드 감지
5. `L2_HUMAN` (SOP) — SOP 준수 점수 미달
6. `L1_REWORK` — 린트 실패, 커버리지 소폭 미달, 단위 테스트 소수 실패
7. `AUTO_PASS` — 모든 체크 통과

상세 설명: [human-gate.md](human-gate.md)

---

### Complexity Router (`src/router/complexity.py`)

태스크 복잡도를 측정하여 동적으로 LLM 모델을 선택합니다. 간단한 작업에 비싼 모델을 쓰지 않도록 하여 비용을 절감하고, 복잡한 작업에는 고성능 모델을 배정하여 품질을 보장합니다.

**8가지 측정 기준**:
1. 지시사항 길이 (500자 이상 → +2점)
2. 변경 파일 수 (5개 이상 → +2점)
3. 과거 결정 수 (3개 이상 → +1점)
4. 블로커 존재 여부 (+2점)
5. 외부 통합 여부 (`has_external_integration` → +2점)
6. 스키마 변경 여부 (`has_schema_change` → +2점)
7. 높은 우선순위 (priority ≥ 8 → +1점)
8. L2 이상 이력 존재 (`gate_decision` L2/L3/L4 → +2점)

**레벨 판정**: LOW (0-3) / MEDIUM (4-6) / HIGH (7+)

`select_model_by_complexity()`는 HIGH일 때 `AgentModelConfig.high_complexity_model`을 반환합니다.

---

### Role Router (`src/router/role_router.py`)

역할별 모델 라우팅 체인을 관리합니다. 여러 LLM 백엔드가 존재할 때, 어떤 순서로 시도할지를 결정하는 **우선순위 폴백 체인**입니다.

**라우팅 우선순위**:
1. **vLLM** — GPU 워커에서 실행 중인 모델을 최우선으로 사용합니다.
2. **Ollama** — vLLM이 없으면 로컬 Ollama를 시도합니다.
3. **default** — 모두 불가하면 YAML에 정의된 기본 모델(LiteLLM Proxy)로 폴백합니다.

이를 통해 인프라 상황에 관계없이 항상 작동하는 모델 선택이 보장됩니다.

---

### 3계층 메모리 (`src/memory/`)

에이전트는 무상태이지만, 시스템 전체는 기억합니다. 3계층 메모리 시스템이 단기·중기·장기 기억을 관리합니다.

| 클래스 | 계층 | 백엔드 | TTL | 용도 |
|---|---|---|---|---|
| `RedisScratchpad` | L1 단기 | Redis | 24시간 | 현재 태스크의 임시 데이터 |
| `VectorStore` | L2 중기 | ChromaDB | 무제한 | 프로젝트 내 유사 경험 검색 |
| `Mem0Store` | L3 장기 | Mem0 API | 무제한 | 크로스 프로젝트 패턴 |
| `MemoryStore` | 파사드 | 모두 통합 | — | 단일 인터페이스 |

`MemoryStore.inject_memory_context()` — 태스크 지시사항을 쿼리로 L2+L3를 검색한 후 `MemoryContext`로 조합하여 에이전트에 주입합니다.

각 계층은 미연결(None) 시 인메모리 dict로 폴백하므로 인프라 없이도 동작합니다.

**Compressor (`src/memory/compressor.py`)**

대형 핸드오프를 압축하는 모듈입니다. Phase 3에서 **token_gap 정밀 타격** 기능이 추가되었습니다. API에서 "prompt too long" 에러가 반환되면, 에러 메시지에 포함된 토큰 초과량을 피드백 받아 정확히 필요한 만큼만 압축합니다. 이를 통해 불필요한 정보 손실 없이 최적의 컨텍스트를 유지할 수 있습니다.

---

### Task Scheduler (`src/queue/scheduler.py`)

의존성 기반 비동기 태스크 스케줄러입니다. 여러 태스크 간의 선후 관계를 정의하고, 가능한 작업은 동시에 실행합니다.

1. `add_task(TaskSpec)` — 태스크 등록 (task_id, agent_role, depends_on, priority)
2. `topological_sort()` — Kahn's algorithm으로 실행 순서를 계산하고, 순환 의존성을 감지합니다.
3. `run(executor)` — asyncio Semaphore로 동시 실행 수를 제한합니다 (`concurrency=3` 기본)

---

### MCP Server (`src/mcp/server.py`)

외부 클라이언트(IDE, CLI)가 Archon을 제어할 수 있는 MCP 도구 5개를 제공합니다.

| 도구 | 설명 |
|---|---|
| `execute_task` | 태스크를 특정 에이전트에게 제출합니다 |
| `get_status` | 프로젝트/태스크 상태를 조회합니다 |
| `list_agents` | 사용 가능한 에이전트 목록을 반환합니다 |
| `get_project` | 프로젝트 레지스트리 상세 정보를 반환합니다 |
| `list_projects` | 등록된 프로젝트 목록을 반환합니다 |

---

### A2A Messaging (`src/mcp/a2a.py`)

에이전트 간 직접 통신을 가능하게 하는 모듈입니다 (Google A2A 프로토콜 기반). 오케스트레이터를 거치지 않고 에이전트끼리 정보를 교환해야 할 때 사용합니다.

- `A2ARouter.send(message)` — 수신 에이전트의 mailbox에 메시지를 적재합니다.
- `A2ARouter.receive(agent_role)` — 자신의 mailbox에서 메시지를 꺼냅니다.
- `BaseAgent.send_a2a()`, `receive_a2a()` — 에이전트 레벨 인터페이스입니다.
- 메시지 타입: `REQUEST`, `RESPONSE`, `BROADCAST`, `NOTIFY`
- 우선순위: `LOW`, `NORMAL`, `HIGH`, `URGENT`

---

### Notifications (`src/notifications/`)

Gate 이벤트 발생 시 개발자에게 알림을 전송합니다.

- `GateEvent` — 알림 페이로드 모델 (project_id, task_id, gate_decision, trigger_reason, severity)
- `TerminalNotifier` — rich 라이브러리 TUI + macOS `osascript` 데스크탑 알림
- `SlackNotifier` — Slack incoming webhook
- `CompositeNotifier` — 여러 Notifier를 묶어 동시 전송합니다 (하나라도 성공하면 True)

AUTO_PASS는 기본적으로 알림을 전송하지 않습니다 (`Notifier.should_notify()`).

---

### vLLM Bridge (`src/runtime/vllm_bridge.py`)

GPU 워커 노드의 vLLM 서버를 LiteLLM에 통합합니다. 원격 GPU에서 실행되는 대형 모델을 마치 로컬 모델처럼 사용할 수 있게 해줍니다.

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

## Phase 3 신규 모듈

다음 모듈들은 Phase 3에서 새로 추가되었습니다. Archon의 자율성, 안전성, 관측성을 한 단계 끌어올리는 핵심 기능들입니다.

### Observability (`src/observability/`)

**왜 필요한가요?** LLM 기반 시스템은 비결정적입니다. 같은 입력에도 다른 결과가 나올 수 있습니다. 문제가 발생했을 때 "어떤 모델이, 어떤 프롬프트로, 얼마나 걸려서, 얼마의 비용으로" 응답했는지를 추적할 수 있어야 디버깅과 최적화가 가능합니다.

**구성 요소:**

| 클래스 | 역할 |
|---|---|
| `ArchonTracer` (ABC) | 트레이싱 추상 인터페이스 |
| `NoOpTracer` | 트레이싱 비활성화 시 사용 (기본값) |
| `CompositeTracer` | 여러 백엔드에 동시 전송 |
| `SamplingTracer` | 샘플링 비율에 따라 일부만 기록 (비용 절감) |

**지원 백엔드:**
- **LangSmith** — LangChain 에코시스템 트레이싱
- **Langfuse** — 오픈소스 LLM 옵저버빌리티
- **AITOP** — OTLP/HTTP 프로토콜 기반 커스텀 백엔드

**동작 방식:**

`TracingMiddleware`가 `BaseAgent.execute()`와 `Orchestrator.process_handoff()`에 자동으로 연동됩니다. 별도 코드 수정 없이 `TracingConfig` 설정만으로 활성화할 수 있습니다.

```python
# config에서 TracingConfig를 설정하면 자동 활성화
tracing:
  enabled: true
  backends: ["langfuse"]
  sampling_rate: 0.5  # 50%만 기록
```

---

### Benchmark (`src/benchmark/`)

**왜 필요한가요?** LLM 모델은 계속 출시되고 업데이트됩니다. 어떤 모델이 어떤 역할에 가장 적합한지를 객관적으로 비교해야 최적의 모델 배치를 유지할 수 있습니다.

**구성 요소:**

| 클래스 | 역할 |
|---|---|
| `BenchmarkRunner` | litellm을 통해 여러 모델에 동일한 태스크를 병렬 실행합니다 |
| `BenchmarkScorer` | accuracy / latency / cost를 가중 점수로 환산합니다 |
| `ModelRecommender` | 역할별 최적 모델을 추천하고, ProjectRegistry를 자동 업데이트합니다 |

**흐름:**
1. `BenchmarkRunner`가 정해진 테스트 셋으로 모델들을 실행합니다.
2. `BenchmarkScorer`가 정확도, 응답 속도, 비용을 종합하여 점수를 매깁니다.
3. `ModelRecommender`가 역할(backend, tester 등)별로 최적의 모델을 선택하고, 프로젝트 설정을 자동으로 갱신합니다.

---

### Evolution (`src/evolution/`)

**왜 필요한가요?** 프로젝트가 진행될수록 코드베이스의 특성이 변합니다. 초기에 설정한 품질 임계값(커버리지 기준, 복잡도 점수 등)이 나중에는 맞지 않을 수 있습니다. Evolution Loop는 시스템이 스스로 학습하고 조정하도록 합니다.

**구성 요소:**

| 클래스 | 역할 |
|---|---|
| `MetricsCollector` | 완료된 태스크의 품질 메트릭을 수집합니다 |
| `PatternAnalyzer` | 수집된 메트릭에서 패턴과 추세를 분석합니다 |
| `ThresholdTuner` | 분석 결과를 바탕으로 임계값을 자동 조정합니다 |
| `EvolutionLoop` | 위 단계를 asyncio 백그라운드 루프로 지속 실행합니다 |

**동작 방식:**

```
MetricsCollector → PatternAnalyzer → ThresholdTuner → (반복)
```

백그라운드 asyncio 루프로 연속 실행되며, 임계값이 변경될 때마다 `on_policy_updated` 콜백을 호출하여 변경 사항을 영구 저장합니다.

---

### Dashboard (`src/dashboard/`)

**왜 필요한가요?** 터미널 로그만으로는 전체 시스템 상태를 파악하기 어렵습니다. 웹 대시보드를 통해 프로젝트, 에이전트, 비용, 대기 중인 Human Gate 요청 등을 한눈에 볼 수 있습니다.

**구성 요소:**

- **FastAPI REST API** — 10개 엔드포인트
- **WebSocket** — 실시간 이벤트 스트리밍
- **SPA 프론트엔드** — `index.html` + `dashboard.js`

**주요 화면:**

| 화면 | 내용 |
|---|---|
| Projects | 프로젝트별 진행 상태, 최근 태스크 |
| Agents | 에이전트 풀 현황, 상태(HEALTHY/DEGRADED 등) |
| Cost | 모델별·기간별 비용 추적 |
| Gate Queue | 승인 대기 중인 Human Gate 요청 목록 |
| Metrics | 품질 메트릭 추세, Evolution Loop 조정 이력 |

---

### Guardrails (`src/guardrails/`)

**왜 필요한가요?** AI 에이전트가 코드를 수정하는 시스템에서는 안전장치가 필수적입니다. 민감 정보 유출, 프롬프트 인젝션, 위험한 코드 실행, 비용 초과를 사전에 방지해야 합니다.

**구성 요소:**

| 클래스 | 역할 |
|---|---|
| `InputValidator` | 민감정보 탐지, 프롬프트 인젝션 방어, 토큰 제한, 금지 키워드 검사 |
| `OutputValidator` | 위험 코드 패턴, 보안 취약점, 환각(hallucination) 힌트 검출 |
| `TokenBudgetTracker` | 일일/에이전트별 토큰 사용량 추적 및 예산 초과 방지 |
| `PathGuard` | `protected_paths` 차단, 설정 파일 변경 시 Human Gate 강제 |

**동작 예시:**

```python
# InputValidator — 프롬프트 인젝션 방어
validator = InputValidator(config)
result = validator.validate(user_input)
if not result.is_safe:
    raise GuardrailViolation(result.reason)

# PathGuard — 보호 경로 차단
guard = PathGuard(protected_paths=[".env", "config/secrets.yaml"])
guard.check(changed_files)  # 위반 시 L2_HUMAN 강제
```

---

### Self-Healing (`src/healing/`)

**왜 필요한가요?** 에이전트가 실패하면 전체 파이프라인이 멈출 수 있습니다. Self-Healing은 에이전트 장애를 자동으로 감지하고 복구하여 시스템의 연속성을 보장합니다.

**구성 요소:**

| 클래스 | 역할 |
|---|---|
| `AgentHealthMonitor` | 에이전트 상태 추적: HEALTHY → DEGRADED → UNHEALTHY → DEAD |
| `AgentDiagnostician` | 에러 분류(8종) + 근본 원인 추정 |
| `SelfHealer` | 복구 전략 실행: model_downgrade, agent_reinit, substitute, escalate |
| `HealthWatchdog` | asyncio 백그라운드 모니터링 루프 |

**복구 전략 (우선순위 순):**

1. **model_downgrade** — 현재 모델에 문제가 있으면 더 안정적인 모델로 교체합니다.
2. **agent_reinit** — 에이전트를 초기화하고 재시도합니다.
3. **substitute** — 같은 역할의 다른 에이전트로 대체합니다.
4. **escalate** — 모든 자동 복구가 실패하면 Human Gate (L2_HUMAN)로 상향합니다.

---

### Ollama Bridge (`src/runtime/ollama_bridge.py`)

**왜 필요한가요?** 모든 개발자가 GPU 워커를 갖고 있지는 않습니다. Ollama Bridge를 통해 로컬 머신(MacBook 등)에서 Ollama로 실행되는 모델을 LiteLLM에 바로 통합할 수 있습니다.

**구성 요소:**

- `OllamaEndpoint` — model_name, base_url, tags 설정
- `health_check()` — Ollama 서버 상태 확인
- 모델 자동 pull — 등록된 모델이 없으면 자동으로 다운로드
- litellm config 자동 생성 — 수동 설정 없이 바로 연동

`role_router.py`와 함께 동작하여 vLLM → Ollama → default 폴백 체인을 구성합니다.

---

### KubeRay (`src/runtime/kuberay.py`)

**왜 필요한가요?** 프로덕션 환경에서 Ray 클러스터를 Kubernetes 위에서 관리해야 할 때 사용합니다. KubeRay CRD(Custom Resource Definition)를 코드로 제어하여 인프라 관리를 자동화합니다.

**구성 요소:**

| 클래스 | 역할 |
|---|---|
| `KubeRayConfig` | 클러스터 전체 설정 |
| `WorkerGroupConfig` | 워커 그룹(CPU/GPU 노드) 설정 |
| `AutoScaleConfig` | 오토스케일링 정책 |
| `KubeRayManager` | deploy / scale / delete / status 관리 |

---

### Hybrid Cloud (`src/runtime/hybrid.py`)

**왜 필요한가요?** 로컬 GPU만으로 충분할 때는 클라우드 비용을 쓸 필요가 없습니다. 하지만 대규모 작업이 몰리면 클라우드로 오버플로우해야 합니다. Hybrid Cloud는 이 결정을 자동으로 내립니다.

**스케줄링 전략:**

| 전략 | 설명 |
|---|---|
| `LOCAL_FIRST` | 로컬 GPU를 최우선으로 사용합니다 |
| `COST_OPTIMAL` | 비용 대비 성능이 가장 좋은 옵션을 선택합니다 |
| `PERFORMANCE` | 최고 성능을 위해 클라우드를 적극 활용합니다 |
| `BALANCED` | 비용과 성능의 균형을 맞춥니다 |

**구성 요소:**

- `GPUResource` — 로컬/클라우드 GPU 리소스 정의
- `HybridConfig` — 일일/월간 예산 한도 설정
- `schedule_task()` — 로컬 GPU 용량 확인 → 초과 시 클라우드 오버플로우

---

### Harness 기능 (여러 모듈에 걸친 기능)

Phase 3에서 기존 모듈에 추가된 주요 기능들입니다.

**GitExecutor 스냅샷 (`src/runtime/git_executor.py`)**

git stash를 기반으로 한 트랜잭션 스냅샷/롤백 기능입니다. 에이전트가 코드를 수정하기 전에 스냅샷을 저장하고, 문제가 발생하면 롤백할 수 있습니다.

```python
executor = GitExecutor(repo_path)
snapshot_id = await executor.save_snapshot()  # git stash로 현재 상태 저장
# ... 에이전트가 코드 수정 ...
# 문제 발생 시:
await executor.rollback_to_snapshot(snapshot_id)  # 원래 상태로 복원
```

**Compressor token_gap (`src/memory/compressor.py`)**

API에서 "prompt too long" 에러가 반환될 때, 에러 메시지에 포함된 초과 토큰 수를 파싱하여 정확히 필요한 만큼만 압축합니다. 기존의 일률적 압축 대비 정보 손실을 최소화합니다.

**BaseAgent 자가 교정 (`src/agents/base.py`)**

JSON 파싱 실패 시 교정 프롬프트를 포함하여 1회만 재시도합니다. 무한 루프에 빠지지 않으면서도 파싱 성공률을 크게 개선합니다.

---

## 에이전트별 담당 역할

| 역할 | 기본 모델 | 담당 |
|---|---|---|
| orchestrator | claude-opus-4-6 | 설계, 분배, 리뷰, Human Gate 관리 |
| reviewer | claude-sonnet-4-6 | 코드 리뷰, review_score 산출 |
| backend | ollama/deepseek-v3.2:70b | API, DB, 비즈니스 로직 |
| frontend | ollama/qwen3.5:32b | UI/UX 구현 |
| tester | ollama/gemma4:14b | 테스트 자동화, 커버리지 |
| devops | ollama/glm-5:14b | CI/CD, IaC, 인프라 |
| docs | ollama/mimo-v2:7b | 문서화, API 스펙 |

## 하드웨어 전략

### Phase 1 — MacBook 단독

M5 Max 128GB에서 모든 에이전트를 실행합니다.

| 용도 | 메모리 |
|---|---|
| OS + 런타임 오버헤드 | ~8 GB |
| 코딩 에이전트 (70B Q4) | ~40 GB |
| 경량 에이전트 x3 (14B Q4) | ~27 GB |
| KV 캐시 + 여유 | ~53 GB |

### Phase 2 — 멀티 노드

MacBook (Ray Head) + PC Worker (GPU). `ray.init(address="auto")` 한 줄로 연결합니다. vLLM Bridge로 GPU 워커 엔드포인트를 등록합니다.

### Phase 3 — 클라우드 하이브리드

KubeRay + 온프레미스 + 클라우드 버스트아웃. 코드 변경 없이 노드를 추가할 수 있습니다. `hybrid.py`의 스케줄링 전략에 따라 로컬과 클라우드 리소스가 자동으로 배분됩니다.

## 관련 문서

- [Handoff Artifact 스키마](handoff-schema.md)
- [Project Registry 스키마](registry-schema.md)
- [Human Gate 설계](human-gate.md)
- [빠른 시작 가이드](quickstart.md)
