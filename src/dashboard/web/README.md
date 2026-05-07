# Archon Dashboard (web)

React 18 + Vite + TypeScript + Tailwind 기반 단일 페이지 앱. FastAPI 백엔드(`src/dashboard/app.py`)가 빌드 산출물(`web/dist/`)을 그대로 서빙합니다.

## 첫 빌드

```bash
cd src/dashboard/web
npm install
npm run build
```

빌드 산출물은 `web/dist/`에 생성되며 FastAPI가 자동으로 마운트합니다.

## 개발 서버

백엔드와 프론트를 분리해서 띄우면 핫리로드가 빠릅니다.

```bash
# 터미널 1 — FastAPI (포트 8000)
ARCHON_ENV=dev .venv/bin/uvicorn src.dashboard.app:DashboardApp \
  --factory src.dashboard.app:DashboardApp.create_app --reload

# 터미널 2 — Vite (포트 5173, /api와 /ws를 8000으로 프록시)
cd src/dashboard/web
npm run dev
```

브라우저는 `http://localhost:5173` 으로 접속.

## 환경 변수 (백엔드에서 인식)

| 변수 | 기본값 | 설명 |
|---|---|---|
| `ARCHON_DASHBOARD_TOKEN` | (미설정) | Bearer 토큰. 미설정이면 인증 비활성. |
| `ARCHON_CORS_ORIGINS` | (빈 목록) | 콤마 분리 origin 목록. 동일 출처 운영이면 비워둘 것. |
| `ARCHON_CSP` | strict default | Content-Security-Policy 오버라이드. |
| `ARCHON_ENV` | `production` | `dev`/`development`/`local` 이면 mock·시나리오 허용. |
| `ARCHON_AGENT_CONFIG_PATH` | `config/agent_config.yaml` | 역할별 에이전트 설정 YAML 경로. |
| `ARCHON_LITELLM_CONFIG_PATH` | `config/litellm_config.yaml` | 모델 레지스트리 YAML 경로. |
| `ARCHON_DASHBOARD_DB_PATH` | `.harness/dashboard.db` | Task/Gate/Usage/Audit 영속화 SQLite 경로. `:memory:` 가능. |
| `ARCHON_PRICING_PATH` | `config/model_pricing.json` | 모델별 단가(USD/1K tokens) 경로. |
| `ARCHON_USERS_PATH` | `config/users.yaml` | 사용자/역할/토큰 디렉토리. 파일이 있으면 multi-user RBAC 모드로 동작. |

## 디렉토리

```
web/
├── public/             # 정적 자원(파비콘 등)
├── src/
│   ├── components/     # UI 컴포넌트(Layout, Sidebar, Card 등)
│   │   └── ui/         # shadcn 스타일 프리미티브(Button, Card, Table, …)
│   ├── lib/            # api, ws, auth, hooks, queryClient, cn
│   ├── pages/          # 라우트 페이지
│   ├── App.tsx
│   ├── main.tsx
│   ├── router.tsx
│   ├── types.ts        # 백엔드 모델 미러링
│   └── index.css       # Tailwind base + design tokens
├── index.html
├── package.json
├── tsconfig*.json
├── tailwind.config.ts
└── vite.config.ts
```

## 라우트

| 경로 | 페이지 | 슬라이스 |
|---|---|---|
| `/login` | 토큰 로그인 | Slice 1 ✅ |
| `/overview` | 카드 + 테이블 + 라이브 이벤트 | Slice 1 ✅ |
| `/agents` | 역할별 에이전트·모델 설정 | Slice 2 ✅ |
| `/instructions` | 작업지시서 등록·실행·취소 | Slice 3 ✅ |
| `/gates` | Human Gate 상세·코멘트 결정 | Slice 3 ✅ |
| `/cost` | 시계열 비용·토큰·예산 임계치 | Slice 4 ✅ |
| `/projects` | 프로젝트 목록 | Slice 6 ✅ |
| `/projects/:id` | 프로젝트 타임라인 + 메모리 검색 | Slice 6 ✅ |
| `/settings` | 사용자/토큰·감사 로그·알림 규칙 | Slice 5+7 ✅ |

## RBAC 운영 가이드

`config/users.yaml`이 존재하면 **multi-user RBAC 모드**가 자동 활성화됩니다.

- **admin** : 사용자 관리, 토큰 발급/취소, 예산·에이전트 설정·알림 규칙 변경, 감사 로그 열람
- **operator** : 작업 등록·취소, Human Gate 결정
- **viewer** : 읽기 전용

토큰은 `/settings` → "Issue token"으로 발급하며 평문은 1회만 노출됩니다(이후 해시만 저장).

`users.yaml`이 없으면 `ARCHON_DASHBOARD_TOKEN` 단일 토큰 모드(=admin), 그것도 없으면 인증 비활성(개발/내부망).
