# 빠른 시작 가이드

> 버전: 1.0.0 | 최종 수정: 2026-04-22

## 사전 요구사항

- Python 3.11+
- macOS (Apple Silicon 권장) 또는 Linux
- Anthropic API 키 (오케스트레이터/리뷰어용)
- Ollama 또는 MLX (로컬 에이전트용)

## 1. 설치

```bash
git clone https://github.com/aurakimjh/archon-framework.git
cd archon-framework

python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## 2. 환경 설정

```bash
cp .env.example .env
cp config/litellm_config.yaml.example config/litellm_config.yaml
```

`.env` 파일을 편집해 API 키를 설정한다:

```
ANTHROPIC_API_KEY=sk-ant-...
LITELLM_MASTER_KEY=sk-...
```

## 3. 로컬 LLM 설정 (Ollama)

```bash
# Ollama 설치 후
ollama pull deepseek-v3.2:70b   # Backend Agent
ollama pull gemma4:14b           # Tester Agent
ollama pull qwen3.5:32b          # Frontend Agent
```

## 4. LiteLLM Proxy 시작

```bash
litellm --config config/litellm_config.yaml --port 4000
```

## 5. 테스트 실행

```bash
pytest tests/ -v
```

## 6. 프로젝트 레지스트리 생성

`.harness/registry/` 디렉토리에 프로젝트 JSON을 생성한다. 스키마는 [registry-schema.md](registry-schema.md) 참조.

## 7. PoC 데모 실행

Phase 1 PoC: Backend Agent → Handoff → Reviewer Agent → auto_commit

```bash
python -m archon demo
```

> Phase 1 구현 중. 자세한 내용은 [work-status.md](../../work-status.md) 참조.

## 관련 문서

- [아키텍처](architecture.md)
- [Handoff Artifact 스키마](handoff-schema.md)
- [Project Registry 스키마](registry-schema.md)
- [Human Gate 설계](human-gate.md)
