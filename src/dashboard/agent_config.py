"""역할별 에이전트 글로벌 설정 — Pydantic 스키마 + YAML 파일 백드 스토어.

ProjectRegistry의 `AgentModelConfig`는 프로젝트 단위 오버라이드 용도이고,
이 모듈은 모든 프로젝트의 기본값으로 작동하는 **글로벌** 설정을 다룬다.

경로: 환경변수 `ARCHON_AGENT_CONFIG_PATH` (기본 `config/agent_config.yaml`).
파일이 없으면 빌드된 기본값을 즉시 반환하고, save() 호출 시 atomic write로 기록한다.
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, ValidationError

from src.registry.models import AgentRole, MultiProviderMode

logger = logging.getLogger(__name__)


_DEFAULT_PATH = "config/agent_config.yaml"
SCHEMA_VERSION = "1.0.0"


# 각 역할의 권장 기본 모델 (litellm config의 model_name과 일치).
_DEFAULT_MODEL: dict[AgentRole, str] = {
    AgentRole.ORCHESTRATOR: "orchestrator",
    AgentRole.REVIEWER: "reviewer",
    AgentRole.BACKEND: "backend-agent",
    AgentRole.FRONTEND: "frontend-agent",
    AgentRole.TESTER: "tester-agent",
    AgentRole.DEVOPS: "devops-agent",
    AgentRole.DOCS: "docs-agent",
}


class AgentRoleConfig(BaseModel):
    """단일 역할 설정."""

    role: AgentRole
    enabled: bool = True
    model: str
    fallback_models: list[str] = Field(default_factory=list)
    multi_provider_mode: MultiProviderMode = MultiProviderMode.SINGLE
    system_prompt_override: str | None = None
    max_tokens: int = Field(default=4096, ge=128, le=200_000)
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)


class AgentRoleConfigSet(BaseModel):
    """전체 역할 설정 묶음."""

    schema_version: str = SCHEMA_VERSION
    configs: dict[AgentRole, AgentRoleConfig] = Field(default_factory=dict)

    def get(self, role: AgentRole) -> AgentRoleConfig:
        """해당 역할의 설정을 반환. 없으면 기본 설정을 만들어 반환한다."""
        if role in self.configs:
            return self.configs[role]
        return AgentRoleConfig(role=role, model=_DEFAULT_MODEL.get(role, ""))

    def upsert(self, cfg: AgentRoleConfig) -> None:
        self.configs[cfg.role] = cfg

    @classmethod
    def with_defaults(cls) -> "AgentRoleConfigSet":
        """모든 역할에 대해 권장 기본값으로 초기화된 설정 묶음."""
        return cls(
            configs={
                role: AgentRoleConfig(role=role, model=model)
                for role, model in _DEFAULT_MODEL.items()
            }
        )


def get_config_path() -> Path:
    """환경변수 우선, 기본 경로 폴백."""
    return Path(os.environ.get("ARCHON_AGENT_CONFIG_PATH", _DEFAULT_PATH))


class AgentConfigStore:
    """YAML 파일 기반 역할 설정 스토어.

    - load(): 파일이 없거나 깨졌으면 기본값 반환 (예외 throw 안 함).
    - save(): 임시파일 → fsync → rename으로 atomic write.
    - 파일 부분 업데이트는 호출자가 load → mutate → save 순으로 한다.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        self._path = Path(path) if path else get_config_path()

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> AgentRoleConfigSet:
        if not self._path.exists():
            return AgentRoleConfigSet.with_defaults()
        try:
            data = yaml.safe_load(self._path.read_text(encoding="utf-8")) or {}
            cfg = AgentRoleConfigSet.model_validate(data)
        except (yaml.YAMLError, ValidationError) as e:
            logger.warning(
                "agent_config invalid (%s): falling back to defaults", e
            )
            return AgentRoleConfigSet.with_defaults()

        # 누락된 역할은 기본값으로 채워 UI가 항상 7개 카드를 그릴 수 있게 한다.
        for role, model in _DEFAULT_MODEL.items():
            if role not in cfg.configs:
                cfg.configs[role] = AgentRoleConfig(role=role, model=model)
        return cfg

    def save(self, cfg: AgentRoleConfigSet) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # Pydantic enum dump → 문자열 키, YAML-friendly.
        payload = cfg.model_dump(mode="json")
        self._atomic_write(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True))

    def update_role(self, role: AgentRole, cfg: AgentRoleConfig) -> AgentRoleConfigSet:
        """단일 역할만 갱신하고 전체 묶음을 반환한다."""
        if cfg.role != role:
            raise ValueError(
                f"role mismatch: path={role} body.role={cfg.role}"
            )
        all_cfg = self.load()
        all_cfg.upsert(cfg)
        self.save(all_cfg)
        return all_cfg

    def _atomic_write(self, content: str) -> None:
        directory = self._path.parent
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=directory,
            prefix=f".{self._path.name}.",
            suffix=".tmp",
            delete=False,
        ) as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
            tmp_path = Path(f.name)
        os.replace(tmp_path, self._path)
