# Handoff Artifact Schema

[한국어](../ko/handoff-schema.md)

> Version: 2.0.0 | Last updated: 2026-04-24

## Overview

A Handoff Artifact is the **standard JSON document** that carries context between agents. One is created per handoff and automatically committed to Git.

In Archon, agents are **stateless**. The only way an agent can know about previous work is through this Handoff Artifact. Think of it as the "handover document" between agents.

Source code: `src/orchestrator/handoff.py`

---

## 7-Section Structure

A Handoff Artifact consists of the following 7 sections.

| Section | Role | Required |
|---|---|---|
| envelope | Handoff identification, routing, retry tracking | Yes |
| project_context | Project namespace injected into stateless agents | Yes |
| task | Completed work summary + next agent instructions | Yes |
| artifacts | Changed files + generated outputs | Yes |
| quality_gates | Automated QA results + Review Agent evaluation + gate_decision | Yes |
| human_gate_package | Context for developer when L2+ is triggered | Conditional |
| memory_context | Past patterns and decisions retrieved from Mem0 | Optional |

---

## Lifecycle

The full journey of a Handoff Artifact from creation to final processing. Understanding this flow helps you see when each section gets populated.

```
1. Orchestrator creates the initial HandoffArtifact
   - envelope, project_context, and task sections are populated
        |
        v
2. MemoryStore.inject_memory_context() adds memory_context
   - Searches Mem0 for similar decisions, patterns, and feedback
        |
        v
3. compress_handoff() shrinks the artifact if it exceeds token limits
   - Uses the token_gap parameter for precision truncation (see details below)
        |
        v
4. BaseAgent.execute() processes it and creates an output HandoffArtifact
   - The agent performs work and populates the artifacts section
   - If <archon-output> JSON is malformed, automatic retry kicks in (see details below)
        |
        v
5. QA pipeline fills quality_gates
   - Runs tests, lint, build, security scan, and SOP compliance checks
        |
        v
6. evaluate_gate() determines gate_decision
   - One of: auto_pass / l1_rework / l2_human / l3_halt / l4_deploy
        |
        v
7. GitExecutor auto-commits on AUTO_PASS
   - auto_pass: changes are automatically committed to Git
   - l1_rework: agent is instructed to redo the work
   - l2_human+: human_gate_package is created and sent to the developer
```

---

## Key Concepts

### Precision Truncation with compress_handoff()

The context sent to an agent can exceed the LLM's token limit. The `compress_handoff()` function uses a `token_gap` parameter for precision truncation.

**How it works:**
- `token_gap` means "current token count minus target token count" (e.g., if 2000 tokens over limit, `token_gap=2000`)
- Truncation priority: `memory_context` > `artifacts.generated_docs` > `task.decisions_made` > `task.blockers` (truncated in this order)
- Critical sections (envelope, project_context) are never truncated

**When it runs:** Called automatically by the Orchestrator just before passing the handoff to an agent. You rarely need to call it directly.

```python
# Internal usage example
compressed = compress_handoff(artifact, token_gap=2000)
# Removes low-similarity items from memory_context first to free 2000 tokens
```

### Self-Correction Flow

An agent may produce malformed `<archon-output>` JSON. BaseAgent automatically detects this and **retries once** with a correction prompt.

**How it works:**
1. BaseAgent.execute() parses the `<archon-output>` tag from the agent's response
2. If JSON parsing fails, the original response plus a correction prompt is sent back to the agent
3. If the retry also fails, a `MalformedOutputError` is raised and escalated to L1 rework

**When it runs:** Automatically, no configuration needed. Note that `envelope.retry_count` tracks L1 rework retries separately from this self-correction retry.

### GitExecutor Snapshots

Before agent execution, GitExecutor calls `save_snapshot()` to preserve the working tree. If the agent is detected to have hallucinated (produced invalid code), `rollback_to_snapshot()` restores the pre-execution state.

**How it works:**
1. Before agent execution: `save_snapshot()` saves the current Git working tree state
2. Agent execution completes
3. QA pipeline detects hallucination (e.g., calling non-existent APIs, invalid imports)
4. `rollback_to_snapshot()` restores the working tree to the snapshot point
5. L1 retry proceeds

**When it runs:** Automatically. This mechanism ensures the project is safely protected even if an agent generates bad code.

---

## Section Details

### envelope

Manages the unique identifier, sender/receiver agents, and retry count for a handoff. Think of it as the "cover page" of every handoff.

| Field | Type | Default | Description |
|---|---|---|---|
| `handoff_id` | `str` | (auto-generated) | Unique handoff identifier. `hf_` prefix + timestamp + random hash |
| `schema_version` | `str` | `"1.1.0"` | Handoff Artifact schema version |
| `created_at` | `str` (ISO 8601) | (auto-generated) | Creation timestamp |
| `expires_at` | `str` (ISO 8601) \| `null` | `null` | Expiration timestamp. null means no expiration |
| `from_agent` | `str` | (required) | Sender agent role name (e.g., `"backend"`) |
| `to_agent` | `str` | (required) | Receiver agent role name (e.g., `"reviewer"`) |
| `retry_count` | `int` | `0` | L1 rework retry count. Escalates to L2 when exceeding `max_retry_before_escalation` |
| `parent_handoff_id` | `str` \| `null` | `null` | Previous handoff ID, used for chain tracking |

```json
{
  "handoff_id": "hf_20260413a3b4c5",
  "schema_version": "1.1.0",
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

Since agents are stateless, this section injects project information. It is the only way an agent knows which project, tech stack, and branch it is working on.

| Field | Type | Default | Description |
|---|---|---|---|
| `project_id` | `str` | (required) | Unique project identifier |
| `project_name` | `str` | (required) | Human-readable project name |
| `git_repo` | `str` | (required) | Git repository URL |
| `git_branch` | `str` | (required) | Agent working branch |
| `base_commit_sha` | `str` | (required) | Base commit SHA for the work |
| `sop_path` | `str` \| `null` | `null` | Path to the SOP file this agent should follow |
| `tech_stack` | `object` | `{}` | Tech stack information (language, framework, database, runtime, etc.) |
| `priority` | `str` | `"medium"` | Priority level: `"low"` \| `"medium"` \| `"high"` \| `"critical"` |

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

Contains the completed work summary, decisions made, blockers, and instructions for the next agent.

| Field | Type | Default | Description |
|---|---|---|---|
| `task_id` | `str` | (required) | Unique task identifier |
| `completed_summary` | `str` | (required) | One-line summary of completed work |
| `decisions_made` | `list[Decision]` | `[]` | List of decisions the agent made. Each item has `decision`, `reason`, `alternatives_considered` |
| `blockers` | `list[Blocker]` | `[]` | List of blockers. Each item has `issue`, `impact`, `suggested_resolution` |
| `next_instructions` | `str` | (required) | Instructions for the next agent |
| `next_agent_context` | `object` \| `null` | `null` | Additional context for the next agent (free-form JSON) |

```json
{
  "task_id": "task_payment_api_v2",
  "completed_summary": "Implemented 3 payment API v2 endpoints",
  "decisions_made": [
    {
      "decision": "UUID v4 for idempotency key",
      "reason": "Prevents duplicate payments, Stripe recommended approach",
      "alternatives_considered": ["timestamp-based", "hash-based"]
    }
  ],
  "blockers": [
    {
      "issue": "Refund API spec not finalized",
      "impact": "medium",
      "suggested_resolution": "L2 Human Gate -- confirm business logic"
    }
  ],
  "next_instructions": "Write unit tests for payment API. Coverage >= 85%.",
  "next_agent_context": { "mock_stripe": true }
}
```

---

### artifacts

Records changed files, generated documents, and dependency changes.

| Field | Type | Default | Description |
|---|---|---|---|
| `changed_files` | `list[ChangedFile]` | `[]` | List of changed files (see ChangedFile below) |
| `generated_docs` | `list[str]` | `[]` | List of generated document file paths |
| `dependency_changes` | `list[DependencyChange]` | `[]` | List of dependency changes |
| `config_changes` | `list[str]` | `[]` | List of changed config file paths |

**ChangedFile object:**

Information about an individual file changed by the agent.

| Field | Type | Default | Description |
|---|---|---|---|
| `path` | `str` | (required) | File path relative to project root |
| `change_type` | `str` | (required) | Type of change. One of the 3 values below |
| `reason` | `str` \| `null` | `null` | Explanation of why the file was changed |

`change_type` enum values:
- `"added"` -- A newly created file
- `"modified"` -- An existing file was modified
- `"deleted"` -- An existing file was deleted

```json
{
  "changed_files": [
    { "path": "src/payments/payments.controller.ts", "change_type": "added", "reason": "Payment API controller" },
    { "path": "src/payments/payments.service.ts", "change_type": "added", "reason": "Payment business logic" },
    { "path": "src/app.module.ts", "change_type": "modified", "reason": "Register PaymentsModule" },
    { "path": "src/payments/old-handler.ts", "change_type": "deleted", "reason": "Remove v1 legacy handler" }
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

Combines automated QA pipeline results with the Review Agent's evaluation. The `gate_decision` is determined based on these results.

| Field | Type | Default | Description |
|---|---|---|---|
| `test_results` | `TestResults` | (required) | Test execution results |
| `test_results.unit_passed` | `int` | `0` | Number of passed unit tests |
| `test_results.unit_failed` | `int` | `0` | Number of failed unit tests |
| `test_results.integration_passed` | `int` | `0` | Number of passed integration tests |
| `test_results.coverage_percent` | `float` | `0.0` | Test coverage percentage |
| `lint_result` | `str` | (required) | Lint result: `"passed"` \| `"failed"` |
| `build_result` | `str` | (required) | Build result: `"passed"` \| `"failed"` |
| `security_scan` | `SecurityScan` | (required) | Security scan results |
| `security_scan.tool` | `str` | (required) | Security scan tool used (e.g., `"semgrep"`) |
| `security_scan.critical` | `int` | `0` | Number of critical vulnerabilities |
| `security_scan.high` | `int` | `0` | Number of high vulnerabilities |
| `security_scan.medium` | `int` | `0` | Number of medium vulnerabilities |
| `security_scan.low` | `int` | `0` | Number of low vulnerabilities |
| `review_score` | `int` | (required) | Score given by the Review Agent (0-100) |
| `review_flags` | `list[ReviewFlag]` | `[]` | List of issues found by the Review Agent |
| `sop_compliance_score` | `int` \| `null` | `null` | SOP compliance score (0-100). `null` means the SOP check was not performed |
| `gate_decision` | `str` | (required) | Final gate decision |

**sop_compliance_score details:**
- Integer in the range `0` to `100`
- `null` means the SOP file was missing or the SOP check was skipped
- Falls below `quality_policy.sop_compliance_threshold` (default 70) triggers L1 rework

**gate_decision enum values:**
- `"auto_pass"` -- All quality criteria met. GitExecutor auto-commits the changes
- `"l1_rework"` -- Agent is instructed to redo the work (test failures, score below threshold, etc.)
- `"l2_human"` -- Developer review required (external API integration, schema changes, etc.)
- `"l3_halt"` -- Immediate halt (critical security vulnerabilities, etc.)
- `"l4_deploy"` -- Triggers the deployment pipeline

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
      "detail": "New Stripe integration detected"
    }
  ],
  "sop_compliance_score": 85,
  "gate_decision": "l2_human"
}
```

---

### human_gate_package

Included only when L2 or above is triggered. Provides the developer with the necessary decision context and options.

| Field | Type | Default | Description |
|---|---|---|---|
| `gate_level` | `str` | (required) | Triggered gate level: `"l2_human"` \| `"l3_halt"` |
| `trigger_reason` | `str` | (required) | Explanation of why the gate was triggered |
| `required_decision` | `str` | (required) | The question being asked of the developer |
| `decision_options` | `list[DecisionOption]` | (required) | List of available options |
| `decision_options[].option` | `str` | (required) | Option description |
| `decision_options[].next_action` | `str` | (required) | What happens if this option is selected |
| `decision_options[].risk` | `str` | (required) | Risk level: `"none"` \| `"low"` \| `"medium"` \| `"high"` |
| `estimated_review_time` | `str` \| `null` | `null` | Estimated time for the developer to review |
| `paused_agents` | `list[str]` | `[]` | List of agent roles paused while waiting for the decision |

```json
{
  "gate_level": "l2_human",
  "trigger_reason": "New external API integration detected (Stripe)",
  "required_decision": "Proceed with Stripe production integration?",
  "decision_options": [
    {
      "option": "Proceed with production",
      "next_action": "Instruct DevOps agent to set up environment variables",
      "risk": "low"
    },
    {
      "option": "Keep mock for now",
      "next_action": "Instruct Tester agent to continue mock-based testing",
      "risk": "none"
    }
  ],
  "estimated_review_time": "5 minutes",
  "paused_agents": ["tester", "devops"]
}
```

---

### memory_context

Contains past patterns, decision history, and error records automatically retrieved from Mem0. Populated by `MemoryStore.inject_memory_context()` during Lifecycle step 2.

| Field | Type | Default | Description |
|---|---|---|---|
| `relevant_past_decisions` | `list[PastDecision]` | `[]` | List of similar past decisions |
| `relevant_past_decisions[].similarity` | `float` | (required) | Cosine similarity score (0.0 to 1.0) |
| `relevant_past_decisions[].project` | `str` | (required) | Project ID where the decision was made |
| `relevant_past_decisions[].decision` | `str` | (required) | The past decision content |
| `relevant_past_decisions[].outcome` | `str` | (required) | Decision outcome: `"success"` \| `"failure"` \| `"unknown"` |
| `known_patterns` | `list[Pattern]` | `[]` | List of applicable code patterns |
| `error_history` | `list[ErrorRecord]` | `[]` | Related past error records |
| `human_feedback` | `list[Feedback]` | `[]` | Developer feedback history |

```json
{
  "relevant_past_decisions": [
    {
      "similarity": 0.92,
      "project": "proj_ecomm_v1",
      "decision": "Auto-retry payment 3 times then notify",
      "outcome": "success"
    }
  ],
  "known_patterns": [
    {
      "pattern": "Repository Pattern",
      "reason": "Standard DB access pattern",
      "example_file": "src/users/users.repository.ts"
    }
  ],
  "error_history": [],
  "human_feedback": [
    {
      "date": "2026-04-10",
      "decision": "Always mock external payment APIs first",
      "applies_to": "payment_integration"
    }
  ]
}
```

---

## Pydantic Model Reference

Full model definitions: `src/orchestrator/handoff.py`

| Model | Description | Required |
|---|---|---|
| `HandoffArtifact` | Root model (contains all 7 sections) | -- |
| `Envelope` | Handoff identification and routing | Yes |
| `ProjectContext` | Project namespace | Yes |
| `Task` | Work summary and instructions | Yes |
| `Artifacts` | Changed files and outputs | Yes |
| `ChangedFile` | Individual file change info | Child of Artifacts |
| `QualityGates` | QA results and gate decision | Yes |
| `HumanGatePackage` | Developer decision request package | Conditional |
| `MemoryContext` | Past memory injection context | Optional |
