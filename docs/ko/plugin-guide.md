# 플러그인 및 확장 개발 가이드

[English](../en/plugin-guide.md)

> 버전: 2.0.0 | 최종 수정: 2026-04-24

## 개요

Archon은 프레임워크의 모든 계층에서 확장이 가능하도록 설계되어 있습니다. 이 가이드에서는 **14개 확장 포인트** 전체를 단계별 설명과 복사 가능한 완성된 예제와 함께 다룹니다.

| # | 확장 포인트 | 방법 | 바로가기 |
|---|---|---|---|
| 1 | 커스텀 에이전트 | `BaseAgent` 상속 | [이동](#1-커스텀-에이전트) |
| 2 | 커스텀 LLM 프로바이더 | vLLM / Ollama Bridge | [이동](#2-커스텀-llm-프로바이더) |
| 3 | 커스텀 QA 도구 | `run_qa_pipeline()` 확장 | [이동](#3-커스텀-qa-도구) |
| 4 | 커스텀 MCP 도구 | `MCPServer.register_tool()` | [이동](#4-커스텀-mcp-도구) |
| 5 | 커스텀 알림 채널 | `Notifier` ABC 상속 | [이동](#5-커스텀-알림-채널) |
| 6 | 커스텀 가드레일 | `GuardrailPolicy` 설정 | [이동](#6-커스텀-가드레일) |
| 7 | 커스텀 트레이싱 백엔드 | `ArchonTracer` 상속 | [이동](#7-커스텀-트레이싱-백엔드) |
| 8 | 커스텀 벤치마크 태스크 | `BenchmarkTask` 모델 | [이동](#8-커스텀-벤치마크-태스크) |
| 9 | 커스텀 진화 분석기 | `PatternAnalyzer` 상속 | [이동](#9-커스텀-진화-분석기) |
| 10 | 커스텀 헬스 복구 전략 | `SelfHealer` + `HealthWatchdog` | [이동](#10-커스텀-헬스-복구-전략) |
| 11 | 커스텀 대시보드 위젯 | `DashboardRoutes` + WebSocket | [이동](#11-커스텀-대시보드-위젯) |
| 12 | Ollama 모델 설정 | `OllamaBridge` | [이동](#12-ollama-모델-설정) |
| 13 | KubeRay 클러스터 설정 | `KubeRayConfig` | [이동](#13-kuberay-클러스터-설정) |
| 14 | 하이브리드 클라우드 전략 | `HybridConfig` | [이동](#14-하이브리드-클라우드-전략) |

---

## 1. 커스텀 에이전트

### 언제 사용하나요?

기본 제공 역할(backend, frontend, tester, docs 등)로는 다루기 어려운 도메인별 전문 에이전트가 필요할 때 사용합니다. 예를 들어, 보안 감사 에이전트, 데이터베이스 마이그레이션 전문가, 규정 준수 검사기 등을 만들 수 있습니다.

### 단계별 구현

1. `src/agents/` 디렉토리에 새 파일을 생성합니다.
2. `BaseAgent`를 상속하고 `_build_system_prompt()`를 구현합니다.
3. `src/registry/models.py`의 `AgentRole` enum에 역할을 추가합니다.
4. `src/orchestrator/orchestrator.py`의 `AGENT_POOL`에 에이전트를 등록합니다.
5. 프로젝트 레지스트리 JSON에 모델을 설정합니다.

### 전체 예제

```python
# src/agents/security.py
from src.agents.base import BaseAgent
from src.orchestrator.handoff import HandoffArtifact
from src.registry.models import ProjectRegistry


class SecurityAgent(BaseAgent):
    """보안 감사 전문 에이전트."""

    def __init__(self, a2a_router=None):
        super().__init__(
            role="security",
            a2a_router=a2a_router,
            # Phase 3 매개변수 (모두 선택 사항)
            tracing_middleware=None,       # Orchestrator에서 자동 감지
            guardrail_policy=None,         # 레지스트리 기본값으로 대체
            token_budget=8192,             # 턴당 최대 토큰 수
            health_monitor=None,           # Orchestrator에서 주입
            diagnostician=None,            # Orchestrator에서 주입
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

역할 enum을 등록합니다:

```python
# src/registry/models.py
class AgentRole(StrEnum):
    # 기존 역할들...
    SECURITY = "security"
```

에이전트 풀에 등록합니다:

```python
# src/orchestrator/orchestrator.py
from src.agents.security import SecurityAgent

AGENT_POOL: dict[str, BaseAgent] = {
    # 기존 에이전트들...
    "security": SecurityAgent(),
}

DEFAULT_TASK_CHAINS = {
    "backend": ["security", "tester", "docs"],
}
```

레지스트리 JSON에 모델을 설정합니다:

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

### 자동 자기 수정 기능

LLM이 `<archon-output>` 태그로 JSON 응답을 반환하면, `_parse_structured_output()`이 자동으로 파싱합니다. JSON 형식이 잘못된 경우, 기본 클래스가 자동으로 자기 수정 루프를 실행하여 LLM에게 출력을 수정하도록 요청합니다. 개발자가 별도의 코드를 작성할 필요가 없습니다.

### 테스트

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

## 2. 커스텀 LLM 프로바이더

### 언제 사용하나요?

셀프 호스팅 모델(vLLM, Ollama, LM Studio)을 연결하거나, 라우팅 체인에 새로운 추론 백엔드를 추가하고 싶을 때 사용합니다.

### 라우팅 체인

Archon은 다음 순서로 모델을 확인합니다(프로젝트별로 설정 가능):

```
vLLM Bridge --> Ollama Bridge --> LiteLLM 기본값
```

요청된 역할에 태그된 vLLM 엔드포인트가 정상이면 해당 엔드포인트를 사용합니다. 그렇지 않으면 Ollama로, 그 다음 LiteLLM 기본값으로 대체됩니다.

### 단계별 구현: vLLM Bridge

1. GPU 워커 URL로 `VLLMEndpoint`를 생성합니다.
2. `VLLMBridge`에 등록합니다.
3. 헬스체크를 실행합니다.
4. Bridge를 `Orchestrator`에 주입합니다.

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
    tags=["security"],  # "security" 역할에 자동 라우팅
))

await bridge.health_check_all()
orch = Orchestrator(registry=registry, vllm_bridge=bridge)
```

### 단계별 구현: Ollama Bridge

1. 역할 매칭을 위한 태그를 포함한 `OllamaEndpoint`를 생성합니다.
2. `OllamaBridge`에 등록합니다.
3. 필요한 경우 모델을 자동으로 풀링합니다.

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

# 모델이 아직 없으면 자동으로 다운로드
await bridge.pull_model("deepseek-v3.2:70b")

# 헬스체크
await bridge.health_check_all()
orch = Orchestrator(registry=registry, ollama_bridge=bridge)
```

### LiteLLM 설정 (Ollama 또는 LM Studio)

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

### 복잡도 기반 모델 분기

레지스트리에서 `high_complexity_model`을 설정하면 Complexity Router가 자동으로 적합한 모델을 선택합니다:

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

### 테스트

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

## 3. 커스텀 QA 도구

### 언제 사용하나요?

보안 스캐너(bandit, semgrep), 커스텀 린트 규칙, 또는 도메인별 품질 검사를 파이프라인에 추가하고 싶을 때 사용합니다.

### 단계별 구현

1. 도구를 실행하는 비동기 함수를 작성합니다.
2. `run_qa_pipeline()`을 래핑하여 두 작업을 병렬로 실행합니다.
3. 결과를 `QualityGates`에 병합합니다.

### 전체 예제

```python
# my_qa.py
import asyncio
from src.runtime.qa import run_qa_pipeline
from src.orchestrator.handoff import QualityGates


async def run_custom_qa_pipeline(
    project_root: str,
    registry,
) -> QualityGates:
    """표준 QA + 커스텀 도구를 병렬 실행합니다."""

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
    """bandit Python 보안 스캐너를 실행합니다."""
    proc = await asyncio.create_subprocess_exec(
        "bandit", "-r", "src/", "-f", "json", "-q",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=project_root,
    )
    stdout, _ = await proc.communicate()
    # JSON 결과 파싱...
```

### SOP 준수도 점수 주입

```python
quality = await run_qa_pipeline(project_root, registry)

sop_score = await evaluate_sop_compliance(
    handoff=handoff,
    sop_path=".harness/sop/backend.md",
)
quality.sop_compliance_score = sop_score  # 0~100

from src.gate.evaluator import evaluate_gate
decision = evaluate_gate(quality, registry.quality_policy)
```

### 테스트

```python
@pytest.mark.asyncio
async def test_custom_qa_pipeline(tmp_path):
    quality = await run_custom_qa_pipeline(str(tmp_path), mock_registry)
    assert quality.security_scan is not None
```

---

## 4. 커스텀 MCP 도구

### 언제 사용하나요?

Model Context Protocol을 통해 LLM에 새로운 기능을 노출하거나, 에이전트 간 메시징을 연결하고 싶을 때 사용합니다.

### 단계별 구현

1. JSON 스키마를 포함한 `ToolDefinition`을 정의합니다.
2. 비동기 핸들러 함수를 작성합니다.
3. `MCPServer`에 등록합니다.

### 전체 예제

```python
from src.mcp.server import MCPServer, ToolDefinition, ToolResult

server = MCPServer()

custom_tool = ToolDefinition(
    name="run_security_audit",
    description="변경된 파일에 대한 보안 감사를 실행합니다.",
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
    # 보안 감사 로직을 여기에 구현합니다...
    return ToolResult(success=True, data={"findings": []})


server.register_tool(custom_tool, handle_security_audit)
```

### A2A 기반 에이전트 협업

```python
from src.mcp.a2a import A2ARouter, A2AMessageType, A2APriority

router = A2ARouter()

# Backend Agent가 Tester에게 테스트를 요청합니다
backend = BackendAgent(a2a_router=router)
backend.send_a2a(
    to_agent="tester",
    subject="결제 API 테스트 요청",
    body="POST /api/v2/payments 엔드포인트 경계값 테스트가 필요합니다",
    message_type=A2AMessageType.REQUEST,
    priority=A2APriority.HIGH,
    project_id="proj-ecomm",
    task_id="task-payment-002",
)

# Tester Agent가 메시지를 수신합니다
tester = TesterAgent(a2a_router=router)
messages = tester.receive_a2a()
for msg in messages:
    print(f"[{msg.priority}] {msg.subject}: {msg.body}")
```

### 테스트

```python
@pytest.mark.asyncio
async def test_mcp_tool():
    result = await handle_security_audit({"project_id": "test", "handoff_id": "h1"})
    assert result.success is True
```

---

## 5. 커스텀 알림 채널

### 언제 사용하나요?

기본 제공되는 터미널 및 Slack 알림 외에 PagerDuty, Discord, 이메일, 커스텀 웹훅 등의 알림 채널로 게이트 결정 결과를 전달하고 싶을 때 사용합니다.

### 단계별 구현

1. `Notifier`를 상속하고 `should_notify()`와 `notify()`를 구현합니다.
2. `CompositeNotifier`에 추가합니다.
3. Composite를 `Orchestrator`에 주입합니다.

### 전체 예제: PagerDuty

```python
from src.notifications.base import Notifier, GateEvent
from src.gate.models import GateDecision


class PagerDutyNotifier(Notifier):
    """PagerDuty 인시던트 알림."""

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

### 전체 예제: Discord

```python
class DiscordNotifier(Notifier):
    """Discord 웹훅 알림."""

    def __init__(self, webhook_url: str):
        self._url = webhook_url

    def should_notify(self, event: GateEvent) -> bool:
        return True  # 모든 게이트 이벤트에 알림

    async def notify(self, event: GateEvent) -> bool:
        import httpx
        embed = {
            "title": event.title,
            "description": event.trigger_reason,
            "color": 0xFF0000 if event.gate_decision == GateDecision.L3_HALT else 0x00FF00,
            "fields": [
                {"name": "프로젝트", "value": event.project_id, "inline": True},
                {"name": "결정", "value": event.gate_decision.value, "inline": True},
            ],
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(self._url, json={"embeds": [embed]})
        return resp.status_code == 204
```

### CompositeNotifier에 등록

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

### 테스트

```python
@pytest.mark.asyncio
async def test_pagerduty_notifier(httpx_mock):
    httpx_mock.add_response(status_code=202)
    notifier = PagerDutyNotifier(integration_key="test-key")
    result = await notifier.notify(sample_gate_event)
    assert result is True
```

---

## 6. 커스텀 가드레일

### 언제 사용하나요?

프로젝트별 안전 규칙이 필요할 때 사용합니다. 금지 키워드, 보호 파일 경로, 또는 더 엄격한 리뷰를 유발하는 커스텀 설정 파일 패턴을 추가할 수 있습니다.

### 단계별 구현

1. 커스텀 규칙을 포함한 `GuardrailPolicy`를 생성합니다.
2. `forbidden_keywords`, `extra_protected_paths`, `config_file_patterns`를 필요에 따라 추가합니다.
3. 레지스트리에 연결하거나 에이전트에 주입합니다.

### 전체 예제

```python
from src.guardrails.policy import GuardrailPolicy

policy = GuardrailPolicy(
    # 항상 사람 리뷰를 유발하는 파일 경로
    high_risk_paths=[
        "payment", "billing", "auth",          # 기본값
        "medical_records", "pii_data",          # 의료/개인정보 도메인
        "nuclear_plant/controls/",              # 프로젝트 특화
    ],
    # 게이트 레벨을 상승시키는 키워드
    high_risk_keywords=[
        "payment", "credential", "deploy",      # 기본값
        "patient_data", "ssn", "hipaa",         # 도메인 특화
    ],
    # 커스텀 금지 키워드 -- 이 키워드를 포함한 에이전트 출력은 차단됩니다
    forbidden_keywords=[
        "DROP TABLE", "rm -rf /", "eval(",
        "hardcoded_api_key",
    ],
    # high_risk_paths 외에 추가로 보호할 경로
    extra_protected_paths=[
        "infrastructure/terraform/",
        "k8s/production/",
        ".github/workflows/",
    ],
    # 설정 파일로 인식되는 패턴 (설정 변경 가드레일을 유발합니다)
    config_file_patterns=[
        "*.yaml", "*.yml", "*.toml",           # 기본값
        "*.hcl", "*.tf",                        # Terraform
        "Tiltfile",                             # Tilt
    ],
    sop_compliance_threshold=85,                # 기본값 70보다 엄격하게 설정
)
```

### 레지스트리에 연결

```json
{
  "quality_policy": {
    "high_risk_paths": ["payment", "billing", "auth", "medical_records"],
    "high_risk_keywords": ["payment", "credential", "patient_data"],
    "sop_compliance_threshold": 85
  }
}
```

### 테스트

```python
def test_guardrail_blocks_forbidden_keyword():
    policy = GuardrailPolicy(forbidden_keywords=["DROP TABLE"])
    result = policy.check_output("Let's run DROP TABLE users;")
    assert result.blocked is True
    assert "DROP TABLE" in result.reason
```

---

## 7. 커스텀 트레이싱 백엔드

### 언제 사용하나요?

기본 제공 옵션(콘솔, JSON 파일) 외의 관측성 플랫폼(Datadog, New Relic, Jaeger 등)으로 트레이스 및 스팬 데이터를 전송하고 싶을 때 사용합니다.

### 단계별 구현

1. `ArchonTracer`를 상속합니다.
2. 4가지 필수 메서드를 구현합니다: `start_trace()`, `start_span()`, `end_span()`, `record_llm_call()`.
3. `CompositeTracer` 또는 `create_tracer_from_config()`를 통해 등록합니다.

### 전체 예제: Datadog 트레이서

```python
from src.tracing.base import ArchonTracer, TraceContext, SpanContext
from ddtrace import tracer as dd_tracer


class DatadogTracer(ArchonTracer):
    """Archon 트레이스를 Datadog APM으로 전송합니다."""

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

### 트레이서 등록

```python
from src.tracing.composite import CompositeTracer
from src.tracing.console import ConsoleTracer

tracer = CompositeTracer([
    ConsoleTracer(),           # 로컬 개발용 출력
    DatadogTracer("archon"),   # 프로덕션 관측성
])

orch = Orchestrator(registry=registry, tracer=tracer)
```

설정 파일을 통한 등록도 가능합니다:

```yaml
# config/tracing.yaml
tracers:
  - type: console
  - type: custom
    class: my_tracers.DatadogTracer
    params:
      service_name: archon
```

### 테스트

```python
def test_datadog_tracer_starts_trace():
    tracer = DatadogTracer("test-service")
    ctx = tracer.start_trace("test-op", metadata={"env": "test"})
    assert ctx.trace_id is not None
```

---

## 8. 커스텀 벤치마크 태스크

### 언제 사용하나요?

도메인별 프롬프트에 대한 에이전트 성능을 평가하고 싶을 때 사용합니다. 예를 들어, 백엔드 에이전트가 FastAPI 엔드포인트를 올바르게 생성하는지, 보안 에이전트가 알려진 취약점을 탐지하는지 검증할 수 있습니다.

### 단계별 구현

1. 예상 키워드와 패턴을 포함한 `BenchmarkTask` 객체를 정의합니다.
2. `BenchmarkRunner.run_suite()`에 전달합니다.
3. 필요한 경우 스코어러 가중치를 커스터마이즈합니다.

### 전체 예제

```python
from src.benchmark.models import BenchmarkTask
from src.benchmark.runner import BenchmarkRunner

# 커스텀 태스크 정의
tasks = [
    BenchmarkTask(
        task_id="custom-api-test",
        role="backend",
        prompt="이메일 검증이 포함된 사용자 등록 FastAPI 엔드포인트를 작성해주세요.",
        expected_keywords=["@app.post", "async def", "Pydantic", "EmailStr"],
        expected_patterns=[
            r"class\s+\w+\(BaseModel\)",          # Pydantic 모델
            r"async\s+def\s+\w+\(.+\)",            # 비동기 핸들러
        ],
    ),
    BenchmarkTask(
        task_id="security-xss-check",
        role="security",
        prompt="이 템플릿에서 XSS 취약점을 검토해주세요: {{ user_input }}",
        expected_keywords=["XSS", "escape", "sanitize"],
        expected_patterns=[r"(escape|sanitize|bleach|markupsafe)"],
    ),
]

# 스위트 실행
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

# 결과 확인
for r in results:
    print(f"{r.task_id}: 점수={r.total_score:.2f}, 지연시간={r.latency_ms:.0f}ms")
```

### 테스트

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

## 9. 커스텀 진화 분석기

### 언제 사용하나요?

시간 경과에 따른 에이전트의 성능 드리프트나 행동 변화를 감지하고, 자동으로 튜닝 액션을 제안하고 싶을 때 사용합니다.

### 단계별 구현

1. `PatternAnalyzer`를 상속합니다.
2. `analyze()`를 오버라이드하여 커스텀 드리프트 패턴을 감지합니다.
3. 권장 변경 사항을 담은 `TuningAction` 객체를 반환합니다.
4. 필요한 경우 `on_policy_updated()`를 구현하여 영구적 변경을 처리합니다.

### 전체 예제

```python
from src.evolution.analyzer import PatternAnalyzer, AnalysisResult
from src.evolution.models import TuningAction, TuningActionType


class LatencyDriftAnalyzer(PatternAnalyzer):
    """에이전트 응답 지연시간이 허용 임계값을 초과하는지 감지합니다."""

    def __init__(self, threshold_ms: float = 5000.0):
        self._threshold = threshold_ms

    def analyze(self, history: list[dict]) -> AnalysisResult:
        recent = history[-10:]  # 최근 10회 실행
        avg_latency = sum(h["latency_ms"] for h in recent) / len(recent)

        actions = []
        if avg_latency > self._threshold:
            actions.append(TuningAction(
                action_type=TuningActionType.SWITCH_MODEL,
                reason=f"평균 지연시간 {avg_latency:.0f}ms가 임계값 {self._threshold:.0f}ms를 초과했습니다",
                params={"fallback_to": "smaller_model"},
            ))

        return AnalysisResult(
            drift_detected=len(actions) > 0,
            actions=actions,
            summary=f"평균 지연시간: {avg_latency:.0f}ms",
        )

    def on_policy_updated(self, old_policy, new_policy) -> None:
        """튜닝 액션이 적용될 때 호출됩니다. 로깅이나 영구 저장에 사용하세요."""
        print(f"정책 변경: {old_policy} -> {new_policy}")
```

### 분석기 등록

```python
from src.evolution.engine import EvolutionEngine

engine = EvolutionEngine(registry=registry)
engine.add_analyzer(LatencyDriftAnalyzer(threshold_ms=3000.0))

# 분석 실행
result = await engine.evolve()
for action in result.actions:
    print(f"권장 사항: {action.action_type} -- {action.reason}")
```

### 테스트

```python
def test_latency_drift_detected():
    analyzer = LatencyDriftAnalyzer(threshold_ms=1000.0)
    history = [{"latency_ms": 2000.0}] * 10
    result = analyzer.analyze(history)
    assert result.drift_detected is True
    assert result.actions[0].action_type == TuningActionType.SWITCH_MODEL
```

---

## 10. 커스텀 헬스 복구 전략

### 언제 사용하나요?

에이전트나 인프라 컴포넌트가 비정상 상태가 되었을 때의 커스텀 복구 동작을 정의하거나, PagerDuty/Opsgenie 같은 외부 시스템으로 알림을 전송하고 싶을 때 사용합니다.

### 단계별 구현

1. 커스텀 `HealingConfig`로 `SelfHealer`를 설정합니다.
2. 특정 장애 유형에 대한 복구 액션을 정의합니다.
3. `HealthWatchdog`에 알림 콜백을 추가합니다.

### 전체 예제

```python
from src.health.healer import SelfHealer, HealingConfig, RecoveryAction
from src.health.watchdog import HealthWatchdog, WatchdogAlert


# 커스텀 힐링 설정
config = HealingConfig(
    max_retries=3,
    retry_delay_seconds=5.0,
    escalation_threshold=2,  # 복구 2회 실패 후 에스컬레이션
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


# 커스텀 알림 콜백
async def pagerduty_alert(alert: WatchdogAlert) -> None:
    """심각한 알림을 PagerDuty로 전송합니다."""
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


# 설정 연결
watchdog = HealthWatchdog(healer=healer, check_interval_seconds=30.0)
watchdog.add_alerter(pagerduty_alert)

# 모니터링 시작 (백그라운드에서 실행)
await watchdog.start()
```

### 테스트

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

## 11. 커스텀 대시보드 위젯

### 언제 사용하나요?

Archon 웹 대시보드에 커스텀 모니터링 뷰, 프로젝트별 메트릭, 또는 실시간 데이터 피드를 추가하고 싶을 때 사용합니다.

### 단계별 구현

1. `DashboardRoutes`에 데이터 엔드포인트를 추가합니다.
2. `WebSocketManager`를 사용하여 실시간 이벤트를 브로드캐스트합니다.
3. 정적 파일(HTML/JS/CSS)을 `src/dashboard/static/`에 배치합니다.

### 전체 예제: 커스텀 메트릭 엔드포인트

```python
from src.dashboard.routes import DashboardRoutes
from src.dashboard.websocket import WebSocketManager
from fastapi import APIRouter

router = APIRouter()


@router.get("/api/custom/agent-performance")
async def get_agent_performance():
    """커스텀 에이전트 성능 메트릭을 반환합니다."""
    return {
        "agents": {
            "backend": {"avg_latency_ms": 1200, "success_rate": 0.95},
            "security": {"avg_latency_ms": 800, "success_rate": 0.99},
        },
    }


# DashboardRoutes에 등록
dashboard = DashboardRoutes()
dashboard.include_router(router, prefix="/custom")
```

### 실시간 이벤트 브로드캐스트

```python
from src.dashboard.websocket import WebSocketManager

ws_manager = WebSocketManager()


async def on_agent_complete(agent_role: str, result: dict):
    """에이전트 완료를 연결된 모든 대시보드 클라이언트에 브로드캐스트합니다."""
    await ws_manager.broadcast({
        "event": "agent_complete",
        "data": {
            "role": agent_role,
            "success": result["success"],
            "latency_ms": result["latency_ms"],
        },
    })
```

### 정적 파일 구조

커스텀 위젯 HTML을 `src/dashboard/static/`에 배치합니다:

```
src/dashboard/static/
  widgets/
    agent-performance.html
    agent-performance.js
    agent-performance.css
```

### 테스트

```python
from fastapi.testclient import TestClient

def test_custom_dashboard_endpoint(app):
    client = TestClient(app)
    resp = client.get("/custom/api/custom/agent-performance")
    assert resp.status_code == 200
    assert "agents" in resp.json()
```

---

## 12. Ollama 모델 설정

### 언제 사용하나요?

Ollama 모델 배포에 대한 세밀한 제어가 필요할 때 사용합니다. GPU 할당, keep-alive 동작, 역할 기반 라우팅, 자동 모델 풀링 등을 설정할 수 있습니다.

### 단계별 구현

1. 역할 매칭용 태그를 포함한 `OllamaEndpoint` 객체를 생성합니다.
2. 엔드포인트별로 `num_gpu`와 `keep_alive`를 튜닝합니다.
3. `pull_model()`을 사용하여 모델 다운로드를 자동화합니다.

### 전체 예제

```python
from src.runtime.ollama_bridge import OllamaBridge, OllamaEndpoint

bridge = OllamaBridge(base_url="http://localhost:11434")

# 백엔드 태스크용 대형 코드 모델 등록
bridge.register(OllamaEndpoint(
    name="ollama/deepseek-backend",
    model_name="deepseek-v3.2:70b",
    tags=["backend", "code"],
    num_gpu=1,
    keep_alive="10m",          # 10분 동안 모델을 메모리에 유지
))

# 문서 태스크용 소형 모델 등록
bridge.register(OllamaEndpoint(
    name="ollama/llama-docs",
    model_name="llama3.3:8b",
    tags=["docs", "general"],
    num_gpu=0,                  # CPU 전용
    keep_alive="5m",
))

# 모델 자동 풀링 (이미 있으면 건너뜁니다)
await bridge.pull_model("deepseek-v3.2:70b")
await bridge.pull_model("llama3.3:8b")

# 헬스체크
status = await bridge.health_check_all()
for name, health in status.items():
    print(f"{name}: {'정상' if health.healthy else '비정상'}")
```

### 테스트

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

## 13. KubeRay 클러스터 설정

### 언제 사용하나요?

분산 에이전트 실행을 위해 Kubernetes에서 Ray를 사용하여 Archon을 배포하며, 워커 그룹, GPU 톨러레이션, 오토스케일링 등을 설정해야 할 때 사용합니다.

### 단계별 구현

1. 워커 그룹 정의를 포함한 `KubeRayConfig`를 생성합니다.
2. GPU 톨러레이션과 노드 셀렉터를 설정합니다.
3. 탄력적 스케일링을 위해 `AutoScaleConfig`를 설정합니다.

### 전체 예제

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

### 배포

```python
from src.infra.kuberay import KubeRayDeployer

deployer = KubeRayDeployer(kubeconfig_path="~/.kube/config")
await deployer.apply(config)
status = await deployer.get_status("archon-agents", namespace="archon")
print(f"클러스터: {status.state}, 워커: {status.ready_workers}/{status.desired_workers}")
```

### 테스트

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

## 14. 하이브리드 클라우드 전략

### 언제 사용하나요?

여러 클라우드 프로바이더 또는 온프레미스와 클라우드 인프라를 혼합하여 에이전트를 실행하면서, 비용 인식 스케줄링을 적용하고 싶을 때 사용합니다.

### 단계별 구현

1. 프로바이더 엔드포인트를 포함한 `HybridConfig`를 정의합니다.
2. `SchedulingStrategy`를 선택합니다.
3. 예산 한도를 설정합니다.

### 전체 예제

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
            priority=1,                        # 최우선 (먼저 사용)
            capabilities=["gpu", "vllm"],
            max_concurrent_agents=8,
        ),
        CloudProvider(
            name="aws-fallback",
            type="aws_ecs",
            endpoint="arn:aws:ecs:us-east-1:123456:cluster/archon",
            priority=2,                        # 대체
            capabilities=["gpu", "cpu"],
            max_concurrent_agents=20,
            cost_per_hour=2.50,
        ),
        CloudProvider(
            name="gcp-burst",
            type="gcp_gke",
            endpoint="projects/my-proj/locations/us-central1/clusters/archon",
            priority=3,                        # 버스트 전용
            capabilities=["gpu", "tpu"],
            max_concurrent_agents=50,
            cost_per_hour=3.00,
        ),
    ],
    scheduling=SchedulingStrategy.COST_AWARE,  # 또는 PRIORITY, ROUND_ROBIN, LATENCY
    budget=BudgetConfig(
        daily_limit_usd=100.0,
        monthly_limit_usd=2000.0,
        alert_threshold_percent=80,            # 예산의 80%에서 알림
    ),
)
```

### 설정 적용

```python
from src.infra.hybrid import HybridScheduler

scheduler = HybridScheduler(config=config)

# 에이전트 태스크 스케줄링
placement = await scheduler.schedule(
    role="backend",
    requirements=["gpu"],
    estimated_duration_minutes=10,
)
print(f"배치 위치: {placement.provider.name}, 예상 비용: ${placement.estimated_cost:.2f}")
```

### 테스트

```python
@pytest.mark.asyncio
async def test_hybrid_scheduler_prefers_on_prem():
    scheduler = HybridScheduler(config=config)
    placement = await scheduler.schedule(role="backend", requirements=["gpu"])
    assert placement.provider.name == "on-prem-gpu"
```

---

## 관련 문서

- [API Reference](api-reference.md)
- [아키텍처](architecture.md)
- [Human Gate 설계](human-gate.md)
- [운영 가이드](operations-guide.md)
