# Archon — Work Status

> 최종 업데이트: 2026-04-22 (Architecture Review 반영)

## Phase 1 — PoC (에이전트 2개가 Handoff로 코드 생성)

### 완료

- [x] 환경 구성
  - [x] `archon-framework/` Public 레포 초기화
  - [x] `archon-private/` Private 레포 초기화
  - [x] pyproject.toml, .gitignore, .env.example 설정
  - [x] LiteLLM config 예시 (`config/litellm_config.yaml.example`)
  - [x] Ray config 예시 (`config/ray_config.yaml.example`)
- [x] 코어 스키마 구현 (Pydantic v2)
  - [x] HandoffArtifact 7섹션 (`src/orchestrator/handoff.py`)
  - [x] ProjectRegistry 8섹션 (`src/registry/models.py`)
  - [x] GateDecision enum (`src/gate/models.py`)
- [x] 에이전트 베이스 클래스
  - [x] BaseAgent — 무상태, LiteLLM 연동 (`src/agents/base.py`)
  - [x] BackendAgent (`src/agents/backend.py`)
  - [x] ReviewerAgent (`src/agents/reviewer.py`)
- [x] Human Gate 기본 구현
  - [x] gate_decision 판정 로직 (`src/gate/evaluator.py`)
  - [x] 테스트 11개 케이스 (`tests/test_gate_evaluator.py`)
- [x] LLM Router
  - [x] Role-based Router (`src/router/role_router.py`)
- [x] 메모리 관리
  - [x] 3계층 메모리 스토어 스텁 (`src/memory/context_injector.py`)
- [x] Ray 클러스터 초기화 (`src/runtime/cluster.py`)
- [x] 오케스트레이터 코어 (`src/orchestrator/orchestrator.py`)
- [x] 설계 문서 (docs/ko, docs/en)
- [x] CLAUDE.md / GEMINI.md (Private 레포)
- [x] **[Review 수용]** Orchestrator 상태 머신 고도화
  - [x] L1_REWORK 루프백 로직 (retry_count 관리, 최대 3회)
  - [x] 3회 초과 시 L2_HUMAN 자동 에스컬레이션
  - [x] 리뷰 플래그를 재작업 지시사항에 자동 반영
- [x] **[Review 수용]** QA Pipeline 연동 (`src/runtime/qa.py`)
  - [x] ruff (lint), mypy (typecheck), pytest (unit test) subprocess 실행
  - [x] JUnit XML 파싱 → TestResults 바인딩
  - [x] semgrep 보안 스캔 → SecurityScan 바인딩
  - [x] pytest-cov 커버리지 측정
  - [x] 전체 QA 병렬 실행 (asyncio.gather)
- [x] **[Review 수용]** Auto-Commit 구현 (`src/runtime/git_executor.py`)
  - [x] GitExecutor 클래스 — 브랜치 생성/체크아웃/커밋/푸시
  - [x] protected_paths 검증 (ProtectedPathViolation 예외)
  - [x] 커밋 메시지 템플릿 치환
  - [x] force push 시도 감지
  - [x] 테스트 6개 케이스 (`tests/test_git_executor.py`)

### 진행 중

- [ ] MLX + Ollama 설치 및 모델 다운로드
  - [ ] deepseek-v3.2:70b (Backend)
  - [ ] gemma4:14b (Tester)
  - [ ] qwen3.5:32b (Frontend)
  - [ ] glm-5:14b (DevOps)
  - [ ] mimo-v2:7b (Docs)
- [ ] LiteLLM Proxy 로컬 실행 테스트

### 미착수

- [ ] PoC 데모 파이프라인
  - [ ] Backend Agent → Handoff Artifact 생성
  - [ ] Reviewer Agent → review_score + gate_decision
  - [ ] auto_pass 시 자동 커밋
  - [ ] L1 시 에이전트 재작업 (최대 3회)
  - [ ] L2 시 터미널 알림 + 프로젝트 일시정지
- [ ] `__main__.py` 엔트리포인트 (`python -m archon demo`)

---

## Phase 2 — 멀티 에이전트 + 멀티 프로젝트

### Architecture Review 연기 항목
- [ ] **[Review 연기]** Async Streaming — LiteLLM 스트리밍 응답 처리 (타임아웃 방지, 실시간 모니터링)
- [ ] **[Review 연기]** Context Compression — 대용량 Handoff Artifact 압축/요약 전달 로직

### 기능 구현
- [ ] 에이전트 풀 완성
  - [ ] FrontendAgent
  - [ ] TesterAgent
  - [ ] DevOpsAgent
  - [ ] DocsAgent
- [ ] Work Queue (Celery + Redis)
  - [ ] 태스크 큐 스케줄러
  - [ ] 의존성 기반 실행 순서
  - [ ] 멀티 프로젝트 우선순위 관리
- [ ] Project Registry 완전 구현
  - [ ] `.harness/registry/` JSON 파일 읽기/쓰기
  - [ ] work_queue 실시간 업데이트
  - [ ] metrics 자동 수집
- [ ] Mem0 + ChromaDB 메모리 연동
  - [ ] 벡터 검색 통합 (cosine similarity > 0.85)
  - [ ] 프로젝트별 컬렉션 격리
  - [ ] 패턴 자동 학습
- [ ] Redis 스크래치패드 연동
  - [ ] TTL 24시간 단기 메모리
  - [ ] 실시간 태스크 컨텍스트
- [ ] PC 워커 노드 Ray 클러스터 연결
  - [ ] vLLM 서버 설정 (GPU 노드)
  - [ ] Ray Worker 등록
- [ ] 알림 연동
  - [ ] Slack 알림 (L2/L3/L4)
  - [ ] 터미널 알림 개선 (rich TUI)
- [ ] MCP / A2A Protocol 통합
  - [ ] MCP 서버 구현
  - [ ] A2A 에이전트 간 통신
- [ ] Complexity Router
  - [ ] 태스크 복잡도 측정
  - [ ] 동적 모델 라우팅

---

## Phase 3 — 프로덕션

- [ ] KubeRay 설정
- [ ] 클라우드 하이브리드 구성
- [ ] 대시보드 UI
  - [ ] 프로젝트별 진행률
  - [ ] 에이전트 상태 모니터링
  - [ ] 비용 대시보드
  - [ ] Human Gate 관리 UI
- [ ] 벤치마크 자동화
  - [ ] 역할별 모델 벤치마크
  - [ ] 최적 모델 자동 교체
- [ ] 문서 완성
  - [ ] API Reference
  - [ ] 플러그인 개발 가이드
  - [ ] 운영 가이드
- [ ] GitHub Public 릴리즈
  - [ ] v0.1.0 태그
  - [ ] PyPI 배포
- [ ] Guardrails 구현
  - [ ] 입출력 검증
  - [ ] 토큰 예산 관리
  - [ ] protected_paths 강제

---

## 기술 부채 / 개선 사항

- [ ] Handoff Artifact 스키마 마이그레이션 도구
- [ ] 에이전트 실행 타임아웃 설정
- [ ] 에러 복구 전략 (partial failure handling)
- [ ] 크로스 프로젝트 메모리 정책 설계
- [ ] LLM 응답 스트리밍 지원
- [ ] Handoff Artifact 압축 (대용량 컨텍스트)
