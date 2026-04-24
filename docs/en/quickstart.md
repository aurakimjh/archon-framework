# Quick Start Guide

🇰🇷 [한국어](../ko/quickstart.md)

> Version: 1.1.0 | Last updated: 2026-04-23

## Prerequisites

- Python 3.11+
- macOS (Apple Silicon recommended) or Linux
- Anthropic API key (for orchestrator/reviewer)
- Ollama or MLX (for local agents)

## 1. Install

```bash
git clone https://github.com/aurakimjh/archon-framework.git
cd archon-framework

python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## 2. Configure

```bash
cp .env.example .env
cp config/litellm_config.yaml.example config/litellm_config.yaml
```

Edit `.env` to set your API key:

```env
ANTHROPIC_API_KEY=sk-ant-...
LITELLM_MASTER_KEY=sk-...
```

## 3. Set Up Local LLMs (Ollama)

```bash
# After installing Ollama
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

## 6. Mock Demo (works without any LLM)

The `DemoPipeline` mock scenarios let you exercise the full pipeline flow without a running LLM.

```bash
# AUTO_PASS scenario: passes on the first attempt
python3 -m archon demo --mock --scenario auto_pass

# L1 scenario: lint failure on attempt 0 → rework → AUTO_PASS
python3 -m archon demo --mock --scenario l1

# L2 scenario: review_score below threshold → Human Gate triggered
python3 -m archon demo --mock --scenario l2
```

Sample output (`auto_pass`):

```
[loop 0] backend → qa → reviewer → gate
  gate: AUTO_PASS (review_score=92, coverage=85%)
  ✓ committed: abc123
```

## 7. Run with a Real LLM

With LiteLLM Proxy and Ollama running:

```bash
python3 -m archon demo
```

## 8. Version Check

```bash
python3 -m archon version
```

## 9. Create a Project Registry

Create a project JSON in `.harness/registry/`. See [registry-schema.md](registry-schema.md) for the full schema.

```json
{
  "project_meta": {
    "project_id": "my_project",
    "project_name": "My Project"
  },
  "git_config": {
    "repo_url": "https://github.com/org/my-project.git"
  },
  "quality_policy": {
    "coverage_threshold": 80,
    "review_score_threshold": 70
  }
}
```

## Understanding Human Gate Scenarios

The pipeline automatically picks a gate level based on QA results.

```
Agent task complete
    → QA pipeline (lint/test/security)
    → Review Agent (score calculation)
    → evaluate_gate() decision
        → AUTO_PASS:  auto-commit
        → L1_REWORK:  agent self-rework (up to 3 retries)
        → L2_HUMAN:   developer notified, project paused
        → L3_HALT:    emergency stop
        → L4_DEPLOY:  human final approval required
```

**Dynamic Guardrails**: if high-risk paths or keywords like `payment`, `auth`, or `migration` are detected, the gate automatically escalates to L2 regardless of other scores.

## Related Docs

- [Architecture](architecture.md)
- [Handoff Artifact Schema](handoff-schema.md)
- [Project Registry Schema](registry-schema.md)
- [Human Gate Design](human-gate.md)
