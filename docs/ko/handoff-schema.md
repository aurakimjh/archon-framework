# Handoff Artifact 스키마

[English](../en/handoff-schema.md)

> 버전: 2.0.0 | 최종 수정: 2026-04-24

## 개요

Handoff Artifact는 에이전트 간 컨텍스트를 전달하는 **표준 JSON 문서**입니다. 핸드오프가 발생할 때마다 하나씩 생성되며, Git에 자동 커밋됩니다.

Archon에서 에이전트는 **무상태(stateless)** 로 동작합니다. 에이전트가 이전 작업의 맥락을 알 수 있는 유일한 방법이 바로 이 Handoff Artifact입니다. 쉽게 말해, 에이전트 간의 "인수인계 문서"라고 생각하시면 됩니다.

소스 코드: `src/orchestrator/handoff.py`

---

## 7섹션 구조

Handoff Artifact는 아래 7개 섹션으로 구성됩니다.

| 섹션 | 역할 | 필수 여부 |
|---|---|---|
| envelope | 핸드오프 식별, 라우팅, 재시도 추적 | 필수 |
| project_context | 무상태 에이전트에 주입하는 프로젝트 정보 | 필수 |
| task | 완료된 작업 요약 + 다음 에이전트 지시 | 필수 |
| artifacts | 변경된 파일 목록 + 생성된 산출물 | 필수 |
| quality_gates | 자동 QA 결과 + Review Agent 평가 + gate_decision | 필수 |
| human_gate_package | L2 이상 발동 시 개발자에게 전달하는 컨텍스트 | 조건부 |
| memory_context | Mem0에서 검색된 과거 패턴 및 결정 이력 | 선택 |

---

## Lifecycle (생명주기)

Handoff Artifact가 생성되어 최종 처리되기까지의 전체 여정입니다. 이 흐름을 이해하면 각 섹션이 언제 채워지는지 알 수 있습니다.

```
1. Orchestrator가 초기 HandoffArtifact를 생성합니다
   - envelope, project_context, task 섹션이 채워집니다
        |
        v
2. MemoryStore.inject_memory_context()가 memory_context를 추가합니다
   - Mem0에서 유사 결정 이력, 패턴, 피드백을 검색하여 주입합니다
        |
        v
3. compress_handoff()가 토큰 초과 시 압축합니다
   - token_gap 파라미터로 정밀 절삭합니다 (아래 상세 설명 참조)
        |
        v
4. BaseAgent.execute()가 처리하고 출력 HandoffArtifact를 생성합니다
   - 에이전트가 작업을 수행하고 artifacts 섹션을 채웁니다
   - <archon-output> JSON이 잘못되면 자동 재시도합니다 (아래 상세 설명 참조)
        |
        v
5. QA 파이프라인이 quality_gates를 채웁니다
   - 테스트, 린트, 빌드, 보안 스캔, SOP 준수도 검사를 실행합니다
        |
        v
6. evaluate_gate()가 gate_decision을 결정합니다
   - auto_pass / l1_rework / l2_human / l3_halt / l4_deploy 중 하나
        |
        v
7. GitExecutor가 AUTO_PASS 시 자동 커밋합니다
   - auto_pass이면 변경사항을 Git에 자동 커밋합니다
   - l1_rework이면 에이전트에게 재작업을 지시합니다
   - l2_human 이상이면 human_gate_package를 생성하고 개발자에게 전달합니다
```

---

## 핵심 개념

### compress_handoff()를 이용한 정밀 압축

에이전트에 전달하는 컨텍스트가 LLM의 토큰 한도를 초과할 수 있습니다. `compress_handoff()` 함수는 `token_gap` 파라미터를 사용하여 정밀하게 압축합니다.

**동작 원리:**
- `token_gap`은 "현재 토큰 수 - 목표 토큰 수"를 의미합니다 (예: 2000 토큰 초과 시 `token_gap=2000`)
- 압축 우선순위: `memory_context` > `artifacts.generated_docs` > `task.decisions_made` > `task.blockers` 순서로 절삭합니다
- 중요한 섹션(envelope, project_context)은 절대 절삭하지 않습니다

**사용 시점:** Orchestrator가 에이전트에게 핸드오프를 전달하기 직전에 자동 호출됩니다. 직접 호출할 일은 거의 없습니다.

```python
# 내부 동작 예시
compressed = compress_handoff(artifact, token_gap=2000)
# memory_context에서 유사도 낮은 항목부터 제거하여 2000토큰을 확보합니다
```

### Self-Correction (자동 재시도) 흐름

에이전트가 `<archon-output>` JSON을 잘못된 형식으로 출력할 수 있습니다. BaseAgent는 이를 자동으로 감지하고 **1회 재시도**합니다.

**동작 흐름:**
1. BaseAgent.execute()가 에이전트의 응답에서 `<archon-output>` 태그를 파싱합니다
2. JSON 파싱에 실패하면, 원본 응답 + 교정 프롬프트를 에이전트에게 다시 전송합니다
3. 재시도에서도 실패하면 `MalformedOutputError`를 발생시키고 L1 재시도로 에스컬레이션합니다

**사용 시점:** 자동으로 동작하므로 별도 설정이 필요 없습니다. `envelope.retry_count`는 이 self-correction 재시도와 별개로, L1 재작업 횟수만 추적합니다.

### GitExecutor Snapshots (스냅샷 복원)

에이전트가 실행되기 전에, GitExecutor는 `save_snapshot()`으로 현재 작업 트리를 보존합니다. 에이전트가 환각(hallucination)으로 잘못된 코드를 생성한 것이 감지되면, `rollback_to_snapshot()`으로 실행 전 상태로 복원합니다.

**동작 흐름:**
1. 에이전트 실행 전: `save_snapshot()` -- 현재 Git 작업 트리의 상태를 저장합니다
2. 에이전트 실행 완료
3. QA 파이프라인에서 환각이 감지되면 (예: 존재하지 않는 API 호출, 잘못된 import 등)
4. `rollback_to_snapshot()` -- 스냅샷 시점으로 작업 트리를 복원합니다
5. L1 재시도가 진행됩니다

**사용 시점:** 자동으로 동작합니다. 이 메커니즘 덕분에 에이전트가 잘못된 코드를 생성해도 프로젝트가 안전하게 보호됩니다.

---

## 섹션 상세

### envelope

핸드오프의 고유 식별자, 발신/수신 에이전트, 재시도 횟수를 관리합니다. 모든 핸드오프의 "표지"라고 생각하시면 됩니다.

| 필드 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `handoff_id` | `str` | (자동 생성) | 핸드오프 고유 식별자. `hf_` 접두사 + 타임스탬프 + 랜덤 해시 |
| `schema_version` | `str` | `"1.0.0"` | Handoff Artifact 스키마 버전 |
| `created_at` | `str` (ISO 8601) | (자동 생성) | 생성 시각 |
| `expires_at` | `str` (ISO 8601) \| `null` | `null` | 만료 시각. null이면 만료 없음 |
| `from_agent` | `str` | (필수) | 발신 에이전트 역할명 (예: `"backend"`) |
| `to_agent` | `str` | (필수) | 수신 에이전트 역할명 (예: `"reviewer"`) |
| `retry_count` | `int` | `0` | L1 재시도 횟수. `max_retry_before_escalation` 초과 시 L2 에스컬레이션 |
| `parent_handoff_id` | `str` \| `null` | `null` | 이전 핸드오프 ID. 체인 추적에 사용 |

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

---

### project_context

에이전트는 무상태이므로, 이 섹션에서 프로젝트 정보를 주입받습니다. 에이전트가 "어떤 프로젝트에서, 어떤 기술 스택으로, 어떤 브랜치에서 작업하는지" 아는 유일한 방법입니다.

| 필드 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `project_id` | `str` | (필수) | 프로젝트 고유 식별자 |
| `project_name` | `str` | (필수) | 사람이 읽을 수 있는 프로젝트명 |
| `git_repo` | `str` | (필수) | Git 저장소 URL |
| `git_branch` | `str` | (필수) | 에이전트 작업 브랜치 |
| `base_commit_sha` | `str` | (필수) | 작업 기준 커밋 SHA |
| `sop_path` | `str` \| `null` | `null` | 이 에이전트가 따라야 할 SOP 파일 경로 |
| `tech_stack` | `object` | `{}` | 기술 스택 정보 (language, framework, database, runtime 등) |
| `priority` | `str` | `"medium"` | 우선순위: `"low"` \| `"medium"` \| `"high"` \| `"critical"` |

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

---

### task

완료된 작업 요약, 내린 결정, 차단 요소, 다음 에이전트에 대한 지시를 포함합니다.

| 필드 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `task_id` | `str` | (필수) | 태스크 고유 식별자 |
| `completed_summary` | `str` | (필수) | 완료된 작업의 한 줄 요약 |
| `decisions_made` | `list[Decision]` | `[]` | 에이전트가 내린 결정 목록. 각 항목에 `decision`, `reason`, `alternatives_considered` 포함 |
| `blockers` | `list[Blocker]` | `[]` | 차단 요소 목록. 각 항목에 `issue`, `impact`, `suggested_resolution` 포함 |
| `next_instructions` | `str` | (필수) | 다음 에이전트에게 전달할 지시사항 |
| `next_agent_context` | `object` \| `null` | `null` | 다음 에이전트에게 전달할 추가 컨텍스트 (자유 형식 JSON) |

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
      "suggested_resolution": "L2 Human Gate -- 비즈니스 로직 확인"
    }
  ],
  "next_instructions": "결제 API 단위 테스트 작성. 커버리지 85% 이상.",
  "next_agent_context": { "mock_stripe": true }
}
```

---

### artifacts

변경된 파일, 생성된 문서, 의존성 변경 사항을 기록합니다.

| 필드 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `changed_files` | `list[ChangedFile]` | `[]` | 변경된 파일 목록 (아래 ChangedFile 참조) |
| `generated_docs` | `list[str]` | `[]` | 생성된 문서 파일 경로 목록 |
| `dependency_changes` | `list[DependencyChange]` | `[]` | 의존성 변경 목록 |
| `config_changes` | `list[str]` | `[]` | 설정 파일 변경 경로 목록 |

**ChangedFile 객체:**

에이전트가 변경한 개별 파일의 정보입니다.

| 필드 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `path` | `str` | (필수) | 파일 경로 (프로젝트 루트 기준 상대 경로) |
| `change_type` | `str` | (필수) | 변경 유형. 아래 3가지 중 하나 |
| `reason` | `str` \| `null` | `null` | 변경 이유 설명 |

`change_type` 열거값:
- `"added"` -- 새로 생성된 파일
- `"modified"` -- 기존 파일을 수정
- `"deleted"` -- 기존 파일을 삭제

```json
{
  "changed_files": [
    { "path": "src/payments/payments.controller.ts", "change_type": "added", "reason": "결제 API 컨트롤러" },
    { "path": "src/payments/payments.service.ts", "change_type": "added", "reason": "결제 비즈니스 로직" },
    { "path": "src/app.module.ts", "change_type": "modified", "reason": "PaymentsModule 등록" },
    { "path": "src/payments/old-handler.ts", "change_type": "deleted", "reason": "v1 레거시 핸들러 제거" }
  ],
  "generated_docs": ["docs/api/payments-v2.yaml"],
  "dependency_changes": [
    {
      "name": "stripe",
      "version": "14.21.0",
      "action": "added",
      "license": "MIT",
      "security_scan": "passed"
    }
  ],
  "config_changes": []
}
```

---

### quality_gates

자동 QA 파이프라인 결과와 Review Agent의 평가를 종합합니다. 이 섹션의 결과에 따라 `gate_decision`이 결정됩니다.

| 필드 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `test_results` | `TestResults` | (필수) | 테스트 실행 결과 |
| `test_results.unit_passed` | `int` | `0` | 통과한 단위 테스트 수 |
| `test_results.unit_failed` | `int` | `0` | 실패한 단위 테스트 수 |
| `test_results.integration_passed` | `int` | `0` | 통과한 통합 테스트 수 |
| `test_results.coverage_percent` | `float` | `0.0` | 테스트 커버리지 (%) |
| `lint_result` | `str` | (필수) | 린트 결과: `"passed"` \| `"failed"` |
| `build_result` | `str` | (필수) | 빌드 결과: `"passed"` \| `"failed"` |
| `security_scan` | `SecurityScan` | (필수) | 보안 스캔 결과 |
| `security_scan.tool` | `str` | (필수) | 사용된 보안 스캔 도구 (예: `"semgrep"`) |
| `security_scan.critical` | `int` | `0` | Critical 취약점 수 |
| `security_scan.high` | `int` | `0` | High 취약점 수 |
| `security_scan.medium` | `int` | `0` | Medium 취약점 수 |
| `security_scan.low` | `int` | `0` | Low 취약점 수 |
| `review_score` | `int` | (필수) | Review Agent가 매긴 점수 (0-100) |
| `review_flags` | `list[ReviewFlag]` | `[]` | Review Agent가 발견한 이슈 목록 |
| `sop_compliance_score` | `int` \| `null` | `null` | SOP 준수도 점수 (0-100). `null`이면 SOP 검사를 수행하지 않았음을 의미합니다 |
| `gate_decision` | `str` | (필수) | 최종 게이트 결정 |

**sop_compliance_score 상세:**
- `0`~`100` 범위의 정수입니다
- `null`이면 SOP 파일이 없거나 SOP 검사를 건너뛴 것입니다
- `quality_policy.sop_compliance_threshold` (기본 70) 미만이면 L1 재작업이 발동됩니다

**gate_decision 열거값:**
- `"auto_pass"` -- 모든 품질 기준 충족. GitExecutor가 자동 커밋합니다
- `"l1_rework"` -- 에이전트에게 재작업을 지시합니다 (테스트 실패, 점수 미달 등)
- `"l2_human"` -- 개발자 확인이 필요합니다 (외부 API 연동, 스키마 변경 등)
- `"l3_halt"` -- 즉시 중단합니다 (critical 보안 취약점 등)
- `"l4_deploy"` -- 배포 파이프라인을 트리거합니다

```json
{
  "test_results": {
    "unit_passed": 42,
    "unit_failed": 0,
    "integration_passed": 8,
    "coverage_percent": 87.3
  },
  "lint_result": "passed",
  "build_result": "passed",
  "security_scan": {
    "tool": "semgrep",
    "critical": 0,
    "high": 0,
    "medium": 1,
    "low": 2
  },
  "review_score": 74,
  "review_flags": [
    {
      "severity": "medium",
      "category": "external_integration",
      "detail": "Stripe 신규 연동 감지"
    }
  ],
  "sop_compliance_score": 85,
  "gate_decision": "l2_human"
}
```

---

### human_gate_package

L2 이상 발동 시에만 포함됩니다. 개발자에게 필요한 결정 사항과 선택지를 제공합니다.

| 필드 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `gate_level` | `str` | (필수) | 발동된 게이트 레벨: `"l2_human"` \| `"l3_halt"` |
| `trigger_reason` | `str` | (필수) | 게이트 발동 이유 설명 |
| `required_decision` | `str` | (필수) | 개발자에게 묻는 질문 |
| `decision_options` | `list[DecisionOption]` | (필수) | 선택 가능한 옵션 목록 |
| `decision_options[].option` | `str` | (필수) | 옵션 설명 |
| `decision_options[].next_action` | `str` | (필수) | 이 옵션 선택 시 다음 동작 |
| `decision_options[].risk` | `str` | (필수) | 위험도: `"none"` \| `"low"` \| `"medium"` \| `"high"` |
| `estimated_review_time` | `str` \| `null` | `null` | 예상 검토 소요 시간 |
| `paused_agents` | `list[str]` | `[]` | 결정 대기 중 일시정지된 에이전트 역할 목록 |

```json
{
  "gate_level": "l2_human",
  "trigger_reason": "Stripe 신규 외부 API 연동 감지",
  "required_decision": "Stripe 프로덕션 연동을 지금 진행할까요?",
  "decision_options": [
    {
      "option": "프로덕션 연동 진행",
      "next_action": "DevOps 에이전트에게 환경변수 설정 지시",
      "risk": "low"
    },
    {
      "option": "Mock 유지 후 나중에",
      "next_action": "Tester 에이전트에게 Mock 기반 테스트 계속",
      "risk": "none"
    }
  ],
  "estimated_review_time": "5분",
  "paused_agents": ["tester", "devops"]
}
```

---

### memory_context

Mem0에서 자동 검색된 과거 패턴, 결정 이력, 에러 기록을 포함합니다. `MemoryStore.inject_memory_context()`가 Lifecycle 2단계에서 자동으로 채웁니다.

| 필드 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `relevant_past_decisions` | `list[PastDecision]` | `[]` | 유사한 과거 결정 목록 |
| `relevant_past_decisions[].similarity` | `float` | (필수) | 코사인 유사도 (0.0 ~ 1.0) |
| `relevant_past_decisions[].project` | `str` | (필수) | 결정이 내려진 프로젝트 ID |
| `relevant_past_decisions[].decision` | `str` | (필수) | 과거 결정 내용 |
| `relevant_past_decisions[].outcome` | `str` | (필수) | 결정의 결과: `"success"` \| `"failure"` \| `"unknown"` |
| `known_patterns` | `list[Pattern]` | `[]` | 적용 가능한 코드 패턴 목록 |
| `error_history` | `list[ErrorRecord]` | `[]` | 관련 과거 에러 기록 |
| `human_feedback` | `list[Feedback]` | `[]` | 개발자가 남긴 피드백 이력 |

```json
{
  "relevant_past_decisions": [
    {
      "similarity": 0.92,
      "project": "proj_ecomm_v1",
      "decision": "결제 실패 시 3회 자동 재시도 후 알림",
      "outcome": "success"
    }
  ],
  "known_patterns": [
    {
      "pattern": "Repository Pattern",
      "reason": "표준 DB 접근 패턴",
      "example_file": "src/users/users.repository.ts"
    }
  ],
  "error_history": [],
  "human_feedback": [
    {
      "date": "2026-04-10",
      "decision": "외부 결제 API는 항상 Mock 우선",
      "applies_to": "payment_integration"
    }
  ]
}
```

---

## Pydantic 모델 참조

전체 모델 정의: `src/orchestrator/handoff.py`

| 모델 | 설명 | 필수 여부 |
|---|---|---|
| `HandoffArtifact` | 루트 모델 (7섹션 포함) | -- |
| `Envelope` | 핸드오프 식별 및 라우팅 | 필수 |
| `ProjectContext` | 프로젝트 네임스페이스 | 필수 |
| `Task` | 작업 요약 및 지시 | 필수 |
| `Artifacts` | 변경 파일 및 산출물 | 필수 |
| `ChangedFile` | 개별 파일 변경 정보 | Artifacts 하위 |
| `QualityGates` | QA 결과 및 게이트 결정 | 필수 |
| `HumanGatePackage` | 개발자 결정 요청 패키지 | 조건부 |
| `MemoryContext` | 과거 메모리 주입 컨텍스트 | 선택 |
