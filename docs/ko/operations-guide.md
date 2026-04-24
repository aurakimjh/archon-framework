# 운영 가이드

[English](../en/operations-guide.md)

> 버전: 2.0.0 | 최종 수정: 2026-04-24

## 목차

1. [배포](#1-배포)
2. [환경 변수](#2-환경-변수)
3. [LLM 모델 설정](#3-llm-모델-설정)
4. [관측성 및 모니터링](#4-관측성-및-모니터링)
5. [가드레일 운영](#5-가드레일-운영)
6. [셀프 힐링 운영](#6-셀프-힐링-운영)
7. [대시보드 운영](#7-대시보드-운영)
8. [벤치마크 운영](#8-벤치마크-운영)
9. [진화 루프 운영](#9-진화-루프-운영)
10. [KubeRay 운영](#10-kuberay-운영)
11. [하이브리드 클라우드 운영](#11-하이브리드-클라우드-운영)
12. [트랜잭션 스냅샷](#12-트랜잭션-스냅샷)
13. [백업 및 복구](#13-백업-및-복구)
14. [트러블슈팅 FAQ](#14-트러블슈팅-faq)

---

## 1. 배포

이 섹션에서는 로컬 개발부터 Kubernetes 클러스터까지 모든 배포 방법을 설명합니다. 처음 시작하시는 분은 "로컬 개발 환경"부터 따라 주세요.

### 1.1 사전 요구 사항

| 항목 | 버전 | 필수 여부 | 설명 |
|---|---|---|---|
| Python | 3.11 이상 | 필수 | 프레임워크 런타임 |
| pip / uv | 최신 | 필수 | 패키지 관리자 |
| Redis | 7.x | 권장 | L1 스크래치패드 (없으면 인메모리 폴백) |
| ChromaDB | 0.4.x | 권장 | L2 벡터 스토어 (없으면 인메모리 폴백) |
| Docker | 24.x 이상 | 선택 | 컨테이너 배포 시 |
| Ollama | 최신 | 선택 | 로컬 LLM 추론 |
| Node.js | 18+ | 선택 | 대시보드 프론트엔드 |

### 1.2 로컬 개발 환경

```bash
# 1. 레포 클론
git clone https://github.com/your-org/archon-framework.git
cd archon-framework

# 2. 가상 환경 생성 (권장)
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# 3. 의존성 설치
pip install -r requirements.txt

# 4. 환경 변수 설정
cp .env.example .env
# .env 파일을 열어 API 키를 입력합니다

# 5. 데모 실행 (mock — LLM 연결 불필요)
python -m src.demo.pipeline

# 6. 실제 파이프라인 실행
python -m src --project-id my-project --task-id task-001
```

> **왜 가상 환경을 사용하나요?** 시스템 Python과 프로젝트 의존성을 분리하면 버전 충돌을 방지할 수 있습니다. 특히 여러 프로젝트를 동시에 관리하는 환경에서 필수적입니다.

### 1.3 Docker

```dockerfile
# Dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1
CMD ["python", "-m", "src"]
```

```bash
# 이미지 빌드
docker build -t archon:latest .

# 컨테이너 실행 (환경 변수 파일 주입)
docker run --env-file .env \
  -v $(pwd)/.harness:/app/.harness \
  archon:latest
```

### 1.4 Docker Compose (전체 스택)

대시보드, Redis, ChromaDB를 포함한 전체 스택을 한 번에 실행합니다.

```yaml
# docker-compose.yml
version: "3.9"

services:
  archon:
    build: .
    env_file: .env
    ports:
      - "8000:8000"         # API 서버
    volumes:
      - ./.harness:/app/.harness
    depends_on:
      - redis
      - chroma

  dashboard:
    build:
      context: ./dashboard
    ports:
      - "3000:3000"         # 대시보드 UI
    environment:
      - ARCHON_API_URL=http://archon:8000
    depends_on:
      - archon

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    command: redis-server --appendonly yes
    # appendonly로 설정하면 장애 시 데이터 손실을 최소화합니다

  chroma:
    image: chromadb/chroma:latest
    ports:
      - "8001:8000"
    volumes:
      - chroma_data:/chroma/chroma

volumes:
  redis_data:
  chroma_data:
```

```bash
# 전체 스택 시작
docker-compose up -d

# 로그 확인
docker-compose logs -f archon

# 중지
docker-compose down
```

### 1.5 Ollama 서버 배포

Ollama는 로컬 환경에서 오픈소스 LLM을 실행할 때 사용합니다. 클라우드 API 비용 없이 개발/테스트가 가능합니다.

```bash
# macOS (Homebrew)
brew install ollama

# Linux
curl -fsSL https://ollama.com/install.sh | sh

# 서비스 시작
ollama serve
# 기본 포트: 11434

# 모델 다운로드
ollama pull llama3.3:70b
ollama pull deepseek-v3.2:7b

# 모델 목록 확인
ollama list

# 헬스체크
curl http://localhost:11434/api/tags
```

Docker Compose에 Ollama를 추가할 수도 있습니다.

```yaml
  ollama:
    image: ollama/ollama:latest
    ports:
      - "11434:11434"
    volumes:
      - ollama_data:/root/.ollama
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]
```

> **왜 Ollama인가요?** 민감한 데이터를 외부 API로 전송하지 않아도 되고, 네트워크 지연 없이 추론할 수 있습니다. 개발 환경에서는 7B 모델로 빠르게 반복 테스트하고, 프로덕션에서는 70B 모델로 품질을 확보하는 전략이 효과적입니다.

### 1.6 AITOP 모니터링 서버

AITOP은 AI 에이전트 워크로드를 추적하는 관측성 서버입니다. OTLP/HTTP 프로토콜로 트레이스를 수신합니다.

```bash
# AITOP 서버 실행
docker run -d \
  --name aitop \
  -p 8080:8080 \
  -e AITOP_DB_PATH=/data/aitop.db \
  -v aitop_data:/data \
  aitop/server:latest

# 헬스체크
curl http://localhost:8080/health
```

Docker Compose에 추가:

```yaml
  aitop:
    image: aitop/server:latest
    ports:
      - "8080:8080"
    environment:
      - AITOP_DB_PATH=/data/aitop.db
    volumes:
      - aitop_data:/data
```

### 1.7 Kubernetes 배포

#### 기본 Deployment

```yaml
# k8s/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: archon
  namespace: archon-system
spec:
  replicas: 2
  selector:
    matchLabels:
      app: archon
  template:
    metadata:
      labels:
        app: archon
    spec:
      containers:
        - name: archon
          image: your-registry/archon:latest
          envFrom:
            - secretRef:
                name: archon-secrets
            - configMapRef:
                name: archon-config
          volumeMounts:
            - name: harness
              mountPath: /app/.harness
      volumes:
        - name: harness
          persistentVolumeClaim:
            claimName: archon-harness-pvc
```

#### Secret 생성

```bash
kubectl create secret generic archon-secrets \
  --from-literal=ANTHROPIC_API_KEY=sk-ant-... \
  --from-literal=LITELLM_MASTER_KEY=sk-litellm-... \
  --from-literal=REDIS_URL=redis://redis-service:6379/0 \
  --from-literal=AITOP_PROJECT_TOKEN=your-token \
  -n archon-system
```

#### ConfigMap

```yaml
# k8s/configmap.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: archon-config
  namespace: archon-system
data:
  ARCHON_LOG_LEVEL: "INFO"
  ARCHON_ENV: "production"
  ARCHON_MAX_CONCURRENT_TASKS: "4"
  CHROMA_HOST: "chroma-service"
  CHROMA_PORT: "8000"
  OLLAMA_BASE_URL: "http://ollama-service:11434"
  AITOP_SERVER_URL: "http://aitop-service:8080"
  RAY_ADDRESS: "auto"
```

#### KubeRay 통합 배포

Kubernetes에서 Ray 클러스터를 운영하려면 KubeRay operator를 사용합니다. 상세 설정은 [10. KubeRay 운영](#10-kuberay-운영)을 참조하세요.

---

## 2. 환경 변수

`.env.example`을 복사해 `.env`를 만들고 아래 변수를 설정합니다. 각 변수가 **무엇을 제어하는지** 설명과 함께 정리했습니다.

### 핵심 API 키

```dotenv
# Anthropic — Orchestrator와 Reviewer 에이전트가 사용합니다
# 없으면 Orchestrator가 시작되지 않습니다
ANTHROPIC_API_KEY=sk-ant-...

# LiteLLM 프록시 마스터 키 — 여러 LLM 프로바이더를 단일 엔드포인트로 통합할 때 사용합니다
LITELLM_MASTER_KEY=sk-litellm-...

# LiteLLM 내부 DB — 프록시 설정과 사용량 로그가 저장됩니다
DATABASE_URL=sqlite:///litellm.db
```

### 메모리 백엔드

```dotenv
# Redis (L1 스크래치패드) — 에이전트 간 실시간 컨텍스트 공유에 사용됩니다
# URL 형식: redis://[password@]host:port/db_number
REDIS_URL=redis://localhost:6379/0
REDIS_TTL=86400                    # 키 만료 시간 (초), 기본 24시간

# ChromaDB (L2 벡터 스토어) — 코드베이스 임베딩 검색에 사용됩니다
CHROMA_HOST=localhost
CHROMA_PORT=8000
CHROMA_COLLECTION_PREFIX=archon    # 컬렉션 네이밍 접두어

# Mem0 (L3 장기 메모리, 선택) — 프로젝트 간 학습 내용을 기억합니다
MEM0_API_KEY=m0-...
MEM0_USER_ID=archon-prod
```

### 로컬 LLM

```dotenv
# Ollama — 로컬 오픈소스 모델 서버
# Ollama 서버의 기본 URL을 설정합니다
OLLAMA_BASE_URL=http://localhost:11434
```

### AITOP 모니터링

```dotenv
# AITOP — AI 에이전트 관측성 서버
# OTLP/HTTP 프로토콜로 트레이스를 전송합니다
AITOP_SERVER_URL=http://localhost:8080
AITOP_PROJECT_TOKEN=               # 프로젝트별 인증 토큰
```

### 관측성 (선택)

```dotenv
# LangSmith — LLM 호출 트레이싱 (선택)
LANGSMITH_API_KEY=ls-...

# Langfuse — 오픈소스 LLM 관측성 (선택)
LANGFUSE_HOST=http://localhost:3100
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
```

### 대시보드

```dotenv
# CORS — 대시보드가 API 서버에 접근할 수 있도록 허용할 오리진을 지정합니다
# 여러 오리진은 쉼표로 구분합니다
ARCHON_CORS_ORIGINS=http://localhost:3000,http://localhost:8501
```

### 알림

```dotenv
# Slack — Gate 판정 결과를 Slack 채널로 전송합니다
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...

# PagerDuty — L3_HALT 이상의 심각한 이벤트에 대해 알림을 보냅니다
PAGERDUTY_INTEGRATION_KEY=...
```

### Ray

```dotenv
# Ray 클러스터 주소 — "auto"로 설정하면 자동으로 로컬 클러스터에 연결합니다
RAY_ADDRESS=auto
```

### 런타임

```dotenv
# 로그 레벨 — DEBUG로 설정하면 LLM 호출 세부 정보가 출력됩니다
ARCHON_LOG_LEVEL=INFO              # DEBUG / INFO / WARNING / ERROR

# 실행 환경 — production에서는 디버그 출력이 비활성화됩니다
ARCHON_ENV=development             # development / production

# 동시 실행 — TaskScheduler가 병렬로 실행할 태스크 수
ARCHON_MAX_CONCURRENT_TASKS=4

# 타임아웃 — 에이전트 하나의 실행 제한 시간 (초)
ARCHON_DEFAULT_TIMEOUT=120
```

---

## 3. LLM 모델 설정

Archon은 여러 LLM 프로바이더를 유연하게 조합할 수 있도록 설계되었습니다. 이 섹션에서는 프로바이더별 설정과 에이전트 역할별 모델 할당 방법을 설명합니다.

### 3.1 LiteLLM 프록시 설정

LiteLLM 프록시는 여러 LLM 프로바이더(Anthropic, OpenAI, Ollama, vLLM 등)를 단일 엔드포인트(`http://localhost:4000`)로 통합합니다. 프로바이더를 교체할 때 코드 변경 없이 설정만 바꾸면 됩니다.

```bash
# LiteLLM 설치
pip install litellm[proxy]

# 프록시 서버 시작
litellm --config config/litellm_config.yaml --port 4000
```

```yaml
# config/litellm_config.yaml (예시)
model_list:
  # Anthropic 모델
  - model_name: orchestrator
    litellm_params:
      model: claude-sonnet-4-6
      api_key: os.environ/ANTHROPIC_API_KEY

  # Ollama 로컬 모델
  - model_name: backend-agent
    litellm_params:
      model: ollama/llama3.3:70b
      api_base: http://localhost:11434
      stream: true

  - model_name: tester-agent
    litellm_params:
      model: ollama/deepseek-v3.2:7b
      api_base: http://localhost:11434

  # vLLM GPU 모델
  - model_name: backend-agent-gpu
    litellm_params:
      model: openai/meta-llama/Llama-3.3-70B-Instruct
      api_base: http://gpu-node-01:8000
      stream: true

general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
  database_url: os.environ/DATABASE_URL
```

### 3.2 Ollama 설정

```bash
# 1. Ollama 설치 (아직 하지 않았다면)
# macOS
brew install ollama
# Linux
curl -fsSL https://ollama.com/install.sh | sh

# 2. 서비스 시작
ollama serve

# 3. 모델 다운로드
ollama pull llama3.3:70b        # 백엔드 에이전트용 (고품질)
ollama pull deepseek-v3.2:7b    # 테스터 에이전트용 (빠른 속도)
ollama pull deepseek-v3.2:70b   # 복잡한 작업용

# 4. 모델이 정상적으로 설치되었는지 확인
ollama list

# 5. LiteLLM에 엔드포인트 등록 (위 litellm_config.yaml 참조)
```

> **팁:** Ollama 모델은 처음 로딩에 시간이 걸립니다. `ollama run llama3.3:70b "hello"` 로 워밍업하면 첫 번째 요청의 지연을 방지할 수 있습니다.

### 3.3 vLLM 설정 (GPU 서버)

GPU가 있는 서버에서 고성능 추론을 원할 때 사용합니다.

```bash
# GPU 노드에서 vLLM 서버 실행
python -m vllm.entrypoints.openai.api_server \
  --model meta-llama/Llama-3.3-70B-Instruct \
  --tensor-parallel-size 2 \
  --gpu-memory-utilization 0.9 \
  --port 8000
```

```python
# Orchestrator에 VLLMBridge 주입
from src.runtime.vllm_bridge import VLLMBridge, VLLMEndpoint

bridge = VLLMBridge(timeout=5.0)
bridge.register(VLLMEndpoint(
    name="vllm/backend-llm",
    base_url="http://gpu-node-01:8000",
    model_name="meta-llama/Llama-3.3-70B-Instruct",
    gpu_memory_utilization=0.9,
    tensor_parallel_size=2,
    tags=["backend"],
))
await bridge.health_check_all()
```

### 3.4 프로바이더 라우팅 체인

Archon은 다음 우선순위로 모델 프로바이더를 선택합니다:

```
vLLM (GPU) → Ollama (로컬 CPU/GPU) → 기본값 (Anthropic/OpenAI API)
```

vLLM 서버가 응답하지 않으면 Ollama로 폴백하고, Ollama도 사용 불가하면 클라우드 API를 사용합니다. 이 체인은 비용 최적화와 가용성을 모두 확보합니다.

### 3.5 에이전트 역할별 모델 할당

Registry JSON의 `agent_config` 섹션에서 역할별 모델을 지정합니다.

```json
{
  "agent_config": {
    "orchestrator": {
      "model": "claude-sonnet-4-6",
      "max_tokens": 8192,
      "temperature": 0.2,
      "streaming": true,
      "timeout_seconds": 120
    },
    "backend": {
      "model": "ollama/llama3.3:70b",
      "max_tokens": 8192,
      "temperature": 0.2,
      "high_complexity_model": "ollama/deepseek-v3.2:70b"
    },
    "tester": {
      "model": "ollama/deepseek-v3.2:7b",
      "max_tokens": 4096,
      "temperature": 0.1
    },
    "reviewer": {
      "model": "claude-sonnet-4-6",
      "max_tokens": 4096,
      "temperature": 0.1
    }
  }
}
```

### 3.6 복잡도 기반 동적 모델 선택

`high_complexity_model`을 설정하면 Complexity Router가 작업 복잡도를 자동 분석해 모델을 전환합니다.

```json
{
  "agent_config": {
    "backend": {
      "model": "ollama/deepseek-v3.2:7b",
      "high_complexity_model": "ollama/deepseek-v3.2:70b"
    }
  }
}
```

Complexity Router는 8가지 기준을 평가합니다:
- 파일 수, diff 라인 수, 의존성 깊이, 순환 복잡도 등
- HIGH로 판정되면 자동으로 `high_complexity_model`을 선택합니다
- 간단한 작업에는 작고 빠른 모델, 복잡한 작업에는 크고 정확한 모델을 사용해 비용과 품질의 균형을 맞춥니다

---

## 4. 관측성 및 모니터링

관측성은 에이전트가 **무엇을 했는지, 얼마나 걸렸는지, 비용은 얼마인지** 파악하는 데 핵심입니다. Archon은 여러 트레이싱 백엔드를 동시에 사용할 수 있습니다.

### 4.1 TracingConfig 설정

```python
from src.observability.tracing import TracingConfig

config = TracingConfig(
    enabled=True,                    # False로 설정하면 모든 트레이싱 비활성화
    backend="composite",             # 단일: "langsmith", "langfuse", "aitop"
                                     # 복합: "composite"
    sample_rate=1.0,                 # 1.0 = 모든 요청 추적
                                     # 0.1 = 10%만 추적 (프로덕션 권장)
    export_interval_seconds=30,      # 배치 전송 간격
)
```

### 4.2 LangSmith 백엔드

LangSmith는 LangChain 팀이 제공하는 LLM 관측성 플랫폼입니다.

```dotenv
LANGSMITH_API_KEY=ls-...
```

```python
from src.observability.tracing import LangSmithTracer

tracer = LangSmithTracer(
    api_key=os.environ["LANGSMITH_API_KEY"],
    project_name="archon-production",
)
```

### 4.3 Langfuse 백엔드

Langfuse는 셀프 호스팅이 가능한 오픈소스 LLM 관측성 도구입니다.

```dotenv
LANGFUSE_HOST=http://localhost:3100
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
```

```python
from src.observability.tracing import LangfuseTracer

tracer = LangfuseTracer(
    host=os.environ["LANGFUSE_HOST"],
    public_key=os.environ["LANGFUSE_PUBLIC_KEY"],
    secret_key=os.environ["LANGFUSE_SECRET_KEY"],
)
```

### 4.4 AITOP 백엔드 (OTLP/HTTP)

AITOP은 OTLP/HTTP 프로토콜을 사용하여 에이전트 트레이스를 수집합니다.

```dotenv
AITOP_SERVER_URL=http://localhost:8080
AITOP_PROJECT_TOKEN=your-project-token
```

```python
from src.observability.tracing import AitopTracer

tracer = AitopTracer(
    server_url=os.environ["AITOP_SERVER_URL"],
    project_token=os.environ["AITOP_PROJECT_TOKEN"],
)
```

### 4.5 CompositeTracer (여러 백엔드 동시 사용)

여러 트레이싱 백엔드에 동시에 트레이스를 전송합니다. 개발 중에는 LangSmith로, 프로덕션에서는 AITOP으로 보내는 식의 구성이 가능합니다.

```python
from src.observability.tracing import CompositeTracer

tracer = CompositeTracer(tracers=[
    LangSmithTracer(api_key="..."),
    AitopTracer(server_url="...", project_token="..."),
])
```

### 4.6 SamplingTracer (프로덕션 최적화)

프로덕션 환경에서 모든 요청을 추적하면 성능 오버헤드가 발생합니다. SamplingTracer를 사용하면 지정된 비율만 추적합니다.

```python
from src.observability.tracing import SamplingTracer

# 전체 요청의 10%만 추적
tracer = SamplingTracer(
    inner=CompositeTracer(tracers=[...]),
    sample_rate=0.1,
)
```

> **왜 샘플링이 필요한가요?** 프로덕션에서 매 요청마다 트레이스를 전송하면 네트워크 비용과 스토리지가 급증합니다. 10% 샘플링으로도 문제 패턴을 충분히 파악할 수 있습니다.

### 4.7 TracingMiddleware 통합

Orchestrator와 BaseAgent에 TracingMiddleware를 연결하면 모든 LLM 호출이 자동으로 추적됩니다.

```python
from src.observability.tracing import TracingMiddleware

middleware = TracingMiddleware(tracer=tracer)

# Orchestrator에 연결
orchestrator = Orchestrator(
    middleware=[middleware],
    # ...
)

# 또는 BaseAgent에 직접 연결
agent = BackendAgent(
    tracing_middleware=middleware,
    # ...
)
```

### 4.8 트레이스 확인 방법

| 백엔드 | 접근 방법 |
|---|---|
| LangSmith | https://smith.langchain.com 에서 프로젝트 선택 |
| Langfuse | `LANGFUSE_HOST` URL 접속 후 Traces 탭 |
| AITOP | `AITOP_SERVER_URL` 접속 후 프로젝트 대시보드 |

### 4.9 로그

Archon은 Python 표준 `logging` 모듈을 사용합니다.

```dotenv
ARCHON_LOG_LEVEL=INFO   # DEBUG로 설정하면 LLM 호출 세부 정보 출력
```

구조화 로그 예시:

```
2026-04-24 12:00:01 INFO  [orchestrator] Task started: task-payment-002
2026-04-24 12:00:05 INFO  [backend_agent] execute() completed in 4.2s
2026-04-24 12:00:05 INFO  [qa] run_qa_pipeline() passed: ruff=OK mypy=OK pytest=12passed
2026-04-24 12:00:06 INFO  [gate] Decision: AUTO_PASS (score=92)
```

### 4.10 Human Gate 알림

`CompositeNotifier`가 Gate 판정 시 각 채널로 이벤트를 전송합니다.

| Gate | TerminalNotifier | SlackNotifier | PagerDuty |
|---|---|---|---|
| AUTO_PASS | 초록 배너 | - | - |
| L1_REWORK | 노란 배너 | 전송 | - |
| L2_HUMAN | 빨간 배너 | 전송 | - |
| L3_HALT | 빨간 배너 | 전송 | 전송 |
| L4_DEPLOY | 파란 배너 | 전송 | 전송 |

---

## 5. 가드레일 운영

가드레일은 에이전트가 **허용된 범위 안에서만 동작**하도록 제한합니다. 토큰 예산 초과, 민감 데이터 노출, 보호 경로 수정 등을 사전에 차단합니다.

### 5.1 GuardrailPolicy 설정

```python
from src.guardrails.policy import GuardrailPolicy

policy = GuardrailPolicy(
    # 토큰 예산 관리
    daily_token_limit=1_000_000,        # 일일 토큰 한도
    per_task_token_limit=50_000,        # 태스크당 토큰 한도
    budget_alert_threshold=0.8,         # 80% 소진 시 경고

    # 민감 데이터 감지
    sensitive_patterns=[
        r"(?i)password\s*=\s*['\"].*['\"]",
        r"(?i)api[_-]?key\s*=\s*['\"].*['\"]",
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",  # 이메일
    ],

    # 보호 경로 — 에이전트가 수정할 수 없는 파일/디렉토리
    protected_paths=[
        ".harness/sop/production/",
        ".env",
        "config/litellm_config.yaml",
    ],

    # 고위험 경로 — 이 경로의 변경은 자동으로 Human Gate로 에스컬레이션
    high_risk_paths=[
        "src/core/",
        "migrations/",
    ],

    # 위반 시 동작: "block" (차단) 또는 "warn" (경고 후 계속)
    violation_action="block",
)
```

### 5.2 토큰 예산 관리

```python
# 현재 사용량 확인
usage = policy.get_daily_usage()
print(f"오늘 사용량: {usage.tokens_used:,} / {usage.daily_limit:,}")
print(f"잔여: {usage.tokens_remaining:,}")

# 예산 경고 콜백 설정
policy.on_budget_alert = lambda usage: notify_slack(
    f"토큰 예산 {usage.percent_used:.0%} 소진 ({usage.tokens_used:,} / {usage.daily_limit:,})"
)

# 일일 예산 수동 리셋 (긴급 시)
policy.reset_daily()
```

> **왜 토큰 예산을 설정하나요?** 에이전트가 무한 루프에 빠지거나 예상보다 큰 컨텍스트를 처리할 때 비용이 폭증할 수 있습니다. 일일 한도를 설정하면 이런 상황을 자동으로 차단합니다.

### 5.3 민감 데이터 감지 튜닝

기본 패턴에 프로젝트 특화 패턴을 추가할 수 있습니다.

```python
# 커스텀 패턴 추가
policy.sensitive_patterns.append(
    r"(?i)aws[_-]?secret[_-]?access[_-]?key\s*=\s*['\"].*['\"]"
)

# 오탐(false positive)이 많으면 패턴을 구체화합니다
# 나쁜 예: r"key" (너무 광범위)
# 좋은 예: r"(?i)api[_-]?key\s*=\s*['\"][A-Za-z0-9]{20,}['\"]"
```

### 5.4 보호 경로 설정

```python
# 경로 추가
policy.protected_paths.append("database/migrations/")

# 확인
for path in policy.protected_paths:
    print(f"  보호됨: {path}")
```

보호 경로의 파일을 에이전트가 수정하려고 하면 `ProtectedPathError`가 발생하고 작업이 중단됩니다.

### 5.5 위반 동작: block vs warn

| 동작 | 설명 | 사용 시기 |
|---|---|---|
| `block` | 위반 즉시 작업을 중단합니다 | 프로덕션 환경 |
| `warn` | 로그에 경고를 남기고 작업을 계속합니다 | 개발/테스트 환경 |

```python
# 개발 중에는 warn으로 설정해 흐름을 끊지 않습니다
policy.violation_action = "warn"

# 프로덕션에서는 반드시 block으로 설정합니다
policy.violation_action = "block"
```

---

## 6. 셀프 힐링 운영

셀프 힐링은 에이전트의 건강 상태를 모니터링하고, 문제가 발생하면 자동으로 복구합니다. 에이전트가 DEAD 상태에 빠지거나 응답 시간이 느려질 때 사람의 개입 없이 시스템이 자체적으로 대응합니다.

### 6.1 HealthMonitorRegistry 설정

```python
from src.self_healing.health import HealthMonitorRegistry, HealthThresholds

registry = HealthMonitorRegistry(
    thresholds=HealthThresholds(
        response_time_warning=5.0,    # 5초 이상이면 WARNING
        response_time_critical=15.0,  # 15초 이상이면 CRITICAL
        error_rate_warning=0.1,       # 10% 이상 에러면 WARNING
        error_rate_critical=0.3,      # 30% 이상 에러면 CRITICAL
        memory_usage_warning=0.8,     # 80% 이상 메모리 사용 시 WARNING
        memory_usage_critical=0.95,   # 95% 이상이면 CRITICAL
    ),
)
```

### 6.2 Watchdog 설정

Watchdog는 주기적으로 에이전트 상태를 점검하고, 문제 발생 시 설정된 동작을 수행합니다.

```python
from src.self_healing.watchdog import Watchdog, WatchdogConfig

config = WatchdogConfig(
    check_interval=30,            # 30초마다 점검
    alert_on_warning=True,        # WARNING 상태에서 알림 전송
    alert_on_critical=True,       # CRITICAL 상태에서 알림 전송
    auto_heal=True,               # 자동 복구 활성화
    max_heal_attempts=3,          # 최대 복구 시도 횟수
    heal_cooldown=60,             # 복구 시도 간 대기 시간 (초)
)

watchdog = Watchdog(
    health_registry=registry,
    config=config,
)
```

### 6.3 알림 콜백 설정

```python
# Slack 알림
async def slack_alert(event):
    await send_slack_message(
        channel="#archon-alerts",
        text=f"[{event.severity}] {event.agent_name}: {event.message}",
    )

# PagerDuty 알림 (CRITICAL만)
async def pagerduty_alert(event):
    if event.severity == "CRITICAL":
        await trigger_pagerduty(
            integration_key=os.environ["PAGERDUTY_INTEGRATION_KEY"],
            summary=f"Archon Agent Down: {event.agent_name}",
        )

# 커스텀 콜백 등록
watchdog.on_alert(slack_alert)
watchdog.on_alert(pagerduty_alert)
```

### 6.4 복구 전략

Archon은 4단계 복구 전략을 순차적으로 시도합니다:

| 단계 | 전략 | 설명 |
|---|---|---|
| 1 | `model_downgrade` | 더 작고 안정적인 모델로 교체 (예: 70B → 7B) |
| 2 | `agent_reinit` | 에이전트를 재초기화 (상태 리셋) |
| 3 | `substitute` | 동일 역할의 대체 에이전트로 교체 |
| 4 | `escalate` | 사람에게 에스컬레이션 (Human Gate L3_HALT) |

```python
from src.self_healing.strategies import RecoveryStrategy

# 커스텀 복구 전략 순서 지정
watchdog.recovery_strategies = [
    RecoveryStrategy.MODEL_DOWNGRADE,
    RecoveryStrategy.AGENT_REINIT,
    RecoveryStrategy.SUBSTITUTE,
    RecoveryStrategy.ESCALATE,
]
```

### 6.5 진단 리포트 해석

```python
# 진단 리포트 생성
report = await watchdog.generate_diagnostic_report()

print(report.summary)
# 출력 예시:
# Agent Health Report (2026-04-24 12:00:00)
# ----------------------------------------
# backend_agent: HEALTHY (response_time: 1.2s, error_rate: 0.02)
# tester_agent:  WARNING (response_time: 6.3s, error_rate: 0.05)
# reviewer:      CRITICAL (response_time: 18.1s, error_rate: 0.35)
#
# Recommendations:
# - reviewer: Consider model_downgrade or check LLM provider status

for agent_report in report.agents:
    if agent_report.status != "HEALTHY":
        print(f"  {agent_report.name}: {agent_report.recommendations}")
```

---

## 7. 대시보드 운영

대시보드는 Archon의 실시간 상태를 시각적으로 모니터링하고, Human Gate 큐를 관리하는 웹 인터페이스입니다.

### 7.1 대시보드 서버 시작

```bash
# 사전 요구 사항
pip install fastapi uvicorn websockets

# 대시보드 API 서버 시작
python -m src.dashboard.server --host 0.0.0.0 --port 8000

# 프론트엔드 (별도 터미널)
cd dashboard
npm install
npm run dev    # http://localhost:3000
```

### 7.2 CORS 설정

대시보드 프론트엔드가 API 서버에 접근하려면 CORS 설정이 필요합니다.

```dotenv
# .env
ARCHON_CORS_ORIGINS=http://localhost:3000,http://localhost:8501
```

> **왜 CORS가 필요한가요?** 브라우저의 보안 정책상, 다른 도메인/포트의 API 요청은 기본적으로 차단됩니다. 대시보드(3000번 포트)가 API 서버(8000번 포트)에 접근하려면 명시적으로 허용해야 합니다.

### 7.3 API 엔드포인트 개요

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/health` | 서버 헬스체크 |
| GET | `/api/tasks` | 진행 중인 태스크 목록 |
| GET | `/api/tasks/{id}` | 태스크 상세 정보 |
| GET | `/api/agents/status` | 에이전트 상태 |
| GET | `/api/gate/queue` | Human Gate 대기열 |
| POST | `/api/gate/{id}/approve` | Gate 항목 승인 |
| POST | `/api/gate/{id}/reject` | Gate 항목 거부 |
| GET | `/api/metrics/cost` | 비용 메트릭 |
| GET | `/api/metrics/tokens` | 토큰 사용량 |

### 7.4 WebSocket 이벤트

실시간 업데이트를 위해 WebSocket 연결을 지원합니다.

```javascript
// ws://localhost:8000/ws
const ws = new WebSocket("ws://localhost:8000/ws");

ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    // 이벤트 타입:
    // - task_started:   태스크 시작
    // - task_completed: 태스크 완료
    // - gate_pending:   Human Gate 대기
    // - agent_status:   에이전트 상태 변경
    // - cost_update:    비용 업데이트
    console.log(data.type, data.payload);
};
```

### 7.5 Human Gate 큐 관리

대시보드에서 Human Gate 대기열을 확인하고 승인/거부할 수 있습니다.

```bash
# CLI로도 관리 가능
# 대기열 확인
curl http://localhost:8000/api/gate/queue

# 승인
curl -X POST http://localhost:8000/api/gate/{id}/approve \
  -H "Content-Type: application/json" \
  -d '{"reviewer": "username", "comment": "LGTM"}'

# 거부 (사유 필수)
curl -X POST http://localhost:8000/api/gate/{id}/reject \
  -H "Content-Type: application/json" \
  -d '{"reviewer": "username", "reason": "보안 검토 필요"}'
```

### 7.6 비용 모니터링

대시보드의 Cost 탭에서 실시간 비용을 확인할 수 있습니다.

```bash
# API로 비용 조회
curl http://localhost:8000/api/metrics/cost?period=today
# 응답 예시:
# {
#   "period": "2026-04-24",
#   "total_cost_usd": 12.45,
#   "by_model": {
#     "claude-sonnet-4-6": 8.20,
#     "ollama/llama3.3:70b": 0.00,
#     "ollama/deepseek-v3.2:7b": 0.00
#   },
#   "by_agent": {
#     "orchestrator": 5.10,
#     "backend": 4.80,
#     "reviewer": 2.55
#   }
# }
```

---

## 8. 벤치마크 운영

벤치마크를 통해 에이전트별 모델 성능을 측정하고, 최적의 모델 할당을 찾을 수 있습니다.

### 8.1 벤치마크 실행

```bash
# 기본 벤치마크 실행
python -m src.benchmark run --config benchmarks/default.yaml

# 특정 에이전트만 벤치마크
python -m src.benchmark run --agent backend --models "ollama/llama3.3:70b,ollama/deepseek-v3.2:7b"

# 결과 저장 경로 지정
python -m src.benchmark run --output benchmarks/results/2026-04-24.json
```

### 8.2 커스텀 벤치마크 태스크

```yaml
# benchmarks/custom_tasks.yaml
tasks:
  - name: "API endpoint 생성"
    description: "FastAPI CRUD 엔드포인트 작성"
    complexity: "medium"
    expected_files: ["src/api/users.py", "tests/test_users.py"]
    evaluation_criteria:
      - "타입 힌트 사용 여부"
      - "에러 처리 포함 여부"
      - "테스트 커버리지 50% 이상"

  - name: "데이터베이스 마이그레이션"
    description: "사용자 테이블에 email 컬럼 추가"
    complexity: "low"
    expected_files: ["migrations/003_add_email.py"]
```

```bash
python -m src.benchmark run --tasks benchmarks/custom_tasks.yaml
```

### 8.3 결과 해석

```bash
# 결과 확인
python -m src.benchmark report --input benchmarks/results/2026-04-24.json

# 출력 예시:
# ┌─────────────────┬──────────────────────┬──────────┬──────────┬─────────┐
# │ Agent           │ Model                │ Score    │ Latency  │ Cost    │
# ├─────────────────┼──────────────────────┼──────────┼──────────┼─────────┤
# │ backend         │ ollama/llama3.3:70b  │ 87/100   │ 12.3s    │ $0.00   │
# │ backend         │ claude-sonnet-4-6    │ 94/100   │ 3.1s     │ $0.12   │
# │ tester          │ ollama/deepseek:7b   │ 72/100   │ 2.1s     │ $0.00   │
# │ tester          │ claude-haiku-4-5     │ 89/100   │ 1.2s     │ $0.01   │
# └─────────────────┴──────────────────────┴──────────┴──────────┴─────────┘
```

### 8.4 모델 추천 적용

```bash
# 벤치마크 결과 기반 모델 추천
python -m src.benchmark recommend --input benchmarks/results/2026-04-24.json

# 추천을 Registry에 자동 적용
python -m src.benchmark apply --input benchmarks/results/2026-04-24.json --registry .harness/registry/my-project.json
```

### 8.5 정기 벤치마크 스케줄링

```bash
# cron으로 주간 벤치마크 실행 (매주 일요일 02:00)
# crontab -e
0 2 * * 0 cd /path/to/archon-framework && python -m src.benchmark run --output benchmarks/results/$(date +\%Y-\%m-\%d).json
```

---

## 9. 진화 루프 운영

진화 루프는 Archon이 **실행 결과를 학습하여 스스로 개선**하는 메커니즘입니다. 반복 실행을 통해 GuardrailPolicy, 모델 할당, 에이전트 파라미터를 자동으로 튜닝합니다.

### 9.1 진화 루프 활성화

```python
from src.evolution.loop import EvolutionLoop, EvolutionConfig

config = EvolutionConfig(
    enabled=True,                     # False면 진화 루프 비활성화
    min_executions=10,                # 최소 10회 실행 후부터 튜닝 시작
    evaluation_window=50,             # 최근 50회 실행 기준으로 평가
    improvement_threshold=0.05,       # 5% 이상 개선될 때만 정책 변경
    max_tuning_actions_per_cycle=3,   # 한 사이클에 최대 3개 액션
)

loop = EvolutionLoop(config=config)
```

> **왜 `min_executions`가 필요한가요?** 실행 횟수가 적을 때는 통계적으로 유의미한 패턴을 판단할 수 없습니다. 충분한 데이터가 모인 후에 튜닝을 시작해야 오판을 방지합니다.

### 9.2 EvolutionConfig 튜닝

| 파라미터 | 기본값 | 설명 |
|---|---|---|
| `enabled` | `False` | 진화 루프 활성화 여부 |
| `min_executions` | 10 | 튜닝 시작 최소 실행 횟수 |
| `evaluation_window` | 50 | 평가 대상 최근 실행 횟수 |
| `improvement_threshold` | 0.05 | 정책 변경 최소 개선 비율 |
| `max_tuning_actions_per_cycle` | 3 | 사이클당 최대 튜닝 액션 수 |
| `cycle_interval_seconds` | 3600 | 사이클 실행 간격 (초) |

### 9.3 튜닝 액션 이해

진화 루프가 수행할 수 있는 튜닝 액션:

| 액션 | 설명 | 예시 |
|---|---|---|
| `adjust_model` | 에이전트 모델 변경 | 7B → 70B (품질이 낮을 때) |
| `adjust_temperature` | 온도 파라미터 조정 | 0.2 → 0.1 (일관성 향상) |
| `adjust_token_limit` | 태스크 토큰 한도 조정 | 50K → 80K (토큰 부족 시) |
| `adjust_timeout` | 에이전트 타임아웃 조정 | 120s → 180s (타임아웃 빈발 시) |
| `adjust_threshold` | Gate 임계값 조정 | 85 → 80 (AUTO_PASS 비율 낮을 때) |

### 9.4 on_policy_updated 콜백

정책이 변경될 때 콜백을 등록하여 변경 내역을 저장하거나 알림을 보낼 수 있습니다.

```python
async def persist_policy(old_policy, new_policy, actions):
    """정책 변경을 파일로 저장하고 Slack에 알림"""
    # 변경 내역 저장
    registry.save()

    # Slack 알림
    changes = "\n".join(f"  - {a.action}: {a.description}" for a in actions)
    await send_slack_message(
        channel="#archon-evolution",
        text=f"정책이 업데이트되었습니다:\n{changes}",
    )

loop.on_policy_updated = persist_policy
```

### 9.5 진화 사이클 결과 모니터링

```python
# 최근 사이클 결과 확인
results = loop.get_recent_cycles(n=5)
for cycle in results:
    print(f"사이클 #{cycle.number} ({cycle.timestamp})")
    print(f"  평가 기간: 최근 {cycle.window_size}회 실행")
    print(f"  성공률: {cycle.success_rate:.1%}")
    print(f"  평균 지연: {cycle.avg_latency:.1f}s")
    print(f"  액션 수: {len(cycle.actions)}")
    for action in cycle.actions:
        print(f"    - {action.action}: {action.description}")
```

---

## 10. KubeRay 운영

KubeRay를 사용하면 Kubernetes 위에서 Ray 클러스터를 관리하고, 에이전트 워크로드를 분산 처리할 수 있습니다.

### 10.1 KubeRay 클러스터 배포

```bash
# 1. KubeRay operator 설치
helm repo add kuberay https://ray-project.github.io/kuberay-helm/
helm repo update
helm install kuberay-operator kuberay/kuberay-operator --namespace ray-system --create-namespace

# 2. RayCluster 배포
kubectl apply -f k8s/ray-cluster.yaml
```

```yaml
# k8s/ray-cluster.yaml
apiVersion: ray.io/v1
kind: RayCluster
metadata:
  name: archon-ray
  namespace: archon-system
spec:
  rayVersion: "2.9.0"
  headGroupSpec:
    rayStartParams:
      dashboard-host: "0.0.0.0"
    template:
      spec:
        containers:
          - name: ray-head
            image: your-registry/archon-ray:latest
            resources:
              limits:
                cpu: "4"
                memory: "8Gi"
              requests:
                cpu: "2"
                memory: "4Gi"
            ports:
              - containerPort: 6379    # Ray GCS
              - containerPort: 8265    # Dashboard
  workerGroupSpecs:
    - replicas: 2
      minReplicas: 1
      maxReplicas: 10
      groupName: default-worker
      rayStartParams: {}
      template:
        spec:
          containers:
            - name: ray-worker
              image: your-registry/archon-ray:latest
              resources:
                limits:
                  cpu: "4"
                  memory: "16Gi"
                requests:
                  cpu: "2"
                  memory: "8Gi"
```

### 10.2 워커 그룹 설정

여러 유형의 워커를 구성할 수 있습니다.

```yaml
workerGroupSpecs:
  # CPU 워커 (일반 에이전트용)
  - replicas: 2
    groupName: cpu-workers
    template:
      spec:
        containers:
          - name: ray-worker
            resources:
              limits:
                cpu: "4"
                memory: "16Gi"

  # GPU 워커 (vLLM 추론용)
  - replicas: 1
    groupName: gpu-workers
    template:
      spec:
        containers:
          - name: ray-worker
            resources:
              limits:
                cpu: "8"
                memory: "32Gi"
                nvidia.com/gpu: "2"
        nodeSelector:
          cloud.google.com/gke-accelerator: nvidia-tesla-a100
```

### 10.3 오토스케일링

```yaml
workerGroupSpecs:
  - replicas: 2
    minReplicas: 1       # 최소 워커 수
    maxReplicas: 10      # 최대 워커 수 (비용 제한)
    groupName: default-worker
    # KubeRay가 Ray 리소스 수요에 따라 자동으로 스케일링합니다
```

> **왜 오토스케일링이 필요한가요?** 업무 시간에는 태스크가 많고 야간에는 적습니다. 오토스케일링으로 필요할 때만 리소스를 확보하면 클라우드 비용을 크게 절감할 수 있습니다.

### 10.4 클러스터 모니터링

```bash
# Ray 클러스터 상태 확인
kubectl get raycluster -n archon-system

# Ray Dashboard 접근 (포트 포워딩)
kubectl port-forward svc/archon-ray-head-svc 8265:8265 -n archon-system
# 브라우저에서 http://localhost:8265 접속

# 워커 상태 확인
kubectl get pods -l ray.io/cluster=archon-ray -n archon-system

# 로그 확인
kubectl logs -l ray.io/node-type=head -n archon-system
```

### 10.5 트러블슈팅

```bash
# 워커가 시작되지 않을 때
kubectl describe pod <pod-name> -n archon-system
# Events 섹션에서 원인 확인 (이미지 pull 실패, 리소스 부족 등)

# Ray head에 연결되지 않을 때
kubectl exec -it <head-pod> -n archon-system -- ray status

# GPU 워커에서 CUDA 오류 발생 시
kubectl logs <gpu-worker-pod> -n archon-system | grep -i "cuda\|gpu\|error"
```

---

## 11. 하이브리드 클라우드 운영

하이브리드 클라우드 전략은 로컬 GPU와 클라우드 API를 조합하여 비용과 성능의 균형을 맞춥니다.

### 11.1 전략 선택

```python
from src.runtime.hybrid_cloud import HybridCloudStrategy

strategy = HybridCloudStrategy(
    # 우선순위: 로컬 → 클라우드
    prefer_local=True,

    # 로컬 GPU가 모두 사용 중일 때만 클라우드 사용
    cloud_fallback=True,

    # 비용 한도
    daily_cloud_budget_usd=50.0,
    monthly_cloud_budget_usd=1000.0,

    # 지연 한도 — 로컬이 이 시간을 초과하면 클라우드로 전환
    max_local_latency_seconds=30.0,
)
```

### 11.2 예산 관리

```python
# 현재 사용량 확인
usage = strategy.get_cloud_usage()
print(f"오늘: ${usage.daily_spent:.2f} / ${usage.daily_budget:.2f}")
print(f"이번 달: ${usage.monthly_spent:.2f} / ${usage.monthly_budget:.2f}")

# 예산 초과 시 자동으로 로컬로만 실행됩니다
# 긴급 시 예산 일시 상향
strategy.daily_cloud_budget_usd = 100.0
```

### 11.3 GPU 리소스 등록

```python
# 로컬 GPU 서버 등록
strategy.register_gpu_resource(
    name="office-gpu-01",
    gpu_type="RTX 4090",
    gpu_count=2,
    vram_gb=48,
    base_url="http://192.168.1.100:8000",
)

strategy.register_gpu_resource(
    name="office-gpu-02",
    gpu_type="A100",
    gpu_count=4,
    vram_gb=320,
    base_url="http://192.168.1.101:8000",
)

# 등록된 리소스 확인
for gpu in strategy.list_gpu_resources():
    print(f"  {gpu.name}: {gpu.gpu_type} x{gpu.gpu_count} ({gpu.status})")
```

### 11.4 클라우드 비용 모니터링

```python
# 비용 알림 콜백
strategy.on_budget_warning = lambda usage: send_slack_message(
    channel="#archon-cost",
    text=f"클라우드 예산 {usage.daily_percent:.0%} 소진 (${usage.daily_spent:.2f})",
)

# 비용 리포트 생성
report = strategy.generate_cost_report(period="monthly")
print(report.to_table())
```

### 11.5 스팟 인스턴스 고려 사항

클라우드 GPU를 사용할 때 스팟/프리엠티블 인스턴스를 활용하면 비용을 60-90% 절감할 수 있습니다.

```python
strategy.spot_instance_config = {
    "enabled": True,
    "max_interruption_rate": 0.1,    # 10% 이하 중단률만 허용
    "fallback_to_on_demand": True,   # 스팟 불가 시 온디맨드로 폴백
}
```

> **주의:** 스팟 인스턴스는 언제든 종료될 수 있습니다. 긴 작업(30분 이상)에는 온디맨드를 사용하고, 짧은 추론 작업에만 스팟을 활용하는 것을 권장합니다.

---

## 12. 트랜잭션 스냅샷

트랜잭션 스냅샷은 위험한 작업 전에 시스템 상태를 저장하고, 문제 발생 시 이전 상태로 롤백할 수 있게 합니다.

### 12.1 스냅샷 저장

```python
from src.transaction.snapshot import SnapshotManager

manager = SnapshotManager()

# 위험한 작업 전에 스냅샷 생성
snapshot_id = await manager.save_snapshot(
    label="before-migration",          # 사람이 읽을 수 있는 라벨
    include_registry=True,             # Registry 상태 포함
    include_scratchpad=True,           # Redis 스크래치패드 포함
    metadata={"task_id": "task-042"},  # 추가 메타데이터
)
print(f"스냅샷 저장됨: {snapshot_id}")
```

### 12.2 롤백

```python
# 문제 발생 시 롤백
try:
    await execute_risky_migration()
except Exception as e:
    print(f"오류 발생: {e}, 스냅샷으로 롤백합니다")
    await manager.rollback_to_snapshot(snapshot_id)
    print("롤백 완료")
```

### 12.3 스냅샷 관리

```python
# 스냅샷 목록 확인
snapshots = manager.list_snapshots()
for s in snapshots:
    print(f"  [{s.id}] {s.label} ({s.created_at}) — {s.size_bytes / 1024:.1f}KB")

# 특정 스냅샷 삭제
manager.delete_snapshot(snapshot_id)

# 오래된 스냅샷 일괄 삭제
manager.clear_snapshots(older_than_days=7)
```

### 12.4 MAX_SNAPSHOTS 제한

스냅샷은 최대 20개까지 보관됩니다. 초과하면 가장 오래된 스냅샷이 자동 삭제됩니다.

```python
# 최대 보관 수 조정 (기본: 20)
manager = SnapshotManager(max_snapshots=20)
```

> **왜 20개로 제한하나요?** 스냅샷에는 Registry와 스크래치패드 데이터가 포함되어 디스크 공간을 차지합니다. 무제한 보관은 스토리지 문제를 일으킬 수 있으므로 적절한 한도를 유지합니다.

---

## 13. 백업 및 복구

### 13.1 백업 대상

| 데이터 | 위치 | 백업 방법 |
|---|---|---|
| 프로젝트 Registry | `.harness/registry/*.json` | 파일 복사 / git |
| SOP 문서 | `.harness/sop/` | 파일 복사 / git |
| Redis 스크래치패드 | Redis DB | `redis-cli SAVE` |
| ChromaDB 벡터 데이터 | `chroma_data/` | 디렉토리 복사 |
| Mem0 장기 메모리 | Mem0 클라우드 | Mem0 대시보드 |
| 벤치마크 결과 | `benchmarks/results/` | 파일 복사 / git |
| 트랜잭션 스냅샷 | `.harness/snapshots/` | 파일 복사 |
| 대시보드 데이터 | 대시보드 DB | API 내보내기 |

### 13.2 Registry 백업

`.harness/registry/` 디렉토리를 git으로 관리하는 것이 권장됩니다.

```bash
git add .harness/registry/
git commit -m "chore: registry snapshot $(date +%Y-%m-%d)"
git push origin main
```

### 13.3 Redis 백업

```bash
# 스냅샷 생성 (프로덕션에서는 BGSAVE 권장)
redis-cli BGSAVE

# 백업 파일 복사
cp /var/lib/redis/dump.rdb /backup/redis-$(date +%Y%m%d).rdb
```

#### 복구

```bash
sudo systemctl stop redis
cp /backup/redis-20260424.rdb /var/lib/redis/dump.rdb
sudo systemctl start redis
```

### 13.4 ChromaDB 백업

```bash
tar -czf chroma-backup-$(date +%Y%m%d).tar.gz ./chroma_data/
```

#### 복구

```bash
tar -xzf chroma-backup-20260424.tar.gz
```

### 13.5 스냅샷 기반 복구

트랜잭션 스냅샷을 사용하면 특정 시점의 시스템 상태로 복원할 수 있습니다.

```python
# 사용 가능한 스냅샷 확인
snapshots = manager.list_snapshots()
for s in snapshots:
    print(f"  [{s.id}] {s.label} ({s.created_at})")

# 원하는 시점으로 롤백
await manager.rollback_to_snapshot("snapshot-id-here")
```

### 13.6 대시보드 데이터 내보내기

```bash
# 메트릭 데이터 내보내기
curl http://localhost:8000/api/metrics/export?format=csv > metrics-$(date +%Y%m%d).csv

# JSON 형식으로 내보내기
curl http://localhost:8000/api/metrics/export?format=json > metrics-$(date +%Y%m%d).json
```

### 13.7 전체 복구 절차

1. `.env` 환경 변수 복원
2. Redis 백업 복원 및 재시작
3. ChromaDB 백업 복원 및 재시작
4. `.harness/registry/*.json` git에서 체크아웃
5. 필요 시 스냅샷 기반 롤백 수행
6. `python -m src.demo.pipeline`으로 동작 확인

---

## 14. 트러블슈팅 FAQ

### Q1. `ModuleNotFoundError: No module named 'src'`

프로젝트 루트 디렉토리에서 `-m` 플래그로 실행해야 합니다.

```bash
cd /path/to/archon-framework
python -m src   # python src/main.py 가 아닌 -m 플래그 사용
```

### Q2. `ANTHROPIC_API_KEY` 오류

```bash
# .env 파일이 로드되는지 확인합니다
cat .env | grep ANTHROPIC
# 또는 export로 직접 설정합니다
export ANTHROPIC_API_KEY=sk-ant-...
```

### Q3. Redis 연결 실패

```
ConnectionRefusedError: [Errno 61] Connection refused
```

Redis가 실행 중이지 않거나 포트가 다를 때 발생합니다. 인메모리 폴백이 자동 활성화되지만, 재시작 시 데이터가 초기화되므로 프로덕션에서는 Redis를 반드시 연결하세요.

```bash
redis-cli ping   # PONG이면 정상
brew services start redis     # macOS
sudo systemctl start redis    # Linux
```

### Q4. ChromaDB `Collection not found`

프로젝트를 처음 실행하면 컬렉션이 자동 생성됩니다. 오류가 지속되면 ChromaDB 버전을 확인합니다.

```bash
pip show chromadb   # 0.4.x 권장
```

### Q5. Gate가 항상 L2_HUMAN으로 판정됨

`high_risk_paths`/`high_risk_keywords`에 매칭되는 파일이 있으면 자동으로 L2로 에스컬레이션됩니다.

```python
print(registry.quality_policy.high_risk_paths)
print(registry.quality_policy.high_risk_keywords)
```

변경 파일 경로가 위험 패턴에 매칭되는지 확인하고, 필요하면 정책을 조정합니다.

### Q6. `ProtectedPathError` 발생

```
ProtectedPathError: Attempt to modify protected path: .harness/sop/production/
```

`protected_paths`에 등록된 경로를 에이전트가 수정하려 할 때 발생합니다. 해당 파일을 의도적으로 수정해야 한다면 `protected_paths`에서 제거하거나 수동으로 커밋합니다.

### Q7. vLLM 헬스체크 타임아웃

```
VLLMBridge: health check timeout for vllm/backend-llm
```

```python
# timeout 값을 늘려서 재시도합니다
bridge = VLLMBridge(timeout=30.0)
await bridge.health_check_all()
```

GPU 워커 로그를 확인하고 모델 로딩이 완료되었는지 확인합니다.

### Q8. 대시보드가 시작되지 않을 때

```
ModuleNotFoundError: No module named 'fastapi'
```

FastAPI와 uvicorn이 설치되어 있는지 확인합니다.

```bash
pip install fastapi uvicorn websockets
python -m src.dashboard.server --host 0.0.0.0 --port 8000
```

CORS 오류가 발생하면 `ARCHON_CORS_ORIGINS`에 대시보드 URL이 포함되어 있는지 확인합니다.

### Q9. Ollama 모델을 찾을 수 없을 때

```
Error: model 'llama3.3:70b' not found
```

```bash
# 1. 모델이 다운로드되었는지 확인합니다
ollama list

# 2. 모델이 없으면 다운로드합니다
ollama pull llama3.3:70b

# 3. Ollama 서버가 실행 중인지 확인합니다
curl http://localhost:11434/api/tags

# 4. OLLAMA_BASE_URL 환경 변수가 정확한지 확인합니다
echo $OLLAMA_BASE_URL   # http://localhost:11434
```

### Q10. AITOP 트레이스가 표시되지 않을 때

```bash
# 1. AITOP 서버가 실행 중인지 확인합니다
curl http://localhost:8080/health

# 2. 환경 변수를 확인합니다
echo $AITOP_SERVER_URL       # http://localhost:8080
echo $AITOP_PROJECT_TOKEN    # 비어 있으면 안 됩니다

# 3. TracingConfig에서 enabled=True인지 확인합니다
# 4. 네트워크 방화벽이 포트를 차단하고 있지 않은지 확인합니다
```

### Q11. 토큰 예산 초과

```
TokenBudgetExceeded: Daily token limit reached (1,000,000 / 1,000,000)
```

```python
# 현재 사용량 확인
usage = policy.get_daily_usage()
print(f"사용량: {usage.tokens_used:,} / {usage.daily_limit:,}")

# 긴급 시 일일 예산 리셋
policy.reset_daily()

# 또는 한도를 상향 조정합니다
policy.daily_token_limit = 2_000_000
```

### Q12. 에이전트가 DEAD 상태에 갇힘

```
Agent 'backend_agent' is in DEAD state
```

```python
# 1. SelfHealer 설정 확인
print(watchdog.config)

# 2. auto_heal이 활성화되어 있는지 확인합니다
watchdog.config.auto_heal = True

# 3. 수동으로 복구를 시도합니다
await watchdog.heal_agent("backend_agent")

# 4. 진단 리포트를 확인합니다
report = await watchdog.generate_diagnostic_report()
print(report.agents["backend_agent"].recommendations)
```

### Q13. 진화 루프가 실행되지 않을 때

```python
# 1. enabled=True인지 확인합니다
print(loop.config.enabled)   # True여야 합니다

# 2. min_executions 이상 실행되었는지 확인합니다
print(f"현재 실행 횟수: {loop.execution_count}")
print(f"최소 요구: {loop.config.min_executions}")

# 3. 수동으로 사이클 실행
await loop.run_cycle()
```

### Q14. 태스크 순환 의존성 오류

```
CyclicDependencyError: Cycle detected in task dependencies
```

`TaskScheduler`는 Kahn의 위상 정렬을 사용합니다. 태스크 `depends_on` 설정에서 순환 참조를 제거합니다.

```python
scheduler = TaskScheduler(tasks)
order = scheduler.topological_sort()  # 오류 없으면 정렬 순서 반환
```

### Q15. pytest 실패로 QA 파이프라인 블로킹

```python
# 개발 중 임시로 테스트 요건 해제
from src.registry.models import QualityPolicy
policy = QualityPolicy(min_test_coverage=0)
```

---

## 관련 문서

- [빠른 시작](quickstart.md)
- [아키텍처](architecture.md)
- [Registry 스키마](registry-schema.md)
- [Plugin 개발 가이드](plugin-guide.md)
- [API Reference](api-reference.md)
