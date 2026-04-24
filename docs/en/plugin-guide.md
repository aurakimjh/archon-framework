# Plugin Development Guide

🇰🇷 [한국어](../ko/plugin-guide.md)

> Version: 1.0.0 | Last updated: 2026-04-24

## Overview

Archon provides four extension points.

| Extension point | Method |
|---|---|
| Custom agent | Subclass `BaseAgent` |
| Custom LLM provider | LiteLLM config + vLLM Bridge registration |
| Custom QA tool | Extend or wrap `run_qa_pipeline()` |
| MCP/A2A plugin | Register tools on `MCPServer` / wire `A2ARouter` |

---

## 1. Adding a Custom Agent

### Subclass BaseAgent

All agents must inherit from `BaseAgent` (`src/agents/base.py`) and implement `_build_system_prompt()`.

```python
# src/agents/security.py
from src.agents.base import BaseAgent
from src.orchestrator.handoff import HandoffArtifact
from src.registry.models import AgentRole, ProjectRegistry


class SecurityAgent(BaseAgent):
    """Security audit specialist agent."""

    def __init__(self, a2a_router=None):
        super().__init__(role="security", a2a_router=a2a_router)

    def _build_system_prompt(
        self,
        handoff: HandoffArtifact,
        registry: ProjectRegistry,
    ) -> str:
        project = handoff.project_context
        sop_path = project.sop_path or ".harness/sop/security.md"
        return f"""You are a security auditor for {project.project_name}.
Stack: {project.tech_stack.language} / {project.tech_stack.framework}
SOP: {sop_path}

Review changed files for:
- Authentication/authorization flaws
- Injection vulnerabilities (SQL, XSS, etc.)
- Sensitive data exposure

Return findings in <archon-output> JSON format:
{{
  "summary": "...",
  "changed_files": [],
  "decisions": []
}}"""
```

### Register in the Agent Pool

Add your agent to `AGENT_POOL` in `src/orchestrator/orchestrator.py`.

```python
# orchestrator.py
from src.agents.security import SecurityAgent

AGENT_POOL: dict[str, BaseAgent] = {
    # existing agents...
    "security": SecurityAgent(),
}

# Add to task chain (optional)
DEFAULT_TASK_CHAINS = {
    "backend": ["security", "tester", "docs"],  # backend → security audit → test
    ...
}
```

### Extend AgentRole enum

Add the new role to `src/registry/models.py`.

```python
class AgentRole(StrEnum):
    # existing roles...
    SECURITY = "security"
```

### Configure the Model in Registry

Add the role under `agent_config` in `.harness/registry/my_project.json`.

```json
{
  "agent_config": {
    "security": {
      "model": "claude-sonnet-4-6",
      "max_tokens": 4096,
      "temperature": 0.1
    }
  }
}
```

### Structured Output

When the LLM returns `<archon-output>` JSON, `_parse_structured_output()` parses it automatically.

```python
# Example LLM response
response = """
I reviewed the changed files.

<archon-output>
{
  "summary": "JWT token expiry vulnerability found",
  "changed_files": [
    {"path": "src/auth/jwt.py", "change_type": "modified", "reason": "Fix vulnerability"}
  ],
  "decisions": [
    {"decision": "Blacklist tokens on expiry immediately", "reason": "Prevent session hijacking"}
  ]
}
</archon-output>
"""
```

---

## 2. Adding a Custom LLM Provider

### Add an Ollama Model

Copy `config/litellm_config.yaml.example` and add your model.

```yaml
# config/litellm_config.yaml
model_list:
  - model_name: security-agent
    litellm_params:
      model: ollama/llama3.3:70b
      api_base: http://localhost:11434
      stream: true

  - model_name: backend-agent
    litellm_params:
      model: ollama/deepseek-v3.2:70b
      api_base: http://localhost:11434
```

### Connect a vLLM GPU Worker

Register with `VLLMBridge` and inject into `Orchestrator`.

```python
from src.runtime.vllm_bridge import VLLMBridge, VLLMEndpoint
from src.orchestrator.orchestrator import Orchestrator

bridge = VLLMBridge(timeout=5.0)
bridge.register(VLLMEndpoint(
    name="vllm/security-llm",
    base_url="http://gpu-node-01:8000",
    model_name="meta-llama/Llama-3.3-70B-Instruct",
    gpu_memory_utilization=0.9,
    tensor_parallel_size=2,
    tags=["security"],  # auto-routes to "security" role
))

await bridge.health_check_all()
orch = Orchestrator(registry=registry, vllm_bridge=bridge)
```

### Complexity-based Model Branching

Set `high_complexity_model` in the registry and the Complexity Router selects it automatically.

```json
{
  "agent_config": {
    "backend": {
      "model": "ollama/deepseek-v3.2:7b",
      "high_complexity_model": "ollama/deepseek-v3.2:70b"
    }
  }
}
```

### Connect LM Studio

```yaml
# config/litellm_config.yaml
model_list:
  - model_name: backend-agent
    litellm_params:
      model: openai/deepseek-v3
      api_base: http://localhost:1234/v1
      api_key: "lm-studio"
```

---

## 3. Adding a Custom QA Tool

### Extending the QA Pipeline

Functions in `src/runtime/qa.py` are independently callable. Wrap them or run custom tools before/after.

```python
# my_qa.py
import asyncio
from src.runtime.qa import run_qa_pipeline
from src.orchestrator.handoff import QualityGates


async def run_custom_qa_pipeline(
    project_root: str,
    registry,
) -> QualityGates:
    """Standard QA + custom tools in parallel."""

    standard_task = asyncio.create_task(
        run_qa_pipeline(project_root, registry)
    )
    # Custom tool — e.g. bandit security scan
    custom_task = asyncio.create_task(
        run_bandit_scan(project_root)
    )

    quality, bandit_result = await asyncio.gather(standard_task, custom_task)

    # Merge bandit findings into security_scan
    if bandit_result.high_severity > 0:
        quality.security_scan.high += bandit_result.high_severity

    return quality


async def run_bandit_scan(project_root: str):
    """Run bandit Python security scanner."""
    proc = await asyncio.create_subprocess_exec(
        "bandit", "-r", "src/", "-f", "json", "-q",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=project_root,
    )
    stdout, _ = await proc.communicate()
    # JSON parsing logic...
```

### Injecting SOP Compliance Score

Set `QualityGates.sop_compliance_score` after QA — the gate evaluator picks it up automatically.

```python
quality = await run_qa_pipeline(project_root, registry)

# Compute SOP compliance with a separate tool
sop_score = await evaluate_sop_compliance(
    handoff=handoff,
    sop_path=".harness/sop/backend.md",
)
quality.sop_compliance_score = sop_score  # 0–100

from src.gate.evaluator import evaluate_gate
decision = evaluate_gate(quality, registry.quality_policy)
```

---

## 4. Adding an MCP Plugin

### Register a Custom MCP Tool

Add a handler to `MCPServer`.

```python
from src.mcp.server import MCPServer, ToolDefinition, ToolResult

server = MCPServer()

custom_tool = ToolDefinition(
    name="run_security_audit",
    description="Run a security audit on changed files.",
    input_schema={
        "type": "object",
        "properties": {
            "project_id": {"type": "string"},
            "handoff_id": {"type": "string"},
        },
        "required": ["project_id", "handoff_id"],
    },
)

async def handle_security_audit(args: dict) -> ToolResult:
    project_id = args["project_id"]
    # Security audit logic...
    return ToolResult(success=True, data={"findings": []})

server._handlers["run_security_audit"] = handle_security_audit
```

### A2A-based Agent Collaboration

Use direct agent-to-agent messages to implement complex collaboration patterns.

```python
from src.mcp.a2a import A2ARouter, A2AMessageType, A2APriority

router = A2ARouter()

# Backend Agent requests tests from Tester
backend = BackendAgent(a2a_router=router)
backend.send_a2a(
    to_agent="tester",
    subject="Payment API test request",
    body="POST /api/v2/payments — edge case coverage needed",
    message_type=A2AMessageType.REQUEST,
    priority=A2APriority.HIGH,
    project_id="proj-ecomm",
    task_id="task-payment-002",
)

# Tester Agent receives messages
tester = TesterAgent(a2a_router=router)
messages = tester.receive_a2a()
for msg in messages:
    print(f"[{msg.priority}] {msg.subject}: {msg.body}")
```

---

## 5. Extending Notification Channels

### Implement a Custom Notifier

Subclass `Notifier` to add a new channel.

```python
from src.notifications.base import Notifier, GateEvent
from src.gate.models import GateDecision


class PagerDutyNotifier(Notifier):
    """PagerDuty incident notifications."""

    def __init__(self, integration_key: str):
        self._key = integration_key

    def should_notify(self, event: GateEvent) -> bool:
        # Only L3 and L4 trigger PagerDuty
        return event.gate_decision in (GateDecision.L3_HALT, GateDecision.L4_DEPLOY)

    async def notify(self, event: GateEvent) -> bool:
        import httpx
        payload = {
            "routing_key": self._key,
            "event_action": "trigger",
            "payload": {
                "summary": event.title,
                "severity": event.severity,
                "source": f"archon:{event.project_id}",
                "custom_details": {"trigger_reason": event.trigger_reason},
            },
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://events.pagerduty.com/v2/enqueue",
                json=payload,
            )
        return resp.status_code == 202
```

### Add to CompositeNotifier

```python
from src.notifications.base import CompositeNotifier
from src.notifications.slack import SlackNotifier
from src.notifications.terminal import TerminalNotifier

notifier = CompositeNotifier([
    TerminalNotifier(),
    SlackNotifier(webhook_url="https://hooks.slack.com/..."),
    PagerDutyNotifier(integration_key="your-key"),
])

orch = Orchestrator(registry=registry, notifier=notifier)
```

---

## 6. Customizing Dynamic Guardrails

Adjust `high_risk_paths` and `high_risk_keywords` per project in the Registry.

```python
from src.registry.models import QualityPolicy

policy = QualityPolicy(
    high_risk_paths=[
        "payment", "billing", "auth",         # defaults
        "medical_records", "pii_data",         # healthcare/PII domain
        "nuclear_plant/controls/",             # project-specific
    ],
    high_risk_keywords=[
        "payment", "credential", "deploy",     # defaults
        "patient_data", "ssn", "hipaa",        # domain-specific
    ],
    sop_compliance_threshold=85,               # stricter than default 70
)
```

---

## Related Docs

- [API Reference](api-reference.md)
- [Architecture](architecture.md)
- [Human Gate Design](human-gate.md)
- [Operations Guide](operations-guide.md)
