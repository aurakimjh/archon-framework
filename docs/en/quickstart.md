# Quick Start Guide

[한국어](../ko/quickstart.md)

> Version: 2.0.0 | Last updated: 2026-04-24

This guide walks you through everything from installation to running your first demo and enabling advanced features like observability, guardrails, and the monitoring dashboard.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Installation](#2-installation)
3. [Environment Setup](#3-environment-setup)
4. [LLM Provider Setup](#4-llm-provider-setup)
5. [Running the Demo Pipeline](#5-running-the-demo-pipeline)
6. [Project Registry Setup](#6-project-registry-setup)
7. [Enabling Observability](#7-enabling-observability)
8. [Enabling Guardrails](#8-enabling-guardrails)
9. [Starting the Dashboard](#9-starting-the-dashboard)
10. [Running Tests](#10-running-tests)
11. [Next Steps](#11-next-steps)

---

## 1. Prerequisites

### Required

- **Python 3.11+** -- Archon relies on modern type hint features introduced in 3.11.
- **Git** -- needed for cloning the repo and the auto-commit feature.

### Optional (install based on which features you need)

| Tool | Purpose | When you need it |
|---|---|---|
| **Redis** | Scratchpad (shared memory between agents) | Multi-agent pipeline runs |
| **ChromaDB** | Vector-search long-term memory | When using the Memory layer |
| **Ollama** | Local LLM inference | Running agents locally |
| **vLLM** | High-performance GPU inference | GPU cluster environments |
| **LiteLLM Proxy** | Unified API across multiple LLM providers | Using multiple models/providers |

---

## 2. Installation

### Base install

```bash
git clone https://github.com/aurakimjh/archon-framework.git
cd archon-framework

python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

The `.[dev]` extra includes pytest, ruff, mypy, and other development tools.

### Optional extras

Install additional extras depending on which features you plan to use.

```bash
# Observability -- LangSmith, Langfuse, and AITOP tracing support
pip install -e ".[observability]"

# Dashboard -- real-time monitoring UI built on FastAPI
pip install -e ".[dashboard]"

# Install multiple extras at once
pip install -e ".[dev,observability,dashboard]"
```

---

## 3. Environment Setup

### 3-1. Copy config templates

```bash
cp .env.example .env
cp config/litellm_config.yaml.example config/litellm_config.yaml
```

### 3-2. Edit `.env`

Open `.env` and fill in the values you need.

```env
# [Required] Anthropic API -- used by the orchestrator and reviewer agents.
ANTHROPIC_API_KEY=sk-ant-...

# [Required] LiteLLM Proxy authentication key
LITELLM_MASTER_KEY=sk-...

# [Optional] Redis -- shared scratchpad memory between agents
REDIS_URL=redis://localhost:6379/0

# [Optional] ChromaDB -- vector-search long-term memory
CHROMA_HOST=localhost
CHROMA_PORT=8000

# [Optional] Ollama -- local LLM inference server
OLLAMA_BASE_URL=http://localhost:11434

# [Optional] AITOP Monitoring -- custom tracing backend
AITOP_SERVER_URL=http://localhost:8080
AITOP_PROJECT_TOKEN=

# [Optional] Ray -- distributed runtime cluster
RAY_ADDRESS=auto
```

> **Note**: If you only want to run mock demos, no API keys are required.

---

## 4. LLM Provider Setup

Archon supports multiple LLM providers. Pick the option that fits your environment.

### Option A: Ollama (easiest for local development)

Run LLMs directly on your local machine. Works without a GPU, but you will need enough RAM.

```bash
# Install Ollama from https://ollama.ai
# Then pull the models:

ollama pull deepseek-v3.2:70b   # Backend Agent
ollama pull qwen3.5:32b          # Frontend Agent
```

### Option B: vLLM (GPU server)

If you have a dedicated GPU server, vLLM gives you high-throughput inference with an OpenAI-compatible API.

```bash
# On your GPU server
python -m vllm.entrypoints.openai.api_server \
    --model deepseek-ai/DeepSeek-V3 \
    --port 8000
```

### Option C: LiteLLM Proxy (multiple providers behind one API)

LiteLLM Proxy unifies multiple models and providers under a single endpoint. This is the recommended setup for production.

```bash
# Edit config/litellm_config.yaml first, then start the proxy
litellm --config config/litellm_config.yaml --port 4000
```

### Option D: Cloud API only (Claude / OpenAI)

You can skip local LLMs entirely and use cloud APIs. Just set the API key in `.env`.

```env
ANTHROPIC_API_KEY=sk-ant-...
```

Configure your LiteLLM Proxy to route to cloud models only.

---

## 5. Running the Demo Pipeline

The demo pipeline is the fastest way to see Archon's full workflow in action.

### Mock mode (no LLM required)

This lets you verify the entire pipeline flow without any running LLM. Start here if you are new.

```bash
# Run the default mock demo
python -m archon demo

# Run specific scenarios
python -m archon demo --scenario auto_pass   # passes on the first attempt
python -m archon demo --scenario l1           # lint failure -> rework -> pass
python -m archon demo --scenario l2           # low review score -> Human Gate
```

#### What each scenario does

| Scenario | Behavior | What you learn |
|---|---|---|
| `auto_pass` | QA passes -> auto-commit | The happy path |
| `l1` | Lint failure -> agent self-rework (up to 3 retries) -> pass | Automatic recovery loop |
| `l2` | Review score below threshold -> Human Gate triggered, developer notified | When human intervention is needed |

#### Sample output (`auto_pass`)

```
[loop 0] backend -> qa -> reviewer -> gate
  gate: AUTO_PASS (review_score=92, coverage=85%)
  committed: abc123
```

### Running with a real LLM

Make sure LiteLLM Proxy (or Ollama) is running, then add the `--real` flag.

```bash
python -m archon demo --real
```

### Version check

```bash
python -m archon version
```

---

## 6. Project Registry Setup

The project registry defines how Archon manages a given project. Create a JSON file in `.harness/registry/`.

```json
{
  "project_meta": {
    "project_id": "my_project",
    "project_name": "My Project",
    "description": "A brief description of the project"
  },
  "agent_config": {
    "backend_model": "deepseek-v3.2:70b",
    "frontend_model": "qwen3.5:32b",
    "reviewer_model": "claude-sonnet-4-20250514"
  },
  "quality_policy": {
    "coverage_threshold": 80,
    "review_score_threshold": 70,
    "lint_required": true,
    "security_scan_required": true
  },
  "git_config": {
    "repo_url": "https://github.com/org/my-project.git",
    "branch": "develop",
    "auto_commit": true
  }
}
```

### Key fields

- **`agent_config`**: Assigns a specific model to each role (backend, frontend, reviewer).
- **`quality_policy`**: Sets the quality thresholds that determine auto-pass, rework, or human intervention.
- **`git_config`**: Specifies the target repository and branch for auto-commits.

See [registry-schema.md](registry-schema.md) for the complete schema.

---

## 7. Enabling Observability

Archon supports three tracing backends: LangSmith, Langfuse, and AITOP. Tracing helps you understand what each agent is doing and debug issues.

### Install

```bash
pip install -e ".[observability]"
```

### Usage

```python
from src.observability import TracingConfig, TracingBackend, create_tracer_from_config

# Example: AITOP backend
config = TracingConfig(
    backend=TracingBackend.AITOP,
    aitop_server_url="http://localhost:8080",
    aitop_project_token="your-token-here",
)
tracer = create_tracer_from_config(config)

# Example: LangSmith backend
config = TracingConfig(
    backend=TracingBackend.LANGSMITH,
)
tracer = create_tracer_from_config(config)
```

Once a tracer is created, it automatically records each agent's inputs/outputs, token usage, and latency during pipeline runs.

---

## 8. Enabling Guardrails

Guardrails add safety constraints to agent behavior -- token budgets, sensitive data detection, and prompt injection defense.

```python
from src.guardrails import GuardrailPolicy

policy = GuardrailPolicy(
    daily_token_limit=100_000,        # max tokens per day
    detect_sensitive_data=True,       # detect PII, API keys, etc.
    detect_prompt_injection=True,     # detect prompt injection attacks
)
```

### Dynamic Guardrails (Human Gate integration)

When the pipeline detects high-risk paths or keywords like `payment`, `auth`, or `migration`, the gate level automatically escalates to L2 or higher -- regardless of review scores.

```
Agent task complete
    -> QA pipeline (lint / test / security)
    -> Review Agent (score calculation)
    -> evaluate_gate() decision
        -> AUTO_PASS:  auto-commit
        -> L1_REWORK:  agent self-rework (up to 3 retries)
        -> L2_HUMAN:   developer notified, project paused
        -> L3_HALT:    emergency stop
        -> L4_DEPLOY:  human final approval required
```

---

## 9. Starting the Dashboard

The dashboard gives you a real-time web UI for monitoring project status, agent health, and pipeline execution history.

### Install

```bash
pip install -e ".[dashboard]"
```

### Run

```python
from src.dashboard import DashboardApp

app = DashboardApp(
    registry_store=store,
    health_registry=health_reg,
)
```

```bash
uvicorn src.dashboard:app --host 0.0.0.0 --port 8501
```

Then open `http://localhost:8501` in your browser.

---

## 10. Running Tests

### Full test suite

```bash
pytest tests/ -v
```

### Individual modules

```bash
pytest tests/test_agents_pool.py -v       # Agent pool
pytest tests/test_gate.py -v              # Human Gate
pytest tests/test_guardrails.py -v        # Guardrails
pytest tests/test_observability.py -v     # Observability
```

### Linting and type checking

```bash
ruff check src/            # code style linting
mypy src/                  # static type checking
```

---

## 11. Next Steps

Now that you have the basics running, explore these guides to go deeper.

- **[Architecture](architecture.md)** -- system design and how agents communicate
- **[Plugin Guide](plugin-guide.md)** -- how to build custom agents and plugins
- **[Operations Guide](operations-guide.md)** -- production deployment and best practices
- **[Human Gate Design](human-gate.md)** -- detailed behavior for each gate level
- **[Handoff Artifact Schema](handoff-schema.md)** -- data exchange format between agents
- **[Project Registry Schema](registry-schema.md)** -- full project configuration schema
- **[API Reference](api-reference.md)** -- per-module API documentation
