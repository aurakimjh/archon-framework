# Human Gate 설계

> 버전: 1.0.0 | 최종 수정: 2026-04-22

## 개요

Human Gate는 에이전트 자동 진행과 인간 개입 사이의 **판단 레이어**다. QA 파이프라인과 Review Agent의 평가를 종합해 4레벨 중 하나를 결정한다.

소스 코드: `src/gate/evaluator.py`, `src/gate/models.py`

## 파이프라인 흐름

```
에이전트 작업 완료
    ↓
자동 QA 파이프라인 (린트 · 빌드 · 단위테스트 · 커버리지 · 보안스캔)
    ↓
Review Agent (Claude Sonnet) — 코드품질 · 설계일관성 · 보안 · 복잡도 점수
    ↓
gate_decision 판정
    ↓
┌───────────┬───────────┬───────────┬───────────┐
│ auto_pass │ l1_rework │ l2_human  │ l3_halt   │
│자동커밋    │에이전트    │개발자알림  │긴급중단    │
│/푸시      │재작업      │프로젝트    │           │
│           │           │일시정지    │           │
└───────────┴───────────┴───────────┴───────────┘
                                         ↓ (배포 요청 시)
                                    l4_deploy
                                    (항상 Human 승인)
```

## 게이트 레벨 상세

### auto_pass — 자동 진행

**조건 (모두 충족 시)**:
- 단위 테스트 전통과 + 커버리지 >= 설정값 (기본 80%)
- 린트 오류 0 · 빌드 성공 · 타입 에러 0
- 보안 스캔 Critical/High 취약점 0개
- 순환 복잡도 <= 10 · 함수 길이 <= 50줄
- review_score >= 70

**후속 액션**: 자동 커밋 → 브랜치 푸시

### L1 — 에이전트 자동 재작업

인간 개입 없이 에이전트가 스스로 수정한다.

**트리거 조건**:
- 린트 경고 · 코드 스타일 위반 · 불필요한 import
- 커버리지 70~79% (설정값 -10% 이내)
- 주석 누락 · 함수명 컨벤션 미준수 · 매직 넘버
- 경미한 성능 이슈 · 단순 중복 코드
- 단위 테스트 소수 실패

**제한**: 최대 3회 재시도. 초과 시 L2로 자동 에스컬레이션.

### L2 — Human Gate

해당 프로젝트만 일시정지. 개발자에게 알림 전송.

**트리거 조건**:
- 아키텍처 패턴 위반 · 레이어 의존성 역전
- DB 스키마 변경 · 마이그레이션 포함
- 신규 외부 API 연동 · 라이선스 미확인 패키지
- 응답시간 20% 이상 증가 예측
- 보안 취약점 Medium · 인증/인가 로직 변경
- 테스트 커버리지 < 70%
- review_score < 70
- L1 재작업 3회 실패

**후속 액션**: `human_gate_package` 생성 → 개발자 알림 → 결정 대기

### L3 — 긴급 전체 중단

즉시 개발자에게 알림. 영향받는 에이전트만 중단.

**트리거 조건**:
- 빌드 실패 · 컴파일 에러 · 런타임 크래시
- 보안 취약점 Critical/High · 데이터 유출 가능성
- 에이전트 루프 감지 (동일 작업 3회 반복 실패)
- 토큰 비용 일일 예산 90% 초과
- 대규모 파일 삭제 시도 · protected_paths 무단 변경
- Git force push 시도

### L4 — 배포 게이트

항상 Human 최종 승인 필요.

**트리거 조건**:
- 프로덕션 환경 배포
- 핵심 인프라 변경 (DNS, 로드밸런서, 보안그룹)
- 프로덕션 DB 마이그레이션 실행
- 외부 서비스 최초 프로덕션 활성화

## 판정 로직 (코드)

`src/gate/evaluator.py`의 `evaluate_gate()` 함수가 판정을 수행한다.

우선순위: **L4 > L3 > L2 > L1 > auto_pass**

```python
def evaluate_gate(quality, policy, ...) -> GateDecision:
    if is_deploy_request:
        return L4_DEPLOY
    if _check_l3_halt(quality, retry_count):
        return L3_HALT
    if _check_l2_human(quality, policy, ...):
        return L2_HUMAN
    if _check_l1_rework(quality, policy):
        return L1_REWORK
    return AUTO_PASS
```

## 테스트

`tests/test_gate_evaluator.py`에 11개 테스트 케이스가 포함되어 있다.
