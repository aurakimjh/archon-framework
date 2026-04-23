# Project Registry 스키마

> 버전: 1.1.0 | 최종 수정: 2026-04-23

## 개요

Project Registry는 각 솔루션 프로젝트의 **전체 설정**을 담는 중앙 레지스트리다.

- 파일 위치: `.harness/registry/{project_id}.json`
- 소스 코드: `src/registry/models.py`, `src/registry/store.py`

## 8섹션 구조

| 섹션 | 역할 |
|---|---|
| project_meta | 식별 · 상태 · 우선순위 · 스케줄링 기준 |
| git_config | 레포 · 브랜치 전략 · SOP 경로 · protected_paths |
| agent_config | 역할별 LLM 모델 지정 (플러그인 교체 레이어) |
| quality_policy | QA 임계값 · Human Gate 판단 기준 · 예산 · Dynamic Guardrails |
| work_queue | 태스크 큐 스냅샷 · 현재 실행 상태 |
| memory_config | 3계층 메모리 설정 (Redis/ChromaDB/Mem0) |
| metrics | 진행률 · 비용 · 품질 · 속도 지표 |
| human_gate_history | 개발자 결정 이력 · 패턴 학습 원천 |

## 섹션 상세

### project_meta

```json
{
  "project_id": "proj_ecomm_v2",
  "project_name": "E-Commerce Platform v2",
  "status": "active",
  "priority": 10,
  "deadline": "2026-06-01T00:00:00Z",
  "owner": "dev_001",
  "description": "B2C 이커머스 플랫폼 v2 재설계",
  "tags": ["backend", "api", "payment", "v2"]
}
```

- `status`: `active` | `paused` | `completed` | `archived`
- `priority`: 1~10 (높을수록 우선)

---

### git_config

```json
{
  "repo_url": "https://github.com/org/ecomm-v2.git",
  "main_branch": "develop",
  "agent_branch_prefix": "agent/",
  "auto_commit_message_template": "feat({agent}): {summary} [task:{task_id}]",
  "sop_directory": ".harness/sop/",
  "protected_paths": [".env", "infrastructure/", "secrets/"]
}
```

- `protected_paths`: 에이전트가 절대 수정할 수 없는 경로. 위반 시 `ProtectedPathError` 발생.

---

### agent_config

역할별 LLM 모델과 파라미터를 지정한다. `model_override`가 있으면 우선 적용.

```json
{
  "orchestrator": {
    "model": "claude-opus-4-6",
    "max_tokens": 8192,
    "temperature": 0.3,
    "streaming": false,
    "timeout_seconds": 300,
    "high_complexity_model": null
  },
  "reviewer": {
    "model": "claude-sonnet-4-6",
    "max_tokens": 4096,
    "temperature": 0.1,
    "streaming": false,
    "timeout_seconds": 300
  },
  "backend": {
    "model": "ollama/deepseek-v3.2:70b",
    "max_tokens": 4096,
    "temperature": 0.2,
    "model_override": null,
    "streaming": true,
    "timeout_seconds": 600,
    "high_complexity_model": "ollama/deepseek-v3.2:70b"
  }
}
```

| 필드 | 기본값 | 설명 |
|---|---|---|
| `model` | — | 기본 LLM 모델 |
| `max_tokens` | 4096 | 최대 생성 토큰 |
| `temperature` | 0.2 | 생성 온도 |
| `model_override` | null | 지정 시 model보다 우선 |
| `streaming` | false | 스트리밍 활성화 여부 |
| `timeout_seconds` | 300 | 스트리밍 타임아웃 (초) |
| `high_complexity_model` | null | Complexity Router가 HIGH 판정 시 사용할 모델 |
| `reviewer_guidelines_path` | null | 리뷰어 가이드라인 파일 경로 |

---

### quality_policy

QA 임계값, Human Gate 기준, 예산, Dynamic Guardrails 설정.

```json
{
  "coverage_threshold": 80,
  "review_score_threshold": 70,
  "max_retry_before_escalation": 3,
  "security_block_level": "critical",
  "require_human_on_schema_change": true,
  "require_human_on_external_integration": true,
  "daily_token_budget": 500,
  "sop_compliance_threshold": 70,
  "high_risk_paths": [
    "payment", "billing", "auth", "security",
    "migration", "infrastructure/", "secrets/"
  ],
  "high_risk_keywords": [
    "payment", "billing", "charge", "refund",
    "credential", "secret", "token", "api_key",
    "delete_all", "drop_table", "truncate",
    "production", "deploy"
  ]
}
```

| 필드 | 기본값 | 설명 |
|---|---|---|
| `coverage_threshold` | 80 | 테스트 커버리지 목표 (%) |
| `review_score_threshold` | 70 | review_score 최솟값 |
| `max_retry_before_escalation` | 3 | L1 최대 재시도 횟수 |
| `sop_compliance_threshold` | 70 | SOP 준수도 최솟값 |
| `high_risk_paths` | (위 목록) | L2 자동 상향 트리거 파일 경로 패턴 |
| `high_risk_keywords` | (위 목록) | L2 자동 상향 트리거 지시사항 키워드 |

---

### work_queue

현재 실행 중인 태스크, 대기 큐, 차단된 태스크의 스냅샷.

```json
{
  "current_task": {
    "task_id": "task_payment_api",
    "agent": "backend",
    "started_at": "2026-04-23T10:00:00Z",
    "priority": 8
  },
  "pending_tasks": [
    { "task_id": "task_payment_test", "depends_on": "task_payment_api", "priority": 7 }
  ],
  "blocked_tasks": [
    { "task_id": "task_refund_api", "blocked_by": "task_payment_api", "unblock_condition": "결제 API 완료 후" }
  ],
  "active_agents": {
    "backend": { "status": "running", "current_task_id": "task_payment_api" },
    "tester": { "status": "waiting" }
  },
  "overall_progress": 62
}
```

---

### memory_config

3계층 메모리 시스템의 연결 설정. 각 계층은 선택적이며, 미연결 시 인메모리 폴백 동작.

```json
{
  "vector_collection_id": "mem_proj_ecomm_v2",
  "scratchpad_key": "scratch:proj_ecomm_v2:",
  "retain_handoff_count": 100,
  "auto_learn_patterns": true,
  "cross_project_memory_enabled": false,
  "redis_url": "redis://localhost:6379/0",
  "redis_ttl": 86400,
  "chroma_path": null,
  "chroma_collection_prefix": "archon",
  "mem0_api_key": null,
  "mem0_user_id": "archon"
}
```

| 필드 | 기본값 | 설명 |
|---|---|---|
| `redis_url` | `redis://localhost:6379/0` | L1 Redis 연결 URL |
| `redis_ttl` | 86400 | L1 스크래치패드 TTL (초, 기본 24시간) |
| `chroma_path` | null | L2 ChromaDB 로컬 경로 (null이면 인메모리) |
| `chroma_collection_prefix` | `"archon"` | L2 컬렉션 이름 접두사 |
| `mem0_api_key` | null | L3 Mem0 API 키 (null이면 L3 비활성화) |
| `cross_project_memory_enabled` | false | 다른 프로젝트 패턴 참조 허용 여부 |

**3계층 메모리 구조**:

| 계층 | 구현 | TTL | 범위 |
|---|---|---|---|
| L1 단기 | Redis scratchpad | 24시간 | 태스크별 |
| L2 중기 | ChromaDB 벡터 검색 | 무제한 | 프로젝트별 |
| L3 장기 | Mem0 패턴 학습 | 무제한 | 크로스 프로젝트 |

---

### metrics

```json
{
  "total_tokens_used": 1240000,
  "estimated_cost_usd": 4.82,
  "auto_commit_count": 34,
  "human_gate_count": 3,
  "l3_halt_count": 0,
  "average_review_score": 81.2,
  "agent_utilization": {
    "backend": 0.78,
    "tester": 0.45,
    "frontend": 0.12
  }
}
```

---

### human_gate_history

개발자가 내린 결정 이력. Mem0에 학습시켜 향후 유사 상황에서 자동 참조한다.

```json
{
  "entries": [
    {
      "handoff_id": "hf_20260410b2c3",
      "gate_level": "l2_human",
      "trigger": "Stripe 신규 연동",
      "decision": "Mock 유지 후 나중에 실 연동",
      "rationale": "MVP 단계에서 실 결제 불필요",
      "response_time_minutes": 4,
      "converted_to_policy": false
    }
  ]
}
```

- `converted_to_policy`: 이 결정이 quality_policy에 반영되었는지 여부
