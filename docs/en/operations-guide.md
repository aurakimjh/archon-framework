# Operations Guide

[한국어](../ko/operations-guide.md)

> Version: 2.0.0 | Last updated: 2026-04-24

## Table of Contents

1. [Deployment](#1-deployment)
2. [Environment Variables](#2-environment-variables)
3. [LLM Model Configuration](#3-llm-model-configuration)
4. [Observability & Monitoring](#4-observability--monitoring)
5. [Guardrails Operations](#5-guardrails-operations)
6. [Self-Healing Operations](#6-self-healing-operations)
7. [Dashboard Operations](#7-dashboard-operations)
8. [Benchmark Operations](#8-benchmark-operations)
9. [Evolution Loop Operations](#9-evolution-loop-operations)
10. [KubeRay Operations](#10-kuberay-operations)
11. [Hybrid Cloud Operations](#11-hybrid-cloud-operations)
12. [Transaction Snapshots](#12-transaction-snapshots)
13. [Backup and Recovery](#13-backup-and-recovery)
14. [Troubleshooting FAQ](#14-troubleshooting-faq)

---

## 1. Deployment

This section covers every deployment method from local development to Kubernetes clusters. If you are new to Archon, start with "Local Development."

### 1.1 Prerequisites

| Item | Version | Required | Purpose |
|---|---|---|---|
| Python | 3.11+ | Yes | Framework runtime |
| pip / uv | latest | Yes | Package manager |
| Redis | 7.x | Recommended | L1 scratchpad (falls back to in-memory) |
| ChromaDB | 0.4.x | Recommended | L2 vector store (falls back to in-memory) |
| Docker | 24.x+ | Optional | Container deployment |
| Ollama | latest | Optional | Local LLM inference |
| Node.js | 18+ | Optional | Dashboard frontend |

### 1.2 Local Development

```bash
# 1. Clone the repo
git clone https://github.com/your-org/archon-framework.git
cd archon-framework

# 2. Create a virtual environment (recommended)
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Set environment variables
cp .env.example .env
# Edit .env and fill in your API keys

# 5. Run mock demo (no LLM required)
python -m src.demo.pipeline

# 6. Run the real pipeline
python -m src --project-id my-project --task-id task-001
```

> **Why a virtual environment?** It isolates project dependencies from your system Python, preventing version conflicts. This is essential when you manage multiple projects on the same machine.

### 1.3 Docker

```dockerfile
# Dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1
CMD ["python", "-m", "src"]
```

```bash
# Build image
docker build -t archon:latest .

# Run container with env file
docker run --env-file .env \
  -v $(pwd)/.harness:/app/.harness \
  archon:latest
```

### 1.4 Docker Compose (Full Stack)

This brings up the entire stack — Archon, the dashboard, Redis, and ChromaDB — in one command.

```yaml
# docker-compose.yml
version: "3.9"

services:
  archon:
    build: .
    env_file: .env
    ports:
      - "8000:8000"         # API server
    volumes:
      - ./.harness:/app/.harness
    depends_on:
      - redis
      - chroma

  dashboard:
    build:
      context: ./dashboard
    ports:
      - "3000:3000"         # Dashboard UI
    environment:
      - ARCHON_API_URL=http://archon:8000
    depends_on:
      - archon

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    command: redis-server --appendonly yes
    # appendonly minimizes data loss on crash

  chroma:
    image: chromadb/chroma:latest
    ports:
      - "8001:8000"
    volumes:
      - chroma_data:/chroma/chroma

volumes:
  redis_data:
  chroma_data:
```

```bash
# Start the full stack
docker-compose up -d

# Follow logs
docker-compose logs -f archon

# Shut down
docker-compose down
```

### 1.5 Ollama Server Deployment

Ollama lets you run open-source LLMs locally. No cloud API costs, no data leaving your network.

```bash
# macOS (Homebrew)
brew install ollama

# Linux
curl -fsSL https://ollama.com/install.sh | sh

# Start the service
ollama serve
# Default port: 11434

# Pull models
ollama pull llama3.3:70b
ollama pull deepseek-v3.2:7b

# Verify installed models
ollama list

# Health check
curl http://localhost:11434/api/tags
```

You can also add Ollama to your Docker Compose stack:

```yaml
  ollama:
    image: ollama/ollama:latest
    ports:
      - "11434:11434"
    volumes:
      - ollama_data:/root/.ollama
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]
```

> **Why Ollama?** Sensitive data stays on-premise, you avoid network latency, and local inference is free. A good strategy: iterate fast with 7B models during development, then use 70B models in production for quality.

### 1.6 AITOP Monitoring Server

AITOP is an observability server purpose-built for AI agent workloads. It ingests traces via OTLP/HTTP.

```bash
# Run AITOP server
docker run -d \
  --name aitop \
  -p 8080:8080 \
  -e AITOP_DB_PATH=/data/aitop.db \
  -v aitop_data:/data \
  aitop/server:latest

# Health check
curl http://localhost:8080/health
```

Add to Docker Compose:

```yaml
  aitop:
    image: aitop/server:latest
    ports:
      - "8080:8080"
    environment:
      - AITOP_DB_PATH=/data/aitop.db
    volumes:
      - aitop_data:/data
```

### 1.7 Kubernetes Deployment

#### Basic Deployment

```yaml
# k8s/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: archon
  namespace: archon-system
spec:
  replicas: 2
  selector:
    matchLabels:
      app: archon
  template:
    metadata:
      labels:
        app: archon
    spec:
      containers:
        - name: archon
          image: your-registry/archon:latest
          envFrom:
            - secretRef:
                name: archon-secrets
            - configMapRef:
                name: archon-config
          volumeMounts:
            - name: harness
              mountPath: /app/.harness
      volumes:
        - name: harness
          persistentVolumeClaim:
            claimName: archon-harness-pvc
```

#### Create Secret

```bash
kubectl create secret generic archon-secrets \
  --from-literal=ANTHROPIC_API_KEY=sk-ant-... \
  --from-literal=LITELLM_MASTER_KEY=sk-litellm-... \
  --from-literal=REDIS_URL=redis://redis-service:6379/0 \
  --from-literal=AITOP_PROJECT_TOKEN=your-token \
  -n archon-system
```

#### ConfigMap

```yaml
# k8s/configmap.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: archon-config
  namespace: archon-system
data:
  ARCHON_LOG_LEVEL: "INFO"
  ARCHON_ENV: "production"
  ARCHON_MAX_CONCURRENT_TASKS: "4"
  CHROMA_HOST: "chroma-service"
  CHROMA_PORT: "8000"
  OLLAMA_BASE_URL: "http://ollama-service:11434"
  AITOP_SERVER_URL: "http://aitop-service:8080"
  RAY_ADDRESS: "auto"
```

#### KubeRay Integration

To run a Ray cluster on Kubernetes, use the KubeRay operator. See [Section 10: KubeRay Operations](#10-kuberay-operations) for the full setup.

---

## 2. Environment Variables

Copy `.env.example` to `.env` and fill in the values below. Each variable includes an explanation of **why it matters**.

### Core API Keys

```dotenv
# Anthropic — used by the Orchestrator and Reviewer agents
# Without this, the Orchestrator will not start
ANTHROPIC_API_KEY=sk-ant-...

# LiteLLM proxy master key — unifies multiple LLM providers behind a single endpoint
LITELLM_MASTER_KEY=sk-litellm-...

# LiteLLM internal DB — stores proxy configuration and usage logs
DATABASE_URL=sqlite:///litellm.db
```

### Memory Backends

```dotenv
# Redis (L1 scratchpad) — real-time context sharing between agents
# Format: redis://[password@]host:port/db_number
REDIS_URL=redis://localhost:6379/0
REDIS_TTL=86400                    # Key expiry in seconds, default 24 hours

# ChromaDB (L2 vector store) — codebase embedding search
CHROMA_HOST=localhost
CHROMA_PORT=8000
CHROMA_COLLECTION_PREFIX=archon    # Collection name prefix

# Mem0 (L3 long-term memory, optional) — retains learnings across projects
MEM0_API_KEY=m0-...
MEM0_USER_ID=archon-prod
```

### Local LLM

```dotenv
# Ollama — local open-source model server
OLLAMA_BASE_URL=http://localhost:11434
```

### AITOP Monitoring

```dotenv
# AITOP — AI agent observability server
# Sends traces via OTLP/HTTP protocol
AITOP_SERVER_URL=http://localhost:8080
AITOP_PROJECT_TOKEN=               # Per-project auth token
```

### Observability (Optional)

```dotenv
# LangSmith — LLM call tracing (optional)
LANGSMITH_API_KEY=ls-...

# Langfuse — open-source LLM observability (optional)
LANGFUSE_HOST=http://localhost:3100
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
```

### Dashboard

```dotenv
# CORS — origins allowed to access the API server
# Separate multiple origins with commas
ARCHON_CORS_ORIGINS=http://localhost:3000,http://localhost:8501
```

### Notifications

```dotenv
# Slack — sends gate decisions to a Slack channel
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...

# PagerDuty — alerts on L3_HALT and above
PAGERDUTY_INTEGRATION_KEY=...
```

### Ray

```dotenv
# Ray cluster address — "auto" connects to the local cluster automatically
RAY_ADDRESS=auto
```

### Runtime

```dotenv
# Log level — set DEBUG for detailed LLM call traces
ARCHON_LOG_LEVEL=INFO              # DEBUG / INFO / WARNING / ERROR

# Environment — disables debug output in production
ARCHON_ENV=development             # development / production

# Concurrency — how many tasks TaskScheduler runs in parallel
ARCHON_MAX_CONCURRENT_TASKS=4

# Timeout — max execution time per agent (seconds)
ARCHON_DEFAULT_TIMEOUT=120
```

---

## 3. LLM Model Configuration

Archon is designed to mix and match LLM providers flexibly. This section covers provider setup and per-agent model assignment.

### 3.1 LiteLLM Proxy Setup

The LiteLLM proxy unifies multiple providers (Anthropic, OpenAI, Ollama, vLLM, etc.) behind a single endpoint (`http://localhost:4000`). Swap providers by changing config, not code.

```bash
# Install LiteLLM
pip install litellm[proxy]

# Start proxy server
litellm --config config/litellm_config.yaml --port 4000
```

```yaml
# config/litellm_config.yaml (example)
model_list:
  # Anthropic models
  - model_name: orchestrator
    litellm_params:
      model: claude-sonnet-4-6
      api_key: os.environ/ANTHROPIC_API_KEY

  # Ollama local models
  - model_name: backend-agent
    litellm_params:
      model: ollama/llama3.3:70b
      api_base: http://localhost:11434
      stream: true

  - model_name: tester-agent
    litellm_params:
      model: ollama/deepseek-v3.2:7b
      api_base: http://localhost:11434

  # vLLM GPU models
  - model_name: backend-agent-gpu
    litellm_params:
      model: openai/meta-llama/Llama-3.3-70B-Instruct
      api_base: http://gpu-node-01:8000
      stream: true

general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
  database_url: os.environ/DATABASE_URL
```

### 3.2 Ollama Setup

```bash
# 1. Install Ollama (if not already done)
# macOS
brew install ollama
# Linux
curl -fsSL https://ollama.com/install.sh | sh

# 2. Start the service
ollama serve

# 3. Pull models
ollama pull llama3.3:70b        # Backend agent (quality)
ollama pull deepseek-v3.2:7b    # Tester agent (speed)
ollama pull deepseek-v3.2:70b   # Complex tasks

# 4. Verify models are installed
ollama list

# 5. Register endpoints in LiteLLM (see litellm_config.yaml above)
```

> **Tip:** Ollama models take time to load on first request. Warm them up with `ollama run llama3.3:70b "hello"` to avoid cold-start latency.

### 3.3 vLLM Setup (GPU Server)

Use this when you have dedicated GPU hardware and want maximum inference throughput.

```bash
# Run vLLM server on GPU node
python -m vllm.entrypoints.openai.api_server \
  --model meta-llama/Llama-3.3-70B-Instruct \
  --tensor-parallel-size 2 \
  --gpu-memory-utilization 0.9 \
  --port 8000
```

```python
# Inject VLLMBridge into Orchestrator
from src.runtime.vllm_bridge import VLLMBridge, VLLMEndpoint

bridge = VLLMBridge(timeout=5.0)
bridge.register(VLLMEndpoint(
    name="vllm/backend-llm",
    base_url="http://gpu-node-01:8000",
    model_name="meta-llama/Llama-3.3-70B-Instruct",
    gpu_memory_utilization=0.9,
    tensor_parallel_size=2,
    tags=["backend"],
))
await bridge.health_check_all()
```

### 3.4 Provider Routing Chain

Archon selects model providers in this priority order:

```
vLLM (GPU) -> Ollama (local CPU/GPU) -> Default (Anthropic/OpenAI API)
```

If the vLLM server is unresponsive, it falls back to Ollama. If Ollama is also unavailable, it uses the cloud API. This chain optimizes for both cost and availability.

### 3.5 Per-Agent Model Assignment

Set the model for each agent role in the `agent_config` section of the Registry JSON.

```json
{
  "agent_config": {
    "orchestrator": {
      "model": "claude-sonnet-4-6",
      "max_tokens": 8192,
      "temperature": 0.2,
      "streaming": true,
      "timeout_seconds": 120
    },
    "backend": {
      "model": "ollama/llama3.3:70b",
      "max_tokens": 8192,
      "temperature": 0.2,
      "high_complexity_model": "ollama/deepseek-v3.2:70b"
    },
    "tester": {
      "model": "ollama/deepseek-v3.2:7b",
      "max_tokens": 4096,
      "temperature": 0.1
    },
    "reviewer": {
      "model": "claude-sonnet-4-6",
      "max_tokens": 4096,
      "temperature": 0.1
    }
  }
}
```

### 3.6 Complexity-Based Dynamic Model Selection

When you set `high_complexity_model`, the Complexity Router automatically analyzes task difficulty and switches models accordingly.

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

The Complexity Router evaluates 8 criteria:
- File count, diff line count, dependency depth, cyclomatic complexity, etc.
- When the score is HIGH, it automatically selects `high_complexity_model`
- Simple tasks get a small, fast model; complex tasks get a large, accurate model — balancing cost and quality

---

## 4. Observability & Monitoring

Observability answers three questions: **what did the agents do, how long did it take, and how much did it cost?** Archon supports multiple tracing backends simultaneously.

### 4.1 TracingConfig Setup

```python
from src.observability.tracing import TracingConfig

config = TracingConfig(
    enabled=True,                    # Set False to disable all tracing
    backend="composite",             # Single: "langsmith", "langfuse", "aitop"
                                     # Multiple: "composite"
    sample_rate=1.0,                 # 1.0 = trace every request
                                     # 0.1 = trace 10% (recommended for production)
    export_interval_seconds=30,      # Batch export interval
)
```

### 4.2 LangSmith Backend

LangSmith is the observability platform from the LangChain team.

```dotenv
LANGSMITH_API_KEY=ls-...
```

```python
from src.observability.tracing import LangSmithTracer

tracer = LangSmithTracer(
    api_key=os.environ["LANGSMITH_API_KEY"],
    project_name="archon-production",
)
```

### 4.3 Langfuse Backend

Langfuse is a self-hostable, open-source LLM observability tool.

```dotenv
LANGFUSE_HOST=http://localhost:3100
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
```

```python
from src.observability.tracing import LangfuseTracer

tracer = LangfuseTracer(
    host=os.environ["LANGFUSE_HOST"],
    public_key=os.environ["LANGFUSE_PUBLIC_KEY"],
    secret_key=os.environ["LANGFUSE_SECRET_KEY"],
)
```

### 4.4 AITOP Backend (OTLP/HTTP)

AITOP collects agent traces using the OTLP/HTTP protocol.

```dotenv
AITOP_SERVER_URL=http://localhost:8080
AITOP_PROJECT_TOKEN=your-project-token
```

```python
from src.observability.tracing import AitopTracer

tracer = AitopTracer(
    server_url=os.environ["AITOP_SERVER_URL"],
    project_token=os.environ["AITOP_PROJECT_TOKEN"],
)
```

### 4.5 CompositeTracer (Multiple Backends)

Send traces to multiple backends simultaneously. For example, LangSmith during development and AITOP in production.

```python
from src.observability.tracing import CompositeTracer

tracer = CompositeTracer(tracers=[
    LangSmithTracer(api_key="..."),
    AitopTracer(server_url="...", project_token="..."),
])
```

### 4.6 SamplingTracer (Production Optimization)

Tracing every request in production adds overhead. SamplingTracer lets you trace only a fraction of requests.

```python
from src.observability.tracing import SamplingTracer

# Trace 10% of requests
tracer = SamplingTracer(
    inner=CompositeTracer(tracers=[...]),
    sample_rate=0.1,
)
```

> **Why sampling?** In production, sending a trace for every request inflates network costs and storage. A 10% sample rate is typically enough to detect anomalous patterns.

### 4.7 TracingMiddleware Integration

Wire TracingMiddleware into the Orchestrator and BaseAgent to automatically trace all LLM calls.

```python
from src.observability.tracing import TracingMiddleware

middleware = TracingMiddleware(tracer=tracer)

# Attach to Orchestrator
orchestrator = Orchestrator(
    middleware=[middleware],
    # ...
)

# Or attach directly to a BaseAgent
agent = BackendAgent(
    tracing_middleware=middleware,
    # ...
)
```

### 4.8 Viewing Traces

| Backend | How to Access |
|---|---|
| LangSmith | Visit https://smith.langchain.com and select your project |
| Langfuse | Navigate to your `LANGFUSE_HOST` URL, open the Traces tab |
| AITOP | Navigate to your `AITOP_SERVER_URL`, open the project dashboard |

### 4.9 Logs

Archon uses Python's standard `logging` module.

```dotenv
ARCHON_LOG_LEVEL=INFO   # Set DEBUG for detailed LLM call traces
```

Structured log example:

```
2026-04-24 12:00:01 INFO  [orchestrator] Task started: task-payment-002
2026-04-24 12:00:05 INFO  [backend_agent] execute() completed in 4.2s
2026-04-24 12:00:05 INFO  [qa] run_qa_pipeline() passed: ruff=OK mypy=OK pytest=12passed
2026-04-24 12:00:06 INFO  [gate] Decision: AUTO_PASS (score=92)
```

### 4.10 Human Gate Notifications

`CompositeNotifier` fans out gate events to every registered channel.

| Gate | TerminalNotifier | SlackNotifier | PagerDuty |
|---|---|---|---|
| AUTO_PASS | green banner | - | - |
| L1_REWORK | yellow banner | sent | - |
| L2_HUMAN | red banner | sent | - |
| L3_HALT | red banner | sent | sent |
| L4_DEPLOY | blue banner | sent | sent |

---

## 5. Guardrails Operations

Guardrails ensure agents operate **within permitted boundaries**. They prevent token budget overruns, sensitive data exposure, and protected path modifications before they happen.

### 5.1 GuardrailPolicy Configuration

```python
from src.guardrails.policy import GuardrailPolicy

policy = GuardrailPolicy(
    # Token budget management
    daily_token_limit=1_000_000,        # Daily token ceiling
    per_task_token_limit=50_000,        # Per-task token ceiling
    budget_alert_threshold=0.8,         # Warn at 80% consumption

    # Sensitive data detection
    sensitive_patterns=[
        r"(?i)password\s*=\s*['\"].*['\"]",
        r"(?i)api[_-]?key\s*=\s*['\"].*['\"]",
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",  # email
    ],

    # Protected paths — agents cannot modify these files/directories
    protected_paths=[
        ".harness/sop/production/",
        ".env",
        "config/litellm_config.yaml",
    ],

    # High-risk paths — changes here auto-escalate to Human Gate
    high_risk_paths=[
        "src/core/",
        "migrations/",
    ],

    # Violation action: "block" (halt immediately) or "warn" (log and continue)
    violation_action="block",
)
```

### 5.2 Token Budget Management

```python
# Check current usage
usage = policy.get_daily_usage()
print(f"Today's usage: {usage.tokens_used:,} / {usage.daily_limit:,}")
print(f"Remaining: {usage.tokens_remaining:,}")

# Set up budget alert callback
policy.on_budget_alert = lambda usage: notify_slack(
    f"Token budget at {usage.percent_used:.0%} ({usage.tokens_used:,} / {usage.daily_limit:,})"
)

# Manual daily reset (emergency only)
policy.reset_daily()
```

> **Why set a token budget?** An agent stuck in a loop or processing an unexpectedly large context can burn through API credits fast. A daily ceiling catches runaway costs automatically.

### 5.3 Sensitive Data Detection Tuning

Add project-specific patterns to the defaults.

```python
# Add a custom pattern
policy.sensitive_patterns.append(
    r"(?i)aws[_-]?secret[_-]?access[_-]?key\s*=\s*['\"].*['\"]"
)

# If you get too many false positives, make patterns more specific
# Bad:  r"key" (too broad)
# Good: r"(?i)api[_-]?key\s*=\s*['\"][A-Za-z0-9]{20,}['\"]"
```

### 5.4 Path Protection Setup

```python
# Add a path
policy.protected_paths.append("database/migrations/")

# List protected paths
for path in policy.protected_paths:
    print(f"  Protected: {path}")
```

When an agent tries to modify a file under a protected path, a `ProtectedPathError` is raised and the operation is aborted.

### 5.5 Violation Actions: block vs warn

| Action | Behavior | When to Use |
|---|---|---|
| `block` | Immediately stops the operation | Production environments |
| `warn` | Logs a warning and continues | Development / testing |

```python
# During development, use warn to avoid breaking flow
policy.violation_action = "warn"

# In production, always use block
policy.violation_action = "block"
```

---

## 6. Self-Healing Operations

Self-healing monitors agent health and automatically recovers from failures. When an agent enters a DEAD state or response times degrade, the system acts without human intervention.

### 6.1 HealthMonitorRegistry Setup

```python
from src.self_healing.health import HealthMonitorRegistry, HealthThresholds

registry = HealthMonitorRegistry(
    thresholds=HealthThresholds(
        response_time_warning=5.0,    # WARNING above 5 seconds
        response_time_critical=15.0,  # CRITICAL above 15 seconds
        error_rate_warning=0.1,       # WARNING above 10% error rate
        error_rate_critical=0.3,      # CRITICAL above 30% error rate
        memory_usage_warning=0.8,     # WARNING above 80% memory
        memory_usage_critical=0.95,   # CRITICAL above 95% memory
    ),
)
```

### 6.2 Watchdog Configuration

The watchdog periodically checks agent health and takes configured actions when problems arise.

```python
from src.self_healing.watchdog import Watchdog, WatchdogConfig

config = WatchdogConfig(
    check_interval=30,            # Check every 30 seconds
    alert_on_warning=True,        # Send alerts on WARNING
    alert_on_critical=True,       # Send alerts on CRITICAL
    auto_heal=True,               # Enable automatic recovery
    max_heal_attempts=3,          # Max recovery attempts
    heal_cooldown=60,             # Seconds between recovery attempts
)

watchdog = Watchdog(
    health_registry=registry,
    config=config,
)
```

### 6.3 Alert Callbacks

```python
# Slack alerts
async def slack_alert(event):
    await send_slack_message(
        channel="#archon-alerts",
        text=f"[{event.severity}] {event.agent_name}: {event.message}",
    )

# PagerDuty alerts (CRITICAL only)
async def pagerduty_alert(event):
    if event.severity == "CRITICAL":
        await trigger_pagerduty(
            integration_key=os.environ["PAGERDUTY_INTEGRATION_KEY"],
            summary=f"Archon Agent Down: {event.agent_name}",
        )

# Register callbacks
watchdog.on_alert(slack_alert)
watchdog.on_alert(pagerduty_alert)
```

### 6.4 Recovery Strategies

Archon tries four recovery strategies in sequence:

| Step | Strategy | Description |
|---|---|---|
| 1 | `model_downgrade` | Switch to a smaller, more stable model (e.g., 70B to 7B) |
| 2 | `agent_reinit` | Reinitialize the agent (state reset) |
| 3 | `substitute` | Replace with an alternate agent of the same role |
| 4 | `escalate` | Escalate to a human (Human Gate L3_HALT) |

```python
from src.self_healing.strategies import RecoveryStrategy

# Customize the recovery order
watchdog.recovery_strategies = [
    RecoveryStrategy.MODEL_DOWNGRADE,
    RecoveryStrategy.AGENT_REINIT,
    RecoveryStrategy.SUBSTITUTE,
    RecoveryStrategy.ESCALATE,
]
```

### 6.5 Diagnostic Reports

```python
# Generate a diagnostic report
report = await watchdog.generate_diagnostic_report()

print(report.summary)
# Example output:
# Agent Health Report (2026-04-24 12:00:00)
# ----------------------------------------
# backend_agent: HEALTHY (response_time: 1.2s, error_rate: 0.02)
# tester_agent:  WARNING (response_time: 6.3s, error_rate: 0.05)
# reviewer:      CRITICAL (response_time: 18.1s, error_rate: 0.35)
#
# Recommendations:
# - reviewer: Consider model_downgrade or check LLM provider status

for agent_report in report.agents:
    if agent_report.status != "HEALTHY":
        print(f"  {agent_report.name}: {agent_report.recommendations}")
```

---

## 7. Dashboard Operations

The dashboard provides a web interface for real-time monitoring and Human Gate queue management.

### 7.1 Starting the Dashboard Server

```bash
# Prerequisites
pip install fastapi uvicorn websockets

# Start the API server
python -m src.dashboard.server --host 0.0.0.0 --port 8000

# Start the frontend (separate terminal)
cd dashboard
npm install
npm run dev    # http://localhost:3000
```

### 7.2 CORS Configuration

The dashboard frontend needs CORS access to the API server.

```dotenv
# .env
ARCHON_CORS_ORIGINS=http://localhost:3000,http://localhost:8501
```

> **Why CORS?** Browsers block cross-origin requests by default. Since the dashboard (port 3000) talks to the API server (port 8000), you must explicitly allow the origin.

### 7.3 API Endpoints Overview

| Method | Path | Description |
|---|---|---|
| GET | `/api/health` | Server health check |
| GET | `/api/tasks` | List in-progress tasks |
| GET | `/api/tasks/{id}` | Task details |
| GET | `/api/agents/status` | Agent status |
| GET | `/api/gate/queue` | Human Gate pending queue |
| POST | `/api/gate/{id}/approve` | Approve a gate item |
| POST | `/api/gate/{id}/reject` | Reject a gate item |
| GET | `/api/metrics/cost` | Cost metrics |
| GET | `/api/metrics/tokens` | Token usage |

### 7.4 WebSocket Events

The dashboard uses WebSocket for real-time updates.

```javascript
// ws://localhost:8000/ws
const ws = new WebSocket("ws://localhost:8000/ws");

ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    // Event types:
    // - task_started:   A task has begun
    // - task_completed: A task has finished
    // - gate_pending:   A Human Gate decision is needed
    // - agent_status:   An agent's status changed
    // - cost_update:    Cost metrics updated
    console.log(data.type, data.payload);
};
```

### 7.5 Human Gate Queue Management

You can review and act on Human Gate items from the dashboard or the CLI.

```bash
# List pending items
curl http://localhost:8000/api/gate/queue

# Approve
curl -X POST http://localhost:8000/api/gate/{id}/approve \
  -H "Content-Type: application/json" \
  -d '{"reviewer": "username", "comment": "LGTM"}'

# Reject (reason required)
curl -X POST http://localhost:8000/api/gate/{id}/reject \
  -H "Content-Type: application/json" \
  -d '{"reviewer": "username", "reason": "Needs security review"}'
```

### 7.6 Cost Monitoring

The Cost tab in the dashboard shows real-time spend.

```bash
# Query cost via API
curl http://localhost:8000/api/metrics/cost?period=today
# Example response:
# {
#   "period": "2026-04-24",
#   "total_cost_usd": 12.45,
#   "by_model": {
#     "claude-sonnet-4-6": 8.20,
#     "ollama/llama3.3:70b": 0.00,
#     "ollama/deepseek-v3.2:7b": 0.00
#   },
#   "by_agent": {
#     "orchestrator": 5.10,
#     "backend": 4.80,
#     "reviewer": 2.55
#   }
# }
```

---

## 8. Benchmark Operations

Benchmarks measure per-agent model performance so you can find the optimal model assignment for your workload.

### 8.1 Running Benchmarks

```bash
# Run the default benchmark suite
python -m src.benchmark run --config benchmarks/default.yaml

# Benchmark a specific agent with specific models
python -m src.benchmark run --agent backend --models "ollama/llama3.3:70b,ollama/deepseek-v3.2:7b"

# Specify output path
python -m src.benchmark run --output benchmarks/results/2026-04-24.json
```

### 8.2 Custom Benchmark Tasks

```yaml
# benchmarks/custom_tasks.yaml
tasks:
  - name: "Create API endpoint"
    description: "Write FastAPI CRUD endpoints"
    complexity: "medium"
    expected_files: ["src/api/users.py", "tests/test_users.py"]
    evaluation_criteria:
      - "Uses type hints"
      - "Includes error handling"
      - "Test coverage above 50%"

  - name: "Database migration"
    description: "Add email column to users table"
    complexity: "low"
    expected_files: ["migrations/003_add_email.py"]
```

```bash
python -m src.benchmark run --tasks benchmarks/custom_tasks.yaml
```

### 8.3 Interpreting Results

```bash
# View results
python -m src.benchmark report --input benchmarks/results/2026-04-24.json

# Example output:
# +------------------+----------------------+----------+----------+---------+
# | Agent            | Model                | Score    | Latency  | Cost    |
# +------------------+----------------------+----------+----------+---------+
# | backend          | ollama/llama3.3:70b  | 87/100   | 12.3s    | $0.00   |
# | backend          | claude-sonnet-4-6    | 94/100   | 3.1s     | $0.12   |
# | tester           | ollama/deepseek:7b   | 72/100   | 2.1s     | $0.00   |
# | tester           | claude-haiku-4-5     | 89/100   | 1.2s     | $0.01   |
# +------------------+----------------------+----------+----------+---------+
```

### 8.4 Applying Model Recommendations

```bash
# Get model recommendations based on results
python -m src.benchmark recommend --input benchmarks/results/2026-04-24.json

# Auto-apply recommendations to the Registry
python -m src.benchmark apply --input benchmarks/results/2026-04-24.json --registry .harness/registry/my-project.json
```

### 8.5 Scheduling Periodic Benchmarks

```bash
# Weekly benchmark via cron (every Sunday at 02:00)
# crontab -e
0 2 * * 0 cd /path/to/archon-framework && python -m src.benchmark run --output benchmarks/results/$(date +\%Y-\%m-\%d).json
```

---

## 9. Evolution Loop Operations

The evolution loop lets Archon **learn from execution results and improve itself**. Over many runs, it automatically tunes GuardrailPolicy, model assignments, and agent parameters.

### 9.1 Enabling the Evolution Loop

```python
from src.evolution.loop import EvolutionLoop, EvolutionConfig

config = EvolutionConfig(
    enabled=True,                     # False disables the evolution loop
    min_executions=10,                # Start tuning only after 10 runs
    evaluation_window=50,             # Evaluate based on the last 50 runs
    improvement_threshold=0.05,       # Only change policy if improvement > 5%
    max_tuning_actions_per_cycle=3,   # Max 3 actions per cycle
)

loop = EvolutionLoop(config=config)
```

> **Why `min_executions`?** With too few data points, statistical patterns are unreliable. Waiting for enough data prevents premature (and likely wrong) optimizations.

### 9.2 EvolutionConfig Tuning

| Parameter | Default | Description |
|---|---|---|
| `enabled` | `False` | Enable/disable the evolution loop |
| `min_executions` | 10 | Minimum runs before tuning starts |
| `evaluation_window` | 50 | Number of recent runs to evaluate |
| `improvement_threshold` | 0.05 | Minimum improvement ratio to change policy |
| `max_tuning_actions_per_cycle` | 3 | Max tuning actions per cycle |
| `cycle_interval_seconds` | 3600 | Seconds between cycles |

### 9.3 Understanding Tuning Actions

Actions the evolution loop can perform:

| Action | Description | Example |
|---|---|---|
| `adjust_model` | Change agent model | 7B to 70B (when quality is low) |
| `adjust_temperature` | Tune temperature | 0.2 to 0.1 (improve consistency) |
| `adjust_token_limit` | Adjust task token limit | 50K to 80K (when tasks hit ceiling) |
| `adjust_timeout` | Adjust agent timeout | 120s to 180s (frequent timeouts) |
| `adjust_threshold` | Adjust gate thresholds | 85 to 80 (when AUTO_PASS rate is low) |

### 9.4 on_policy_updated Callback

Register a callback to persist policy changes or send notifications.

```python
async def persist_policy(old_policy, new_policy, actions):
    """Save policy changes and notify Slack."""
    # Persist changes
    registry.save()

    # Slack notification
    changes = "\n".join(f"  - {a.action}: {a.description}" for a in actions)
    await send_slack_message(
        channel="#archon-evolution",
        text=f"Policy updated:\n{changes}",
    )

loop.on_policy_updated = persist_policy
```

### 9.5 Monitoring Evolution Cycle Results

```python
# View recent cycle results
results = loop.get_recent_cycles(n=5)
for cycle in results:
    print(f"Cycle #{cycle.number} ({cycle.timestamp})")
    print(f"  Window: last {cycle.window_size} runs")
    print(f"  Success rate: {cycle.success_rate:.1%}")
    print(f"  Avg latency: {cycle.avg_latency:.1f}s")
    print(f"  Actions: {len(cycle.actions)}")
    for action in cycle.actions:
        print(f"    - {action.action}: {action.description}")
```

---

## 10. KubeRay Operations

KubeRay lets you manage Ray clusters on Kubernetes, distributing agent workloads across worker pods.

### 10.1 KubeRay Cluster Deployment

```bash
# 1. Install KubeRay operator
helm repo add kuberay https://ray-project.github.io/kuberay-helm/
helm repo update
helm install kuberay-operator kuberay/kuberay-operator --namespace ray-system --create-namespace

# 2. Deploy a RayCluster
kubectl apply -f k8s/ray-cluster.yaml
```

```yaml
# k8s/ray-cluster.yaml
apiVersion: ray.io/v1
kind: RayCluster
metadata:
  name: archon-ray
  namespace: archon-system
spec:
  rayVersion: "2.9.0"
  headGroupSpec:
    rayStartParams:
      dashboard-host: "0.0.0.0"
    template:
      spec:
        containers:
          - name: ray-head
            image: your-registry/archon-ray:latest
            resources:
              limits:
                cpu: "4"
                memory: "8Gi"
              requests:
                cpu: "2"
                memory: "4Gi"
            ports:
              - containerPort: 6379    # Ray GCS
              - containerPort: 8265    # Dashboard
  workerGroupSpecs:
    - replicas: 2
      minReplicas: 1
      maxReplicas: 10
      groupName: default-worker
      rayStartParams: {}
      template:
        spec:
          containers:
            - name: ray-worker
              image: your-registry/archon-ray:latest
              resources:
                limits:
                  cpu: "4"
                  memory: "16Gi"
                requests:
                  cpu: "2"
                  memory: "8Gi"
```

### 10.2 Worker Group Configuration

Configure different worker types for different workloads.

```yaml
workerGroupSpecs:
  # CPU workers (general agent tasks)
  - replicas: 2
    groupName: cpu-workers
    template:
      spec:
        containers:
          - name: ray-worker
            resources:
              limits:
                cpu: "4"
                memory: "16Gi"

  # GPU workers (vLLM inference)
  - replicas: 1
    groupName: gpu-workers
    template:
      spec:
        containers:
          - name: ray-worker
            resources:
              limits:
                cpu: "8"
                memory: "32Gi"
                nvidia.com/gpu: "2"
        nodeSelector:
          cloud.google.com/gke-accelerator: nvidia-tesla-a100
```

### 10.3 Autoscaling Configuration

```yaml
workerGroupSpecs:
  - replicas: 2
    minReplicas: 1       # Minimum worker count
    maxReplicas: 10      # Maximum worker count (cost ceiling)
    groupName: default-worker
    # KubeRay scales workers automatically based on Ray resource demand
```

> **Why autoscaling?** Workloads are bursty — heavy during business hours, quiet at night. Autoscaling provisions resources only when needed, significantly reducing cloud costs.

### 10.4 Cluster Monitoring

```bash
# Check RayCluster status
kubectl get raycluster -n archon-system

# Access the Ray Dashboard (port-forward)
kubectl port-forward svc/archon-ray-head-svc 8265:8265 -n archon-system
# Open http://localhost:8265 in your browser

# Check worker status
kubectl get pods -l ray.io/cluster=archon-ray -n archon-system

# View logs
kubectl logs -l ray.io/node-type=head -n archon-system
```

### 10.5 Troubleshooting

```bash
# Workers not starting
kubectl describe pod <pod-name> -n archon-system
# Check the Events section for causes (image pull failure, insufficient resources, etc.)

# Cannot connect to Ray head
kubectl exec -it <head-pod> -n archon-system -- ray status

# CUDA errors on GPU workers
kubectl logs <gpu-worker-pod> -n archon-system | grep -i "cuda\|gpu\|error"
```

---

## 11. Hybrid Cloud Operations

The hybrid cloud strategy blends local GPU hardware with cloud APIs to balance cost and performance.

### 11.1 Strategy Selection

```python
from src.runtime.hybrid_cloud import HybridCloudStrategy

strategy = HybridCloudStrategy(
    # Priority: local first, cloud as fallback
    prefer_local=True,

    # Use cloud only when all local GPUs are busy
    cloud_fallback=True,

    # Budget ceilings
    daily_cloud_budget_usd=50.0,
    monthly_cloud_budget_usd=1000.0,

    # Latency ceiling — switch to cloud if local exceeds this
    max_local_latency_seconds=30.0,
)
```

### 11.2 Budget Management

```python
# Check current spend
usage = strategy.get_cloud_usage()
print(f"Today: ${usage.daily_spent:.2f} / ${usage.daily_budget:.2f}")
print(f"This month: ${usage.monthly_spent:.2f} / ${usage.monthly_budget:.2f}")

# When the budget is exceeded, Archon automatically runs local-only
# Emergency budget override
strategy.daily_cloud_budget_usd = 100.0
```

### 11.3 GPU Resource Registration

```python
# Register local GPU servers
strategy.register_gpu_resource(
    name="office-gpu-01",
    gpu_type="RTX 4090",
    gpu_count=2,
    vram_gb=48,
    base_url="http://192.168.1.100:8000",
)

strategy.register_gpu_resource(
    name="office-gpu-02",
    gpu_type="A100",
    gpu_count=4,
    vram_gb=320,
    base_url="http://192.168.1.101:8000",
)

# List registered resources
for gpu in strategy.list_gpu_resources():
    print(f"  {gpu.name}: {gpu.gpu_type} x{gpu.gpu_count} ({gpu.status})")
```

### 11.4 Monitoring Cloud Spend

```python
# Budget warning callback
strategy.on_budget_warning = lambda usage: send_slack_message(
    channel="#archon-cost",
    text=f"Cloud budget at {usage.daily_percent:.0%} (${usage.daily_spent:.2f})",
)

# Generate a cost report
report = strategy.generate_cost_report(period="monthly")
print(report.to_table())
```

### 11.5 Spot Instance Considerations

Using spot/preemptible instances for cloud GPUs can save 60-90%.

```python
strategy.spot_instance_config = {
    "enabled": True,
    "max_interruption_rate": 0.1,    # Accept up to 10% interruption rate
    "fallback_to_on_demand": True,   # Fall back to on-demand if spot unavailable
}
```

> **Caution:** Spot instances can be terminated at any time. Use on-demand for long tasks (30+ minutes) and spot only for short inference bursts.

---

## 12. Transaction Snapshots

Transaction snapshots let you save system state before risky operations and roll back if something goes wrong.

### 12.1 Saving a Snapshot

```python
from src.transaction.snapshot import SnapshotManager

manager = SnapshotManager()

# Save a snapshot before a risky operation
snapshot_id = await manager.save_snapshot(
    label="before-migration",          # Human-readable label
    include_registry=True,             # Include Registry state
    include_scratchpad=True,           # Include Redis scratchpad
    metadata={"task_id": "task-042"},  # Additional metadata
)
print(f"Snapshot saved: {snapshot_id}")
```

### 12.2 Rolling Back

```python
# Roll back on failure
try:
    await execute_risky_migration()
except Exception as e:
    print(f"Error: {e}, rolling back to snapshot")
    await manager.rollback_to_snapshot(snapshot_id)
    print("Rollback complete")
```

### 12.3 Snapshot Management

```python
# List snapshots
snapshots = manager.list_snapshots()
for s in snapshots:
    print(f"  [{s.id}] {s.label} ({s.created_at}) -- {s.size_bytes / 1024:.1f}KB")

# Delete a specific snapshot
manager.delete_snapshot(snapshot_id)

# Bulk delete old snapshots
manager.clear_snapshots(older_than_days=7)
```

### 12.4 MAX_SNAPSHOTS Limit

A maximum of 20 snapshots are retained. When exceeded, the oldest snapshot is automatically deleted.

```python
# Adjust the retention limit (default: 20)
manager = SnapshotManager(max_snapshots=20)
```

> **Why the 20-snapshot limit?** Snapshots include Registry and scratchpad data, consuming disk space. Unlimited retention can cause storage issues, so we keep a practical ceiling.

---

## 13. Backup and Recovery

### 13.1 What to Back Up

| Data | Location | Method |
|---|---|---|
| Project Registry | `.harness/registry/*.json` | file copy / git |
| SOP documents | `.harness/sop/` | file copy / git |
| Redis scratchpad | Redis DB | `redis-cli SAVE` |
| ChromaDB vectors | `chroma_data/` | directory copy |
| Mem0 long-term memory | Mem0 cloud | Mem0 dashboard |
| Benchmark results | `benchmarks/results/` | file copy / git |
| Transaction snapshots | `.harness/snapshots/` | file copy |
| Dashboard data | Dashboard DB | API export |

### 13.2 Registry Backup

Managing `.harness/registry/` in git is strongly recommended.

```bash
git add .harness/registry/
git commit -m "chore: registry snapshot $(date +%Y-%m-%d)"
git push origin main
```

### 13.3 Redis Backup

```bash
# Create a snapshot (use BGSAVE in production)
redis-cli BGSAVE

# Copy the dump file
cp /var/lib/redis/dump.rdb /backup/redis-$(date +%Y%m%d).rdb
```

#### Restore

```bash
sudo systemctl stop redis
cp /backup/redis-20260424.rdb /var/lib/redis/dump.rdb
sudo systemctl start redis
```

### 13.4 ChromaDB Backup

```bash
tar -czf chroma-backup-$(date +%Y%m%d).tar.gz ./chroma_data/
```

#### Restore

```bash
tar -xzf chroma-backup-20260424.tar.gz
```

### 13.5 Snapshot-Based Recovery

Transaction snapshots let you restore system state to a specific point in time.

```python
# List available snapshots
snapshots = manager.list_snapshots()
for s in snapshots:
    print(f"  [{s.id}] {s.label} ({s.created_at})")

# Roll back to a chosen point
await manager.rollback_to_snapshot("snapshot-id-here")
```

### 13.6 Dashboard Data Export

```bash
# Export metrics as CSV
curl http://localhost:8000/api/metrics/export?format=csv > metrics-$(date +%Y%m%d).csv

# Export as JSON
curl http://localhost:8000/api/metrics/export?format=json > metrics-$(date +%Y%m%d).json
```

### 13.7 Full Recovery Procedure

1. Restore `.env` environment variables
2. Restore Redis backup and restart
3. Restore ChromaDB backup and restart
4. Check out `.harness/registry/*.json` from git
5. Perform snapshot-based rollback if needed
6. Run `python -m src.demo.pipeline` to verify everything works

---

## 14. Troubleshooting FAQ

### Q1. `ModuleNotFoundError: No module named 'src'`

Make sure you are running from the project root with the `-m` flag.

```bash
cd /path/to/archon-framework
python -m src   # not: python src/main.py
```

### Q2. `ANTHROPIC_API_KEY` error

```bash
# Verify .env is loaded
cat .env | grep ANTHROPIC
# Or export directly
export ANTHROPIC_API_KEY=sk-ant-...
```

### Q3. Redis connection refused

```
ConnectionRefusedError: [Errno 61] Connection refused
```

Redis is not running or is on a different port. The in-memory fallback activates automatically, but data will be lost on restart — always connect Redis in production.

```bash
redis-cli ping   # PONG = healthy
brew services start redis     # macOS
sudo systemctl start redis    # Linux
```

### Q4. ChromaDB `Collection not found`

Collections are created automatically on first run. If the error persists, check your ChromaDB version.

```bash
pip show chromadb   # 0.4.x recommended
```

### Q5. Gate always returns L2_HUMAN

Dynamic Guardrails may be triggering the escalation. If any changed file path matches `high_risk_paths` or `high_risk_keywords`, the gate automatically escalates to L2.

```python
print(registry.quality_policy.high_risk_paths)
print(registry.quality_policy.high_risk_keywords)
```

Check whether the changed file paths match the risk patterns and adjust the policy if needed.

### Q6. `ProtectedPathError` raised

```
ProtectedPathError: Attempt to modify protected path: .harness/sop/production/
```

An agent tried to modify a file under `protected_paths`. If the modification is intentional, remove the path from `protected_paths` or commit it manually.

### Q7. vLLM health check timeout

```
VLLMBridge: health check timeout for vllm/backend-llm
```

```python
# Increase timeout and retry
bridge = VLLMBridge(timeout=30.0)
await bridge.health_check_all()
```

Check the GPU worker logs to confirm the model has finished loading.

### Q8. Dashboard won't start

```
ModuleNotFoundError: No module named 'fastapi'
```

Ensure FastAPI and uvicorn are installed.

```bash
pip install fastapi uvicorn websockets
python -m src.dashboard.server --host 0.0.0.0 --port 8000
```

If you see CORS errors in the browser, make sure `ARCHON_CORS_ORIGINS` includes the dashboard URL.

### Q9. Ollama model not found

```
Error: model 'llama3.3:70b' not found
```

```bash
# 1. Check if the model is downloaded
ollama list

# 2. Pull the model if missing
ollama pull llama3.3:70b

# 3. Verify the Ollama server is running
curl http://localhost:11434/api/tags

# 4. Verify OLLAMA_BASE_URL is correct
echo $OLLAMA_BASE_URL   # should be http://localhost:11434
```

### Q10. AITOP traces not appearing

```bash
# 1. Verify AITOP server is running
curl http://localhost:8080/health

# 2. Check environment variables
echo $AITOP_SERVER_URL       # http://localhost:8080
echo $AITOP_PROJECT_TOKEN    # must not be empty

# 3. Confirm TracingConfig has enabled=True
# 4. Check that no firewall is blocking the port
```

### Q11. Token budget exceeded

```
TokenBudgetExceeded: Daily token limit reached (1,000,000 / 1,000,000)
```

```python
# Check current usage
usage = policy.get_daily_usage()
print(f"Usage: {usage.tokens_used:,} / {usage.daily_limit:,}")

# Emergency daily reset
policy.reset_daily()

# Or raise the limit
policy.daily_token_limit = 2_000_000
```

### Q12. Agent stuck in DEAD state

```
Agent 'backend_agent' is in DEAD state
```

```python
# 1. Check SelfHealer config
print(watchdog.config)

# 2. Ensure auto_heal is enabled
watchdog.config.auto_heal = True

# 3. Attempt manual recovery
await watchdog.heal_agent("backend_agent")

# 4. Check the diagnostic report
report = await watchdog.generate_diagnostic_report()
print(report.agents["backend_agent"].recommendations)
```

### Q13. Evolution loop not running

```python
# 1. Verify enabled=True
print(loop.config.enabled)   # Must be True

# 2. Check if min_executions has been met
print(f"Current executions: {loop.execution_count}")
print(f"Minimum required: {loop.config.min_executions}")

# 3. Manually trigger a cycle
await loop.run_cycle()
```

### Q14. Cyclic dependency error in task scheduler

```
CyclicDependencyError: Cycle detected in task dependencies
```

`TaskScheduler` uses Kahn's topological sort. Remove the circular reference from the `depends_on` configuration.

```python
scheduler = TaskScheduler(tasks)
order = scheduler.topological_sort()  # returns sorted order if no cycle
```

### Q15. pytest failures blocking the QA pipeline

```python
# Temporarily relax requirements during development
from src.registry.models import QualityPolicy
policy = QualityPolicy(min_test_coverage=0)
```

---

## Related Docs

- [Quick Start](quickstart.md)
- [Architecture](architecture.md)
- [Registry Schema](registry-schema.md)
- [Plugin Development Guide](plugin-guide.md)
- [API Reference](api-reference.md)
