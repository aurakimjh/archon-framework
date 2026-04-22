# Archon 시스템 아키텍처

> 버전: 1.0.0 | 최종 수정: 2026-04-22

## 개요

Archon은 7계층 아키텍처로 구성된 멀티 에이전트 AI 개발 플랫폼이다. Claude API를 마스터 오케스트레이터로, 오픈소스 LLM들을 전문 에이전트로 활용해 1인 개발자가 팀급 생산성을 달성한다.

## 핵심 설계 원칙

| 원칙 | 설명 |
|---|---|
| P1. 에이전트는 무상태 | 프로젝트에 종속되지 않음. 태스크마다 project_context 주입 |
| P2. 구조는 공개, 영혼은 비공개 | 스키마·설계는 오픈소스, 프롬프트·SOP는 Private |
| P3. 코드 변경 없이 스케일아웃 | Ray 기반 — 노드 추가만으로 선형 확장 |
| P4. 작업은 멈추지 않는다 | Human Gate 발동 시 해당 프로젝트만 일시정지 |
| P5. 모델은 항상 교체 가능 | LiteLLM Proxy로 역할별 모델 YAML 교체 |

## 7계층 구조

```
Layer 0 — Human in the Loop
  개발자: 아이디어 입력 · 설계 검토 · 실 테스트 · 최종 승인
          │
          │ Human Gate (양방향)
          ▼
Layer 1 — Orchestrator (Claude API)
  마스터 아키텍트 · 코드 리뷰어 · Human Gate 관리
  모델: Claude Opus 4.6 (설계) / Claude Sonnet 4.6 (리뷰)
          │
          │ MCP / A2A Protocol
          ▼
Layer 2 — Protocol Bus
  MCP (Anthropic) · A2A (Google) · Handoff Artifact JSON
          │
          │ Task Queue (Ray / Celery)
          ▼
Layer 3 — LLM Selector / Router
  Role-based Router · Complexity Router · Fallback
  구현: LiteLLM Proxy (localhost:4000)
          │
          ▼
Layer 4 — Specialized Agent Pool
  Frontend │ Backend │ Tester │ DevOps │ Docs
  (무상태 · 컨텍스트 주입 · 풀 공유)
          │
          ▼
Layer 5 — Shared Memory & Context Store
  Git + Artifact (장기) · ChromaDB (중기) · Redis (단기)
          │
          ▼
Layer 6 — LLM Runtime
  MLX (Apple Silicon) · Ollama · vLLM · Claude API
          │
          ▼
Layer 7 — Observability & Governance
  Tracing · Cost Monitor · Eval Loop · Guardrails
```

## 계층별 상세

### Layer 0 — Human in the Loop

개발자는 아이디어 제시, 설계 검토, 실 테스트, 최종 승인을 담당한다. 에이전트가 자동으로 처리할 수 없는 판단(L2~L4 Human Gate)에만 개입한다.

### Layer 1 — Orchestrator

Claude API가 전체 파이프라인을 지휘한다.

- **마스터 아키텍트**: 요구사항 분해 → SOP 생성 → 작업 분배
- **코드 리뷰어**: 전체 리뷰, 보안 검토, 설계 일관성
- **Human Gate 관리**: L1~L4 판단, 개발자 알림

### Layer 2 — Protocol Bus

에이전트 간 통신 표준 인터페이스.

- **MCP** (Anthropic): 에이전트 ↔ 도구 표준
- **A2A** (Google): 이종 프레임워크 간 P2P 협업
- **Handoff Artifact**: 구조화 JSON 핸드오프 문서 → [상세](handoff-schema.md)

### Layer 3 — LLM Selector / Router

LiteLLM Proxy를 단일 API 게이트웨이로 사용.

- **Role-based Router**: 역할별 사전 정의 모델
- **Complexity Router**: 태스크 복잡도 기반 동적 라우팅 (Phase 2)
- **Fallback**: 모델 장애 시 자동 페일오버

### Layer 4 — Specialized Agent Pool

| 역할 | 기본 모델 | 담당 |
|---|---|---|
| orchestrator | claude-opus-4-6 | 설계, 분배, 리뷰 |
| reviewer | claude-sonnet-4-6 | 코드 리뷰, 품질 점수 |
| frontend | ollama/qwen3.5:32b | UI/UX 구현 |
| backend | ollama/deepseek-v3.2:70b | API, DB, 비즈니스 로직 |
| tester | ollama/gemma4:14b | 테스트 자동화 |
| devops | ollama/glm-5:14b | CI/CD, IaC |
| docs | ollama/mimo-v2:7b | 문서화 |

### Layer 5 — Shared Memory

3계층 메모리 구조 → [상세](../ko/architecture.md#공유-메모리)

- **L1 단기**: Redis 스크래치패드 (TTL 24시간)
- **L2 중기**: Git + ChromaDB (프로젝트 격리)
- **L3 장기**: Mem0 (크로스 프로젝트, 기본 비활성)

### Layer 6 — LLM Runtime

- **MLX**: Apple Silicon 최적화, Ollama 대비 20~50% 빠름
- **Ollama**: 간편 설치, 폭넓은 모델 지원
- **vLLM**: 프로덕션급 고처리량 서빙

### Layer 7 — Observability

- **Tracing**: LangSmith / Langfuse
- **Cost Monitor**: LiteLLM Dashboard
- **Eval Loop**: 산출물 품질 자동 평가
- **Guardrails**: 입출력 검증, 보안 정책

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

MacBook (Ray Head) + PC Worker (GPU). `ray.init(address="auto")` 한 줄로 연결.

### Phase 3 — 클라우드 하이브리드

KubeRay + 온프레미스 + 클라우드 버스트아웃. 코드 변경 없이 노드 추가.
