# Archon Framework

> 1인 개발자가 AI 에이전트 군단을 지휘해 중소 개발팀의 생산성을 능가하는 멀티 에이전트 AI 개발 플랫폼

## Overview

Archon uses Claude as a master orchestrator and open-source LLMs as specialized agents to enable a single developer to achieve team-level output.

- [English Documentation](docs/en/)
- [한국어 문서](docs/ko/)

## Key Features

- **Agent Orchestration**: Stateless agents with context injection via Handoff Artifacts
- **Human Gate**: 4-level decision framework (auto_pass / L1 rework / L2 human / L3 halt / L4 deploy)
- **LLM Plugin Swap**: Role-based model routing via LiteLLM Proxy
- **Multi-Project**: Isolated project namespaces with shared agent pools
- **Air-gap Support**: Local open-source LLM execution via MLX/Ollama

## Quick Start

```bash
# 1. Clone
git clone https://github.com/org/archon-framework.git
cd archon-framework

# 2. Setup environment
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# 3. Configure
cp .env.example .env
cp config/litellm_config.yaml.example config/litellm_config.yaml
# Edit .env and config files with your settings

# 4. Start LiteLLM Proxy
litellm --config config/litellm_config.yaml

# 5. Run
python -m archon
```

## Architecture

See [docs/en/architecture.md](docs/en/architecture.md) for the full 7-layer architecture.

## License

MIT
