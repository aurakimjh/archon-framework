# Human Gate Design

🇰🇷 [한국어](../ko/human-gate.md)

> Version: 1.1.0 | Last updated: 2026-04-23

## Overview

The Human Gate is the **decision layer** between automatic agent progression and human intervention. It synthesizes QA pipeline results and Review Agent scores to choose one of 5 levels.

Source code: `src/gate/evaluator.py`, `src/gate/models.py`

## Pipeline Flow

```
Agent task complete
    ↓
Automated QA pipeline (ruff lint · build · pytest · coverage · semgrep)
    ↓
Review Agent (Claude Sonnet) — produces review_score 0–100
    ↓
evaluate_gate() decision
    ↓
┌───────────┬───────────┬───────────┬───────────┬───────────┐
│AUTO_PASS  │L1_REWORK  │L2_HUMAN   │L3_HALT    │L4_DEPLOY  │
│auto-commit│agent      │developer  │emergency  │always     │
│branch push│self-rework│notified,  │stop       │human      │
│           │(max 3x)   │project    │           │approval   │
│           │           │paused     │           │           │
└───────────┴───────────┴───────────┴───────────┴───────────┘
```

## Gate Level Details

### AUTO_PASS — automatic progression

**Conditions** (all must hold):
- `lint_result == "passed"` · `build_result == "passed"`
- `security_scan.critical == 0` and `security_scan.high == 0` and `security_scan.medium == 0`
- `test_results.coverage_percent >= coverage_threshold` (default 80%)
- `test_results.unit_failed == 0`
- `review_score >= review_score_threshold` (default 70)
- No Dynamic Guardrails triggered · SOP score passes

**Next action**: auto-commit → branch push

---

### L1 — Agent Self-Rework

The agent fixes the issue without human involvement.

**Trigger conditions** (any one):
- `lint_result != "passed"` — lint errors
- `coverage_threshold - 10 <= coverage_percent < coverage_threshold` — borderline coverage
- `test_results.unit_failed > 0` — some unit tests failing

**Limit**: when `max_retry_before_escalation` is reached (default 3), automatically **escalates to L2**.

---

### L2 — Human Gate

Only the affected project pauses. Developer receives a notification.

**Trigger conditions** (any one):

| Check | Condition |
|---|---|
| review_score below threshold | `review_score < review_score_threshold` (default 70) |
| coverage hard fail | `coverage_percent < coverage_threshold - 10` (default 70%) |
| schema change | `has_schema_change == True` AND `require_human_on_schema_change == True` |
| external integration | `has_external_integration == True` AND `require_human_on_external_integration == True` |
| security Medium | `security_scan.medium > 0` |
| retries exhausted | `retry_count >= max_retry_before_escalation` |
| **Dynamic Guardrails** | high-risk path/keyword detected (see below) |
| SOP below threshold | `sop_compliance_score < sop_compliance_threshold` (default 70) |

**Next action**: generate `human_gate_package` → notify developer → await decision

---

### Dynamic Guardrails — automatic risk detection

`_check_dynamic_guardrails()` checks two things.

**1. Changed file path check** (`policy.high_risk_paths`)

Default detected paths: `payment`, `billing`, `auth`, `security`, `migration`, `infrastructure/`, `secrets/`

```python
# Any of these path changes auto-escalates to L2
src/payments/checkout.py     # matches "payment"
src/auth/jwt_middleware.py   # matches "auth"
infrastructure/terraform/    # matches "infrastructure/"
```

**2. Task instruction keyword check** (`policy.high_risk_keywords`)

Default detected keywords: `payment`, `billing`, `charge`, `refund`, `credential`, `secret`, `token`, `api_key`, `delete_all`, `drop_table`, `truncate`, `production`, `deploy`

```python
# Instructions containing any of these auto-escalate to L2
"Implement a refund API and deploy to production"
# → "refund", "production", "deploy" detected
```

> **Why this matters**: even perfect review scores and coverage don't guarantee safety in payment, auth, or infrastructure changes — a human should always review these.

---

### SOP Compliance Check

`_check_sop_compliance()`. If `QualityGates.sop_compliance_score` is `None`, the check is skipped (pass). If the score is below `sop_compliance_threshold` (default 70), escalates to L2.

The SOP score measures adherence to procedures defined in the `.harness/sop/` directory.

---

### L3 — Emergency Halt

Immediate developer notification. Only the affected agent stops.

**Trigger conditions**:
- `build_result != "passed"` — build failure
- `security_scan.critical > 0` or `security_scan.high > 0` — Critical/High vulnerabilities

> **Note**: L1 retry exhaustion escalates to **L2**, not L3.

---

### L4 — Deploy Gate

Always requires human final approval. `is_deploy_request=True` returns L4 immediately, regardless of other conditions.

**Applies to**:
- Production environment deployments
- Core infrastructure changes (DNS, load balancer, security groups)
- Production DB migrations

---

## Decision Logic (Code)

`evaluate_gate()` in `src/gate/evaluator.py`.

Priority: **L4 > L3 > L2 > L1 > AUTO_PASS**

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

    if _check_l3_halt(quality, retry_count):       # build fail, Critical/High security
        return GateDecision.L3_HALT

    if _check_l2_human(quality, policy, ...):      # review_score, schema, retries, etc.
        return GateDecision.L2_HUMAN

    if _check_dynamic_guardrails(policy, ...):     # high-risk paths/keywords
        return GateDecision.L2_HUMAN

    if _check_sop_compliance(quality, policy):     # SOP score below threshold
        return GateDecision.L2_HUMAN

    if _check_l1_rework(quality, policy):          # lint, borderline coverage
        return GateDecision.L1_REWORK

    return GateDecision.AUTO_PASS
```

## Testing

`tests/test_gate_evaluator.py` — gate decision unit tests (11 cases)

`tests/test_demo_pipeline.py` — full pipeline integration tests (8 cases)

```bash
pytest tests/test_gate_evaluator.py -v
pytest tests/test_demo_pipeline.py -v
```

## Human Gate Package

The `HandoffArtifact.human_gate_package` payload for L2 and above.

```json
{
  "gate_level": "l2_human",
  "trigger_reason": "high-risk path: src/payments/checkout.py",
  "required_decision": "Review the changes and decide whether to proceed.",
  "decision_options": [
    { "option": "Approve", "next_action": "Resume agent work", "risk": "low" },
    { "option": "Reject", "next_action": "Request agent rework", "risk": "none" }
  ],
  "paused_agents": ["backend", "tester"]
}
```
