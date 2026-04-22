# Human Gate Design

> Version: 1.0.0 | Last updated: 2026-04-22

## Overview

The Human Gate is the **decision layer** between automated agent progress and human intervention. It synthesizes QA pipeline results and Review Agent evaluations to determine one of 4 gate levels.

Source code: `src/gate/evaluator.py`, `src/gate/models.py`

## Pipeline Flow

```
Agent work completed
    ↓
Automated QA (lint · build · unit tests · coverage · security scan)
    ↓
Review Agent (Claude Sonnet) — quality · consistency · security · complexity
    ↓
gate_decision
    ↓
┌───────────┬───────────┬───────────┬───────────┐
│ auto_pass │ l1_rework │ l2_human  │ l3_halt   │
│ Auto      │ Agent     │ Developer │ Emergency │
│ commit    │ self-fix  │ notified  │ stop      │
└───────────┴───────────┴───────────┴───────────┘
                                         ↓ (deploy request)
                                    l4_deploy
                                    (always human approval)
```

## Gate Levels

### auto_pass — Automatic Proceed

All conditions met:
- All unit tests pass + coverage >= threshold (default 80%)
- Lint errors 0 · build success · type errors 0
- Security scan: 0 Critical/High
- Cyclomatic complexity <= 10 · function length <= 50 lines
- review_score >= 70

### L1 — Agent Auto-Rework

No human intervention. Agent self-corrects.

Triggers: lint warnings, style violations, coverage 70-79%, minor issues.

**Limit**: Max 3 retries. Escalates to L2 on exhaustion.

### L2 — Human Gate

Affected project paused. Developer notified.

Triggers: architecture violations, DB schema changes, external API integrations, security medium, review_score < 70, L1 retry exhaustion.

### L3 — Emergency Halt

Immediate developer notification. Affected agents stopped.

Triggers: build failure, Critical/High security, agent loops (3+ retries), budget 90%+ exceeded, protected_paths violations, force push attempts.

### L4 — Deploy Gate

Always requires human approval.

Triggers: production deployments, core infrastructure changes, production DB migrations, external service activation.

## Decision Priority

**L4 > L3 > L2 > L1 > auto_pass**

## Tests

`tests/test_gate_evaluator.py` — 11 test cases covering all gate levels.
