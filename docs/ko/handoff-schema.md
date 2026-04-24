# Handoff Artifact 스키마

🇺🇸 [English](../en/handoff-schema.md)

> 버전: 1.1.0 | 최종 수정: 2026-04-23

## 개요

Handoff Artifact는 에이전트 간 컨텍스트를 전달하는 **표준 JSON 문서**다. 핸드오프마다 생성되며 Git에 커밋된다.

소스 코드: `src/orchestrator/handoff.py`

## 7섹션 구조

| 섹션 | 역할 | 필수 |
|---|---|---|
| envelope | 핸드오프 식별 · 라우팅 · 재시도 추적 | O |
| project_context | 무상태 에이전트에 주입하는 프로젝트 네임스페이스 | O |
| task | 완료 작업 요약 + 다음 에이전트 지시 | O |
| artifacts | 변경 파일 목록 + 생성 산출물 | O |
| quality_gates | 자동 QA 결과 + Review Agent 평가 + gate_decision | O |
| human_gate_package | L2 이상 발동 시 개발자에게 전달하는 컨텍스트 | 조건부 |
| memory_context | Mem0에서 검색된 과거 패턴 · 결정 | 선택 |

## 섹션 상세

### envelope

핸드오프의 고유 식별자, 발신/수신 에이전트, 재시도 횟수를 관리한다.

```json
{
  "handoff_id": "hf_20260413a3b4c5",
  "schema_version": "1.0.0",
  "created_at": "2026-04-13T09:23:11Z",
  "expires_at": "2026-04-14T09:23:11Z",
  "from_agent": "backend",
  "to_agent": "reviewer",
  "retry_count": 0,
  "parent_handoff_id": "hf_20260413f9a2b1"
}
```

### project_context

에이전트는 무상태이므로, 이 섹션에서 프로젝트 정보를 주입받는다.

```json
{
  "project_id": "proj_ecomm_v2",
  "project_name": "E-Commerce Platform v2",
  "git_repo": "https://github.com/org/ecomm-v2.git",
  "git_branch": "agent/backend/hf_a3b4",
  "base_commit_sha": "a3f9d2c",
  "sop_path": ".harness/sop/backend.md",
  "tech_stack": {
    "language": "TypeScript",
    "framework": "NestJS",
    "database": "PostgreSQL 15",
    "runtime": "Node.js 22"
  },
  "priority": "high"
}
```

### task

완료된 작업 요약, 내린 결정, 차단 요소, 다음 에이전트에 대한 지시를 포함한다.

```json
{
  "task_id": "task_payment_api_v2",
  "completed_summary": "결제 API v2 엔드포인트 3개 구현",
  "decisions_made": [
    {
      "decision": "Idempotency key를 UUID v4로 구현",
      "reason": "중복 결제 방지, Stripe 권장 방식",
      "alternatives_considered": ["timestamp 기반", "hash 기반"]
    }
  ],
  "blockers": [
    {
      "issue": "환불 API 스펙 미정",
      "impact": "medium",
      "suggested_resolution": "L2 Human Gate — 비즈니스 로직 확인"
    }
  ],
  "next_instructions": "결제 API 단위 테스트 작성. 커버리지 85% 이상.",
  "next_agent_context": { "mock_stripe": true }
}
```

### artifacts

변경된 파일, 생성된 문서, 의존성 변경 사항을 기록한다.

```json
{
  "changed_files": [
    { "path": "src/payments/payments.controller.ts", "change_type": "added", "reason": "결제 API" }
  ],
  "generated_docs": ["docs/api/payments-v2.yaml"],
  "dependency_changes": [
    { "name": "stripe", "version": "14.21.0", "action": "added", "license": "MIT", "security_scan": "passed" }
  ],
  "config_changes": []
}
```

### quality_gates

자동 QA 파이프라인 결과와 Review Agent의 평가를 종합한다.

```json
{
  "test_results": { "unit_passed": 42, "unit_failed": 0, "integration_passed": 8, "coverage_percent": 87.3 },
  "lint_result": "passed",
  "build_result": "passed",
  "security_scan": { "tool": "semgrep", "critical": 0, "high": 0, "medium": 1, "low": 2 },
  "review_score": 74,
  "review_flags": [
    { "severity": "medium", "category": "external_integration", "detail": "Stripe 신규 연동" }
  ],
  "sop_compliance_score": 85,
  "gate_decision": "l2_human"
}
```

- `sop_compliance_score`: SOP 준수도 점수 (0~100). `null`이면 SOP 검사 스킵.
- `gate_decision`: `auto_pass` | `l1_rework` | `l2_human` | `l3_halt` | `l4_deploy`

### human_gate_package

L2 이상 발동 시에만 포함. 개발자에게 필요한 결정 사항과 옵션을 제공한다.

```json
{
  "gate_level": "l2_human",
  "trigger_reason": "Stripe 신규 외부 API 연동 감지",
  "required_decision": "Stripe 프로덕션 연동을 지금 진행할까요?",
  "decision_options": [
    { "option": "프로덕션 연동 진행", "next_action": "DevOps 에이전트에게 환경변수 설정 지시", "risk": "low" },
    { "option": "Mock 유지 후 나중에", "next_action": "Tester 에이전트에게 Mock 기반 테스트 계속", "risk": "none" }
  ],
  "estimated_review_time": "5분",
  "paused_agents": ["tester", "devops"]
}
```

### memory_context

Mem0에서 자동 검색된 과거 패턴, 결정 이력, 에러 기록을 포함한다.

```json
{
  "relevant_past_decisions": [
    { "similarity": 0.92, "project": "proj_ecomm_v1", "decision": "결제 실패 시 3회 자동 재시도 후 알림", "outcome": "success" }
  ],
  "known_patterns": [
    { "pattern": "Repository Pattern", "reason": "표준 DB 접근 패턴", "example_file": "src/users/users.repository.ts" }
  ],
  "error_history": [],
  "human_feedback": [
    { "date": "2026-04-10", "decision": "외부 결제 API는 항상 Mock 우선", "applies_to": "payment_integration" }
  ]
}
```

## Pydantic 모델 참조

전체 모델 정의: `src/orchestrator/handoff.py`

- `HandoffArtifact` — 루트 모델
- `Envelope`, `ProjectContext`, `Task`, `Artifacts`, `QualityGates` — 필수 섹션
- `HumanGatePackage`, `MemoryContext` — 조건부/선택 섹션
