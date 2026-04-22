# Archon System Architecture

> Version: 1.0.0 | Last updated: 2026-04-22

## Overview

Archon is a multi-agent AI development platform built on a 7-layer architecture. It uses Claude API as the master orchestrator and open-source LLMs as specialized agents, enabling a solo developer to achieve team-level productivity.

## Core Design Principles

| Principle | Description |
|---|---|
| P1. Stateless Agents | Not bound to any project. Receives project_context per task |
| P2. Open Structure, Private Soul | Schemas/design are open-source; prompts/SOPs are private |
| P3. Scale-out Without Code Changes | Ray-based — linear scaling by adding nodes |
| P4. Work Never Stops | Human Gate only pauses the affected project |
| P5. Models Are Always Swappable | LiteLLM Proxy enables role-based model swap via YAML |

## 7-Layer Architecture

```
Layer 0 — Human in the Loop
  Developer: Ideas · Design Review · Testing · Final Approval
          │
          │ Human Gate (bidirectional)
          ▼
Layer 1 — Orchestrator (Claude API)
  Master Architect · Code Reviewer · Human Gate Manager
  Models: Claude Opus 4.6 (design) / Claude Sonnet 4.6 (review)
          │
          │ MCP / A2A Protocol
          ▼
Layer 2 — Protocol Bus
  MCP (Anthropic) · A2A (Google) · Handoff Artifact JSON
          │
          │ Task Queue (Ray / Celery)
          ▼
Layer 3 — LLM Selector / Router
  Role-based Router · Complexity Router · Fallback
  Implementation: LiteLLM Proxy (localhost:4000)
          │
          ▼
Layer 4 — Specialized Agent Pool
  Frontend │ Backend │ Tester │ DevOps │ Docs
  (Stateless · Context Injection · Shared Pool)
          │
          ▼
Layer 5 — Shared Memory & Context Store
  Git + Artifacts (long-term) · ChromaDB (mid-term) · Redis (short-term)
          │
          ▼
Layer 6 — LLM Runtime
  MLX (Apple Silicon) · Ollama · vLLM · Claude API
          │
          ▼
Layer 7 — Observability & Governance
  Tracing · Cost Monitor · Eval Loop · Guardrails
```

## Layer Details

### Layer 0 — Human in the Loop

The developer handles idea generation, design review, real testing, and final approval. Only intervenes for decisions that agents cannot make autonomously (L2-L4 Human Gates).

### Layer 1 — Orchestrator

Claude API directs the entire pipeline.

- **Master Architect**: Requirement decomposition → SOP generation → task distribution
- **Code Reviewer**: Full review, security audit, design consistency
- **Human Gate Manager**: L1-L4 decision, developer notification

### Layer 2 — Protocol Bus

Standard communication interface between agents.

- **MCP** (Anthropic): Agent ↔ Tool standard
- **A2A** (Google): Cross-framework P2P collaboration
- **Handoff Artifact**: Structured JSON handoff document → [Details](handoff-schema.md)

### Layer 3 — LLM Selector / Router

LiteLLM Proxy as single API gateway.

- **Role-based Router**: Pre-defined models per role
- **Complexity Router**: Dynamic routing based on task complexity (Phase 2)
- **Fallback**: Automatic failover on model failure

### Layer 4 — Specialized Agent Pool

| Role | Default Model | Responsibility |
|---|---|---|
| orchestrator | claude-opus-4-6 | Design, distribution, review |
| reviewer | claude-sonnet-4-6 | Code review, quality scoring |
| frontend | ollama/qwen3.5:32b | UI/UX implementation |
| backend | ollama/deepseek-v3.2:70b | API, DB, business logic |
| tester | ollama/gemma4:14b | Test automation |
| devops | ollama/glm-5:14b | CI/CD, IaC |
| docs | ollama/mimo-v2:7b | Documentation |

### Layer 5 — Shared Memory

3-tier memory structure:

- **L1 Short-term**: Redis scratchpad (TTL 24h)
- **L2 Mid-term**: Git + ChromaDB (project-isolated)
- **L3 Long-term**: Mem0 (cross-project, disabled by default)

### Layer 6 — LLM Runtime

- **MLX**: Apple Silicon native, 20-50% faster than Ollama
- **Ollama**: Easy setup, broad model support
- **vLLM**: Production-grade high-throughput serving

### Layer 7 — Observability

- **Tracing**: LangSmith / Langfuse
- **Cost Monitor**: LiteLLM Dashboard
- **Eval Loop**: Automated output quality evaluation
- **Guardrails**: I/O validation, security policies

## Hardware Strategy

### Phase 1 — MacBook Solo

All agents run on M5 Max 128GB.

### Phase 2 — Multi-node

MacBook (Ray Head) + PC Workers (GPU). Connect with `ray.init(address="auto")`.

### Phase 3 — Cloud Hybrid

KubeRay + on-premise + cloud burst-out. Scale by adding nodes without code changes.
