# Operations Guide

🇰🇷 [한국어](../ko/operations-guide.md)

> Version: 1.1.0 | Last updated: 2026-04-24

## Table of Contents

1. [Deployment](#1-deployment)
2. [Environment Variables](#2-environment-variables)
3. [LLM Model Configuration](#3-llm-model-configuration)
4. [Redis / ChromaDB Setup](#4-redis--chromadb-setup)
5. [Monitoring](#5-monitoring)
6. [Troubleshooting FAQ](#6-troubleshooting-faq)
7. [Backup and Recovery](#7-backup-and-recovery)

---

## 1. Deployment

### Local

#### Prerequisites

| Item | Version |
|---|---|
| Python | 3.11+ |
| pip / uv | latest |
| Redis | 7.x (optional — falls back to in-memory) |
| ChromaDB | 0.4.x (optional) |

```bash
# 1. Clone the repo
git clone https://github.com/your-org/archon-framework.git
cd archon-framework

# 2. Install dependencies
pip install -r requirements.txt

# 3. Set environment variables
cp .env.example .env
# Edit .env and fill in your API keys

# 4. Run mock demo (no LLM required)
python -m src.demo.pipeline

# 5. Run the real pipeline
python -m src --project-id my-project --task-id task-001
```

### Docker

```dockerfile
# Dockerfile (example)
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

#### Docker Compose (with Redis + ChromaDB)

```yaml
# docker-compose.yml
version: "3.9"

services:
  archon:
    build: .
    env_file: .env
    volumes:
      - ./.harness:/app/.harness
    depends_on:
      - redis
      - chroma

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data

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
docker-compose up -d
```

### Kubernetes

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
  --from-literal=REDIS_URL=redis://redis-service:6379 \
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
  ARCHON_MAX_CONCURRENT_TASKS: "4"
  CHROMA_HOST: "chroma-service"
  CHROMA_PORT: "8000"
```

---

## 2. Environment Variables

Copy `.env.example` to `.env` and fill in the values below.

### LLM API Keys

```dotenv
# Anthropic (orchestrator)
ANTHROPIC_API_KEY=sk-ant-...

# OpenAI (optional)
OPENAI_API_KEY=sk-...

# Groq (optional)
GROQ_API_KEY=gsk_...
```

### Memory Backends

```dotenv
# Redis (L1 scratchpad)
REDIS_URL=redis://localhost:6379
REDIS_TTL=86400          # seconds, default 86400 (24 hours)

# ChromaDB (L2 vector store)
CHROMA_HOST=localhost
CHROMA_PORT=8001
CHROMA_COLLECTION_PREFIX=archon

# Mem0 (L3 long-term memory, optional)
MEM0_API_KEY=m0-...
MEM0_USER_ID=archon-prod
```

### Notifications

```dotenv
# Slack
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...

# PagerDuty (optional)
PAGERDUTY_INTEGRATION_KEY=...
```

### Runtime

```dotenv
ARCHON_LOG_LEVEL=INFO          # DEBUG / INFO / WARNING / ERROR
ARCHON_MAX_CONCURRENT_TASKS=4  # TaskScheduler concurrency
ARCHON_DEFAULT_TIMEOUT=120     # agent default timeout (seconds)
```

### LiteLLM Proxy (optional)

```dotenv
LITELLM_PROXY_URL=http://localhost:4000
LITELLM_PROXY_KEY=sk-litellm-...
```

---

## 3. LLM Model Configuration

### Default Models (Anthropic)

Set the model per agent role in the `agent_config` section of the Registry JSON.

```json
{
  "agent_config": {
    "backend": {
      "model": "claude-sonnet-4-6",
      "max_tokens": 8192,
      "temperature": 0.2,
      "streaming": true,
      "timeout_seconds": 120
    },
    "tester": {
      "model": "claude-haiku-4-5-20251001",
      "max_tokens": 4096,
      "temperature": 0.1
    }
  }
}
```

### Ollama (Local Open-Source Models)

```bash
# Install Ollama and download models
ollama pull llama3.3:70b
ollama pull deepseek-v3.2:70b
```

```yaml
# config/litellm_config.yaml
model_list:
  - model_name: backend-agent
    litellm_params:
      model: ollama/llama3.3:70b
      api_base: http://localhost:11434
      stream: true

  - model_name: tester-agent
    litellm_params:
      model: ollama/deepseek-v3.2:7b
      api_base: http://localhost:11434
```

### LiteLLM Proxy Server

Use this to route multiple models through a single endpoint.

```bash
# Install LiteLLM
pip install litellm[proxy]

# Start proxy server
litellm --config config/litellm_config.yaml --port 4000
```

### vLLM GPU Worker

For high-performance GPU inference, run a vLLM server on a dedicated node.

```bash
# Run vLLM server (on GPU node)
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

### Complexity-Based Model Branching

Set `high_complexity_model` to let the Complexity Router automatically select a larger model for hard tasks.

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

The Complexity Router scores 8 criteria (file count, diff lines, dependency depth, etc.) and selects `high_complexity_model` when the score is HIGH.

---

## 4. Redis / ChromaDB Setup

### Redis (L1 Scratchpad)

```bash
# macOS
brew install redis
brew services start redis

# Ubuntu
sudo apt install redis-server
sudo systemctl start redis
```

```python
# Verify connection
import redis
r = redis.from_url("redis://localhost:6379")
r.ping()  # True
```

If Redis is unavailable, `RedisScratchpad` falls back to an in-memory dictionary automatically. Data is lost on restart — always connect Redis in production.

#### Key Format

```
archon:scratch:{project_id}:{task_id}:{key}
```

- TTL: 86400 seconds by default (24 hours)
- Adjust with the `REDIS_TTL` environment variable

### ChromaDB (L2 Vector Store)

```bash
# Install ChromaDB
pip install chromadb

# Run local server (optional)
chroma run --host 0.0.0.0 --port 8001 --path ./chroma_data
```

```python
# Verify connection
import chromadb
client = chromadb.HttpClient(host="localhost", port=8001)
client.heartbeat()  # {"nanosecond heartbeat": ...}
```

If ChromaDB is unavailable, `VectorStore` falls back to an in-memory store automatically.

#### Collection Naming Convention

```
{CHROMA_COLLECTION_PREFIX}_{project_id}
# Example: archon_proj-ecomm
```

### Mem0 (L3 Long-Term Memory, Optional)

Create a [Mem0](https://mem0.ai) account and obtain an API key.

```dotenv
MEM0_API_KEY=m0-...
MEM0_USER_ID=archon-prod   # user or team identifier
```

If Mem0 is unavailable, `Mem0Store` falls back to an in-memory dictionary automatically.

---

## 5. Monitoring

### Logs

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

### Key Metrics

`ProjectRegistry.metrics` is updated on every task completion.

```python
registry.update_metrics(
    task_id="task-001",
    success=True,
    latency_seconds=4.2,
    gate_decision="AUTO_PASS",
)
```

`RegistryStore` persists this to `.harness/registry/{project_id}.json` automatically.

### Human Gate Notifications

`CompositeNotifier` fans out gate events to every registered channel.

| Gate | TerminalNotifier | SlackNotifier | PagerDuty |
|---|---|---|---|
| AUTO_PASS | ✅ green banner | - | - |
| L1_REWORK | 🟡 yellow banner | ✅ | - |
| L2_HUMAN | 🔴 red banner | ✅ | - |
| L3_HALT | 🚨 red banner | ✅ | ✅ |
| L4_DEPLOY | 🔵 blue banner | ✅ | ✅ |

### macOS Native Notifications

`TerminalNotifier` uses `osascript` to post to the macOS Notification Center. No additional configuration is required.

---

## 6. Troubleshooting FAQ

### Q1. `ModuleNotFoundError: No module named 'src'`

```bash
# Make sure you're running from the project root with -m
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

Redis is not running or is on a different port. The in-memory fallback activates automatically, but data will be lost on restart.

```bash
# Check Redis status
redis-cli ping   # PONG = healthy

# Start the service
brew services start redis     # macOS
sudo systemctl start redis    # Linux
```

### Q4. ChromaDB `Collection not found`

Collections are created automatically on first run. If the error persists, check your ChromaDB version.

```bash
pip show chromadb   # 0.4.x recommended
```

### Q5. Gate always returns L2_HUMAN

Dynamic Guardrails may be triggering the escalation. If any changed file path or content matches `high_risk_paths` or `high_risk_keywords`, the gate automatically escalates to L2.

```python
# Inspect the active policy
print(registry.quality_policy.high_risk_paths)
print(registry.quality_policy.high_risk_keywords)
```

Check whether the changed file paths match the risk patterns and adjust the policy if needed.

### Q6. `ProtectedPathError` raised

```
ProtectedPathError: Attempt to modify protected path: .harness/sop/production/
```

`GitExecutor.auto_commit()` detected a file in `protected_paths`. If the modification is intentional, remove the path from `protected_paths` or commit it manually.

```python
executor = GitExecutor(repo_path=".", protected_paths=registry.protected_paths)
```

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

### Q8. pytest failures blocking the QA pipeline

```python
# Temporarily relax requirements during development
from src.registry.models import QualityPolicy
policy = QualityPolicy(
    min_test_coverage=0,   # disable coverage requirement
)
```

Alternatively, adjust the gate evaluator thresholds in the registry quality policy to allow passage even when test results are incomplete.

### Q9. Cyclic dependency error in task scheduler

```
CyclicDependencyError: Cycle detected in task dependencies
```

`TaskScheduler` uses Kahn's topological sort algorithm. Remove the circular reference from the `depends_on` configuration.

```python
# Verify dependency graph
scheduler = TaskScheduler(tasks)
order = scheduler.topological_sort()  # returns sorted order if no cycle
```

---

## 7. Backup and Recovery

### What to Back Up

| Data | Location | Method |
|---|---|---|
| Project Registry | `.harness/registry/*.json` | file copy / git |
| SOP documents | `.harness/sop/` | file copy / git |
| Redis scratchpad | Redis DB | `redis-cli SAVE` |
| ChromaDB vectors | `chroma_data/` | directory copy |
| Mem0 long-term memory | Mem0 cloud | Mem0 dashboard |
| Benchmark results | `benchmarks/results/` | file copy / git |

### Registry Backup

Managing `.harness/registry/` in git is strongly recommended.

```bash
# Commit on every change
git add .harness/registry/
git commit -m "chore: registry snapshot $(date +%Y-%m-%d)"
git push origin main
```

### Redis Backup

```bash
# Create a snapshot
redis-cli BGSAVE   # async (recommended for production)

# Copy the dump file (default path)
cp /var/lib/redis/dump.rdb /backup/redis-$(date +%Y%m%d).rdb
```

#### Restore

```bash
# Stop Redis
sudo systemctl stop redis

# Restore dump
cp /backup/redis-20260424.rdb /var/lib/redis/dump.rdb

# Restart Redis
sudo systemctl start redis
```

### ChromaDB Backup

```bash
# Archive the data directory
tar -czf chroma-backup-$(date +%Y%m%d).tar.gz ./chroma_data/
```

#### Restore

```bash
# Stop ChromaDB, then restore
tar -xzf chroma-backup-20260424.tar.gz
```

### Full Recovery Procedure

1. Restore `.env` environment variables
2. Restore Redis backup and restart
3. Restore ChromaDB backup and restart
4. Check out `.harness/registry/*.json` from git
5. Run `python -m src.demo.pipeline` to verify everything works

---

## Related Docs

- [Quick Start](quickstart.md)
- [Architecture](architecture.md)
- [Registry Schema](registry-schema.md)
- [Plugin Development Guide](plugin-guide.md)
- [API Reference](api-reference.md)
