# Human Gate 설계

> 버전: 1.1.0 | 최종 수정: 2026-04-23

## 개요

Human Gate는 에이전트 자동 진행과 인간 개입 사이의 **판단 레이어**다. QA 파이프라인과 Review Agent의 평가를 종합해 5개 레벨 중 하나를 결정한다.

소스 코드: `src/gate/evaluator.py`, `src/gate/models.py`

## 파이프라인 흐름

```
에이전트 작업 완료
    ↓
자동 QA 파이프라인 (ruff lint · build · pytest · coverage · semgrep)
    ↓
Review Agent (Claude Sonnet) — review_score 0~100 산출
    ↓
evaluate_gate() 판정
    ↓
┌───────────┬───────────┬───────────┬───────────┬───────────┐
│AUTO_PASS  │L1_REWORK  │L2_HUMAN   │L3_HALT    │L4_DEPLOY  │
│자동커밋   │에이전트    │개발자알림  │긴급중단    │항상       │
│브랜치푸시  │재작업      │프로젝트    │           │Human승인  │
│           │(최대3회)   │일시정지   │           │           │
└───────────┴───────────┴───────────┴───────────┴───────────┘
```

## 게이트 레벨 상세

### AUTO_PASS — 자동 진행

**조건** (모두 충족 시):
- `lint_result == "passed"` · `build_result == "passed"`
- `security_scan.critical == 0` and `security_scan.high == 0` and `security_scan.medium == 0`
- `test_results.coverage_percent >= coverage_threshold` (기본 80%)
- `test_results.unit_failed == 0`
- `review_score >= review_score_threshold` (기본 70)
- Dynamic Guardrails 미감지 · SOP 점수 통과

**후속 액션**: 자동 커밋 → 브랜치 푸시

---

### L1 — 에이전트 자동 재작업

인간 개입 없이 에이전트가 스스로 수정한다.

**트리거 조건** (하나라도 해당 시):
- `lint_result != "passed"` — 린트 오류
- `coverage_threshold - 10 <= coverage_percent < coverage_threshold` — 커버리지 아슬아슬 미달
- `test_results.unit_failed > 0` — 단위 테스트 일부 실패

**제한**: `max_retry_before_escalation` 횟수(기본 3) 도달 시 자동으로 **L2 에스컬레이션**.

---

### L2 — Human Gate

해당 프로젝트만 일시정지. 개발자에게 알림 전송.

**트리거 조건** (하나라도 해당 시):

| 체크 | 조건 |
|---|---|
| review_score 미달 | `review_score < review_score_threshold` (기본 70) |
| 커버리지 하드 미달 | `coverage_percent < coverage_threshold - 10` (기본 70%) |
| 스키마 변경 | `has_schema_change == True` AND `require_human_on_schema_change == True` |
| 외부 연동 | `has_external_integration == True` AND `require_human_on_external_integration == True` |
| 보안 Medium | `security_scan.medium > 0` |
| 재작업 소진 | `retry_count >= max_retry_before_escalation` |
| **Dynamic Guardrails** | 고위험 경로/키워드 감지 (아래 참조) |
| SOP 미달 | `sop_compliance_score < sop_compliance_threshold` (기본 70) |

**후속 액션**: `human_gate_package` 생성 → 개발자 알림 → 결정 대기

---

### Dynamic Guardrails — 자동 위험 감지

`_check_dynamic_guardrails()` 함수가 두 가지를 검사한다.

**1. 변경 파일 경로 검사** (`policy.high_risk_paths`)

기본 감지 경로: `payment`, `billing`, `auth`, `security`, `migration`, `infrastructure/`, `secrets/`

```python
# 예: 아래 경로 변경 시 자동 L2 상향
src/payments/checkout.py     # "payment" 매칭
src/auth/jwt_middleware.py   # "auth" 매칭
infrastructure/terraform/    # "infrastructure/" 매칭
```

**2. 태스크 지시사항 키워드 검사** (`policy.high_risk_keywords`)

기본 감지 키워드: `payment`, `billing`, `charge`, `refund`, `credential`, `secret`, `token`, `api_key`, `delete_all`, `drop_table`, `truncate`, `production`, `deploy`

```python
# 예: 지시사항에 아래 단어 포함 시 자동 L2 상향
"결제 환불 API를 구현하고 production 환경에 deploy해줘"
# → "refund", "production", "deploy" 감지
```

> **왜 필요한가**: review_score나 coverage 수치가 아무리 좋아도, 결제·인증·인프라 영역 변경은 인간이 한 번은 눈으로 확인해야 한다.

---

### SOP Compliance 검사

`_check_sop_compliance()` 함수. `QualityGates.sop_compliance_score`가 `None`이면 검사 스킵(통과). 점수가 `sop_compliance_threshold`(기본 70) 미만이면 L2 상향.

SOP(Standard Operating Procedure) 점수는 `.harness/sop/` 디렉토리의 절차서 준수도를 측정한다.

---

### L3 — 긴급 전체 중단

즉시 개발자에게 알림. 영향받는 에이전트만 중단.

**트리거 조건**:
- `build_result != "passed"` — 빌드 실패
- `security_scan.critical > 0` or `security_scan.high > 0` — Critical/High 보안 취약점

> **참고**: L1 재작업 소진(retry 횟수 초과)은 L3이 아닌 **L2**에서 처리한다.

---

### L4 — 배포 게이트

항상 Human 최종 승인 필요. `is_deploy_request=True`이면 다른 조건과 무관하게 즉시 L4 반환.

**해당 상황**:
- 프로덕션 환경 배포
- 핵심 인프라 변경 (DNS, 로드밸런서, 보안그룹)
- 프로덕션 DB 마이그레이션 실행

---

## 판정 로직 (코드)

`src/gate/evaluator.py`의 `evaluate_gate()` 함수.

우선순위: **L4 > L3 > L2 > L1 > AUTO_PASS**

```python
def evaluate_gate(
    quality: QualityGates,
    policy: QualityPolicy,
    has_schema_change: bool = False,
    has_external_integration: bool = False,
    is_deploy_request: bool = False,
    retry_count: int = 0,
    changed_paths: list[str] | None = None,
    task_instructions: str = "",
) -> GateDecision:
    if is_deploy_request:
        return GateDecision.L4_DEPLOY

    if _check_l3_halt(quality, retry_count):       # 빌드 실패, Critical/High 보안
        return GateDecision.L3_HALT

    if _check_l2_human(quality, policy, ...):      # review_score, 스키마, 재작업 소진 등
        return GateDecision.L2_HUMAN

    if _check_dynamic_guardrails(policy, ...):     # 고위험 경로/키워드
        return GateDecision.L2_HUMAN

    if _check_sop_compliance(quality, policy):     # SOP 점수 미달
        return GateDecision.L2_HUMAN

    if _check_l1_rework(quality, policy):          # 린트, 커버리지 소폭 미달
        return GateDecision.L1_REWORK

    return GateDecision.AUTO_PASS
```

## 테스트

`tests/test_gate_evaluator.py` — 게이트 판정 단위 테스트 (11개 케이스)

`tests/test_demo_pipeline.py` — 전체 파이프라인 통합 테스트 (8개 케이스)

```bash
pytest tests/test_gate_evaluator.py -v
pytest tests/test_demo_pipeline.py -v
```

## Human Gate Package

L2 이상 발동 시 `HandoffArtifact.human_gate_package`에 포함되는 구조체.

```json
{
  "gate_level": "l2_human",
  "trigger_reason": "high-risk path: src/payments/checkout.py",
  "required_decision": "변경 사항을 검토하고 진행 여부를 결정하세요.",
  "decision_options": [
    { "option": "승인", "next_action": "에이전트 작업 재개", "risk": "low" },
    { "option": "반려", "next_action": "에이전트 재작업 요청", "risk": "none" }
  ],
  "paused_agents": ["backend", "tester"]
}
```
