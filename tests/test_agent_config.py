"""AgentConfigStore + model_registry 단위 테스트."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from src.dashboard.agent_config import (
    AgentConfigStore,
    AgentRoleConfig,
    AgentRoleConfigSet,
)
from src.dashboard.model_registry import (
    ModelEntry,
    is_known_model,
    load_models,
    sanitize_dict,
)
from src.registry.models import AgentRole, MultiProviderMode


# ---------------------------------------------------------------------------
# AgentConfigStore
# ---------------------------------------------------------------------------


class TestAgentConfigStore:
    def test_load_returns_defaults_when_missing(self, tmp_path):
        store = AgentConfigStore(tmp_path / "agent_config.yaml")
        cfg = store.load()
        # 7개 역할 모두 기본값으로 채워져야 한다.
        for role in AgentRole:
            assert role in cfg.configs
            entry = cfg.configs[role]
            assert entry.role == role
            assert entry.model  # 비어있지 않은 기본 모델

    def test_save_and_load_roundtrip(self, tmp_path):
        path = tmp_path / "agent_config.yaml"
        store = AgentConfigStore(path)
        cfg = AgentRoleConfigSet.with_defaults()
        cfg.configs[AgentRole.BACKEND].model = "backend-agent-ollama"
        cfg.configs[AgentRole.BACKEND].temperature = 0.4
        store.save(cfg)

        assert path.exists()
        reloaded = store.load()
        assert reloaded.configs[AgentRole.BACKEND].model == "backend-agent-ollama"
        assert reloaded.configs[AgentRole.BACKEND].temperature == 0.4

    def test_atomic_write_no_temp_left_behind(self, tmp_path):
        store = AgentConfigStore(tmp_path / "agent_config.yaml")
        store.save(AgentRoleConfigSet.with_defaults())
        leftover = list(tmp_path.glob(".agent_config.yaml.*"))
        assert leftover == []

    def test_invalid_yaml_falls_back_to_defaults(self, tmp_path):
        path = tmp_path / "agent_config.yaml"
        path.write_text("::: invalid: yaml: ::: [", encoding="utf-8")
        store = AgentConfigStore(path)
        cfg = store.load()
        assert AgentRole.BACKEND in cfg.configs

    def test_partial_file_filled_with_defaults(self, tmp_path):
        path = tmp_path / "agent_config.yaml"
        # backend만 있는 부분 파일
        partial = {
            "schema_version": "1.0.0",
            "configs": {
                "backend": {
                    "role": "backend",
                    "enabled": False,
                    "model": "custom-backend",
                    "max_tokens": 8192,
                    "temperature": 0.1,
                }
            },
        }
        path.write_text(yaml.safe_dump(partial), encoding="utf-8")

        store = AgentConfigStore(path)
        cfg = store.load()
        assert cfg.configs[AgentRole.BACKEND].enabled is False
        assert cfg.configs[AgentRole.BACKEND].model == "custom-backend"
        # 누락된 역할은 기본값 자동 채움
        assert AgentRole.FRONTEND in cfg.configs

    def test_update_role(self, tmp_path):
        store = AgentConfigStore(tmp_path / "agent_config.yaml")
        new_cfg = AgentRoleConfig(
            role=AgentRole.REVIEWER,
            model="reviewer",
            multi_provider_mode=MultiProviderMode.CONSENSUS,
            temperature=0.0,
        )
        result = store.update_role(AgentRole.REVIEWER, new_cfg)
        assert (
            result.configs[AgentRole.REVIEWER].multi_provider_mode
            == MultiProviderMode.CONSENSUS
        )
        # 디스크에도 반영
        reloaded = store.load()
        assert reloaded.configs[AgentRole.REVIEWER].temperature == 0.0

    def test_update_role_mismatch_raises(self, tmp_path):
        store = AgentConfigStore(tmp_path / "agent_config.yaml")
        with pytest.raises(ValueError):
            store.update_role(
                AgentRole.REVIEWER,
                AgentRoleConfig(role=AgentRole.BACKEND, model="x"),
            )


# ---------------------------------------------------------------------------
# model_registry
# ---------------------------------------------------------------------------


def _write_litellm(path: Path, data: dict) -> None:
    path.write_text(yaml.safe_dump(data), encoding="utf-8")


class TestLoadModels:
    def test_missing_file_returns_empty(self, tmp_path):
        assert load_models(tmp_path / "missing.yaml") == []

    def test_invalid_yaml_returns_empty(self, tmp_path):
        path = tmp_path / "broken.yaml"
        path.write_text("::: invalid: [", encoding="utf-8")
        assert load_models(path) == []

    def test_extracts_model_names_only(self, tmp_path):
        path = tmp_path / "litellm.yaml"
        _write_litellm(
            path,
            {
                "model_list": [
                    {
                        "model_name": "orchestrator",
                        "litellm_params": {
                            "model": "anthropic/claude-opus-4-6",
                            "api_key": "SECRET-XYZ",
                        },
                    },
                    {
                        "model_name": "backend-agent",
                        "litellm_params": {
                            "model": "openai/gpt-4o",
                            "api_base": "https://api.example/v1",
                            "api_key": "secret",
                        },
                    },
                ]
            },
        )
        result = load_models(path)
        names = [m.model_name for m in result]
        assert names == ["orchestrator", "backend-agent"]

        # 시크릿/URL이 응답에 노출되지 않는다.
        for m in result:
            dumped = m.model_dump_json()
            assert "SECRET" not in dumped
            assert "api_base" not in dumped
            assert "api_key" not in dumped
            assert "api.example" not in dumped

    def test_provider_split(self, tmp_path):
        path = tmp_path / "litellm.yaml"
        _write_litellm(
            path,
            {
                "model_list": [
                    {
                        "model_name": "x",
                        "litellm_params": {"model": "ollama_chat/llama3:8b"},
                    },
                    {"model_name": "y", "litellm_params": {"model": "raw-id"}},
                ]
            },
        )
        result = load_models(path)
        assert result[0].provider == "ollama_chat"
        assert result[0].underlying_model == "llama3:8b"
        assert result[1].provider is None
        assert result[1].underlying_model == "raw-id"

    def test_dedup_by_name(self, tmp_path):
        path = tmp_path / "litellm.yaml"
        _write_litellm(
            path,
            {
                "model_list": [
                    {"model_name": "dup", "litellm_params": {"model": "a/x"}},
                    {"model_name": "dup", "litellm_params": {"model": "b/y"}},
                ]
            },
        )
        result = load_models(path)
        assert len(result) == 1
        assert result[0].underlying_model == "x"

    def test_is_known_model(self):
        models = [
            ModelEntry(model_name="a"),
            ModelEntry(model_name="b"),
        ]
        assert is_known_model("a", models)
        assert not is_known_model("c", models)


class TestSanitize:
    def test_sanitize_masks_secrets(self):
        out = sanitize_dict(
            {
                "model": "anthropic/claude",
                "api_key": "SECRET",
                "api_base": "https://x",
                "master_key": "M",
            }
        )
        assert out["api_key"] == "***"
        assert out["api_base"] == "***"
        assert out["master_key"] == "***"
        assert out["model"] == "anthropic/claude"
