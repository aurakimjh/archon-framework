# Archon Framework

🇺🇸 [English](README.md)

> 1인 개발자가 AI 에이전트 군단을 지휘해 중소 개발팀의 생산성을 능가하는 멀티 에이전트 AI 개발 플랫폼

## 개요

Archon은 Claude를 마스터 오케스트레이터로, 오픈소스 LLM들을 전문 에이전트로 활용한다. 에이전트는 **무상태**다 — 태스크마다 [Handoff Artifact](docs/ko/handoff-schema.md)로 컨텍스트를 주입받으므로, 어떤 에이전트도 사전 상태 없이 어떤 프로젝트든 처리할 수 있다.

- [한국어 문서](docs/ko/)
- [English Documentation](docs/en/)

## 핵심 기능

| 기능 | 상태 | 설명 |
|---|---|---|
| 에이전트 오케스트레이션 | ✅ | Handoff Artifact를 통한 컨텍스트 주입, 무상태 에이전트 |
| Human Gate | ✅ | 5단계 판정: AUTO_PASS / L1_REWORK / L2_HUMAN / L3_HALT / L4_DEPLOY |
| Dynamic Guardrails | ✅ | 고위험 경로/키워드(결제·인증·인프라) 감지 시 자동 L2 상향 |
| Complexity Router | ✅ | 8기준 복잡도 측정, 복잡 태스크에 `high_complexity_model` 라우팅 |
| 3계층 메모리 | ✅ | L1 Redis 스크래치패드 · L2 ChromaDB 벡터 검색 · L3 Mem0 크로스 프로젝트 |
| 비동기 스트리밍 | ✅ | BaseAgent의 `execute_streaming()`, litellm `stream=True` + 타임아웃 |
| 태스크 스케줄러 | ✅ | 의존성 기반 토폴로지 정렬 + asyncio 세마포어 동시성 |
| vLLM Bridge | ✅ | GPU 워커 엔드포인트 관리 + LiteLLM 통합 |
| MCP 서버 | ✅ | 5개 도구: execute_task / get_status / list_agents / get_project / list_projects |
| A2A 메시지 | ✅ | 에이전트 간 메일박스 라우팅 (Google A2A 프로토콜) |
| 알림 | ✅ | 터미널 (rich TUI + macOS 데스크탑) + Slack 웹훅 |
| SOP 준수 | ✅ | 절차 준수 점수 미달 시 L2 Human Gate 강제 상향 |
| LLM 플러그인 교체 | ✅ | LiteLLM Proxy를 통한 역할별 모델 YAML 교체 |
| 멀티 프로젝트 | ✅ | 공유 에이전트 풀 + 격리된 프로젝트 네임스페이스 |
| 에어갭 지원 | ✅ | MLX/Ollama/vLLM로 로컬 오픈소스 LLM 실행 |
| Ray 클러스터 | 🔧 | 로컬/클러스터/쿠버네티스 모드 (Phase 3) |

## 아키텍처

```
┌─────────────────────────────────────────────────────────┐
│  Layer 0 — Human in the Loop                            │
│  개발자: 아이디어 입력 · 설계 검토 · Human Gate 결정     │
└────────────────────────┬────────────────────────────────┘
                         │ Human Gate (양방향)
┌────────────────────────▼────────────────────────────────┐
│  Layer 1 — Orchestrator (Claude API)                    │
│  src/orchestrator/  — 설계·분배·리뷰·알림               │
└────────────────────────┬────────────────────────────────┘
                         │ Handoff Artifact JSON
┌────────────────────────▼────────────────────────────────┐
│  Layer 2 — Protocol Bus                                 │
│  src/mcp/server.py  — MCP 5 tools                      │
│  src/mcp/a2a.py     — A2A mailbox routing               │
└────────────────────────┬────────────────────────────────┘
                         │ Task Queue
┌────────────────────────▼────────────────────────────────┐
│  Layer 3 — LLM Selector / Router                        │
│  src/router/complexity.py  — 복잡도 기반 동적 라우팅    │
│  LiteLLM Proxy (localhost:4000)                         │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────┐
│  Layer 4 — Specialized Agent Pool                       │
│  src/agents/  — Backend · Frontend · Tester             │
│                 DevOps · Docs (무상태, 컨텍스트 주입)   │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────┐
│  Layer 5 — QA Pipeline + Human Gate                     │
│  src/pipeline/qa.py        — lint/build/test/security   │
│  src/gate/evaluator.py     — 5단계 게이트 판정          │
│  src/notifications/        — Slack · Terminal           │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────┐
│  Layer 6 — Shared Memory                                │
│  src/memory/  — Redis (L1) · ChromaDB (L2) · Mem0 (L3) │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────┐
│  Layer 7 — LLM Runtime                                  │
│  src/runtime/vllm_bridge.py  — vLLM 엔드포인트 관리    │
│  src/runtime/cluster.py      — Ray 클러스터             │
│  MLX · Ollama · vLLM · Claude API                       │
└─────────────────────────────────────────────────────────┘
```

## 모듈 맵

| 모듈 경로 | 설명 |
|---|---|
| `src/orchestrator/orchestrator.py` | 메인 오케스트레이터, 6개 에이전트 풀, task chain 실행 |
| `src/orchestrator/handoff.py` | HandoffArtifact 7-섹션 Pydantic 모델 |
| `src/agents/base.py` | 무상태 BaseAgent — streaming, A2A, 구조화 출력 파싱 |
| `src/agents/{backend,frontend,tester,devops,docs}.py` | 역할별 에이전트 구현 |
| `src/gate/evaluator.py` | Human Gate 5단계 판정 로직 |
| `src/gate/models.py` | GateDecision enum |
| `src/pipeline/qa.py` | ruff/mypy/pytest/semgrep/coverage 병렬 실행 |
| `src/pipeline/git_executor.py` | 자동 커밋, protected_paths 검증 |
| `src/pipeline/demo_pipeline.py` | mock 시나리오 기반 데모/테스트 파이프라인 |
| `src/registry/models.py` | ProjectRegistry 8-섹션 Pydantic 모델 |
| `src/registry/store.py` | JSON 파일 기반 레지스트리 영속성 |
| `src/router/complexity.py` | 8기준 복잡도 측정, 동적 모델 라우팅 |
| `src/memory/context_injector.py` | 3계층 메모리 파사드 (MemoryStore) |
| `src/memory/redis_scratchpad.py` | L1 Redis 단기 메모리 (TTL 24h) |
| `src/memory/vector_store.py` | L2 ChromaDB 벡터 검색 |
| `src/memory/mem0_store.py` | L3 Mem0 크로스 프로젝트 패턴 학습 |
| `src/memory/compressor.py` | 대형 핸드오프 컨텍스트 압축 |
| `src/queue/scheduler.py` | 의존성 토폴로지 정렬 + asyncio 스케줄러 |
| `src/queue/priority.py` | 우선순위 큐 유틸리티 |
| `src/mcp/server.py` | MCP 서버 — 5개 도구 정의 및 핸들러 |
| `src/mcp/a2a.py` | A2A 에이전트 간 메시지 라우팅 |
| `src/notifications/base.py` | GateEvent 모델 + Notifier 추상 클래스 |
| `src/notifications/terminal.py` | rich TUI + macOS 데스크탑 알림 |
| `src/notifications/slack.py` | Slack webhook 알림 |
| `src/runtime/vllm_bridge.py` | vLLM 엔드포인트 관리, LiteLLM 통합 |
| `src/runtime/cluster.py` | Ray 클러스터 (local/cluster/kubernetes) |
| `src/errors.py` | 커스텀 예외 계층 구조 |
| `archon/__main__.py` | CLI 엔트리포인트 (`python -m archon`) |

## 빠른 시작

```bash
# 1. Clone
git clone https://github.com/aurakimjh/archon-framework.git
cd archon-framework

# 2. 환경 설정
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# 3. 설정 파일
cp .env.example .env
cp config/litellm_config.yaml.example config/litellm_config.yaml
# .env에 ANTHROPIC_API_KEY 입력

# 4. LiteLLM Proxy 시작 (로컬 모델용)
litellm --config config/litellm_config.yaml --port 4000

# 5. Mock 데모 (LLM 없이 동작 확인)
python3 -m archon demo --mock --scenario auto_pass
python3 -m archon demo --mock --scenario l1
python3 -m archon demo --mock --scenario l2

# 6. 실제 LLM으로 실행
python3 -m archon demo

# 7. 버전 확인
python3 -m archon version
```

## Human Gate — 5단계

| 레벨 | 트리거 | 후속 동작 |
|---|---|---|
| `AUTO_PASS` | 모든 체크 통과 | 자동 커밋 → 브랜치 푸시 |
| `L1_REWORK` | 린트 실패, 커버리지 아슬, 단위 테스트 소수 실패 | 에이전트 자동 재작업 (최대 3회) |
| `L2_HUMAN` | review_score < 70, 스키마 변경, 외부 연동, SOP 미달, **Dynamic Guardrails** | 개발자 알림, 프로젝트 일시정지 |
| `L3_HALT` | 빌드 실패, Critical/High 보안 취약점 | 즉시 중단, 긴급 알림 |
| `L4_DEPLOY` | 배포 요청 | 항상 Human 최종 승인 |

**Dynamic Guardrails**: `payment`, `auth`, `migration`, `secrets/` 등 고위험 경로나 키워드 감지 시 다른 점수와 무관하게 자동으로 L2로 상향.

## 테스트

```bash
# 전체 테스트
pytest tests/ -v

# 데모 파이프라인 테스트 (mock, LLM 불필요)
pytest tests/test_demo_pipeline.py -v

# Gate 로직 테스트
pytest tests/test_gate_evaluator.py -v
```

## 문서

- [아키텍처](docs/ko/architecture.md)
- [Handoff Artifact 스키마](docs/ko/handoff-schema.md)
- [Project Registry 스키마](docs/ko/registry-schema.md)
- [Human Gate 설계](docs/ko/human-gate.md)
- [빠른 시작 가이드](docs/ko/quickstart.md)

## 라이선스

MIT
