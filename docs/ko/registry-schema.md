# Project Registry 스키마

> 버전: 1.0.0 | 최종 수정: 2026-04-22

## 개요

Project Registry는 각 솔루션 프로젝트의 **전체 설정**을 담는 중앙 레지스트리다.

- 파일 위치: `.harness/registry/{project_id}.json`
- 소스 코드: `src/registry/models.py`

## 8섹션 구조

| 섹션 | 역할 |
|---|---|
| project_meta | 식별 · 상태 · 우선순위 · 스케줄링 기준 |
| git_config | 레포 · 브랜치 전략 · SOP 경로 · protected_paths |
| agent_config | 역할별 LLM 모델 지정 (플러그인 교체 레이어) |
| quality_policy | QA 임계값 · Human Gate 판단 기준 · 예산 |
| work_queue | 태스크 큐 스냅샷 · 현재 실행 상태 |
| memory_config | 벡터 메모리 네임스페이스 · 프로젝트 격리 |
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

- `protected_paths`: 에이전트가 절대 수정할 수 없는 경로

### agent_config

역할별 LLM 모델과 파라미터를 지정한다. `model_override`가 있으면 우선 적용.

```json
{
  "orchestrator": { "model": "claude-opus-4-6", "max_tokens": 8192, "temperature": 0.3 },
  "reviewer": { "model": "claude-sonnet-4-6", "max_tokens": 4096, "temperature": 0.1 },
  "backend": { "model": "ollama/deepseek-v3.2:70b", "max_tokens": 4096, "temperature": 0.2, "model_override": null }
}
```

### quality_policy

```json
{
  "coverage_threshold": 80,
  "review_score_threshold": 70,
  "max_retry_before_escalation": 3,
  "security_block_level": "critical",
  "require_human_on_schema_change": true,
  "require_human_on_external_integration": true,
  "daily_token_budget": 500
}
```

### work_queue

현재 실행 중인 태스크, 대기 큐, 차단된 태스크의 스냅샷.

```json
{
  "current_task": { "task_id": "task_payment_api", "agent": "backend" },
  "pending_tasks": [{ "task_id": "task_payment_test", "depends_on": "task_payment_api" }],
  "blocked_tasks": [{ "task_id": "task_refund_api", "blocked_by": "환불 로직 미확정" }],
  "active_agents": { "backend": { "status": "running" }, "tester": { "status": "waiting" } },
  "overall_progress": 62
}
```

### memory_config

```json
{
  "vector_collection_id": "mem_proj_ecomm_v2",
  "scratchpad_key": "scratch:proj_ecomm_v2:",
  "retain_handoff_count": 100,
  "auto_learn_patterns": true,
  "cross_project_memory_enabled": false
}
```

- `cross_project_memory_enabled`: 기본 `false` — 명시적 허용 시에만 다른 프로젝트 참조

### metrics

```json
{
  "total_tokens_used": 1240000,
  "estimated_cost_usd": 4.82,
  "auto_commit_count": 34,
  "human_gate_count": 3,
  "average_review_score": 81.2,
  "agent_utilization": { "backend": 0.78, "tester": 0.45, "frontend": 0.12 }
}
```

### human_gate_history

개발자가 내린 결정 이력. Mem0에 학습시켜 향후 유사 상황에서 자동 참조한다.

```json
{
  "entries": [{
    "handoff_id": "hf_20260410b2c3",
    "gate_level": "l2_human",
    "trigger": "Stripe 신규 연동",
    "decision": "Mock 유지 후 나중에 실 연동",
    "rationale": "MVP 단계에서 실 결제 불필요",
    "response_time_minutes": 4,
    "converted_to_policy": false
  }]
}
```
