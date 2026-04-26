# Project Registry 스키마

[English](../en/registry-schema.md)

> 버전: 2.0.0 | 최종 수정: 2026-04-24

## 개요

Project Registry는 각 솔루션 프로젝트의 **전체 설정**을 담는 중앙 레지스트리입니다. 프로젝트를 Archon에 등록하면 이 파일이 생성되고, 에이전트, QA, 메모리, 스케줄링 등 모든 동작이 이 설정에 따라 결정됩니다.

- 파일 위치: `.harness/registry/{project_id}.json`
- 소스 코드: `src/registry/models.py`, `src/registry/store.py`

---

## 8섹션 구조

| 섹션 | 역할 |
|---|---|
| project_meta | 프로젝트 식별, 상태, 우선순위, 스케줄링 기준 |
| git_config | 저장소, 브랜치 전략, SOP 경로, protected_paths |
| agent_config | 역할별 LLM 모델 지정 (플러그인 교체 레이어) |
| quality_policy | QA 임계값, Human Gate 판단 기준, 예산, Dynamic Guardrails |
| work_queue | 태스크 큐 스냅샷, 현재 실행 상태 |
| memory_config | 3계층 메모리 설정 (Redis / ChromaDB / Mem0) |
| metrics | 진행률, 비용, 품질, 속도 지표 |
| human_gate_history | 개발자 결정 이력, 패턴 학습 원천 |

---

## 섹션 상세

### project_meta

프로젝트의 기본 정보입니다. `status`와 `priority`는 Orchestrator의 스케줄링에 직접 영향을 미칩니다.

| 필드 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `project_id` | `str` | (필수) | 프로젝트 고유 식별자 (예: `"proj_ecomm_v2"`) |
| `project_name` | `str` | (필수) | 사람이 읽을 수 있는 프로젝트 이름 |
| `status` | `str` | `"active"` | 프로젝트 상태: `"active"` \| `"paused"` \| `"completed"` \| `"archived"` |
| `priority` | `int` | `5` | 우선순위 1~10 (높을수록 우선 처리) |
| `deadline` | `str` (ISO 8601) \| `null` | `null` | 마감 기한. 설정하면 스케줄링에 반영됩니다 |
| `owner` | `str` | (필수) | 프로젝트 담당 개발자 식별자 |
| `description` | `str` | `""` | 프로젝트 설명 |
| `tags` | `list[str]` | `[]` | 검색 및 분류용 태그 목록 |

**사용 시점:** 프로젝트를 처음 등록할 때 설정합니다. `status`를 `"paused"`로 변경하면 해당 프로젝트의 모든 에이전트 실행이 일시정지됩니다.

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

---

### git_config

Git 저장소, 브랜치 전략, SOP 경로, 보호 경로를 설정합니다.

| 필드 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `repo_url` | `str` | (필수) | Git 저장소 URL |
| `main_branch` | `str` | `"main"` | 메인 브랜치 이름 |
| `agent_branch_prefix` | `str` | `"agent/"` | 에이전트 작업 브랜치 접두사 (예: `agent/backend/hf_a3b4`) |
| `auto_commit_message_template` | `str` | `"feat({agent}): {summary} [task:{task_id}]"` | 자동 커밋 메시지 템플릿. `{agent}`, `{summary}`, `{task_id}` 변수 사용 가능 |
| `sop_directory` | `str` | `".harness/sop/"` | SOP 파일 디렉토리 경로 |
| `protected_paths` | `list[str]` | `[]` | 에이전트가 절대 수정할 수 없는 경로 목록. 위반 시 `ProtectedPathError` 발생 |

**사용 시점:** 프로젝트를 처음 등록할 때 설정합니다. `protected_paths`에 `.env`, `secrets/` 같은 민감 경로를 반드시 추가하세요.

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

---

### agent_config

역할별 LLM 모델과 파라미터를 지정합니다. 각 에이전트 역할(orchestrator, reviewer, backend 등)에 대해 개별 설정이 가능합니다.

| 필드 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `model` | `str` | (필수) | 기본 LLM 모델 (예: `"claude-opus-4-6"`, `"ollama/deepseek-v3.2:70b"`) |
| `max_tokens` | `int` | `4096` | 최대 생성 토큰 수 |
| `temperature` | `float` | `0.2` | 생성 온도. 낮을수록 결정적(deterministic) 출력 |
| `model_override` | `str` \| `null` | `null` | 지정하면 `model`보다 우선 적용됩니다. 임시로 다른 모델을 테스트할 때 유용합니다 |
| `streaming` | `bool` | `false` | 스트리밍 출력 활성화 여부. `true`로 설정하면 에이전트 응답을 실시간으로 수신합니다 |
| `timeout_seconds` | `int` | `300` | 에이전트 실행 타임아웃 (초). 이 시간을 초과하면 실행이 중단됩니다 |
| `high_complexity_model` | `str` \| `null` | `null` | Complexity Router가 HIGH로 판정했을 때 사용할 모델. null이면 `model`을 그대로 사용합니다 |
| `reviewer_guidelines_path` | `str` \| `null` | `null` | 리뷰어 가이드라인 파일 경로 (reviewer 역할에서만 사용) |

**사용 시점:**
- **streaming**: 긴 코드 생성 작업에서 진행 상황을 실시간으로 모니터링하고 싶을 때 `true`로 설정하세요.
- **timeout_seconds**: 복잡한 작업을 수행하는 에이전트(예: 대규모 리팩토링)는 기본 300초로 부족할 수 있으므로 600초 이상으로 설정하세요.
- **high_complexity_model**: 비용 최적화에 유용합니다. 일반 작업은 작은 모델로 처리하고, 복잡한 작업만 큰 모델로 처리합니다.

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
    "timeout_seconds": 300,
    "reviewer_guidelines_path": ".harness/guidelines/review.md"
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

---

### quality_policy

QA 임계값, Human Gate 기준, 토큰 예산, Dynamic Guardrails 설정입니다. 이 설정이 `evaluate_gate()`의 판단에 직접 사용됩니다.

| 필드 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `coverage_threshold` | `int` | `80` | 테스트 커버리지 목표 (%). 미달 시 L1 재작업 |
| `review_score_threshold` | `int` | `70` | Review Agent 점수 최솟값. 미달 시 L1 재작업 |
| `max_retry_before_escalation` | `int` | `3` | L1 최대 재시도 횟수. 초과 시 L2 에스컬레이션 |
| `security_block_level` | `str` | `"critical"` | 이 레벨 이상의 보안 취약점 발견 시 L3 중단. `"critical"` \| `"high"` \| `"medium"` |
| `require_human_on_schema_change` | `bool` | `true` | DB 스키마 변경 시 L2 Human Gate 자동 발동 여부 |
| `require_human_on_external_integration` | `bool` | `true` | 외부 API 연동 감지 시 L2 Human Gate 자동 발동 여부 |
| `daily_token_budget` | `int` | `500` | 일일 토큰 예산 (단위: 천 토큰). 초과 시 경고 |
| `sop_compliance_threshold` | `int` | `70` | SOP 준수도 점수 최솟값 (0-100). 미달 시 L2 Human Gate 발동. SOP 파일이 없으면 검사를 건너뜁니다 |
| `high_risk_paths` | `list[str]` | `[]` | 이 경로 패턴에 해당하는 파일이 변경되면 자동으로 L2 Human Gate가 발동됩니다 |
| `high_risk_keywords` | `list[str]` | `[]` | 태스크 지시사항에 이 키워드가 포함되면 자동으로 L2 Human Gate가 발동됩니다 |

**사용 시점:**
- **sop_compliance_threshold**: 팀에서 SOP를 엄격하게 관리한다면 80~90으로 높이세요. SOP를 사용하지 않는다면 이 필드는 무시됩니다.
- **high_risk_paths**: 결제, 인증, 인프라 등 민감한 코드 경로를 등록하세요. 에이전트가 이 경로의 파일을 변경하면 자동으로 개발자 확인을 요청합니다.
- **high_risk_keywords**: `"payment"`, `"delete_all"`, `"production"` 같은 키워드를 등록하면, 해당 키워드가 태스크에 포함될 때 자동으로 L2 게이트가 발동됩니다.

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

---

### work_queue

현재 실행 중인 태스크, 대기 큐, 차단된 태스크의 스냅샷입니다. Orchestrator가 자동으로 관리합니다.

| 필드 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `current_task` | `CurrentTask` \| `null` | `null` | 현재 실행 중인 태스크 |
| `current_task.task_id` | `str` | (필수) | 태스크 식별자 |
| `current_task.agent` | `str` | (필수) | 실행 중인 에이전트 역할 |
| `current_task.started_at` | `str` (ISO 8601) | (필수) | 실행 시작 시각 |
| `current_task.priority` | `int` | (필수) | 태스크 우선순위 |
| `pending_tasks` | `list[PendingTask]` | `[]` | 대기 중인 태스크 목록 |
| `blocked_tasks` | `list[BlockedTask]` | `[]` | 차단된 태스크 목록 |
| `active_agents` | `dict[str, AgentStatus]` | `{}` | 에이전트별 상태 (`"running"` \| `"waiting"` \| `"paused"`) |
| `overall_progress` | `int` | `0` | 전체 진행률 (0-100) |

**사용 시점:** 일반적으로 직접 수정할 필요가 없습니다. Orchestrator가 자동으로 관리합니다. 모니터링 대시보드에서 실시간 현황을 확인하는 용도로 참조합니다.

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

3계층 메모리 시스템의 연결 설정입니다. 각 계층은 선택적이며, 미연결 시 인메모리 폴백으로 동작합니다.

| 필드 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `vector_collection_id` | `str` | (자동 생성) | 벡터 DB 컬렉션 ID |
| `scratchpad_key` | `str` | (자동 생성) | Redis 스크래치패드 키 접두사 |
| `retain_handoff_count` | `int` | `100` | 보존할 최근 핸드오프 수 |
| `auto_learn_patterns` | `bool` | `true` | 성공 패턴 자동 학습 여부 |
| `cross_project_memory_enabled` | `bool` | `false` | 다른 프로젝트 패턴 참조 허용 여부 |
| `redis_url` | `str` | `"redis://localhost:6379/0"` | L1 Redis 연결 URL |
| `redis_ttl` | `int` | `86400` | L1 스크래치패드 TTL (초, 기본 24시간) |
| `chroma_host` | `str` \| `null` | `null` | L2 ChromaDB 서버 호스트. null이면 로컬/인메모리 |
| `chroma_port` | `int` | `8000` | L2 ChromaDB 서버 포트 |
| `chroma_collection` | `str` | `"archon"` | L2 ChromaDB 컬렉션 이름 |
| `mem0_api_key` | `str` \| `null` | `null` | L3 Mem0 API 키. null이면 L3 비활성화 |

**3계층 메모리 구조:**

| 계층 | 구현 | TTL | 범위 | 용도 |
|---|---|---|---|---|
| L1 단기 | Redis scratchpad | 24시간 | 태스크별 | 현재 작업의 임시 데이터 저장 |
| L2 중기 | ChromaDB 벡터 검색 | 무제한 | 프로젝트별 | 프로젝트 내 유사 결정/패턴 검색 |
| L3 장기 | Mem0 패턴 학습 | 무제한 | 크로스 프로젝트 | 전체 프로젝트 패턴 학습 및 참조 |

**사용 시점:**
- **최소 설정**: Redis만 연결하면 기본 동작합니다. ChromaDB와 Mem0는 점진적으로 추가할 수 있습니다.
- **chroma_host**: 팀에서 ChromaDB 서버를 운영한다면 호스트를 지정하세요. null이면 인메모리로 동작하며, 프로세스 종료 시 데이터가 사라집니다.
- **mem0_api_key**: Mem0 클라우드를 사용하면 크로스 프로젝트 패턴 학습이 가능합니다. 보안에 주의하세요.

```json
{
  "vector_collection_id": "mem_proj_ecomm_v2",
  "scratchpad_key": "scratch:proj_ecomm_v2:",
  "retain_handoff_count": 100,
  "auto_learn_patterns": true,
  "cross_project_memory_enabled": false,
  "redis_url": "redis://localhost:6379/0",
  "redis_ttl": 86400,
  "chroma_host": null,
  "chroma_port": 8000,
  "chroma_collection": "archon",
  "mem0_api_key": null
}
```

---

### metrics

프로젝트 수준의 지표입니다. Orchestrator가 자동으로 업데이트합니다.

| 필드 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `total_tokens_used` | `int` | `0` | 누적 사용 토큰 수 |
| `estimated_cost_usd` | `float` | `0.0` | 추정 비용 (USD) |
| `auto_commit_count` | `int` | `0` | 자동 커밋(auto_pass) 횟수 |
| `human_gate_count` | `int` | `0` | Human Gate 발동 횟수 |
| `l3_halt_count` | `int` | `0` | L3 중단 횟수 |
| `average_review_score` | `float` | `0.0` | 평균 Review Agent 점수 |
| `agent_utilization` | `dict[str, float]` | `{}` | 에이전트별 활용률 (0.0 ~ 1.0) |

**사용 시점:** 직접 수정할 필요가 없습니다. 대시보드에서 프로젝트 진행 현황, 비용, 품질 추세를 확인하는 용도입니다.

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

개발자가 내린 결정 이력입니다. Mem0에 학습시켜 향후 유사 상황에서 자동 참조합니다.

| 필드 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `entries` | `list[GateEntry]` | `[]` | 결정 이력 목록 |
| `entries[].handoff_id` | `str` | (필수) | 해당 핸드오프 ID |
| `entries[].gate_level` | `str` | (필수) | 발동된 게이트 레벨 |
| `entries[].trigger` | `str` | (필수) | 발동 원인 |
| `entries[].decision` | `str` | (필수) | 개발자의 결정 |
| `entries[].rationale` | `str` | (필수) | 결정 근거 |
| `entries[].response_time_minutes` | `int` | (필수) | 응답까지 걸린 시간 (분) |
| `entries[].converted_to_policy` | `bool` | `false` | 이 결정이 quality_policy에 반영되었는지 여부 |

**사용 시점:** 직접 수정할 필요가 없습니다. 개발자가 Human Gate에서 결정을 내리면 자동으로 기록됩니다. `converted_to_policy`가 `true`이면 해당 결정이 quality_policy 규칙으로 승격된 것입니다.

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

---

## 관련 설정 (Related Configs)

아래 설정들은 Project Registry 자체에 포함되지 않지만, Archon의 확장 기능을 구성하는 독립적인 설정 파일입니다. 필요에 따라 사용하세요.

### TracingConfig

LLM 호출 추적 및 관측 설정입니다. 디버깅과 비용 분석에 필수적입니다.

| 필드 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `backend` | `str` | `"none"` | 추적 백엔드: `"none"` \| `"langsmith"` \| `"langfuse"` \| `"aitop"` |
| `langsmith_api_key` | `str` \| `null` | `null` | LangSmith API 키 |
| `langsmith_project` | `str` \| `null` | `null` | LangSmith 프로젝트 이름 |
| `langfuse_public_key` | `str` \| `null` | `null` | Langfuse Public 키 |
| `langfuse_secret_key` | `str` \| `null` | `null` | Langfuse Secret 키 |
| `langfuse_host` | `str` | `"https://cloud.langfuse.com"` | Langfuse 서버 URL |
| `aitop_endpoint` | `str` \| `null` | `null` | AITop 엔드포인트 URL |
| `aitop_api_key` | `str` \| `null` | `null` | AITop API 키 |

**사용 시점:** 에이전트의 LLM 호출을 추적하고 싶을 때 설정합니다. 운영 환경에서는 반드시 활성화하는 것을 권장합니다.

```json
{
  "backend": "langsmith",
  "langsmith_api_key": "ls-your-api-key",
  "langsmith_project": "archon-ecomm-v2",
  "langfuse_public_key": null,
  "langfuse_secret_key": null,
  "langfuse_host": "https://cloud.langfuse.com",
  "aitop_endpoint": null,
  "aitop_api_key": null
}
```

---

### EvolutionConfig

에이전트 자가 진화(Self-Evolution) 설정입니다. 과거 핸드오프 데이터를 분석하여 SOP와 프롬프트를 자동으로 개선합니다.

| 필드 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `enabled` | `bool` | `false` | 자가 진화 활성화 여부 |
| `analysis_window` | `int` | `50` | 분석 대상 최근 핸드오프 수 |
| `auto_apply_threshold` | `float` | `0.85` | 이 신뢰도 이상이면 개선안을 자동 적용 (0.0 ~ 1.0) |

**사용 시점:** 프로젝트가 충분히 성숙하고 핸드오프 이력이 50개 이상 쌓였을 때 활성화하세요. `auto_apply_threshold`를 높게 설정할수록 보수적으로 동작합니다.

```json
{
  "enabled": true,
  "analysis_window": 50,
  "auto_apply_threshold": 0.85
}
```

---

### HybridConfig

하이브리드 LLM 라우팅 설정입니다. 여러 LLM 프로바이더를 조합하여 비용과 성능을 최적화합니다.

| 필드 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `strategy` | `str` | `"cost_optimized"` | 라우팅 전략: `"cost_optimized"` \| `"quality_first"` \| `"latency_first"` |
| `budget` | `float` | `10.0` | 일일 예산 (USD) |
| `providers` | `list[str]` | `["anthropic"]` | 사용 가능한 프로바이더 목록 (예: `["anthropic", "openai", "ollama"]`) |

**사용 시점:** 여러 LLM 프로바이더를 사용하여 비용을 절감하고 싶을 때 설정합니다. `strategy`에 따라 라우팅 방식이 달라집니다.

```json
{
  "strategy": "cost_optimized",
  "budget": 10.0,
  "providers": ["anthropic", "openai", "ollama"]
}
```

---

### KubeRayConfig

KubeRay 기반 분산 실행 설정입니다. 대규모 프로젝트에서 에이전트를 Kubernetes 클러스터에서 병렬 실행할 때 사용합니다.

| 필드 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `namespace` | `str` | `"archon"` | Kubernetes 네임스페이스 |
| `cluster_name` | `str` | `"archon-ray"` | Ray 클러스터 이름 |
| `worker_groups` | `list[WorkerGroup]` | `[]` | 워커 그룹 설정 목록 |
| `worker_groups[].name` | `str` | (필수) | 워커 그룹 이름 |
| `worker_groups[].replicas` | `int` | `1` | 워커 인스턴스 수 |
| `worker_groups[].resources` | `object` | `{}` | CPU/메모리 리소스 제한 |

**사용 시점:** 로컬 실행으로는 처리량이 부족한 대규모 프로젝트에서 사용합니다. Kubernetes와 Ray가 이미 설치되어 있어야 합니다.

```json
{
  "namespace": "archon",
  "cluster_name": "archon-ray",
  "worker_groups": [
    {
      "name": "agent-workers",
      "replicas": 4,
      "resources": {
        "cpu": "2",
        "memory": "4Gi"
      }
    },
    {
      "name": "review-workers",
      "replicas": 2,
      "resources": {
        "cpu": "1",
        "memory": "2Gi"
      }
    }
  ]
}
```

---

### GuardrailPolicy

에이전트의 입출력 가드레일 설정입니다. 예산 초과, 위험 경로 접근, 악의적 입력을 방지합니다.

| 필드 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `input_max_tokens` | `int` | `32000` | 에이전트에 전달하는 입력 최대 토큰 수 |
| `output_max_tokens` | `int` | `16000` | 에이전트 출력 최대 토큰 수 |
| `budget_hard_limit_usd` | `float` | `50.0` | 일일 하드 예산 한도 (USD). 초과 시 모든 에이전트 실행 중단 |
| `blocked_paths` | `list[str]` | `[]` | 에이전트가 읽기조차 할 수 없는 경로 목록 |
| `allowed_domains` | `list[str]` | `[]` | 에이전트가 접근할 수 있는 외부 도메인 화이트리스트. 비어 있으면 모든 도메인 허용 |

**사용 시점:** 운영 환경에서 에이전트의 동작을 제한하고 싶을 때 설정합니다. `budget_hard_limit_usd`는 예기치 않은 비용 폭증을 방지합니다.

```json
{
  "input_max_tokens": 32000,
  "output_max_tokens": 16000,
  "budget_hard_limit_usd": 50.0,
  "blocked_paths": [".git/", "node_modules/", ".env"],
  "allowed_domains": ["api.stripe.com", "api.github.com"]
}
```

---

### HealingConfig

자가 치유(Self-Healing) 설정입니다. 에이전트 실행 실패 시 대체 모델이나 대체 역할로 자동 전환합니다.

| 필드 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `fallback_model` | `str` \| `null` | `null` | 기본 모델 실패 시 사용할 대체 모델. null이면 폴백 없음 |
| `substitute_role` | `str` \| `null` | `null` | 에이전트 역할 실패 시 대체할 역할. null이면 대체 없음 |

**사용 시점:** 특정 LLM 프로바이더의 장애에 대비하고 싶을 때 설정합니다. 예를 들어, Anthropic API 장애 시 OpenAI로 자동 전환됩니다.

```json
{
  "fallback_model": "gpt-4o",
  "substitute_role": "general"
}
```
