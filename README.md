# Archon Framework

> 1인 개발자가 AI 에이전트 군단을 지휘해 중소 개발팀의 생산성을 능가하는 멀티 에이전트 AI 개발 플랫폼

## Overview

Archon uses Claude as a master orchestrator and open-source LLMs as specialized agents. Agents are **stateless** — each task injects context via a [Handoff Artifact](docs/ko/handoff-schema.md), so any agent can handle any project without prior state.

- [한국어 문서](docs/ko/)
- [English Documentation](docs/en/)

## Key Features

| Feature | Status | Description |
|---|---|---|
| Agent Orchestration | ✅ | Stateless agents with context injection via Handoff Artifacts |
| Human Gate | ✅ | 5-level decision framework: AUTO_PASS / L1_REWORK / L2_HUMAN / L3_HALT / L4_DEPLOY |
| Dynamic Guardrails | ✅ | Auto-escalate to L2 on high-risk paths/keywords (payment, auth, infra...) |
| Complexity Router | ✅ | 8-criteria scoring; routes to `high_complexity_model` for complex tasks |
| 3-Layer Memory | ✅ | L1 Redis scratchpad · L2 ChromaDB vector search · L3 Mem0 cross-project patterns |
| Async Streaming | ✅ | `execute_streaming()` on BaseAgent; litellm `stream=True` with timeout |
| Task Scheduler | ✅ | Dependency-based topological sort + asyncio semaphore concurrency |
| vLLM Bridge | ✅ | GPU worker endpoint management + LiteLLM integration |
| MCP Server | ✅ | 5 tools: execute_task / get_status / list_agents / get_project / list_projects |
| A2A Messaging | ✅ | Agent-to-Agent mailbox routing (Google A2A protocol) |
| Notifications | ✅ | Terminal (rich TUI + macOS desktop) + Slack webhook |
| SOP Compliance | ✅ | Procedure score check; below threshold forces L2 Human Gate |
| LLM Plugin Swap | ✅ | Role-based model routing via LiteLLM Proxy |
| Multi-Project | ✅ | Isolated project namespaces with shared agent pools |
| Air-gap Support | ✅ | Local open-source LLM execution via MLX/Ollama/vLLM |
| Ray Cluster | 🔧 | Local/cluster/kubernetes modes (Phase 3) |

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Layer 0 — Human in the Loop                            │
│  개발자: 아이디어 입력 · 설계 검토 · Human Gate 결정      │
└────────────────────────┬────────────────────────────────┘
                         │ Human Gate (양방향)
┌────────────────────────▼────────────────────────────────┐
│  Layer 1 — Orchestrator (Claude API)                    │
│  src/orchestrator/  — 설계·분배·리뷰·알림                │
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
│  src/router/complexity.py  — 복잡도 기반 동적 라우팅     │
│  LiteLLM Proxy (localhost:4000)                         │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────┐
│  Layer 4 — Specialized Agent Pool                       │
│  src/agents/  — Backend · Frontend · Tester             │
│                 DevOps · Docs (무상태, 컨텍스트 주입)    │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────┐
│  Layer 5 — QA Pipeline + Human Gate                     │
│  src/pipeline/qa.py        — lint/build/test/security   │
│  src/gate/evaluator.py     — 5-level gate decision      │
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
│  src/runtime/vllm_bridge.py  — vLLM 엔드포인트 관리     │
│  src/runtime/cluster.py      — Ray 클러스터             │
│  MLX · Ollama · vLLM · Claude API                       │
└─────────────────────────────────────────────────────────┘
```

## Module Map

| 모듈 경로 | 설명 |
|---|---|
| `src/orchestrator/orchestrator.py` | 메인 오케스트레이터, 6개 에이전트 풀, task chain 실행 |
| `src/orchestrator/handoff.py` | HandoffArtifact 7-섹션 Pydantic 모델 |
| `src/agents/base.py` | 무상태 BaseAgent — streaming, A2A, structured output 파싱 |
| `src/agents/{backend,frontend,tester,devops,docs}.py` | 역할별 에이전트 구현 |
| `src/gate/evaluator.py` | Human Gate 5-레벨 판정 로직 |
| `src/gate/models.py` | GateDecision enum |
| `src/pipeline/qa.py` | ruff/mypy/pytest/semgrep/coverage 병렬 실행 |
| `src/pipeline/git_executor.py` | 자동 커밋, protected_paths 검증 |
| `src/pipeline/demo_pipeline.py` | mock 시나리오 기반 데모/테스트 파이프라인 |
| `src/registry/models.py` | ProjectRegistry 8-섹션 Pydantic 모델 |
| `src/registry/store.py` | JSON 파일 기반 레지스트리 영속성 |
| `src/router/complexity.py` | 8-기준 복잡도 측정, 동적 모델 라우팅 |
| `src/memory/context_injector.py` | 3-계층 메모리 파사드 (MemoryStore) |
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

## Quick Start

```bash
# 1. Clone
git clone https://github.com/aurakimjh/archon-framework.git
cd archon-framework

# 2. Setup environment
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# 3. Configure
cp .env.example .env
cp config/litellm_config.yaml.example config/litellm_config.yaml
# Edit .env with your ANTHROPIC_API_KEY

# 4. Start LiteLLM Proxy (for local models)
litellm --config config/litellm_config.yaml --port 4000

# 5. Run mock demo (LLM 없이 동작)
python3 -m archon demo --mock --scenario auto_pass
python3 -m archon demo --mock --scenario l1
python3 -m archon demo --mock --scenario l2

# 6. Run with real LLM
python3 -m archon demo

# 7. Version
python3 -m archon version
```

## Human Gate — 5 Levels

| 레벨 | 트리거 | 후속 동작 |
|---|---|---|
| `AUTO_PASS` | 모든 체크 통과 | 자동 커밋 → 브랜치 푸시 |
| `L1_REWORK` | 린트 실패, 커버리지 아슬, 단위 테스트 소수 실패 | 에이전트 자동 재작업 (최대 3회) |
| `L2_HUMAN` | review_score < 70, 스키마 변경, 외부 연동, SOP 미달, **Dynamic Guardrails** | 개발자 알림, 프로젝트 일시정지 |
| `L3_HALT` | 빌드 실패, Critical/High 보안 취약점 | 즉시 중단, 긴급 알림 |
| `L4_DEPLOY` | 배포 요청 | 항상 Human 최종 승인 |

**Dynamic Guardrails**: `payment`, `auth`, `migration`, `secrets/` 등 고위험 경로나 키워드 감지 시 자동으로 L2 상향.

## Testing

```bash
# 전체 테스트
pytest tests/ -v

# 데모 파이프라인 테스트 (mock, LLM 불필요)
pytest tests/test_demo_pipeline.py -v

# Gate 로직 테스트
pytest tests/test_gate_evaluator.py -v
```

## Documentation

- [아키텍처](docs/ko/architecture.md)
- [Handoff Artifact 스키마](docs/ko/handoff-schema.md)
- [Project Registry 스키마](docs/ko/registry-schema.md)
- [Human Gate 설계](docs/ko/human-gate.md)
- [빠른 시작 가이드](docs/ko/quickstart.md)

## License

MIT
