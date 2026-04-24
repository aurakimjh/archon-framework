# 운영 가이드

🇺🇸 [English](../en/operations-guide.md)

> 버전: 1.1.0 | 최종 수정: 2026-04-24

## 목차

1. [배포 방법](#1-배포-방법)
2. [환경 변수 설정](#2-환경-변수-설정)
3. [LLM 모델 설정](#3-llm-모델-설정)
4. [Redis / ChromaDB 연결](#4-redis--chromadb-연결)
5. [모니터링](#5-모니터링)
6. [트러블슈팅 FAQ](#6-트러블슈팅-faq)
7. [백업 및 복구](#7-백업-및-복구)

---

## 1. 배포 방법

### 로컬 실행

#### 사전 요구 사항

| 항목 | 버전 |
|---|---|
| Python | 3.11 이상 |
| pip / uv | 최신 |
| Redis | 7.x (옵션, 없으면 인메모리 폴백) |
| ChromaDB | 0.4.x (옵션) |

```bash
# 1. 레포 클론
git clone https://github.com/your-org/archon-framework.git
cd archon-framework

# 2. 의존성 설치
pip install -r requirements.txt

# 3. 환경 변수 설정
cp .env.example .env
# .env 편집 후 API 키 입력

# 4. 데모 실행 (mock — LLM 연결 불필요)
python -m src.demo.pipeline

# 5. 실제 파이프라인 실행
python -m src --project-id my-project --task-id task-001
```

### Docker

```dockerfile
# Dockerfile (예시)
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

#### Docker Compose (Redis + ChromaDB 포함)

```yaml
# docker-compose.yml
version: "3.9"

services:
  archon:
    build: .
    env_file: .env
    volumes:
      - ./.harness:/app/.harness
    depends_on:
      - redis
      - chroma

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data

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
docker-compose up -d
```

### Kubernetes

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
  --from-literal=REDIS_URL=redis://redis-service:6379 \
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
  ARCHON_MAX_CONCURRENT_TASKS: "4"
  CHROMA_HOST: "chroma-service"
  CHROMA_PORT: "8000"
```

---

## 2. 환경 변수 설정

`.env.example`을 복사해 `.env`를 만들고 아래 변수를 채운다.

### LLM API 키

```dotenv
# Anthropic (오케스트레이터용)
ANTHROPIC_API_KEY=sk-ant-...

# OpenAI (선택)
OPENAI_API_KEY=sk-...

# Groq (선택)
GROQ_API_KEY=gsk_...
```

### 메모리 백엔드

```dotenv
# Redis (L1 스크래치패드)
REDIS_URL=redis://localhost:6379
REDIS_TTL=86400          # 초 단위, 기본 86400 (24시간)

# ChromaDB (L2 벡터 스토어)
CHROMA_HOST=localhost
CHROMA_PORT=8001
CHROMA_COLLECTION_PREFIX=archon

# Mem0 (L3 장기 메모리, 선택)
MEM0_API_KEY=m0-...
MEM0_USER_ID=archon-prod
```

### 알림

```dotenv
# Slack
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...

# PagerDuty (선택)
PAGERDUTY_INTEGRATION_KEY=...
```

### 런타임

```dotenv
ARCHON_LOG_LEVEL=INFO          # DEBUG / INFO / WARNING / ERROR
ARCHON_MAX_CONCURRENT_TASKS=4  # TaskScheduler 동시 실행 수
ARCHON_DEFAULT_TIMEOUT=120     # 에이전트 기본 타임아웃 (초)
```

### LiteLLM 프록시 (선택)

```dotenv
LITELLM_PROXY_URL=http://localhost:4000
LITELLM_PROXY_KEY=sk-litellm-...
```

---

## 3. LLM 모델 설정

### 기본 모델 (Anthropic)

Registry JSON의 `agent_config`에서 역할별 모델을 지정한다.

```json
{
  "agent_config": {
    "backend": {
      "model": "claude-sonnet-4-6",
      "max_tokens": 8192,
      "temperature": 0.2,
      "streaming": true,
      "timeout_seconds": 120
    },
    "tester": {
      "model": "claude-haiku-4-5-20251001",
      "max_tokens": 4096,
      "temperature": 0.1
    }
  }
}
```

### Ollama (로컬 오픈소스 모델)

```bash
# Ollama 설치 및 모델 다운로드
ollama pull llama3.3:70b
ollama pull deepseek-v3.2:70b
```

```yaml
# config/litellm_config.yaml
model_list:
  - model_name: backend-agent
    litellm_params:
      model: ollama/llama3.3:70b
      api_base: http://localhost:11434
      stream: true

  - model_name: tester-agent
    litellm_params:
      model: ollama/deepseek-v3.2:7b
      api_base: http://localhost:11434
```

### LiteLLM 프록시 서버

여러 모델을 단일 엔드포인트로 라우팅할 때 사용한다.

```bash
# LiteLLM 설치
pip install litellm[proxy]

# 프록시 서버 시작
litellm --config config/litellm_config.yaml --port 4000
```

### vLLM GPU 워커

고성능 GPU 추론이 필요한 경우 vLLM 서버를 별도 노드에 실행한다.

```bash
# vLLM 서버 실행 (GPU 노드)
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

### 복잡도 기반 모델 분기

작업 복잡도에 따라 자동으로 모델을 선택하려면 `high_complexity_model`을 설정한다.

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

Complexity Router가 8개 기준(파일 수, diff 라인, 의존성 등)을 스코어링해 HIGH로 판정되면 자동으로 `high_complexity_model`을 선택한다.

---

## 4. Redis / ChromaDB 연결

### Redis (L1 스크래치패드)

```bash
# Redis 설치 (macOS)
brew install redis
brew services start redis

# Redis 설치 (Ubuntu)
sudo apt install redis-server
sudo systemctl start redis
```

```python
# 연결 확인
import redis
r = redis.from_url("redis://localhost:6379")
r.ping()  # True
```

Redis가 없으면 `RedisScratchpad`는 자동으로 인메모리 딕셔너리 폴백을 사용한다. 재시작 시 데이터가 초기화되므로 프로덕션에서는 Redis를 반드시 연결할 것.

#### Redis 키 구조

```
archon:scratch:{project_id}:{task_id}:{key}
```

- TTL: 기본 86400초 (24시간)
- `REDIS_TTL` 환경 변수로 조정 가능

### ChromaDB (L2 벡터 스토어)

```bash
# ChromaDB 설치
pip install chromadb

# 로컬 서버 실행 (옵션)
chroma run --host 0.0.0.0 --port 8001 --path ./chroma_data
```

```python
# 연결 확인
import chromadb
client = chromadb.HttpClient(host="localhost", port=8001)
client.heartbeat()  # {"nanosecond heartbeat": ...}
```

ChromaDB가 없으면 `VectorStore`는 자동으로 인메모리 폴백을 사용한다.

#### 컬렉션 명명 규칙

```
{CHROMA_COLLECTION_PREFIX}_{project_id}
# 예: archon_proj-ecomm
```

### Mem0 (L3 장기 메모리, 선택)

[Mem0](https://mem0.ai) 계정을 생성하고 API 키를 발급받는다.

```dotenv
MEM0_API_KEY=m0-...
MEM0_USER_ID=archon-prod   # 사용자/팀 식별자
```

Mem0가 없으면 `Mem0Store`는 인메모리 딕셔너리 폴백을 사용한다.

---

## 5. 모니터링

### 로그

Archon은 Python 표준 `logging` 모듈을 사용한다.

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

### 주요 메트릭

`ProjectRegistry.metrics`에 태스크 완료 시마다 기록된다.

```python
registry.update_metrics(
    task_id="task-001",
    success=True,
    latency_seconds=4.2,
    gate_decision="AUTO_PASS",
)
```

`RegistryStore`가 `.harness/registry/{project_id}.json`에 자동 저장한다.

### Human Gate 알림

Gate 판정 시 `CompositeNotifier`가 각 채널로 이벤트를 전송한다.

| Gate | TerminalNotifier | SlackNotifier | PagerDuty |
|---|---|---|---|
| AUTO_PASS | ✅ 초록 배너 | - | - |
| L1_REWORK | 🟡 노란 배너 | ✅ | - |
| L2_HUMAN | 🔴 빨간 배너 | ✅ | - |
| L3_HALT | 🚨 빨간 배너 | ✅ | ✅ |
| L4_DEPLOY | 🔵 파란 배너 | ✅ | ✅ |

### macOS 네이티브 알림

`TerminalNotifier`는 `osascript`를 통해 macOS 알림 센터에 팝업을 표시한다. 별도 설정 없이 동작한다.

---

## 6. 트러블슈팅 FAQ

### Q1. `ModuleNotFoundError: No module named 'src'`

```bash
# 프로젝트 루트에서 실행 중인지 확인
cd /path/to/archon-framework
python -m src  # python src/main.py 가 아닌 -m 플래그 사용
```

### Q2. `ANTHROPIC_API_KEY` 오류

```bash
# .env 파일이 로드되는지 확인
cat .env | grep ANTHROPIC
# 또는 export로 직접 설정
export ANTHROPIC_API_KEY=sk-ant-...
```

### Q3. Redis 연결 실패

```
ConnectionRefusedError: [Errno 61] Connection refused
```

Redis가 실행 중이지 않거나 포트가 다를 때 발생한다. 인메모리 폴백이 자동 활성화되므로 데이터 손실에 주의.

```bash
# Redis 상태 확인
redis-cli ping   # PONG 이면 정상

# 서비스 시작
brew services start redis     # macOS
sudo systemctl start redis    # Linux
```

### Q4. ChromaDB `Collection not found`

프로젝트를 처음 실행하면 컬렉션이 자동 생성된다. 오류가 지속되면 ChromaDB 버전을 확인한다.

```bash
pip show chromadb   # 0.4.x 권장
```

### Q5. Gate가 항상 L2_HUMAN으로 판정됨

Dynamic Guardrails 때문일 수 있다. `high_risk_paths`/`high_risk_keywords`에 매칭되는 파일이 있으면 자동으로 L2로 에스컬레이션된다.

```python
# QualityPolicy 확인
print(registry.quality_policy.high_risk_paths)
print(registry.quality_policy.high_risk_keywords)
```

변경 파일 경로가 위험 패턴에 매칭되는지 확인하고, 필요하면 정책을 조정한다.

### Q6. `ProtectedPathError` 발생

```
ProtectedPathError: Attempt to modify protected path: .harness/sop/production/
```

`GitExecutor.auto_commit()` 호출 시 `protected_paths`에 등록된 경로를 수정하려 할 때 발생한다.

```python
# protected_paths 확인
executor = GitExecutor(repo_path=".", protected_paths=registry.protected_paths)
```

해당 파일을 의도적으로 수정해야 한다면 `protected_paths`에서 제거하거나 수동으로 커밋한다.

### Q7. vLLM 헬스체크 타임아웃

```
VLLMBridge: health check timeout for vllm/backend-llm
```

```python
# timeout 값을 늘려서 재시도
bridge = VLLMBridge(timeout=30.0)
await bridge.health_check_all()
```

GPU 워커 로그를 확인하고 모델 로딩이 완료됐는지 확인한다.

### Q8. pytest 실패로 QA 파이프라인 블로킹

```python
# 임시로 테스트 스킵 (개발 중)
from src.registry.models import QualityPolicy
policy = QualityPolicy(
    min_test_coverage=0,   # 커버리지 요건 해제
)
```

또는 `run_qa_pipeline()`에서 반환된 `QualityGates.test_results.passed`가 0이더라도 `gate_evaluator`의 정책 임계값을 조정해 통과시킬 수 있다.

### Q9. 태스크 순환 의존성 오류

```
CyclicDependencyError: Cycle detected in task dependencies
```

`TaskScheduler`는 Kahn의 위상 정렬을 사용한다. 태스크 `depends_on` 설정에서 순환 참조를 제거한다.

```python
# 의존성 그래프 확인
scheduler = TaskScheduler(tasks)
order = scheduler.topological_sort()  # 오류 없으면 정렬 순서 반환
```

---

## 7. 백업 및 복구

### 백업 대상

| 데이터 | 위치 | 백업 방법 |
|---|---|---|
| 프로젝트 Registry | `.harness/registry/*.json` | 파일 복사 / git |
| SOP 문서 | `.harness/sop/` | 파일 복사 / git |
| Redis 스크래치패드 | Redis DB | `redis-cli SAVE` |
| ChromaDB 벡터 데이터 | `chroma_data/` | 디렉토리 복사 |
| Mem0 장기 메모리 | Mem0 클라우드 | Mem0 대시보드 |
| 벤치마크 결과 | `benchmarks/results/` | 파일 복사 / git |

### Registry 백업

`.harness/registry/` 디렉토리를 git으로 관리하는 것이 권장된다.

```bash
# 변경 시 커밋
git add .harness/registry/
git commit -m "chore: registry snapshot $(date +%Y-%m-%d)"
git push origin main
```

### Redis 백업

```bash
# 스냅샷 생성
redis-cli SAVE   # 동기식 (프로덕션에서는 BGSAVE 권장)
redis-cli BGSAVE

# 백업 파일 복사 (기본 경로)
cp /var/lib/redis/dump.rdb /backup/redis-$(date +%Y%m%d).rdb
```

#### 복구

```bash
# Redis 서비스 정지
sudo systemctl stop redis

# 백업 복원
cp /backup/redis-20260424.rdb /var/lib/redis/dump.rdb

# Redis 재시작
sudo systemctl start redis
```

### ChromaDB 백업

```bash
# ChromaDB 데이터 디렉토리 복사
tar -czf chroma-backup-$(date +%Y%m%d).tar.gz ./chroma_data/
```

#### 복구

```bash
# ChromaDB 서비스 정지 후 복원
tar -xzf chroma-backup-20260424.tar.gz
```

### 전체 복구 절차

1. `.env` 환경 변수 복원
2. Redis 백업 복원 + 재시작
3. ChromaDB 백업 복원 + 재시작
4. `.harness/registry/*.json` git에서 체크아웃
5. `python -m src.demo.pipeline`으로 동작 확인

---

## 관련 문서

- [빠른 시작](quickstart.md)
- [아키텍처](architecture.md)
- [Registry 스키마](registry-schema.md)
- [Plugin 개발 가이드](plugin-guide.md)
- [API Reference](api-reference.md)
