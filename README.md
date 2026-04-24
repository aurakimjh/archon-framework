# Archon Framework

🇰🇷 [한국어](README_KO.md)

> A multi-agent AI development platform where a solo developer commands an army of AI agents to outperform a mid-sized engineering team.

## Overview

Archon uses Claude as a master orchestrator and open-source LLMs as specialized agents. Agents are **stateless** — each task injects context via a [Handoff Artifact](docs/en/handoff-schema.md), so any agent can handle any project without prior state.

- [한국어 문서](docs/ko/)
- [English Documentation](docs/en/)

## Key Features

| Feature | Status | Description |
|---|---|---|
| Agent Orchestration | ✅ | Stateless agents with context injection via Handoff Artifacts |
| Human Gate | ✅ | 5-level decision framework: AUTO_PASS / L1_REWORK / L2_HUMAN / L3_HALT / L4_DEPLOY |
| Dynamic Guardrails | ✅ | Auto-escalate to L2 on high-risk paths/keywords (payment, auth, infra…) |
| Complexity Router | ✅ | 8-criteria scoring; routes to `high_complexity_model` for complex tasks |
| 3-Layer Memory | ✅ | L1 Redis scratchpad · L2 ChromaDB vector search · L3 Mem0 cross-project patterns |
| Async Streaming | ✅ | `execute_streaming()` on BaseAgent; litellm `stream=True` with timeout |
| Task Scheduler | ✅ | Dependency-based topological sort + asyncio semaphore concurrency |
| vLLM Bridge | ✅ | GPU worker endpoint management + LiteLLM integration |
| MCP Server | ✅ | 5 tools: execute_task / get_status / list_agents / get_project / list_projects |
| A2A Messaging | ✅ | Agent-to-Agent mailbox routing (Google A2A protocol) |
| Notifications | ✅ | Terminal (rich TUI + macOS desktop) + Slack webhook |
| SOP Compliance | ✅ | Procedure score check; below threshold forces L2 Human Gate |
| LLM Plugin Swap | ✅ | Role-based model routing via LiteLLM Proxy |
| Multi-Project | ✅ | Isolated project namespaces with shared agent pools |
| Air-gap Support | ✅ | Local open-source LLM execution via MLX/Ollama/vLLM |
| Ray Cluster | 🔧 | Local/cluster/kubernetes modes (Phase 3) |

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Layer 0 — Human in the Loop                            │
│  Developer: ideas · design review · Human Gate          │
└────────────────────────┬────────────────────────────────┘
                         │ Human Gate (bidirectional)
┌────────────────────────▼────────────────────────────────┐
│  Layer 1 — Orchestrator (Claude API)                    │
│  src/orchestrator/  — design · dispatch · review        │
└────────────────────────┬────────────────────────────────┘
                         │ Handoff Artifact JSON
┌────────────────────────▼────────────────────────────────┐
│  Layer 2 — Protocol Bus                                 │
│  src/mcp/server.py  — MCP 5 tools                      │
│  src/mcp/a2a.py     — A2A mailbox routing               │
└────────────────────────┬────────────────────────────────┘
                         │ Task Queue
┌────────────────────────▼────────────────────────────────┐
│  Layer 3 — LLM Selector / Router                        │
│  src/router/complexity.py  — dynamic routing by score   │
│  LiteLLM Proxy (localhost:4000)                         │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────┐
│  Layer 4 — Specialized Agent Pool                       │
│  src/agents/  — Backend · Frontend · Tester             │
│                 DevOps · Docs  (stateless, ctx injected) │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────┐
│  Layer 5 — QA Pipeline + Human Gate                     │
│  src/pipeline/qa.py        — lint/build/test/security   │
│  src/gate/evaluator.py     — 5-level gate decision      │
│  src/notifications/        — Slack · Terminal           │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────┐
│  Layer 6 — Shared Memory                                │
│  src/memory/  — Redis (L1) · ChromaDB (L2) · Mem0 (L3) │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────┐
│  Layer 7 — LLM Runtime                                  │
│  src/runtime/vllm_bridge.py  — vLLM endpoint management │
│  src/runtime/cluster.py      — Ray cluster              │
│  MLX · Ollama · vLLM · Claude API                       │
└─────────────────────────────────────────────────────────┘
```

## Module Map

| Module path | Description |
|---|---|
| `src/orchestrator/orchestrator.py` | Main orchestrator — 6-agent pool, task chain execution |
| `src/orchestrator/handoff.py` | HandoffArtifact 7-section Pydantic model |
| `src/agents/base.py` | Stateless BaseAgent — streaming, A2A, structured output parsing |
| `src/agents/{backend,frontend,tester,devops,docs}.py` | Role-specific agent implementations |
| `src/gate/evaluator.py` | 5-level Human Gate decision logic |
| `src/gate/models.py` | GateDecision enum |
| `src/pipeline/qa.py` | Parallel ruff/mypy/pytest/semgrep/coverage |
| `src/pipeline/git_executor.py` | Auto-commit, protected_paths validation |
| `src/pipeline/demo_pipeline.py` | Mock-scenario demo/test pipeline |
| `src/registry/models.py` | ProjectRegistry 8-section Pydantic model |
| `src/registry/store.py` | JSON file-based registry persistence |
| `src/router/complexity.py` | 8-criteria complexity scoring, dynamic model routing |
| `src/memory/context_injector.py` | 3-layer memory facade (MemoryStore) |
| `src/memory/redis_scratchpad.py` | L1 Redis short-term memory (TTL 24h) |
| `src/memory/vector_store.py` | L2 ChromaDB vector search |
| `src/memory/mem0_store.py` | L3 Mem0 cross-project pattern learning |
| `src/memory/compressor.py` | Large handoff context compression |
| `src/queue/scheduler.py` | Dependency topological sort + asyncio scheduler |
| `src/queue/priority.py` | Priority queue utilities |
| `src/mcp/server.py` | MCP server — 5 tool definitions and handlers |
| `src/mcp/a2a.py` | A2A agent-to-agent message routing |
| `src/notifications/base.py` | GateEvent model + Notifier abstract class |
| `src/notifications/terminal.py` | rich TUI + macOS desktop notifications |
| `src/notifications/slack.py` | Slack webhook notifications |
| `src/runtime/vllm_bridge.py` | vLLM endpoint management, LiteLLM integration |
| `src/runtime/cluster.py` | Ray cluster (local/cluster/kubernetes) |
| `src/errors.py` | Custom exception hierarchy |
| `archon/__main__.py` | CLI entrypoint (`python -m archon`) |

## Quick Start

```bash
# 1. Clone
git clone https://github.com/aurakimjh/archon-framework.git
cd archon-framework

# 2. Setup environment
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# 3. Configure
cp .env.example .env
cp config/litellm_config.yaml.example config/litellm_config.yaml
# Edit .env with your ANTHROPIC_API_KEY

# 4. Start LiteLLM Proxy (for local models)
litellm --config config/litellm_config.yaml --port 4000

# 5. Run mock demo (works without LLM)
python3 -m archon demo --mock --scenario auto_pass
python3 -m archon demo --mock --scenario l1
python3 -m archon demo --mock --scenario l2

# 6. Run with real LLM
python3 -m archon demo

# 7. Version check
python3 -m archon version
```

## Human Gate — 5 Levels

| Level | Trigger | Action |
|---|---|---|
| `AUTO_PASS` | All checks pass | Auto-commit → branch push |
| `L1_REWORK` | Lint failure, borderline coverage, few unit test failures | Agent self-rework (up to 3 retries) |
| `L2_HUMAN` | review_score < 70, schema change, external integration, SOP below threshold, **Dynamic Guardrails** | Developer notification, project paused |
| `L3_HALT` | Build failure, Critical/High security vulnerabilities | Emergency stop, urgent alert |
| `L4_DEPLOY` | Deploy request | Always requires human final approval |

**Dynamic Guardrails**: High-risk paths or keywords (`payment`, `auth`, `migration`, `secrets/`, etc.) auto-escalate to L2 regardless of other scores.

## Testing

```bash
# All tests
pytest tests/ -v

# Demo pipeline tests (mock, no LLM needed)
pytest tests/test_demo_pipeline.py -v

# Gate logic tests
pytest tests/test_gate_evaluator.py -v
```

## Documentation

- [Architecture](docs/en/architecture.md)
- [Handoff Artifact Schema](docs/en/handoff-schema.md)
- [Project Registry Schema](docs/en/registry-schema.md)
- [Human Gate Design](docs/en/human-gate.md)
- [Quick Start Guide](docs/en/quickstart.md)

## License

MIT
