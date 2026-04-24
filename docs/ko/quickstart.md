# 빠른 시작 가이드

[English](../en/quickstart.md)

> 버전: 2.0.0 | 최종 수정: 2026-04-24

이 가이드는 Archon Framework를 처음 사용하시는 분을 위해, 설치부터 데모 실행, 주요 기능 활성화까지 전체 과정을 단계별로 안내합니다.

---

## 목차

1. [사전 요구사항](#1-사전-요구사항)
2. [설치](#2-설치)
3. [환경 설정](#3-환경-설정)
4. [LLM 프로바이더 설정](#4-llm-프로바이더-설정)
5. [데모 파이프라인 실행](#5-데모-파이프라인-실행)
6. [프로젝트 레지스트리 설정](#6-프로젝트-레지스트리-설정)
7. [Observability 활성화](#7-observability-활성화)
8. [Guardrails 활성화](#8-guardrails-활성화)
9. [대시보드 실행](#9-대시보드-실행)
10. [테스트 실행](#10-테스트-실행)
11. [다음 단계](#11-다음-단계)

---

## 1. 사전 요구사항

### 필수

- **Python 3.11+** -- Archon은 3.11 이상의 타입 힌트 기능을 사용합니다.
- **Git** -- 소스 클론 및 자동 커밋 기능에 필요합니다.

### 선택 (사용하려는 기능에 따라 설치)

| 도구 | 용도 | 필요 시점 |
|---|---|---|
| **Redis** | 에이전트 간 Scratchpad(공유 메모리) | 멀티 에이전트 파이프라인 실행 시 |
| **ChromaDB** | 벡터 검색 기반 장기 메모리 | Memory 계층 사용 시 |
| **Ollama** | 로컬 LLM 추론 | 로컬 환경에서 에이전트 실행 시 |
| **vLLM** | GPU 서버 기반 고성능 추론 | GPU 클러스터 환경 |
| **LiteLLM Proxy** | 여러 LLM 프로바이더를 단일 API로 통합 | 복수 모델/프로바이더 사용 시 |

---

## 2. 설치

### 기본 설치

```bash
git clone https://github.com/aurakimjh/archon-framework.git
cd archon-framework

python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

`.[dev]`에는 pytest, ruff, mypy 등 개발 도구가 포함되어 있습니다.

### 추가 기능 설치 (선택)

필요한 기능에 따라 extras를 추가로 설치하실 수 있습니다.

```bash
# Observability -- LangSmith, Langfuse, AITOP 트레이싱 지원
pip install -e ".[observability]"

# Dashboard -- FastAPI 기반 실시간 모니터링 UI
pip install -e ".[dashboard]"

# 여러 extras를 한번에 설치
pip install -e ".[dev,observability,dashboard]"
```

---

## 3. 환경 설정

### 3-1. 설정 파일 복사

```bash
cp .env.example .env
cp config/litellm_config.yaml.example config/litellm_config.yaml
```

### 3-2. `.env` 파일 편집

`.env` 파일을 열어 필요한 값을 채워 넣으세요.

```env
# [필수] Anthropic API -- 오케스트레이터와 리뷰어 에이전트가 사용합니다.
ANTHROPIC_API_KEY=sk-ant-...

# [필수] LiteLLM Proxy 인증 키
LITELLM_MASTER_KEY=sk-...

# [선택] Redis -- 에이전트 간 Scratchpad 공유 메모리
REDIS_URL=redis://localhost:6379/0

# [선택] ChromaDB -- 벡터 검색 장기 메모리
CHROMA_HOST=localhost
CHROMA_PORT=8000

# [선택] Ollama -- 로컬 LLM 추론 서버
OLLAMA_BASE_URL=http://localhost:11434

# [선택] AITOP Monitoring -- 커스텀 트레이싱 백엔드
AITOP_SERVER_URL=http://localhost:8080
AITOP_PROJECT_TOKEN=

# [선택] Ray -- 분산 런타임 클러스터
RAY_ADDRESS=auto
```

> **참고**: Mock 데모만 실행하실 경우에는 API 키 없이도 동작합니다.

---

## 4. LLM 프로바이더 설정

Archon은 다양한 LLM 프로바이더를 지원합니다. 환경에 맞는 옵션을 선택하세요.

### 옵션 A: Ollama (로컬 환경에서 가장 간편)

로컬 머신에서 LLM을 직접 실행하는 방식입니다. GPU가 없어도 동작하지만, 충분한 RAM이 필요합니다.

```bash
# Ollama 설치 (https://ollama.ai)
# 설치 후 아래 모델을 다운로드합니다:

ollama pull deepseek-v3.2:70b   # Backend Agent용
ollama pull qwen3.5:32b          # Frontend Agent용
```

### 옵션 B: vLLM (GPU 서버)

전용 GPU 서버가 있는 경우, vLLM으로 고성능 추론 환경을 구성할 수 있습니다.

```bash
# GPU 서버에서 vLLM 실행
python -m vllm.entrypoints.openai.api_server \
    --model deepseek-ai/DeepSeek-V3 \
    --port 8000
```

### 옵션 C: LiteLLM Proxy (복수 프로바이더 통합)

여러 모델과 프로바이더를 하나의 API 엔드포인트로 묶어 관리합니다. 프로덕션 환경에 적합합니다.

```bash
# config/litellm_config.yaml을 편집한 뒤 실행합니다
litellm --config config/litellm_config.yaml --port 4000
```

### 옵션 D: 클라우드 API만 사용 (Claude / OpenAI)

로컬 LLM 없이 클라우드 API만 사용하실 수도 있습니다. `.env`에 API 키만 설정하면 됩니다.

```env
ANTHROPIC_API_KEY=sk-ant-...
```

이 경우 LiteLLM Proxy 설정에서 클라우드 모델만 라우팅하도록 구성하세요.

---

## 5. 데모 파이프라인 실행

데모 파이프라인은 Archon의 전체 워크플로우를 체험할 수 있는 가장 빠른 방법입니다.

### Mock 모드 (LLM 불필요)

LLM 없이 파이프라인의 전체 흐름을 확인할 수 있습니다. 처음 시작할 때 이 모드를 권장합니다.

```bash
# 기본 mock 데모 실행
python -m archon demo

# 시나리오별 실행
python -m archon demo --scenario auto_pass   # 첫 시도에 통과
python -m archon demo --scenario l1           # 린트 실패 -> 재작업 -> 통과
python -m archon demo --scenario l2           # 리뷰 점수 미달 -> Human Gate 발동
```

#### 각 시나리오 설명

| 시나리오 | 동작 | 학습 포인트 |
|---|---|---|
| `auto_pass` | QA 통과 -> 자동 커밋 | 정상 흐름의 기본 동작 |
| `l1` | 린트 실패 -> 에이전트 자동 재작업 (최대 3회) -> 통과 | 자동 복구 루프 |
| `l2` | 리뷰 점수 미달 -> Human Gate 발동, 개발자 알림 | 사람 개입이 필요한 상황 |

#### 출력 예시 (`auto_pass`)

```
[loop 0] backend -> qa -> reviewer -> gate
  gate: AUTO_PASS (review_score=92, coverage=85%)
  committed: abc123
```

### 실제 LLM으로 실행

LiteLLM Proxy(또는 Ollama)가 실행 중인 상태에서 `--real` 플래그를 추가합니다.

```bash
python -m archon demo --real
```

### 버전 확인

```bash
python -m archon version
```

---

## 6. 프로젝트 레지스트리 설정

프로젝트 레지스트리는 Archon이 관리할 프로젝트의 설정을 정의합니다. `.harness/registry/` 디렉토리에 JSON 파일을 생성하세요.

```json
{
  "project_meta": {
    "project_id": "my_project",
    "project_name": "My Project",
    "description": "프로젝트 설명"
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

### 주요 필드 설명

- **`agent_config`**: 각 역할(백엔드, 프론트엔드, 리뷰어)에 할당할 모델을 지정합니다.
- **`quality_policy`**: 자동 통과/재작업/사람 개입의 기준이 되는 품질 임계값을 설정합니다.
- **`git_config`**: 자동 커밋 대상 레포지토리와 브랜치를 지정합니다.

전체 스키마는 [registry-schema.md](registry-schema.md)를 참고하세요.

---

## 7. Observability 활성화

Archon은 LangSmith, Langfuse, AITOP 세 가지 트레이싱 백엔드를 지원합니다. 에이전트의 동작을 추적하고 디버깅하는 데 유용합니다.

### 설치

```bash
pip install -e ".[observability]"
```

### 사용 예시

```python
from src.observability import TracingConfig, TracingBackend, create_tracer_from_config

# AITOP 백엔드 사용 예시
config = TracingConfig(
    backend=TracingBackend.AITOP,
    aitop_server_url="http://localhost:8080",
    aitop_project_token="your-token-here",
)
tracer = create_tracer_from_config(config)

# LangSmith 백엔드 사용 예시
config = TracingConfig(
    backend=TracingBackend.LANGSMITH,
)
tracer = create_tracer_from_config(config)
```

트레이서를 생성하면 파이프라인 실행 시 각 에이전트의 입출력, 토큰 사용량, 지연 시간 등을 자동으로 기록합니다.

---

## 8. Guardrails 활성화

Guardrails는 에이전트의 행동에 안전장치를 설정합니다. 토큰 사용량 제한, 민감 데이터 감지, 프롬프트 인젝션 방어 등을 지원합니다.

```python
from src.guardrails import GuardrailPolicy

policy = GuardrailPolicy(
    daily_token_limit=100_000,        # 일일 토큰 사용량 상한
    detect_sensitive_data=True,       # PII, API 키 등 민감 데이터 감지
    detect_prompt_injection=True,     # 프롬프트 인젝션 공격 탐지
)
```

### Dynamic Guardrails (Human Gate 연동)

파이프라인 실행 중 `payment`, `auth`, `migration` 등 고위험 경로나 키워드가 감지되면, 리뷰 점수와 무관하게 자동으로 게이트 레벨이 L2 이상으로 상향됩니다.

```
에이전트 작업 완료
    -> QA 파이프라인 (lint / test / security)
    -> Review Agent (점수 산출)
    -> evaluate_gate() 판정
        -> AUTO_PASS:  자동 커밋
        -> L1_REWORK:  에이전트 재작업 (최대 3회)
        -> L2_HUMAN:   개발자 알림, 일시정지
        -> L3_HALT:    긴급 중단
        -> L4_DEPLOY:  Human 최종 승인 필요
```

---

## 9. 대시보드 실행

대시보드는 프로젝트 상태, 에이전트 헬스체크, 파이프라인 실행 이력을 실시간으로 모니터링할 수 있는 웹 UI입니다.

### 설치

```bash
pip install -e ".[dashboard]"
```

### 실행

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

브라우저에서 `http://localhost:8501`에 접속하면 대시보드를 확인하실 수 있습니다.

---

## 10. 테스트 실행

### 전체 테스트 실행

```bash
pytest tests/ -v
```

### 특정 모듈 테스트

```bash
pytest tests/test_agents_pool.py -v       # 에이전트 풀
pytest tests/test_gate.py -v              # Human Gate
pytest tests/test_guardrails.py -v        # Guardrails
pytest tests/test_observability.py -v     # Observability
```

### 린트 및 타입 체크

```bash
ruff check src/            # 코드 스타일 린트
mypy src/                  # 정적 타입 체크
```

---

## 11. 다음 단계

기본 설정과 데모를 마치셨다면, 아래 문서에서 더 자세한 내용을 확인하실 수 있습니다.

- **[아키텍처](architecture.md)** -- 시스템 전체 구조와 에이전트 간 통신 방식
- **[플러그인 가이드](plugin-guide.md)** -- 커스텀 에이전트 및 플러그인 개발 방법
- **[운영 가이드](operations-guide.md)** -- 프로덕션 배포 및 운영 모범 사례
- **[Human Gate 설계](human-gate.md)** -- 게이트 레벨별 동작 상세
- **[Handoff Artifact 스키마](handoff-schema.md)** -- 에이전트 간 데이터 교환 형식
- **[Project Registry 스키마](registry-schema.md)** -- 프로젝트 설정 전체 스키마
- **[API 레퍼런스](api-reference.md)** -- 모듈별 API 상세
