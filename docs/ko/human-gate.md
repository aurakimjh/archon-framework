# Human Gate 설계

🇺🇸 [English](../en/human-gate.md)

> 버전: 2.0.0 | 최종 수정: 2026-04-24

## 개요

Human Gate는 에이전트의 자동 진행과 인간 개입 사이의 **판단 레이어**입니다. QA 파이프라인, Review Agent 평가, 가드레일 검사, 에이전트 상태 모니터링을 종합하여 5개 레벨 중 하나를 결정합니다.

에이전트가 아무리 뛰어나도, 결제 로직 변경이나 프로덕션 배포처럼 실수가 큰 영향을 미치는 작업에서는 사람이 한 번은 확인해야 합니다. Human Gate는 그 "한 번"을 체계적으로 보장하는 장치입니다.

소스 코드: `src/gate/evaluator.py`, `src/gate/models.py`

---

## Gate Decision Flow Diagram

에이전트 작업이 완료되면 아래 전체 흐름을 거칩니다.

```
Input → InputValidator → LLM Call → OutputValidator → QA Pipeline → Gate Evaluator → Decision
                                                                          ↓
                                              AUTO_PASS → GitExecutor.auto_commit()
                                              L1_REWORK → retry (max 3) → L2 escalation
                                              L2_HUMAN  → Dashboard queue / Terminal alert
                                              L3_HALT   → Pipeline stop + alert
                                              L4_DEPLOY → Deploy approval required
```

각 단계를 설명하면 다음과 같습니다.

1. **InputValidator** — LLM 호출 전에 입력을 검사합니다 (민감 데이터, 프롬프트 인젝션, 토큰 한도, 금지 키워드).
2. **LLM Call** — 에이전트가 모델을 호출하여 작업을 수행합니다.
3. **OutputValidator** — LLM 응답을 검사합니다 (위험 코드, 보안 패턴, 환각 힌트).
4. **QA Pipeline** — ruff lint, build, pytest, coverage, semgrep 등 자동 품질 검사를 실행합니다.
5. **Gate Evaluator** — 모든 결과를 종합하여 게이트 레벨을 결정합니다.

---

## 게이트 레벨 상세

### AUTO_PASS — 자동 진행

모든 검사를 통과했을 때 에이전트가 자동으로 진행합니다.

**조건** (모두 충족 시):
- `lint_result == "passed"` 그리고 `build_result == "passed"`
- `security_scan.critical == 0` 그리고 `security_scan.high == 0` 그리고 `security_scan.medium == 0`
- `test_results.coverage_percent >= coverage_threshold` (기본 80%)
- `test_results.unit_failed == 0`
- `review_score >= review_score_threshold` (기본 70)
- Dynamic Guardrails 미감지
- SOP 점수 통과
- InputValidator / OutputValidator 통과
- PathGuard 보호 파일 미변경

**후속 액션**: `GitExecutor.auto_commit()` 실행 → protected_paths 유효성 검증 → 브랜치 푸시

**예시**: 에이전트가 유틸리티 함수를 추가하고, 테스트 커버리지 92%, 린트 통과, 보안 이슈 없음 → 자동 커밋됩니다.

---

### L1 — 에이전트 자동 재작업

사소한 문제가 있지만 에이전트가 스스로 수정할 수 있는 수준입니다. 사람이 개입하지 않아도 됩니다.

**트리거 조건** (하나라도 해당 시):
- `lint_result != "passed"` — 린트 오류
- `coverage_threshold - 10 <= coverage_percent < coverage_threshold` — 커버리지 아슬아슬 미달
- `test_results.unit_failed > 0` — 단위 테스트 일부 실패

**제한**: `max_retry_before_escalation` 횟수(기본 3) 도달 시 자동으로 **L2**로 에스컬레이션됩니다.

**예시**: 에이전트가 생성한 코드에 import 정렬 오류가 있음 → 린트 실패 → 에이전트가 자동으로 수정 후 재시도합니다.

**왜 L1인가**: 린트 오류나 소폭 커버리지 미달은 에이전트가 충분히 자동 해결할 수 있는 문제이기 때문입니다. 사람의 시간을 아끼기 위한 설계입니다.

---

### L2 — Human Gate

에이전트가 해결할 수 없거나 사람의 판단이 필요한 상황입니다. 해당 프로젝트만 일시정지되고, 개발자에게 알림이 전송됩니다.

**트리거 조건** (하나라도 해당 시):

| 체크 | 조건 |
|---|---|
| review_score 미달 | `review_score < review_score_threshold` (기본 70) |
| 커버리지 하드 미달 | `coverage_percent < coverage_threshold - 10` (기본 70%) |
| 스키마 변경 | `has_schema_change == True` AND `require_human_on_schema_change == True` |
| 외부 연동 | `has_external_integration == True` AND `require_human_on_external_integration == True` |
| 보안 Medium | `security_scan.medium > 0` |
| 재작업 소진 | `retry_count >= max_retry_before_escalation` |
| Dynamic Guardrails | 고위험 경로/키워드 감지 (아래 참조) |
| SOP 미달 | `sop_compliance_score < sop_compliance_threshold` (기본 70) |
| PathGuard | 보호된 파일(.env, *.pem, *.key) 또는 설정 파일 변경 감지 |
| 에이전트 사망 | AgentHealthMonitor가 DEAD 상태 감지 시 |

**후속 액션**: `human_gate_package` 생성 → Dashboard 큐 등록 또는 터미널 알림 → 개발자 결정 대기

**예시**: 에이전트가 `src/auth/oauth.py`를 수정함 → Dynamic Guardrails에서 "auth" 경로 감지 → 사람 검토 요청됩니다.

**왜 L2인가**: review_score가 높더라도 결제, 인증, 인프라 같은 고위험 영역은 자동화만으로 신뢰하기 어렵습니다. 에이전트가 3번 재작업해도 실패하면, 그것은 에이전트 수준을 넘는 문제일 가능성이 높습니다.

---

### L3 — 긴급 전체 중단

심각한 문제가 발생한 상황입니다. 즉시 개발자에게 알림이 전송되고, 영향받는 에이전트가 중단됩니다.

**트리거 조건**:
- `build_result != "passed"` — 빌드 실패
- `security_scan.critical > 0` or `security_scan.high > 0` — Critical/High 보안 취약점

> **참고**: L1 재작업 소진(retry 횟수 초과)은 L3이 아닌 **L2**에서 처리됩니다.

**예시**: semgrep에서 SQL Injection 취약점(High)이 감지됨 → 즉시 파이프라인 중단 및 개발자 알림이 전송됩니다.

**왜 L3인가**: 빌드가 깨지거나 Critical 보안 취약점이 있는 코드는 어떤 상황에서도 진행되면 안 됩니다. 재작업으로 해결할 문제가 아닙니다.

---

### L4 — 배포 게이트

프로덕션에 영향을 주는 작업에는 항상 사람의 최종 승인이 필요합니다. `is_deploy_request=True`이면 다른 조건과 무관하게 즉시 L4가 반환됩니다.

**해당 상황**:
- 프로덕션 환경 배포
- 핵심 인프라 변경 (DNS, 로드밸런서, 보안그룹)
- 프로덕션 DB 마이그레이션 실행

**예시**: 에이전트가 Kubernetes 매니페스트를 변경하고 배포 요청 → 모든 QA 통과해도 반드시 사람 승인이 필요합니다.

**왜 L4인가**: 프로덕션 배포는 되돌리기 어렵고 사용자에게 직접 영향을 줍니다. 테스트를 아무리 잘 해도 배포 결정은 사람이 내려야 합니다.

---

## Dynamic Guardrails — 자동 위험 감지

`_check_dynamic_guardrails()` 함수가 두 가지를 검사합니다.

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

---

## SOP Compliance 검사

`_check_sop_compliance()` 함수가 SOP 준수도를 확인합니다. `QualityGates.sop_compliance_score`가 `None`이면 검사를 스킵합니다(통과). 점수가 `sop_compliance_threshold`(기본 70) 미만이면 L2로 상향됩니다.

SOP(Standard Operating Procedure) 점수는 `.harness/sop/` 디렉토리의 절차서 준수도를 측정합니다.

---

## 가드레일 통합

Phase 3에서 전체 가드레일 모듈이 Human Gate와 통합되었습니다. 가드레일은 LLM 호출 전후에 동작하여 위험한 입력/출력을 사전에 차단합니다.

### InputValidator — LLM 호출 전 검사

에이전트가 LLM을 호출하기 전에 입력을 검사합니다.

| 검사 항목 | 감지 대상 |
|---|---|
| 민감 데이터 | API 키, AWS 키, 개인 키, 비밀번호, JWT, 신용카드 번호, SSN |
| 프롬프트 인젝션 | "ignore instructions", "system override", jailbreak 시도 |
| 토큰 한도 | 입력 토큰이 `max_input_tokens` 초과 여부 |
| 금지 키워드 | 정책에서 정의한 커스텀 금지 키워드 |

민감 데이터가 LLM에 전달되면 모델이 학습하거나 로그에 남을 수 있습니다. InputValidator는 이를 사전에 차단하여 정보 유출을 방지합니다.

### OutputValidator — LLM 호출 후 검사

LLM 응답에 위험한 내용이 포함되어 있는지 검사합니다.

| 검사 항목 | 감지 대상 |
|---|---|
| 위험 코드 | `rm -rf`, `DROP TABLE`, `eval()`/`exec()` |
| 보안 패턴 | 하드코딩된 시크릿, SQL 인젝션, XSS |
| 환각 힌트 | 존재하지 않는 표준 라이브러리, 존재하지 않는 메서드 |

에이전트가 `rm -rf /` 같은 명령을 실행하면 돌이킬 수 없습니다. OutputValidator는 이런 위험 코드가 실제로 실행되기 전에 차단합니다.

### TokenBudgetTracker — 토큰 예산 관리

| 항목 | 설명 |
|---|---|
| 일일 토큰 한도 | `daily_token_limit` (기본 100,000) |
| 에이전트별 한도 | 개별 에이전트의 최대 토큰 사용량 |
| 비용 추적 | 토큰 사용량 기반 비용 계산 |
| 경고 임계값 | 80% 사용 시 경고 (`budget_warn_threshold`) |

예산을 추적하지 않으면 에이전트가 무한 루프에 빠져 비용이 폭증할 수 있습니다. TokenBudgetTracker가 이를 방지합니다.

### PathGuard — 파일 경로 보호

| 항목 | 설명 |
|---|---|
| 항상 보호 | `.env`, `*.pem`, `*.key` 파일 |
| 추가 보호 | 정책의 `extra_protected_paths`에 정의된 경로 |
| 설정 파일 변경 | `force_human_gate_on_config_change=True`일 때 설정 파일 변경 시 Human Gate 강제 |

`.env` 파일이나 인증서 파일을 에이전트가 실수로 수정하거나 삭제하면 서비스 장애로 이어집니다. PathGuard가 이런 파일에 대한 변경을 차단하거나 사람 검토를 강제합니다.

---

## 가드레일 설정

`GuardrailPolicy`를 사용하여 모든 가드레일을 중앙에서 설정할 수 있습니다.

```python
from src.guardrails import GuardrailPolicy

policy = GuardrailPolicy(
    # Input
    max_input_tokens=32_000,
    detect_sensitive_data=True,
    detect_prompt_injection=True,
    # Output
    detect_dangerous_code=True,
    detect_security_patterns=True,
    # Budget
    daily_token_limit=100_000,
    budget_warn_threshold=0.8,
    # Path
    extra_protected_paths=["migrations/", "k8s/"],
    force_human_gate_on_config_change=True,
)
```

각 옵션 설명:

| 옵션 | 기본값 | 설명 |
|---|---|---|
| `max_input_tokens` | 32,000 | 입력 토큰 최대치. 초과 시 입력 거부 |
| `detect_sensitive_data` | True | API 키, 비밀번호 등 민감 데이터 자동 감지 |
| `detect_prompt_injection` | True | 프롬프트 인젝션 시도 차단 |
| `detect_dangerous_code` | True | 위험 명령어(rm -rf 등) 차단 |
| `detect_security_patterns` | True | 하드코딩 시크릿, SQL 인젝션 패턴 감지 |
| `daily_token_limit` | 100,000 | 일일 토큰 사용 한도 |
| `budget_warn_threshold` | 0.8 | 예산의 80% 사용 시 경고 |
| `extra_protected_paths` | [] | 추가로 보호할 경로 목록 |
| `force_human_gate_on_config_change` | True | 설정 파일 변경 시 Human Gate 강제 여부 |

---

## 관측성(Observability) 통합

게이트 판정은 Archon의 Tracing 시스템과 연동됩니다.

- **TracingMiddleware**가 파이프라인에서 `gate_span`을 시작합니다.
- 게이트 결정(레벨, 사유)이 span output에 기록됩니다.
- 파이프라인 중 모든 LLM 호출이 지연 시간, 토큰 수, 비용과 함께 추적됩니다.

이를 통해 "왜 이 작업이 L2로 올라갔는지", "LLM 호출에 얼마나 걸렸는지"를 사후에 추적할 수 있습니다. 디버깅과 최적화에 필수적인 기능입니다.

---

## Self-Healing 통합

에이전트가 비정상 상태에 빠졌을 때 자동 복구를 시도하며, 복구 실패 시 Human Gate로 에스컬레이션됩니다.

### 에이전트 상태 모니터링

`AgentHealthMonitor`가 각 에이전트의 상태를 지속적으로 추적합니다.

| 상태 | 설명 | 조치 |
|---|---|---|
| HEALTHY | 정상 동작 | 없음 |
| DEGRADED | 응답 지연, 간헐적 오류 | 모니터링 강화 |
| UNHEALTHY | 반복적 오류 | `SelfHealer`가 자동 복구 시도 |
| DEAD | 응답 없음 또는 완전 실패 | **L2_HUMAN 에스컬레이션** |

### 자동 복구 전략

`SelfHealer`가 시도하는 복구 방법입니다 (순서대로 시도):

1. **model_downgrade** — 더 안정적인 모델로 다운그레이드
2. **agent_reinit** — 에이전트 재초기화
3. **substitute** — 대체 에이전트로 교체

### HealthWatchdog

백그라운드에서 지속적으로 모든 에이전트의 상태를 모니터링합니다. DEAD 상태가 감지되면 자동으로 L2_HUMAN 에스컬레이션을 트리거합니다.

---

## Dashboard 통합

웹 대시보드를 통해 게이트 결정을 관리할 수 있습니다.

| 엔드포인트 | 메서드 | 설명 |
|---|---|---|
| `/api/gates/queue` | GET | 대기 중인 게이트 목록 조회 |
| `/api/gates/{id}/approve` | POST | 게이트 승인 |
| `/api/gates/{id}/reject` | POST | 게이트 반려 |

**WebSocket 실시간 알림**: 게이트 이벤트가 발생하면 WebSocket을 통해 실시간으로 알림을 받을 수 있습니다. 대시보드를 열어두면 새로운 L2/L3/L4 이벤트가 즉시 표시됩니다.

---

## Evolution 통합

Human Gate의 판정 기록을 분석하여 임계값을 자동으로 최적화합니다.

- **MetricsCollector** — 모든 게이트 결정(레벨, 사유, 빈도)을 기록합니다.
- **PatternAnalyzer** — 패턴을 분석합니다. 예를 들어, L1_REWORK가 지나치게 자주 발생하면 임계값 조정을 제안합니다.
- **ThresholdTuner** — 안전 범위 내에서 `review_score_threshold` 등의 값을 자동으로 조정할 수 있습니다.

이를 통해 Human Gate가 시간이 지남에 따라 프로젝트에 맞게 점점 더 정확해집니다. "너무 자주 사람을 부르는" 문제나 "너무 많이 자동 통과시키는" 문제를 데이터 기반으로 해결합니다.

---

## 트랜잭션 스냅샷

에이전트 실행 전후의 코드 상태를 스냅샷으로 관리하여 안전한 롤백을 보장합니다.

| 시점 | 동작 |
|---|---|
| 에이전트 실행 전 | `GitExecutor.save_snapshot()` — 현재 상태를 스냅샷으로 저장 |
| 환각 감지 시 | `rollback_to_snapshot()` — 스냅샷으로 롤백 |
| AUTO_PASS 시 | `auto_commit()` — protected_paths 유효성 검증 후 자동 커밋 |

에이전트가 환각(hallucination)으로 존재하지 않는 라이브러리를 import하거나 잘못된 코드를 생성했을 때, 스냅샷 덕분에 안전하게 이전 상태로 되돌릴 수 있습니다.

---

## Self-Correction Flow

에이전트 출력의 형식 오류를 자동으로 수정하는 메커니즘입니다.

1. 에이전트 출력에 `<archon-output>` 태그가 있지만 JSON이 유효하지 않을 때 트리거됩니다.
2. `BaseAgent._self_correct_output()`가 LLM에게 수정 프롬프트를 전송합니다.
3. 1회 재시도 후에도 실패하면 원시 텍스트(raw text)로 폴백합니다.

이 기능은 LLM이 가끔 JSON 형식을 깨뜨리는 문제를 자동으로 해결합니다. 사소한 형식 오류 때문에 전체 파이프라인이 실패하는 것을 방지합니다.

---

## 판정 로직 (코드)

`src/gate/evaluator.py`의 `evaluate_gate()` 함수입니다.

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

---

## 테스트

```bash
# 게이트 판정 단위 테스트
pytest tests/test_gate_evaluator.py -v

# 가드레일 테스트
pytest tests/test_guardrails.py -v

# 하네스 통합 테스트
pytest tests/test_harness.py -v
```

`tests/test_gate_evaluator.py` — 게이트 판정 단위 테스트 (11개 케이스)

`tests/test_guardrails.py` — InputValidator, OutputValidator, TokenBudgetTracker, PathGuard 테스트

`tests/test_harness.py` — 전체 파이프라인 통합 테스트 (가드레일 + 게이트 + 스냅샷 포함)

---

## Human Gate Package

L2 이상 발동 시 `HandoffArtifact.human_gate_package`에 포함되는 구조체입니다.

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

Dashboard의 `/api/gates/queue`에서 이 패키지를 확인하고, `/api/gates/{id}/approve` 또는 `/api/gates/{id}/reject`로 판정할 수 있습니다.
