# Quick Start Guide

> Version: 1.0.0 | Last updated: 2026-04-22

## Prerequisites

- Python 3.11+
- macOS (Apple Silicon recommended) or Linux
- Anthropic API key (for orchestrator/reviewer)
- Ollama or MLX (for local agents)

## 1. Installation

```bash
git clone https://github.com/aurakimjh/archon-framework.git
cd archon-framework

python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## 2. Configuration

```bash
cp .env.example .env
cp config/litellm_config.yaml.example config/litellm_config.yaml
```

Edit `.env` with your API keys:

```
ANTHROPIC_API_KEY=sk-ant-...
LITELLM_MASTER_KEY=sk-...
```

## 3. Local LLM Setup (Ollama)

```bash
ollama pull deepseek-v3.2:70b   # Backend Agent
ollama pull gemma4:14b           # Tester Agent
ollama pull qwen3.5:32b          # Frontend Agent
```

## 4. Start LiteLLM Proxy

```bash
litellm --config config/litellm_config.yaml --port 4000
```

## 5. Run Tests

```bash
pytest tests/ -v
```

## 6. Create Project Registry

Create a project JSON in `.harness/registry/`. See [registry-schema.md](registry-schema.md) for the schema.

## 7. Run PoC Demo

Phase 1 PoC: Backend Agent → Handoff → Reviewer Agent → auto_commit

```bash
python -m archon demo
```

> Phase 1 in progress. See [work-status.md](../../work-status.md) for details.

## Related Docs

- [Architecture](architecture.md)
- [Handoff Artifact Schema](handoff-schema.md)
- [Project Registry Schema](registry-schema.md)
- [Human Gate Design](human-gate.md)
