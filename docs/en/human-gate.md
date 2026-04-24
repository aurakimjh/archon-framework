# Human Gate Design

🇰🇷 [한국어](../ko/human-gate.md)

> Version: 2.0.0 | Last updated: 2026-04-24

## Overview

The Human Gate is the **decision layer** between automatic agent progression and human intervention. It synthesizes QA pipeline results, Review Agent evaluations, guardrail checks, and agent health monitoring to choose one of 5 levels.

No matter how capable an agent is, some actions — changing payment logic, deploying to production — carry consequences that demand a human pair of eyes. The Human Gate systematically guarantees that checkpoint.

Source code: `src/gate/evaluator.py`, `src/gate/models.py`

---

## Gate Decision Flow Diagram

After an agent completes its task, it passes through this entire pipeline:

```
Input → InputValidator → LLM Call → OutputValidator → QA Pipeline → Gate Evaluator → Decision
                                                                          ↓
                                              AUTO_PASS → GitExecutor.auto_commit()
                                              L1_REWORK → retry (max 3) → L2 escalation
                                              L2_HUMAN  → Dashboard queue / Terminal alert
                                              L3_HALT   → Pipeline stop + alert
                                              L4_DEPLOY → Deploy approval required
```

Here is what happens at each stage:

1. **InputValidator** — checks inputs before the LLM call (sensitive data, prompt injection, token limits, forbidden keywords).
2. **LLM Call** — the agent invokes the model to perform its task.
3. **OutputValidator** — inspects the LLM response (dangerous code, security patterns, hallucination hints).
4. **QA Pipeline** — runs automated quality checks: ruff lint, build, pytest, coverage, semgrep.
5. **Gate Evaluator** — combines all results and selects a gate level.

---

## Gate Level Details

### AUTO_PASS — Automatic Progression

Everything looks good. The agent proceeds without human involvement.

**Conditions** (all must hold):
- `lint_result == "passed"` and `build_result == "passed"`
- `security_scan.critical == 0` and `security_scan.high == 0` and `security_scan.medium == 0`
- `test_results.coverage_percent >= coverage_threshold` (default 80%)
- `test_results.unit_failed == 0`
- `review_score >= review_score_threshold` (default 70)
- No Dynamic Guardrails triggered
- SOP score passes
- InputValidator / OutputValidator pass
- PathGuard detects no protected file changes

**Next action**: `GitExecutor.auto_commit()` with protected_paths validation, then branch push.

**Example**: An agent adds a utility function. Test coverage is 92%, lint passes, no security issues. The change is auto-committed.

---

### L1 — Agent Self-Rework

Minor issues the agent can fix on its own. No human involvement needed.

**Trigger conditions** (any one):
- `lint_result != "passed"` — lint errors
- `coverage_threshold - 10 <= coverage_percent < coverage_threshold` — borderline coverage
- `test_results.unit_failed > 0` — some unit tests failing

**Limit**: when `max_retry_before_escalation` is reached (default 3), automatically **escalates to L2**.

**Example**: The agent generates code with an import sorting error. Lint fails. The agent automatically fixes the import order and retries.

**Why L1**: Lint errors and slight coverage misses are well within an agent's ability to self-correct. This saves human time for issues that actually need it.

---

### L2 — Human Gate

The issue either exceeds the agent's capability or requires human judgment. Only the affected project pauses. The developer receives a notification.

**Trigger conditions** (any one):

| Check | Condition |
|---|---|
| review_score below threshold | `review_score < review_score_threshold` (default 70) |
| coverage hard fail | `coverage_percent < coverage_threshold - 10` (default 70%) |
| schema change | `has_schema_change == True` AND `require_human_on_schema_change == True` |
| external integration | `has_external_integration == True` AND `require_human_on_external_integration == True` |
| security Medium | `security_scan.medium > 0` |
| retries exhausted | `retry_count >= max_retry_before_escalation` |
| Dynamic Guardrails | high-risk path/keyword detected (see below) |
| SOP below threshold | `sop_compliance_score < sop_compliance_threshold` (default 70) |
| PathGuard | protected file (.env, *.pem, *.key) or config file change detected |
| agent death | AgentHealthMonitor detects DEAD status |

**Next action**: generate `human_gate_package`, add to Dashboard queue or send terminal alert, await developer decision.

**Example**: An agent modifies `src/auth/oauth.py`. Dynamic Guardrails detects the "auth" path. Human review is requested.

**Why L2**: Even with high review scores, high-risk areas like payments, auth, and infrastructure cannot be trusted to automation alone. If an agent fails after 3 retries, the problem likely exceeds its capabilities.

---

### L3 — Emergency Halt

A serious problem has been found. The developer is notified immediately and the affected agent stops.

**Trigger conditions**:
- `build_result != "passed"` — build failure
- `security_scan.critical > 0` or `security_scan.high > 0` — Critical/High vulnerabilities

> **Note**: L1 retry exhaustion escalates to **L2**, not L3.

**Example**: Semgrep detects a SQL Injection vulnerability (High severity). The pipeline halts immediately and the developer is alerted.

**Why L3**: Code with a broken build or critical security vulnerabilities must never proceed under any circumstances. This is not a problem retries can solve.

---

### L4 — Deploy Gate

Actions that affect production always require human final approval. `is_deploy_request=True` returns L4 immediately, regardless of all other conditions.

**Applies to**:
- Production environment deployments
- Core infrastructure changes (DNS, load balancer, security groups)
- Production DB migrations

**Example**: An agent modifies a Kubernetes manifest and requests deployment. Even with all QA checks passing, human approval is mandatory.

**Why L4**: Production deployments are hard to reverse and directly impact end users. No amount of testing replaces the need for a deliberate human decision to deploy.

---

## Dynamic Guardrails — Automatic Risk Detection

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

---

## SOP Compliance Check

`_check_sop_compliance()` verifies adherence to standard procedures. If `QualityGates.sop_compliance_score` is `None`, the check is skipped (pass). If the score is below `sop_compliance_threshold` (default 70), it escalates to L2.

The SOP score measures adherence to procedures defined in the `.harness/sop/` directory.

---

## Guardrails Integration

In Phase 3, the full guardrails module was integrated with the Human Gate. Guardrails operate before and after LLM calls to proactively block dangerous inputs and outputs.

### InputValidator — Pre-LLM Checks

Inspects agent input before the LLM is called.

| Check | Detects |
|---|---|
| Sensitive data | API keys, AWS keys, private keys, passwords, JWT, credit card numbers, SSN |
| Prompt injection | "ignore instructions", "system override", jailbreak attempts |
| Token limits | Input exceeding `max_input_tokens` |
| Forbidden keywords | Custom forbidden keywords defined in policy |

If sensitive data reaches the LLM, it could be logged or retained in training data. InputValidator blocks this at the source to prevent information leakage.

### OutputValidator — Post-LLM Checks

Inspects LLM responses for dangerous content.

| Check | Detects |
|---|---|
| Dangerous code | `rm -rf`, `DROP TABLE`, `eval()`/`exec()` |
| Security patterns | hardcoded secrets, SQL injection, XSS |
| Hallucination hints | nonexistent stdlib modules, nonexistent methods |

If an agent executes `rm -rf /`, the damage is irreversible. OutputValidator catches dangerous code before it is ever executed.

### TokenBudgetTracker — Token Budget Management

| Item | Description |
|---|---|
| Daily token limit | `daily_token_limit` (default 100,000) |
| Per-agent limit | Maximum token usage per individual agent |
| Cost tracking | Cost calculation based on token usage |
| Warning threshold | Warns at 80% usage (`budget_warn_threshold`) |

Without budget tracking, an agent stuck in an infinite loop could run up costs indefinitely. TokenBudgetTracker prevents this.

### PathGuard — File Path Protection

| Item | Description |
|---|---|
| Always protected | `.env`, `*.pem`, `*.key` files |
| Extra protected | Paths defined in policy's `extra_protected_paths` |
| Config file changes | When `force_human_gate_on_config_change=True`, config file changes force Human Gate |

If an agent accidentally modifies or deletes `.env` or certificate files, it can cause service outages. PathGuard blocks such changes or forces human review.

---

## Guardrails Configuration

Use `GuardrailPolicy` to configure all guardrails from a single place.

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

Option reference:

| Option | Default | Description |
|---|---|---|
| `max_input_tokens` | 32,000 | Maximum input tokens. Inputs exceeding this are rejected |
| `detect_sensitive_data` | True | Auto-detect API keys, passwords, and other sensitive data |
| `detect_prompt_injection` | True | Block prompt injection attempts |
| `detect_dangerous_code` | True | Block dangerous commands (rm -rf, etc.) |
| `detect_security_patterns` | True | Detect hardcoded secrets, SQL injection patterns |
| `daily_token_limit` | 100,000 | Daily token usage limit |
| `budget_warn_threshold` | 0.8 | Warn when 80% of budget is consumed |
| `extra_protected_paths` | [] | Additional paths to protect |
| `force_human_gate_on_config_change` | True | Force Human Gate when config files change |

---

## Observability Integration

Gate decisions are integrated with Archon's tracing system.

- **TracingMiddleware** starts a `gate_span` in the pipeline.
- The gate decision (level and reason) is recorded in the span output.
- All LLM calls during the pipeline are traced with latency, token count, and cost.

This lets you answer questions like "why did this task escalate to L2?" and "how long did the LLM call take?" after the fact. Essential for debugging and optimization.

---

## Self-Healing Integration

When an agent enters an abnormal state, the system attempts automatic recovery. If recovery fails, it escalates to the Human Gate.

### Agent Health Monitoring

`AgentHealthMonitor` continuously tracks each agent's status.

| Status | Description | Action |
|---|---|---|
| HEALTHY | Operating normally | None |
| DEGRADED | Slow responses, intermittent errors | Increased monitoring |
| UNHEALTHY | Repeated errors | `SelfHealer` attempts automatic recovery |
| DEAD | No response or complete failure | **L2_HUMAN escalation** |

### Automatic Recovery Strategies

`SelfHealer` tries these recovery methods in order:

1. **model_downgrade** — switch to a more stable model
2. **agent_reinit** — reinitialize the agent
3. **substitute** — replace with an alternate agent

### HealthWatchdog

Continuously monitors all agents in the background. When a DEAD status is detected, it automatically triggers L2_HUMAN escalation.

---

## Dashboard Integration

Manage gate decisions through the web dashboard.

| Endpoint | Method | Description |
|---|---|---|
| `/api/gates/queue` | GET | List pending gate decisions |
| `/api/gates/{id}/approve` | POST | Approve a gate decision |
| `/api/gates/{id}/reject` | POST | Reject a gate decision |

**WebSocket real-time notifications**: Gate events are pushed via WebSocket in real time. Keep the dashboard open and new L2/L3/L4 events appear instantly.

---

## Evolution Integration

Gate decision history is analyzed to automatically optimize thresholds over time.

- **MetricsCollector** — records every gate decision (level, reason, frequency).
- **PatternAnalyzer** — detects patterns. For example, if L1_REWORK triggers too frequently, it suggests a threshold adjustment.
- **ThresholdTuner** — can auto-adjust values like `review_score_threshold` within safe bounds.

This means the Human Gate becomes more accurate for your project over time. Problems like "calling a human too often" or "auto-passing too much" are solved with data, not guesswork.

---

## Transaction Snapshots

Code state is captured as snapshots before and after agent execution, ensuring safe rollback.

| Timing | Action |
|---|---|
| Before agent execution | `GitExecutor.save_snapshot()` — saves current state as a snapshot |
| On hallucination detection | `rollback_to_snapshot()` — rolls back to the snapshot |
| On AUTO_PASS | `auto_commit()` — validates protected_paths, then auto-commits |

When an agent hallucinates — importing a nonexistent library or generating broken code — the snapshot makes it safe to revert to the previous known-good state.

---

## Self-Correction Flow

A mechanism for automatically fixing format errors in agent output.

1. Triggers when the agent output contains an `<archon-output>` tag but the JSON inside is malformed.
2. `BaseAgent._self_correct_output()` sends a correction prompt to the LLM.
3. After 1 retry attempt, if it still fails, it falls back to raw text.

This handles the occasional case where an LLM breaks JSON formatting. It prevents trivial format errors from crashing the entire pipeline.

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

---

## Testing Gate Decisions

```bash
# Gate decision unit tests
pytest tests/test_gate_evaluator.py -v

# Guardrails tests
pytest tests/test_guardrails.py -v

# Harness integration tests
pytest tests/test_harness.py -v
```

`tests/test_gate_evaluator.py` — gate decision unit tests (11 cases)

`tests/test_guardrails.py` — InputValidator, OutputValidator, TokenBudgetTracker, PathGuard tests

`tests/test_harness.py` — full pipeline integration tests (guardrails + gate + snapshots)

---

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

You can view this package at `/api/gates/queue` on the Dashboard, and act on it via `/api/gates/{id}/approve` or `/api/gates/{id}/reject`.
