# Archon 시스템 아키텍처

🇺🇸 [English](../en/architecture.md)

> 버전: 1.1.0 | 최종 수정: 2026-04-23

## 개요

Archon은 7계층 아키텍처로 구성된 멀티 에이전트 AI 개발 플랫폼이다. Claude API를 마스터 오케스트레이터로, 오픈소스 LLM들을 전문 에이전트로 활용해 1인 개발자가 팀급 생산성을 달성한다.

## 핵심 설계 원칙

| 원칙 | 설명 |
|---|---|
| P1. 에이전트는 무상태 | 프로젝트에 종속되지 않음. 태스크마다 `project_context` 주입 |
| P2. 구조는 공개, 영혼은 비공개 | 스키마·설계는 오픈소스, 프롬프트·SOP는 Private |
| P3. 코드 변경 없이 스케일아웃 | Ray 기반 — 노드 추가만으로 선형 확장 |
| P4. 작업은 멈추지 않는다 | Human Gate 발동 시 해당 프로젝트만 일시정지 |
| P5. 모델은 항상 교체 가능 | LiteLLM Proxy로 역할별 모델 YAML 교체 |
| P6. 고위험 영역은 반드시 인간이 본다 | Dynamic Guardrails — 결제·인증·인프라 자동 L2 상향 |

## 7계층 구조

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
  LiteLLM Proxy (localhost:4000)
          │
          ▼
Layer 4 — Specialized Agent Pool
  src/agents/base.py           — BaseAgent (streaming, A2A, 구조화 출력)
  src/agents/{backend,frontend,tester,devops,docs}.py
  (무상태 · 컨텍스트 주입 · 풀 공유)
          │
          ▼
Layer 5 — QA Pipeline + Human Gate
  src/pipeline/qa.py           — 병렬 lint/build/test/security
  src/pipeline/git_executor.py — 자동 커밋, protected_paths 검증
  src/gate/evaluator.py        — 5-레벨 gate decision
  src/notifications/           — Slack · Terminal 알림
          │
          ▼
Layer 6 — Shared Memory & Context Store
  src/memory/context_injector.py   — 3계층 파사드 (MemoryStore)
  src/memory/redis_scratchpad.py   — L1: Redis (TTL 24h)
  src/memory/vector_store.py       — L2: ChromaDB 벡터 검색
  src/memory/mem0_store.py         — L3: Mem0 크로스 프로젝트
  src/memory/compressor.py         — 대형 핸드오프 압축
          │
          ▼
Layer 7 — LLM Runtime
  src/runtime/vllm_bridge.py  — vLLM 엔드포인트 관리
  src/runtime/cluster.py      — Ray 클러스터
  MLX (Apple Silicon) · Ollama · vLLM · Claude API
```

## 모듈별 역할

### Orchestrator (`src/orchestrator/`)

`orchestrator.py` — 전체 파이프라인을 지휘한다.

- **6개 에이전트 풀**: `backend`, `frontend`, `tester`, `devops`, `docs`, `reviewer`
- **Task Chain**: 에이전트 완료 후 연쇄 실행. 기본값:
  - `backend` → tester → docs
  - `frontend` → tester → docs
  - `devops` → tester
- **`process_chain()`**: 체인을 순차 실행하며 각 핸드오프를 반환
- **알림**: Gate 판정 후 `CompositeNotifier`로 Slack/Terminal에 이벤트 전송

`handoff.py` — 에이전트 간 컨텍스트 전달 표준.

7섹션 Pydantic 모델: `Envelope` · `ProjectContext` · `Task` · `Artifacts` · `QualityGates` · `HumanGatePackage` · `MemoryContext`

---

### BaseAgent (`src/agents/base.py`)

모든 에이전트의 공통 베이스 클래스.

- **무상태**: 에이전트 인스턴스는 아무것도 기억하지 않는다. 매 태스크마다 `HandoffArtifact`로 컨텍스트가 주입된다.
- **3가지 실행 모드**:
  - `execute()` — 일반 동기식 LLM 호출
  - `execute_streaming()` — 청크 단위 스트리밍 (`AsyncIterator[str]`)
  - `execute_with_streaming()` — `AgentModelConfig.streaming`이 True면 스트리밍, 아니면 일반 폴백
- **자동 압축**: 토큰 초과 시 `compress_handoff()`로 자동 컨텍스트 압축
- **구조화 출력**: LLM이 `<archon-output>JSON</archon-output>` 태그로 반환하면 `changed_files`, `decisions` 등을 파싱
- **A2A 메시지**: `send_a2a()`, `receive_a2a()`로 에이전트 간 직접 통신

---

### Human Gate (`src/gate/`)

`evaluator.py`의 `evaluate_gate()` 함수가 5-레벨을 결정한다.

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

태스크 복잡도를 측정해 동적으로 LLM 모델을 선택한다.

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

`select_model_by_complexity()`는 HIGH일 때 `AgentModelConfig.high_complexity_model`을 반환.

---

### 3계층 메모리 (`src/memory/`)

| 클래스 | 계층 | 백엔드 | TTL |
|---|---|---|---|
| `RedisScratchpad` | L1 단기 | Redis | 24시간 (`redis_ttl`) |
| `VectorStore` | L2 중기 | ChromaDB | 무제한 |
| `Mem0Store` | L3 장기 | Mem0 API | 무제한 |
| `MemoryStore` | 파사드 | 모두 통합 | — |

`MemoryStore.inject_memory_context()` — 태스크 지시사항을 쿼리로 L2+L3 검색 후 `MemoryContext`로 조합해 에이전트에 주입.

각 계층은 미연결(None) 시 인메모리 dict로 폴백하므로 인프라 없이도 동작한다.

---

### Task Scheduler (`src/queue/scheduler.py`)

의존성 기반 비동기 태스크 스케줄러.

1. `add_task(TaskSpec)` — 태스크 등록 (task_id, agent_role, depends_on, priority)
2. `topological_sort()` — Kahn's algorithm으로 실행 순서 계산, 순환 의존성 감지
3. `run(executor)` — asyncio Semaphore로 동시 실행 수 제한 (`concurrency=3` 기본)

---

### MCP Server (`src/mcp/server.py`)

외부 클라이언트(IDE, CLI)가 Archon을 제어하는 MCP 도구 5개.

| 도구 | 설명 |
|---|---|
| `execute_task` | 태스크를 특정 에이전트에게 제출 |
| `get_status` | 프로젝트/태스크 상태 조회 |
| `list_agents` | 사용 가능한 에이전트 목록 |
| `get_project` | 프로젝트 레지스트리 상세 |
| `list_projects` | 등록된 프로젝트 목록 |

실제 MCP SDK 전송 계층(stdio/SSE) 연동은 Phase 3.

---

### A2A Messaging (`src/mcp/a2a.py`)

에이전트 간 직접 통신 (Google A2A 프로토콜 기반).

- `A2ARouter.send(message)` — 수신 에이전트의 mailbox에 메시지 적재
- `A2ARouter.receive(agent_role)` — 자신의 mailbox에서 메시지 꺼내기
- `BaseAgent.send_a2a()`, `receive_a2a()` — 에이전트 레벨 인터페이스
- 메시지 타입: `REQUEST`, `RESPONSE`, `BROADCAST`, `NOTIFY`
- 우선순위: `LOW`, `NORMAL`, `HIGH`, `URGENT`

---

### Notifications (`src/notifications/`)

Gate 이벤트 발생 시 개발자에게 알림을 전송한다.

- `GateEvent` — 알림 페이로드 모델 (project_id, task_id, gate_decision, trigger_reason, severity)
- `TerminalNotifier` — rich 라이브러리 TUI + macOS `osascript` 데스크탑 알림
- `SlackNotifier` — Slack incoming webhook
- `CompositeNotifier` — 여러 Notifier 묶어 동시 전송 (하나라도 성공하면 True)

AUTO_PASS는 기본적으로 알림 미전송 (`Notifier.should_notify()`).

---

### vLLM Bridge (`src/runtime/vllm_bridge.py`)

GPU 워커 노드의 vLLM 서버를 LiteLLM에 통합한다.

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

M5 Max 128GB에서 모든 에이전트 실행.

| 용도 | 메모리 |
|---|---|
| OS + 런타임 오버헤드 | ~8 GB |
| 코딩 에이전트 (70B Q4) | ~40 GB |
| 경량 에이전트 ×3 (14B Q4) | ~27 GB |
| KV 캐시 + 여유 | ~53 GB |

### Phase 2 — 멀티 노드

MacBook (Ray Head) + PC Worker (GPU). `ray.init(address="auto")` 한 줄로 연결. vLLM Bridge로 GPU 워커 엔드포인트 등록.

### Phase 3 — 클라우드 하이브리드

KubeRay + 온프레미스 + 클라우드 버스트아웃. 코드 변경 없이 노드 추가.

## 관련 문서

- [Handoff Artifact 스키마](handoff-schema.md)
- [Project Registry 스키마](registry-schema.md)
- [Human Gate 설계](human-gate.md)
- [빠른 시작 가이드](quickstart.md)
