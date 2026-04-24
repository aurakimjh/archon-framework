# 빠른 시작 가이드

🇺🇸 [English](../en/quickstart.md)

> 버전: 1.1.0 | 최종 수정: 2026-04-23

## 사전 요구사항

- Python 3.11+
- macOS (Apple Silicon 권장) 또는 Linux
- Anthropic API 키 (오케스트레이터/리뷰어용)
- Ollama 또는 MLX (로컬 에이전트용)

## 1. 설치

```bash
git clone https://github.com/aurakimjh/archon-framework.git
cd archon-framework

python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## 2. 환경 설정

```bash
cp .env.example .env
cp config/litellm_config.yaml.example config/litellm_config.yaml
```

`.env` 파일을 편집해 API 키를 설정한다:

```env
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

## 6. Mock 데모 (LLM 없이 동작 확인)

LLM이 없어도 파이프라인 전체 흐름을 시험할 수 있다. `DemoPipeline`의 mock 시나리오를 사용한다.

```bash
# AUTO_PASS 시나리오: 첫 시도에 통과
python3 -m archon demo --mock --scenario auto_pass

# L1 시나리오: 첫 시도 린트 실패 → 재작업 → AUTO_PASS
python3 -m archon demo --mock --scenario l1

# L2 시나리오: review_score 미달 → Human Gate 발동
python3 -m archon demo --mock --scenario l2
```

출력 예시 (`auto_pass`):

```
[loop 0] backend → qa → reviewer → gate
  gate: AUTO_PASS (review_score=92, coverage=85%)
  ✓ committed: abc123
```

## 7. 실제 LLM으로 데모

LiteLLM Proxy와 Ollama가 실행 중인 상태에서:

```bash
python3 -m archon demo
```

## 8. 버전 확인

```bash
python3 -m archon version
```

## 9. 프로젝트 레지스트리 생성

`.harness/registry/` 디렉토리에 프로젝트 JSON을 생성한다. 스키마는 [registry-schema.md](registry-schema.md) 참조.

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

## Human Gate 시나리오 이해

파이프라인은 QA 결과에 따라 자동으로 게이트 레벨을 결정한다.

```
에이전트 작업 완료
    → QA 파이프라인 (lint/test/security)
    → Review Agent (score 산출)
    → evaluate_gate() 판정
        → AUTO_PASS: 자동 커밋
        → L1_REWORK: 에이전트 재작업 (최대 3회)
        → L2_HUMAN: 개발자 알림, 일시정지
        → L3_HALT: 긴급 중단
        → L4_DEPLOY: Human 최종 승인 필요
```

**Dynamic Guardrails**: `payment`, `auth`, `migration` 등 고위험 경로나 키워드가 감지되면 다른 점수와 무관하게 자동으로 L2로 상향된다.

## 관련 문서

- [아키텍처](architecture.md)
- [Handoff Artifact 스키마](handoff-schema.md)
- [Project Registry 스키마](registry-schema.md)
- [Human Gate 설계](human-gate.md)
