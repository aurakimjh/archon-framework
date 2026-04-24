# 플러그인 개발 가이드

🇺🇸 [English](../en/plugin-guide.md)

> 버전: 1.0.0 | 최종 수정: 2026-04-24

## 개요

Archon은 4개 확장 포인트를 제공한다.

| 확장 포인트 | 방법 |
|---|---|
| 커스텀 에이전트 | `BaseAgent` 상속 |
| 커스텀 LLM 프로바이더 | LiteLLM config + vLLM Bridge 등록 |
| 커스텀 QA 도구 | `run_qa_pipeline()` 확장 또는 전처리 |
| MCP/A2A 플러그인 | `MCPServer` 도구 등록 / `A2ARouter` 연결 |

---

## 1. 커스텀 에이전트 추가

### BaseAgent 상속

모든 에이전트는 `src/agents/base.py`의 `BaseAgent`를 상속하고 `_build_system_prompt()`를 구현해야 한다.

```python
# src/agents/security.py
from src.agents.base import BaseAgent
from src.orchestrator.handoff import HandoffArtifact
from src.registry.models import AgentRole, ProjectRegistry


class SecurityAgent(BaseAgent):
    """보안 감사 전문 에이전트."""

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

Return your findings in <archon-output> JSON format:
{{
  "summary": "...",
  "changed_files": [],
  "decisions": []
}}"""
```

### 에이전트 풀에 등록

`src/orchestrator/orchestrator.py`의 `AGENT_POOL`에 추가한다.

```python
# orchestrator.py
from src.agents.security import SecurityAgent

AGENT_POOL: dict[str, BaseAgent] = {
    # 기존 에이전트들...
    "security": SecurityAgent(),
}

# 태스크 체인에도 추가 (선택)
DEFAULT_TASK_CHAINS = {
    "backend": ["security", "tester", "docs"],  # 백엔드 → 보안 감사 → 테스트
    ...
}
```

### AgentRole enum 확장

`src/registry/models.py`에 역할 추가.

```python
class AgentRole(StrEnum):
    # 기존 역할들...
    SECURITY = "security"
```

### Registry에 모델 설정

`.harness/registry/my_project.json`의 `agent_config`에 추가.

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

### 구조화 출력 활용

에이전트가 `<archon-output>` 태그로 JSON을 반환하면 `_parse_structured_output()`이 자동으로 파싱한다.

```python
# LLM 응답 예시
response = """
변경 파일을 검토했습니다.

<archon-output>
{
  "summary": "JWT 토큰 만료 처리 취약점 발견",
  "changed_files": [
    {"path": "src/auth/jwt.py", "change_type": "modified", "reason": "취약점 수정"}
  ],
  "decisions": [
    {"decision": "토큰 만료 시 즉시 블랙리스트 처리", "reason": "세션 하이재킹 방지"}
  ]
}
</archon-output>
"""
```

---

## 2. 커스텀 LLM 프로바이더 추가

### Ollama 모델 추가

`config/litellm_config.yaml.example`을 복사하고 모델을 추가한다.

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

### vLLM GPU 워커 연결

`VLLMBridge`로 GPU 워커를 등록하고 `Orchestrator`에 주입한다.

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

# 헬스체크 후 Orchestrator에 주입
await bridge.health_check_all()
orch = Orchestrator(registry=registry, vllm_bridge=bridge)
```

### 복잡도 기반 모델 분기

Registry에 `high_complexity_model`을 설정하면 Complexity Router가 자동으로 선택한다.

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

### LM Studio 연결

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

## 3. 커스텀 QA 도구 추가

### QA 파이프라인 확장

`src/runtime/qa.py`의 함수들은 독립적으로 호출 가능하다. 커스텀 도구는 `run_qa_pipeline()` 전후에 실행하거나, 래퍼 함수를 만들면 된다.

```python
# my_qa.py
import asyncio
from src.runtime.qa import run_qa_pipeline
from src.orchestrator.handoff import QualityGates


async def run_custom_qa_pipeline(
    project_root: str,
    registry,
) -> QualityGates:
    """표준 QA + 커스텀 도구를 병렬 실행."""

    # 표준 QA 파이프라인
    standard_task = asyncio.create_task(
        run_qa_pipeline(project_root, registry)
    )
    # 커스텀 도구 (예: bandit 보안 스캔)
    custom_task = asyncio.create_task(
        run_bandit_scan(project_root)
    )

    quality, bandit_result = await asyncio.gather(standard_task, custom_task)

    # bandit 결과를 security_scan에 합산
    if bandit_result.high_severity > 0:
        quality.security_scan.high += bandit_result.high_severity

    return quality


async def run_bandit_scan(project_root: str) -> BanditResult:
    """bandit Python 보안 스캐너 실행."""
    import asyncio
    proc = await asyncio.create_subprocess_exec(
        "bandit", "-r", "src/", "-f", "json", "-q",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=project_root,
    )
    stdout, _ = await proc.communicate()
    # JSON 파싱 로직...
    return BanditResult(...)
```

### SOP Compliance 스코어 주입

QA 후 `QualityGates.sop_compliance_score`를 직접 설정할 수 있다.

```python
quality = await run_qa_pipeline(project_root, registry)

# SOP 준수도 계산 (별도 도구)
sop_score = await evaluate_sop_compliance(
    handoff=handoff,
    sop_path=".harness/sop/backend.md",
)
quality.sop_compliance_score = sop_score  # 0~100

# Gate 판정에 자동 반영
from src.gate.evaluator import evaluate_gate
decision = evaluate_gate(quality, registry.quality_policy)
```

---

## 4. MCP 플러그인 추가

### 커스텀 MCP 도구 등록

`MCPServer`에 새 도구 핸들러를 추가한다.

```python
from src.mcp.server import MCPServer, ToolDefinition, ToolResult

server = MCPServer()

# 커스텀 도구 정의
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

# 핸들러 등록 (MCPServer._handlers에 직접 추가)
async def handle_security_audit(args: dict) -> ToolResult:
    project_id = args["project_id"]
    # 실제 보안 감사 로직...
    return ToolResult(success=True, data={"findings": []})

server._handlers["run_security_audit"] = handle_security_audit
```

### A2A 기반 에이전트 협업

에이전트 간 직접 메시지를 주고받아 복잡한 협업 패턴을 구현한다.

```python
from src.mcp.a2a import A2ARouter, A2AMessage, A2AMessageType, A2APriority

router = A2ARouter()

# Backend Agent가 Tester에게 테스트 요청
backend = BackendAgent(a2a_router=router)
backend.send_a2a(
    to_agent="tester",
    subject="결제 API 테스트 요청",
    body="POST /api/v2/payments 엔드포인트 경계값 테스트 필요",
    message_type=A2AMessageType.REQUEST,
    priority=A2APriority.HIGH,
    project_id="proj-ecomm",
    task_id="task-payment-002",
)

# Tester Agent가 메시지 수신
tester = TesterAgent(a2a_router=router)
messages = tester.receive_a2a()
for msg in messages:
    print(f"[{msg.priority}] {msg.subject}: {msg.body}")
```

---

## 5. 알림 채널 확장

### 커스텀 Notifier 구현

`Notifier` 추상 클래스를 상속해 새 알림 채널을 추가한다.

```python
from src.notifications.base import Notifier, GateEvent
from src.gate.models import GateDecision


class PagerDutyNotifier(Notifier):
    """PagerDuty 인시던트 알림."""

    def __init__(self, integration_key: str):
        self._key = integration_key

    def should_notify(self, event: GateEvent) -> bool:
        # L3, L4만 PagerDuty 알림
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

### CompositeNotifier에 추가

```python
from src.notifications.base import CompositeNotifier
from src.notifications.slack import SlackNotifier
from src.notifications.terminal import TerminalNotifier

notifier = CompositeNotifier([
    TerminalNotifier(),
    SlackNotifier(webhook_url="https://hooks.slack.com/..."),
    PagerDutyNotifier(integration_key="your-key"),
])

# Orchestrator에 주입
orch = Orchestrator(registry=registry, notifier=notifier)
```

---

## 6. Dynamic Guardrails 커스터마이징

`quality_policy.high_risk_paths`와 `high_risk_keywords`를 Registry에서 프로젝트별로 조정한다.

```python
from src.registry.models import QualityPolicy

# 프로젝트에 맞게 위험 패턴 커스터마이징
policy = QualityPolicy(
    high_risk_paths=[
        "payment", "billing", "auth",        # 기본값
        "medical_records", "pii_data",        # 의료/개인정보 도메인 추가
        "nuclear_plant/controls/",            # 프로젝트 특화
    ],
    high_risk_keywords=[
        "payment", "credential", "deploy",    # 기본값
        "patient_data", "ssn", "hipaa",       # 도메인 특화
    ],
    sop_compliance_threshold=85,              # 기본 70 → 엄격하게
)
```

---

## 관련 문서

- [API Reference](api-reference.md)
- [아키텍처](architecture.md)
- [Human Gate 설계](human-gate.md)
- [운영 가이드](operations-guide.md)
