"""GuardrailPolicy — 프로젝트별 가드레일 정책 모델."""

from __future__ import annotations

from pydantic import BaseModel, Field


class GuardrailPolicy(BaseModel):
    """가드레일 전체 정책. ProjectRegistry에 선택적으로 추가할 수 있다."""

    # --- 입력 검증 ---
    max_input_tokens: int = 32_000
    forbidden_keywords: list[str] = Field(
        default_factory=lambda: [
            "ignore previous instructions",
            "ignore all instructions",
            "disregard system",
        ]
    )
    # 민감 정보 탐지 활성화 여부
    detect_sensitive_data: bool = True
    # 프롬프트 인젝션 탐지 활성화 여부
    detect_prompt_injection: bool = True
    # 입력 검증 실패 시 동작: "block" | "warn"
    input_violation_action: str = "block"

    # --- 출력 검증 ---
    detect_dangerous_code: bool = True
    detect_security_patterns: bool = True
    # 출력 검증 실패 시 동작: "block" | "warn"
    output_violation_action: str = "warn"

    # --- 토큰 예산 ---
    # 프로젝트 전체 일일 토큰 한도 (0 = 무제한)
    daily_token_limit: int = 0
    # 에이전트별 태스크 토큰 한도 (0 = 무제한)
    per_task_token_limit: int = 0
    # 예산 경고 임계값 (0.0~1.0, 예: 0.8 = 80% 소진 시 경고)
    budget_warn_threshold: float = 0.8
    # 예산 초과 시 동작: "block" | "warn"
    budget_exceeded_action: str = "warn"
    # 비용 환산용 모델 단가 (USD per 1K tokens input/output)
    model_pricing: dict[str, dict[str, float]] = Field(
        default_factory=lambda: {
            "claude-sonnet-4-6": {"input": 0.003, "output": 0.015},
            "claude-haiku-4-5-20251001": {"input": 0.00025, "output": 0.00125},
            "claude-opus-4-7": {"input": 0.015, "output": 0.075},
        }
    )

    # --- 경로 보호 ---
    # GitConfig.protected_paths를 override하거나 추가 경로 지정
    extra_protected_paths: list[str] = Field(
        default_factory=lambda: [
            ".env", ".env.local", ".env.production",
            "credentials/", "secrets/", "certs/",
            "*.pem", "*.key", "*.p12",
        ]
    )
    # 설정 파일 변경 시 Human Gate 강제 여부
    force_human_gate_on_config_change: bool = True
    config_file_patterns: list[str] = Field(
        default_factory=lambda: [
            "*.yaml", "*.yml", "*.toml", "*.ini",
            "docker-compose*", "Dockerfile*",
            "k8s/", "infrastructure/",
        ]
    )
