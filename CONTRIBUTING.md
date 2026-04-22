# Contributing to Archon Framework

## Development Setup

```bash
git clone https://github.com/org/archon-framework.git
cd archon-framework
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Code Standards

- Python 3.11+
- Type hints required
- Pydantic v2 for data models
- Async/await preferred
- Ruff for linting: `ruff check .`
- MyPy for type checking: `mypy src/`

## Branch Strategy

- `main` — stable releases
- `develop` — integration branch
- `agent/{role}/{task_id}` — agent work branches
- Never commit directly to `main`

## Commit Messages

Format: `feat({role}): {summary} [task:{task_id}]`

## Pull Requests

1. Create a branch from `develop`
2. Make your changes
3. Run tests: `pytest`
4. Run linter: `ruff check .`
5. Submit PR with description of changes
