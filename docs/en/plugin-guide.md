# Plugin & Extension Development Guide

[Korean](../ko/plugin-guide.md)

> Version: 2.0.0 | Last updated: 2026-04-24

## Overview

Archon is designed to be extended at every layer. This guide covers **all 14 extension points** with step-by-step instructions and complete, copy-pasteable examples.

| # | Extension Point | Method | Section |
|---|---|---|---|
| 1 | Custom Agent | Subclass `BaseAgent` | [Link](#1-custom-agent) |
| 2 | Custom LLM Provider | vLLM / Ollama Bridge | [Link](#2-custom-llm-provider) |
| 3 | Custom QA Tool | Extend `run_qa_pipeline()` | [Link](#3-custom-qa-tool) |
| 4 | Custom MCP Tool | `MCPServer.register_tool()` | [Link](#4-custom-mcp-tool) |
| 5 | Custom Notifier | Subclass `Notifier` ABC | [Link](#5-custom-notifier) |
| 6 | Custom Guardrail | `GuardrailPolicy` config | [Link](#6-custom-guardrail) |
| 7 | Custom Tracing Backend | Subclass `ArchonTracer` | [Link](#7-custom-tracing-backend) |
| 8 | Custom Benchmark Task | `BenchmarkTask` model | [Link](#8-custom-benchmark-task) |
| 9 | Custom Evolution Analyzer | Subclass `PatternAnalyzer` | [Link](#9-custom-evolution-analyzer) |
| 10 | Custom Health Recovery Strategy | `SelfHealer` + `HealthWatchdog` | [Link](#10-custom-health-recovery-strategy) |
| 11 | Custom Dashboard Widget | `DashboardRoutes` + WebSocket | [Link](#11-custom-dashboard-widget) |
| 12 | Ollama Model Configuration | `OllamaBridge` | [Link](#12-ollama-model-configuration) |
| 13 | KubeRay Cluster Configuration | `KubeRayConfig` | [Link](#13-kuberay-cluster-configuration) |
| 14 | Hybrid Cloud Strategy | `HybridConfig` | [Link](#14-hybrid-cloud-strategy) |

---

## 1. Custom Agent

### When to Use

You need an agent with domain-specific behavior that the built-in roles (backend, frontend, tester, docs, etc.) do not cover -- for example, a security auditor, a database migration specialist, or a compliance checker.

### Step-by-step

1. Create a new file under `src/agents/`.
2. Subclass `BaseAgent` and implement `_build_system_prompt()`.
3. Add the role to the `AgentRole` enum in `src/registry/models.py`.
4. Register the agent in `AGENT_POOL` in `src/orchestrator/orchestrator.py`.
5. Configure the model in your project's registry JSON.

### Complete Example

```python
# src/agents/security.py
from src.agents.base import BaseAgent
from src.orchestrator.handoff import HandoffArtifact
from src.registry.models import ProjectRegistry


class SecurityAgent(BaseAgent):
    """Security audit specialist agent."""

    def __init__(self, a2a_router=None):
        super().__init__(
            role="security",
            a2a_router=a2a_router,
            # Phase 3 params (all optional)
            tracing_middleware=None,       # auto-detected from Orchestrator
            guardrail_policy=None,         # falls back to registry default
            token_budget=8192,             # max tokens per turn
            health_monitor=None,           # injected by Orchestrator
            diagnostician=None,            # injected by Orchestrator
        )

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

Register the role enum:

```python
# src/registry/models.py
class AgentRole(StrEnum):
    # existing roles...
    SECURITY = "security"
```

Register in the agent pool:

```python
# src/orchestrator/orchestrator.py
from src.agents.security import SecurityAgent

AGENT_POOL: dict[str, BaseAgent] = {
    # existing agents...
    "security": SecurityAgent(),
}

DEFAULT_TASK_CHAINS = {
    "backend": ["security", "tester", "docs"],
}
```

Configure the model in registry JSON:

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

### Self-correction

When the LLM returns an `<archon-output>` tagged response, `_parse_structured_output()` handles parsing automatically. If the JSON is malformed, the base class triggers a self-correction loop that asks the LLM to fix its output -- no extra code needed on your side.

### Testing

```python
import pytest
from src.agents.security import SecurityAgent

@pytest.fixture
def agent():
    return SecurityAgent()

def test_system_prompt_contains_stack(agent, sample_handoff, sample_registry):
    prompt = agent._build_system_prompt(sample_handoff, sample_registry)
    assert "security auditor" in prompt.lower()
    assert sample_handoff.project_context.tech_stack.language in prompt
```

---

## 2. Custom LLM Provider

### When to Use

You want to connect a self-hosted model (vLLM, Ollama, LM Studio) or add a new inference backend to the routing chain.

### Routing Chain

Archon resolves models in this order (configurable per project):

```
vLLM Bridge --> Ollama Bridge --> LiteLLM default
```

If a vLLM endpoint tagged for the requested role is healthy, it is used. Otherwise Archon falls back to Ollama, then to the LiteLLM default.

### Step-by-step: vLLM Bridge

1. Create a `VLLMEndpoint` with the GPU worker URL.
2. Register it with `VLLMBridge`.
3. Run health checks.
4. Inject the bridge into `Orchestrator`.

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

### Step-by-step: Ollama Bridge

1. Create an `OllamaEndpoint` with tags for role matching.
2. Register it with `OllamaBridge`.
3. Optionally pull the model automatically.

```python
from src.runtime.ollama_bridge import OllamaBridge, OllamaEndpoint

bridge = OllamaBridge(base_url="http://localhost:11434")
bridge.register(OllamaEndpoint(
    name="ollama/deepseek",
    model_name="deepseek-v3.2:70b",
    tags=["backend", "code"],
    num_gpu=1,
    keep_alive="10m",
))

# Pull model if not already available
await bridge.pull_model("deepseek-v3.2:70b")

# Health check
await bridge.health_check_all()
orch = Orchestrator(registry=registry, ollama_bridge=bridge)
```

### LiteLLM Config (Ollama or LM Studio)

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
      model: openai/deepseek-v3
      api_base: http://localhost:1234/v1
      api_key: "lm-studio"
```

### Complexity-based Model Branching

Set `high_complexity_model` in the registry and the Complexity Router picks the right model:

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

### Testing

```python
@pytest.mark.asyncio
async def test_vllm_health_check():
    bridge = VLLMBridge(timeout=2.0)
    bridge.register(VLLMEndpoint(
        name="test-endpoint",
        base_url="http://localhost:8000",
        model_name="test-model",
        tags=["test"],
    ))
    results = await bridge.health_check_all()
    assert results["test-endpoint"].healthy is True
```

---

## 3. Custom QA Tool

### When to Use

You want to add a security scanner (bandit, semgrep), a custom lint rule, or a domain-specific quality check to the pipeline.

### Step-by-step

1. Write an async function that runs your tool.
2. Wrap `run_qa_pipeline()` to run both in parallel.
3. Merge results into `QualityGates`.

### Complete Example

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
    custom_task = asyncio.create_task(
        run_bandit_scan(project_root)
    )

    quality, bandit_result = await asyncio.gather(standard_task, custom_task)

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
    # Parse JSON result...
```

### Injecting SOP Compliance Score

```python
quality = await run_qa_pipeline(project_root, registry)

sop_score = await evaluate_sop_compliance(
    handoff=handoff,
    sop_path=".harness/sop/backend.md",
)
quality.sop_compliance_score = sop_score  # 0-100

from src.gate.evaluator import evaluate_gate
decision = evaluate_gate(quality, registry.quality_policy)
```

### Testing

```python
@pytest.mark.asyncio
async def test_custom_qa_pipeline(tmp_path):
    quality = await run_custom_qa_pipeline(str(tmp_path), mock_registry)
    assert quality.security_scan is not None
```

---

## 4. Custom MCP Tool

### When to Use

You want to expose a new capability to the LLM via the Model Context Protocol, or wire up agent-to-agent messaging.

### Step-by-step

1. Define a `ToolDefinition` with a JSON schema.
2. Write an async handler function.
3. Register it on `MCPServer`.

### Complete Example

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
    # Your audit logic here...
    return ToolResult(success=True, data={"findings": []})


server.register_tool(custom_tool, handle_security_audit)
```

### A2A Agent Collaboration

```python
from src.mcp.a2a import A2ARouter, A2AMessageType, A2APriority

router = A2ARouter()

# Backend Agent requests tests from Tester
backend = BackendAgent(a2a_router=router)
backend.send_a2a(
    to_agent="tester",
    subject="Payment API test request",
    body="POST /api/v2/payments -- edge case coverage needed",
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

### Testing

```python
@pytest.mark.asyncio
async def test_mcp_tool():
    result = await handle_security_audit({"project_id": "test", "handoff_id": "h1"})
    assert result.success is True
```

---

## 5. Custom Notifier

### When to Use

You want gate decisions delivered to a channel beyond the built-in terminal and Slack notifiers -- for example, PagerDuty, Discord, email, or a custom webhook.

### Step-by-step

1. Subclass `Notifier` and implement `should_notify()` and `notify()`.
2. Add your notifier to a `CompositeNotifier`.
3. Inject the composite into `Orchestrator`.

### Complete Example: PagerDuty

```python
from src.notifications.base import Notifier, GateEvent
from src.gate.models import GateDecision


class PagerDutyNotifier(Notifier):
    """PagerDuty incident notifications."""

    def __init__(self, integration_key: str):
        self._key = integration_key

    def should_notify(self, event: GateEvent) -> bool:
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

### Complete Example: Discord

```python
class DiscordNotifier(Notifier):
    """Discord webhook notifications."""

    def __init__(self, webhook_url: str):
        self._url = webhook_url

    def should_notify(self, event: GateEvent) -> bool:
        return True  # notify on every gate event

    async def notify(self, event: GateEvent) -> bool:
        import httpx
        embed = {
            "title": event.title,
            "description": event.trigger_reason,
            "color": 0xFF0000 if event.gate_decision == GateDecision.L3_HALT else 0x00FF00,
            "fields": [
                {"name": "Project", "value": event.project_id, "inline": True},
                {"name": "Decision", "value": event.gate_decision.value, "inline": True},
            ],
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(self._url, json={"embeds": [embed]})
        return resp.status_code == 204
```

### Register with CompositeNotifier

```python
from src.notifications.base import CompositeNotifier
from src.notifications.slack import SlackNotifier
from src.notifications.terminal import TerminalNotifier

notifier = CompositeNotifier([
    TerminalNotifier(),
    SlackNotifier(webhook_url="https://hooks.slack.com/..."),
    PagerDutyNotifier(integration_key="your-key"),
    DiscordNotifier(webhook_url="https://discord.com/api/webhooks/..."),
])

orch = Orchestrator(registry=registry, notifier=notifier)
```

### Testing

```python
@pytest.mark.asyncio
async def test_pagerduty_notifier(httpx_mock):
    httpx_mock.add_response(status_code=202)
    notifier = PagerDutyNotifier(integration_key="test-key")
    result = await notifier.notify(sample_gate_event)
    assert result is True
```

---

## 6. Custom Guardrail

### When to Use

You need project-specific safety rules: forbidden keywords, protected file paths, or custom config file patterns that trigger stricter review.

### Step-by-step

1. Create a `GuardrailPolicy` with your custom rules.
2. Optionally add `forbidden_keywords`, `extra_protected_paths`, or `config_file_patterns`.
3. Attach to registry or inject into the agent.

### Complete Example

```python
from src.guardrails.policy import GuardrailPolicy

policy = GuardrailPolicy(
    # Files that always trigger human review
    high_risk_paths=[
        "payment", "billing", "auth",          # defaults
        "medical_records", "pii_data",          # healthcare domain
        "nuclear_plant/controls/",              # project-specific
    ],
    # Keywords that escalate gate level
    high_risk_keywords=[
        "payment", "credential", "deploy",      # defaults
        "patient_data", "ssn", "hipaa",         # domain-specific
    ],
    # Custom forbidden keywords -- agent output containing these is blocked
    forbidden_keywords=[
        "DROP TABLE", "rm -rf /", "eval(",
        "hardcoded_api_key",
    ],
    # Additional protected paths beyond high_risk_paths
    extra_protected_paths=[
        "infrastructure/terraform/",
        "k8s/production/",
        ".github/workflows/",
    ],
    # Patterns that identify config files (triggers config-change guardrail)
    config_file_patterns=[
        "*.yaml", "*.yml", "*.toml",           # defaults
        "*.hcl", "*.tf",                        # Terraform
        "Tiltfile",                             # Tilt
    ],
    sop_compliance_threshold=85,                # stricter than default 70
)
```

### Attach to Registry

```json
{
  "quality_policy": {
    "high_risk_paths": ["payment", "billing", "auth", "medical_records"],
    "high_risk_keywords": ["payment", "credential", "patient_data"],
    "sop_compliance_threshold": 85
  }
}
```

### Testing

```python
def test_guardrail_blocks_forbidden_keyword():
    policy = GuardrailPolicy(forbidden_keywords=["DROP TABLE"])
    result = policy.check_output("Let's run DROP TABLE users;")
    assert result.blocked is True
    assert "DROP TABLE" in result.reason
```

---

## 7. Custom Tracing Backend

### When to Use

You want to send trace and span data to an observability platform beyond the built-in options (console, JSON file) -- for example, Datadog, New Relic, or Jaeger.

### Step-by-step

1. Subclass `ArchonTracer`.
2. Implement the four required methods: `start_trace()`, `start_span()`, `end_span()`, `record_llm_call()`.
3. Register via `CompositeTracer` or `create_tracer_from_config()`.

### Complete Example: Datadog Tracer

```python
from src.tracing.base import ArchonTracer, TraceContext, SpanContext
from ddtrace import tracer as dd_tracer


class DatadogTracer(ArchonTracer):
    """Send Archon traces to Datadog APM."""

    def __init__(self, service_name: str = "archon"):
        self._service = service_name

    def start_trace(self, name: str, metadata: dict | None = None) -> TraceContext:
        span = dd_tracer.trace(
            name,
            service=self._service,
            resource=name,
        )
        if metadata:
            for k, v in metadata.items():
                span.set_tag(k, v)
        return TraceContext(trace_id=str(span.trace_id), root_span=span)

    def start_span(
        self, trace_ctx: TraceContext, name: str, metadata: dict | None = None
    ) -> SpanContext:
        span = dd_tracer.trace(name, child_of=trace_ctx.root_span)
        if metadata:
            for k, v in metadata.items():
                span.set_tag(k, v)
        return SpanContext(span_id=str(span.span_id), span=span)

    def end_span(self, span_ctx: SpanContext, status: str = "ok") -> None:
        span_ctx.span.set_tag("status", status)
        span_ctx.span.finish()

    def record_llm_call(
        self,
        span_ctx: SpanContext,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        latency_ms: float,
    ) -> None:
        span_ctx.span.set_tag("llm.model", model)
        span_ctx.span.set_metric("llm.prompt_tokens", prompt_tokens)
        span_ctx.span.set_metric("llm.completion_tokens", completion_tokens)
        span_ctx.span.set_metric("llm.latency_ms", latency_ms)
```

### Register the Tracer

```python
from src.tracing.composite import CompositeTracer
from src.tracing.console import ConsoleTracer

tracer = CompositeTracer([
    ConsoleTracer(),           # local dev output
    DatadogTracer("archon"),   # production observability
])

orch = Orchestrator(registry=registry, tracer=tracer)
```

Or via config:

```yaml
# config/tracing.yaml
tracers:
  - type: console
  - type: custom
    class: my_tracers.DatadogTracer
    params:
      service_name: archon
```

### Testing

```python
def test_datadog_tracer_starts_trace():
    tracer = DatadogTracer("test-service")
    ctx = tracer.start_trace("test-op", metadata={"env": "test"})
    assert ctx.trace_id is not None
```

---

## 8. Custom Benchmark Task

### When to Use

You want to evaluate agent performance on domain-specific prompts -- for example, testing whether the backend agent correctly generates FastAPI endpoints or whether the security agent catches known vulnerabilities.

### Step-by-step

1. Define `BenchmarkTask` objects with expected keywords and patterns.
2. Pass them to `BenchmarkRunner.run_suite()`.
3. Optionally customize scorer weights.

### Complete Example

```python
from src.benchmark.models import BenchmarkTask
from src.benchmark.runner import BenchmarkRunner

# Define custom tasks
tasks = [
    BenchmarkTask(
        task_id="custom-api-test",
        role="backend",
        prompt="Write a FastAPI endpoint for user registration with email validation.",
        expected_keywords=["@app.post", "async def", "Pydantic", "EmailStr"],
        expected_patterns=[
            r"class\s+\w+\(BaseModel\)",          # Pydantic model
            r"async\s+def\s+\w+\(.+\)",            # async handler
        ],
    ),
    BenchmarkTask(
        task_id="security-xss-check",
        role="security",
        prompt="Review this template for XSS vulnerabilities: {{ user_input }}",
        expected_keywords=["XSS", "escape", "sanitize"],
        expected_patterns=[r"(escape|sanitize|bleach|markupsafe)"],
    ),
]

# Run the suite
runner = BenchmarkRunner(registry=registry)
results = await runner.run_suite(
    tasks=tasks,
    scorer_weights={
        "keyword_match": 0.4,
        "pattern_match": 0.3,
        "structure_valid": 0.2,
        "latency": 0.1,
    },
)

# Inspect results
for r in results:
    print(f"{r.task_id}: score={r.total_score:.2f}, latency={r.latency_ms:.0f}ms")
```

### Testing

```python
@pytest.mark.asyncio
async def test_benchmark_runner(mock_registry):
    task = BenchmarkTask(
        task_id="test-task",
        role="backend",
        prompt="Hello",
        expected_keywords=["hello"],
    )
    runner = BenchmarkRunner(registry=mock_registry)
    results = await runner.run_suite(tasks=[task])
    assert len(results) == 1
    assert 0.0 <= results[0].total_score <= 1.0
```

---

## 9. Custom Evolution Analyzer

### When to Use

You want to detect performance drift or behavioral changes in agents over time, and automatically suggest tuning actions.

### Step-by-step

1. Subclass `PatternAnalyzer`.
2. Override `analyze()` to detect custom drift patterns.
3. Return `TuningAction` objects with recommended changes.
4. Optionally implement `on_policy_updated()` for persistent changes.

### Complete Example

```python
from src.evolution.analyzer import PatternAnalyzer, AnalysisResult
from src.evolution.models import TuningAction, TuningActionType


class LatencyDriftAnalyzer(PatternAnalyzer):
    """Detect when agent response latency drifts above acceptable thresholds."""

    def __init__(self, threshold_ms: float = 5000.0):
        self._threshold = threshold_ms

    def analyze(self, history: list[dict]) -> AnalysisResult:
        recent = history[-10:]  # last 10 runs
        avg_latency = sum(h["latency_ms"] for h in recent) / len(recent)

        actions = []
        if avg_latency > self._threshold:
            actions.append(TuningAction(
                action_type=TuningActionType.SWITCH_MODEL,
                reason=f"Avg latency {avg_latency:.0f}ms exceeds {self._threshold:.0f}ms",
                params={"fallback_to": "smaller_model"},
            ))

        return AnalysisResult(
            drift_detected=len(actions) > 0,
            actions=actions,
            summary=f"Avg latency: {avg_latency:.0f}ms",
        )

    def on_policy_updated(self, old_policy, new_policy) -> None:
        """Called when a tuning action is applied. Use for logging or persistence."""
        print(f"Policy updated: {old_policy} -> {new_policy}")
```

### Register the Analyzer

```python
from src.evolution.engine import EvolutionEngine

engine = EvolutionEngine(registry=registry)
engine.add_analyzer(LatencyDriftAnalyzer(threshold_ms=3000.0))

# Run analysis
result = await engine.evolve()
for action in result.actions:
    print(f"Recommended: {action.action_type} -- {action.reason}")
```

### Testing

```python
def test_latency_drift_detected():
    analyzer = LatencyDriftAnalyzer(threshold_ms=1000.0)
    history = [{"latency_ms": 2000.0}] * 10
    result = analyzer.analyze(history)
    assert result.drift_detected is True
    assert result.actions[0].action_type == TuningActionType.SWITCH_MODEL
```

---

## 10. Custom Health Recovery Strategy

### When to Use

You want to define custom recovery actions when agents or infrastructure components become unhealthy, or route alerts to external systems like PagerDuty or Opsgenie.

### Step-by-step

1. Configure `SelfHealer` with a custom `HealingConfig`.
2. Define recovery actions for specific failure types.
3. Add alerter callbacks to `HealthWatchdog`.

### Complete Example

```python
from src.health.healer import SelfHealer, HealingConfig, RecoveryAction
from src.health.watchdog import HealthWatchdog, WatchdogAlert


# Custom healing config
config = HealingConfig(
    max_retries=3,
    retry_delay_seconds=5.0,
    escalation_threshold=2,  # escalate after 2 failed recoveries
    recovery_actions={
        "llm_timeout": RecoveryAction(
            action="switch_model",
            params={"fallback": "ollama/llama3.3:7b"},
        ),
        "memory_overflow": RecoveryAction(
            action="restart_worker",
            params={"grace_period_seconds": 10},
        ),
        "gpu_oom": RecoveryAction(
            action="reduce_batch_size",
            params={"factor": 0.5},
        ),
    },
)

healer = SelfHealer(config=config)


# Custom alerter callback
async def pagerduty_alert(alert: WatchdogAlert) -> None:
    """Send critical alerts to PagerDuty."""
    import httpx
    async with httpx.AsyncClient() as client:
        await client.post(
            "https://events.pagerduty.com/v2/enqueue",
            json={
                "routing_key": "your-integration-key",
                "event_action": "trigger",
                "payload": {
                    "summary": f"Archon: {alert.component} - {alert.message}",
                    "severity": alert.severity,
                    "source": "archon-health-watchdog",
                },
            },
        )


# Wire it up
watchdog = HealthWatchdog(healer=healer, check_interval_seconds=30.0)
watchdog.add_alerter(pagerduty_alert)

# Start monitoring (runs in background)
await watchdog.start()
```

### Testing

```python
@pytest.mark.asyncio
async def test_healer_switches_model():
    config = HealingConfig(
        recovery_actions={
            "llm_timeout": RecoveryAction(
                action="switch_model",
                params={"fallback": "test-model"},
            ),
        },
    )
    healer = SelfHealer(config=config)
    result = await healer.recover("llm_timeout")
    assert result.action_taken == "switch_model"
```

---

## 11. Custom Dashboard Widget

### When to Use

You want to add custom monitoring views, project-specific metrics, or live data feeds to the Archon web dashboard.

### Step-by-step

1. Add a route to `DashboardRoutes` for your data endpoint.
2. Use `WebSocketManager` to broadcast real-time events.
3. Place static files (HTML/JS/CSS) in `src/dashboard/static/`.

### Complete Example: Custom Metrics Endpoint

```python
from src.dashboard.routes import DashboardRoutes
from src.dashboard.websocket import WebSocketManager
from fastapi import APIRouter

router = APIRouter()


@router.get("/api/custom/agent-performance")
async def get_agent_performance():
    """Return custom agent performance metrics."""
    return {
        "agents": {
            "backend": {"avg_latency_ms": 1200, "success_rate": 0.95},
            "security": {"avg_latency_ms": 800, "success_rate": 0.99},
        },
    }


# Register with DashboardRoutes
dashboard = DashboardRoutes()
dashboard.include_router(router, prefix="/custom")
```

### Broadcasting Real-time Events

```python
from src.dashboard.websocket import WebSocketManager

ws_manager = WebSocketManager()


async def on_agent_complete(agent_role: str, result: dict):
    """Broadcast agent completion to all connected dashboard clients."""
    await ws_manager.broadcast({
        "event": "agent_complete",
        "data": {
            "role": agent_role,
            "success": result["success"],
            "latency_ms": result["latency_ms"],
        },
    })
```

### Static Files

Place your custom widget HTML in `src/dashboard/static/`:

```
src/dashboard/static/
  widgets/
    agent-performance.html
    agent-performance.js
    agent-performance.css
```

### Testing

```python
from fastapi.testclient import TestClient

def test_custom_dashboard_endpoint(app):
    client = TestClient(app)
    resp = client.get("/custom/api/custom/agent-performance")
    assert resp.status_code == 200
    assert "agents" in resp.json()
```

---

## 12. Ollama Model Configuration

### When to Use

You want fine-grained control over Ollama model deployment: GPU allocation, keep-alive behavior, role-based routing, or automated model pulling.

### Step-by-step

1. Create `OllamaEndpoint` objects with tags for role matching.
2. Tune `num_gpu` and `keep_alive` per endpoint.
3. Use `pull_model()` to automate model downloads.

### Complete Example

```python
from src.runtime.ollama_bridge import OllamaBridge, OllamaEndpoint

bridge = OllamaBridge(base_url="http://localhost:11434")

# Register a large code model for backend tasks
bridge.register(OllamaEndpoint(
    name="ollama/deepseek-backend",
    model_name="deepseek-v3.2:70b",
    tags=["backend", "code"],
    num_gpu=1,
    keep_alive="10m",          # keep model loaded for 10 minutes
))

# Register a smaller model for docs tasks
bridge.register(OllamaEndpoint(
    name="ollama/llama-docs",
    model_name="llama3.3:8b",
    tags=["docs", "general"],
    num_gpu=0,                  # CPU only
    keep_alive="5m",
))

# Pull models automatically (skips if already present)
await bridge.pull_model("deepseek-v3.2:70b")
await bridge.pull_model("llama3.3:8b")

# Health check
status = await bridge.health_check_all()
for name, health in status.items():
    print(f"{name}: {'healthy' if health.healthy else 'unhealthy'}")
```

### Testing

```python
@pytest.mark.asyncio
async def test_ollama_endpoint_tags():
    bridge = OllamaBridge()
    bridge.register(OllamaEndpoint(
        name="test", model_name="test:latest", tags=["backend"],
    ))
    endpoint = bridge.resolve_for_role("backend")
    assert endpoint.name == "test"
```

---

## 13. KubeRay Cluster Configuration

### When to Use

You are deploying Archon on Kubernetes with Ray for distributed agent execution, and need to configure worker groups, GPU tolerations, or autoscaling.

### Step-by-step

1. Create a `KubeRayConfig` with worker group definitions.
2. Set GPU tolerations and node selectors.
3. Configure `AutoScaleConfig` for elastic scaling.

### Complete Example

```python
from src.infra.kuberay import KubeRayConfig, WorkerGroup, AutoScaleConfig

config = KubeRayConfig(
    cluster_name="archon-agents",
    namespace="archon",
    head_cpu="4",
    head_memory="8Gi",
    worker_groups=[
        WorkerGroup(
            name="gpu-workers",
            replicas=2,
            min_replicas=1,
            max_replicas=8,
            cpu="8",
            memory="32Gi",
            gpu=1,
            gpu_type="nvidia.com/gpu",
            tolerations=[
                {"key": "nvidia.com/gpu", "operator": "Exists", "effect": "NoSchedule"},
            ],
            node_selector={"node.kubernetes.io/gpu": "a100"},
        ),
        WorkerGroup(
            name="cpu-workers",
            replicas=4,
            min_replicas=2,
            max_replicas=16,
            cpu="4",
            memory="16Gi",
        ),
    ],
    autoscale=AutoScaleConfig(
        enabled=True,
        target_utilization=0.7,
        scale_up_threshold=0.8,
        scale_down_threshold=0.3,
        cooldown_seconds=300,
    ),
)
```

### Deploy

```python
from src.infra.kuberay import KubeRayDeployer

deployer = KubeRayDeployer(kubeconfig_path="~/.kube/config")
await deployer.apply(config)
status = await deployer.get_status("archon-agents", namespace="archon")
print(f"Cluster: {status.state}, Workers: {status.ready_workers}/{status.desired_workers}")
```

### Testing

```python
def test_kuberay_config_validation():
    config = KubeRayConfig(
        cluster_name="test",
        worker_groups=[WorkerGroup(name="w1", replicas=1, cpu="2", memory="4Gi")],
    )
    assert config.cluster_name == "test"
    assert len(config.worker_groups) == 1
```

---

## 14. Hybrid Cloud Strategy

### When to Use

You want to run agents across multiple cloud providers or a mix of on-premises and cloud infrastructure, with cost-aware scheduling.

### Step-by-step

1. Define a `HybridConfig` with provider endpoints.
2. Choose a `SchedulingStrategy`.
3. Set budget limits.

### Complete Example

```python
from src.infra.hybrid import (
    HybridConfig,
    CloudProvider,
    SchedulingStrategy,
    BudgetConfig,
)

config = HybridConfig(
    providers=[
        CloudProvider(
            name="on-prem-gpu",
            type="kuberay",
            endpoint="https://k8s.internal:6443",
            priority=1,                        # highest priority (use first)
            capabilities=["gpu", "vllm"],
            max_concurrent_agents=8,
        ),
        CloudProvider(
            name="aws-fallback",
            type="aws_ecs",
            endpoint="arn:aws:ecs:us-east-1:123456:cluster/archon",
            priority=2,                        # fallback
            capabilities=["gpu", "cpu"],
            max_concurrent_agents=20,
            cost_per_hour=2.50,
        ),
        CloudProvider(
            name="gcp-burst",
            type="gcp_gke",
            endpoint="projects/my-proj/locations/us-central1/clusters/archon",
            priority=3,                        # burst only
            capabilities=["gpu", "tpu"],
            max_concurrent_agents=50,
            cost_per_hour=3.00,
        ),
    ],
    scheduling=SchedulingStrategy.COST_AWARE,  # or PRIORITY, ROUND_ROBIN, LATENCY
    budget=BudgetConfig(
        daily_limit_usd=100.0,
        monthly_limit_usd=2000.0,
        alert_threshold_percent=80,            # alert at 80% of budget
    ),
)
```

### Apply the Configuration

```python
from src.infra.hybrid import HybridScheduler

scheduler = HybridScheduler(config=config)

# Schedule an agent task
placement = await scheduler.schedule(
    role="backend",
    requirements=["gpu"],
    estimated_duration_minutes=10,
)
print(f"Scheduled on: {placement.provider.name}, estimated cost: ${placement.estimated_cost:.2f}")
```

### Testing

```python
@pytest.mark.asyncio
async def test_hybrid_scheduler_prefers_on_prem():
    scheduler = HybridScheduler(config=config)
    placement = await scheduler.schedule(role="backend", requirements=["gpu"])
    assert placement.provider.name == "on-prem-gpu"
```

---

## Related Docs

- [API Reference](api-reference.md)
- [Architecture](architecture.md)
- [Human Gate Design](human-gate.md)
- [Operations Guide](operations-guide.md)
