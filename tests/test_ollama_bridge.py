"""Ollama Bridge 테스트 — 엔드포인트 등록, 헬스체크, LiteLLM 설정, 라우팅 통합."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.runtime.ollama_bridge import (
    DEFAULT_OLLAMA_BASE_URL,
    OllamaBridge,
    OllamaEndpoint,
)

# --- OllamaEndpoint ---


class TestOllamaEndpoint:
    def test_create_with_defaults(self):
        ep = OllamaEndpoint(name="test-ollama")
        assert ep.name == "test-ollama"
        assert ep.base_url == DEFAULT_OLLAMA_BASE_URL
        assert ep.max_tokens == 4096
        assert ep.keep_alive == "5m"
        assert ep.num_gpu == -1
        assert ep.tags == []

    def test_create_with_custom(self):
        ep = OllamaEndpoint(
            name="backend-ollama",
            base_url="http://gpu-node:11434",
            model_name="llama3:8b",
            max_tokens=8192,
            keep_alive="24h",
            num_gpu=2,
            tags=["backend", "tester"],
        )
        assert ep.model_name == "llama3:8b"
        assert ep.keep_alive == "24h"
        assert ep.num_gpu == 2
        assert "backend" in ep.tags

    def test_litellm_model(self):
        ep = OllamaEndpoint(
            name="test",
            model_name="codellama:13b",
        )
        assert ep.litellm_model == "ollama_chat/codellama:13b"

    def test_api_url_strips_trailing_slash(self):
        ep = OllamaEndpoint(
            name="test",
            base_url="http://localhost:11434/",
        )
        assert ep.api_url == "http://localhost:11434"

    def test_tags_url(self):
        ep = OllamaEndpoint(
            name="test",
            base_url="http://localhost:11434",
        )
        assert ep.tags_url == "http://localhost:11434/api/tags"


# --- OllamaBridge ---


class TestOllamaBridge:
    def _make_endpoint(self, **kwargs):
        defaults = {
            "name": "test-ollama",
            "base_url": "http://localhost:11434",
            "model_name": "llama3:8b",
        }
        defaults.update(kwargs)
        return OllamaEndpoint(**defaults)

    def test_register_and_list(self):
        bridge = OllamaBridge()
        ep = self._make_endpoint()
        bridge.register(ep)

        assert len(bridge.list_endpoints()) == 1
        assert bridge.get_endpoint("test-ollama") is ep

    def test_unregister(self):
        bridge = OllamaBridge()
        bridge.register(self._make_endpoint())

        assert bridge.unregister("test-ollama") is True
        assert bridge.unregister("nonexistent") is False
        assert len(bridge.list_endpoints()) == 0

    def test_unregister_clears_healthy(self):
        bridge = OllamaBridge()
        bridge.register(self._make_endpoint())
        bridge._healthy.add("test-ollama")

        bridge.unregister("test-ollama")
        assert not bridge.is_healthy("test-ollama")

    def test_list_healthy_empty(self):
        bridge = OllamaBridge()
        bridge.register(self._make_endpoint())
        assert bridge.list_healthy() == []

    def test_list_healthy_with_healthy(self):
        bridge = OllamaBridge()
        ep = self._make_endpoint()
        bridge.register(ep)
        bridge._healthy.add("test-ollama")

        healthy = bridge.list_healthy()
        assert len(healthy) == 1
        assert healthy[0] is ep

    def test_is_healthy(self):
        bridge = OllamaBridge()
        bridge.register(self._make_endpoint())
        assert not bridge.is_healthy("test-ollama")
        bridge._healthy.add("test-ollama")
        assert bridge.is_healthy("test-ollama")

    def test_get_litellm_config(self):
        bridge = OllamaBridge()
        ep = self._make_endpoint(model_name="qwen2.5:32b", max_tokens=8192)
        bridge.register(ep)

        config = bridge.get_litellm_config("test-ollama")
        assert config is not None
        assert config["model"] == "ollama_chat/qwen2.5:32b"
        assert config["api_base"] == "http://localhost:11434"
        assert config["max_tokens"] == 8192

    def test_get_litellm_config_not_found(self):
        bridge = OllamaBridge()
        assert bridge.get_litellm_config("nonexistent") is None

    def test_get_all_litellm_configs(self):
        bridge = OllamaBridge()
        bridge.register(self._make_endpoint(name="a", model_name="llama3:8b"))
        bridge.register(self._make_endpoint(name="b", model_name="codellama:13b"))
        bridge._healthy.add("a")

        configs = bridge.get_all_litellm_configs()
        assert len(configs) == 1
        assert configs[0]["model"] == "ollama_chat/llama3:8b"

    def test_get_all_litellm_configs_empty(self):
        bridge = OllamaBridge()
        bridge.register(self._make_endpoint())
        assert bridge.get_all_litellm_configs() == []


# --- Health Check ---


class TestOllamaBridgeHealthCheck:
    def _make_bridge(self):
        bridge = OllamaBridge()
        ep = OllamaEndpoint(
            name="test-ollama",
            base_url="http://localhost:11434",
            model_name="llama3:8b",
        )
        bridge.register(ep)
        return bridge

    @pytest.mark.asyncio
    async def test_health_check_success(self):
        bridge = self._make_bridge()

        mock_response_root = MagicMock()
        mock_response_root.status_code = 200

        mock_response_tags = MagicMock()
        mock_response_tags.status_code = 200
        mock_response_tags.json.return_value = {
            "models": [{"name": "llama3:8b"}],
        }

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(
            side_effect=[mock_response_root, mock_response_tags],
        )
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("src.runtime.ollama_bridge.httpx.AsyncClient", return_value=mock_client):
            result = await bridge.health_check("test-ollama")

        assert result is True
        assert bridge.is_healthy("test-ollama")

    @pytest.mark.asyncio
    async def test_health_check_server_down(self):
        bridge = self._make_bridge()

        mock_response = MagicMock()
        mock_response.status_code = 500

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("src.runtime.ollama_bridge.httpx.AsyncClient", return_value=mock_client):
            result = await bridge.health_check("test-ollama")

        assert result is False
        assert not bridge.is_healthy("test-ollama")

    @pytest.mark.asyncio
    async def test_health_check_model_not_found(self):
        bridge = self._make_bridge()

        mock_response_root = MagicMock()
        mock_response_root.status_code = 200

        mock_response_tags = MagicMock()
        mock_response_tags.status_code = 200
        mock_response_tags.json.return_value = {
            "models": [{"name": "mistral:7b"}],
        }

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(
            side_effect=[mock_response_root, mock_response_tags],
        )
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("src.runtime.ollama_bridge.httpx.AsyncClient", return_value=mock_client):
            result = await bridge.health_check("test-ollama")

        assert result is False

    @pytest.mark.asyncio
    async def test_health_check_network_error(self):
        bridge = self._make_bridge()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(
            side_effect=httpx.ConnectError("Connection refused"),
        )
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("src.runtime.ollama_bridge.httpx.AsyncClient", return_value=mock_client):
            result = await bridge.health_check("test-ollama")

        assert result is False

    @pytest.mark.asyncio
    async def test_health_check_nonexistent(self):
        bridge = OllamaBridge()
        result = await bridge.health_check("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_health_check_all(self):
        bridge = OllamaBridge()
        bridge.register(OllamaEndpoint(
            name="a", model_name="llama3:8b",
        ))
        bridge.register(OllamaEndpoint(
            name="b", model_name="codellama:13b",
        ))

        mock_response_root = MagicMock()
        mock_response_root.status_code = 200

        mock_response_tags = MagicMock()
        mock_response_tags.status_code = 200
        mock_response_tags.json.return_value = {
            "models": [
                {"name": "llama3:8b"},
                {"name": "codellama:13b"},
            ],
        }

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(
            return_value=mock_response_root,
        )
        # Alternate between root and tags responses
        mock_client.get = AsyncMock(
            side_effect=[
                mock_response_root, mock_response_tags,
                mock_response_root, mock_response_tags,
            ],
        )
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("src.runtime.ollama_bridge.httpx.AsyncClient", return_value=mock_client):
            results = await bridge.health_check_all()

        assert results["a"] is True
        assert results["b"] is True

    @pytest.mark.asyncio
    async def test_health_check_no_model_name(self):
        """model_name이 빈 문자열이면 모델 확인을 건너뛴다."""
        bridge = OllamaBridge()
        bridge.register(OllamaEndpoint(name="bare", model_name=""))

        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("src.runtime.ollama_bridge.httpx.AsyncClient", return_value=mock_client):
            result = await bridge.health_check("bare")

        assert result is True


# --- Model Operations ---


class TestOllamaBridgeModelOps:
    @pytest.mark.asyncio
    async def test_list_models(self):
        bridge = OllamaBridge()
        bridge.register(OllamaEndpoint(
            name="test", model_name="llama3:8b",
        ))

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "models": [
                {"name": "llama3:8b"},
                {"name": "codellama:13b"},
            ],
        }

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("src.runtime.ollama_bridge.httpx.AsyncClient", return_value=mock_client):
            models = await bridge.list_models("test")

        assert "llama3:8b" in models
        assert "codellama:13b" in models

    @pytest.mark.asyncio
    async def test_list_models_no_endpoint(self):
        bridge = OllamaBridge()
        models = await bridge.list_models("nonexistent")
        assert models == []

    @pytest.mark.asyncio
    async def test_list_models_default_endpoint(self):
        bridge = OllamaBridge()
        bridge.register(OllamaEndpoint(
            name="default", model_name="llama3:8b",
        ))

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "models": [{"name": "llama3:8b"}],
        }

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("src.runtime.ollama_bridge.httpx.AsyncClient", return_value=mock_client):
            models = await bridge.list_models()

        assert len(models) == 1

    @pytest.mark.asyncio
    async def test_pull_model_success(self):
        bridge = OllamaBridge()
        bridge.register(OllamaEndpoint(name="test", model_name="llama3:8b"))

        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("src.runtime.ollama_bridge.httpx.AsyncClient", return_value=mock_client):
            result = await bridge.pull_model("qwen2.5:32b", "test")

        assert result is True

    @pytest.mark.asyncio
    async def test_pull_model_no_endpoint(self):
        bridge = OllamaBridge()
        result = await bridge.pull_model("llama3:8b")
        assert result is False

    @pytest.mark.asyncio
    async def test_pull_model_failure(self):
        bridge = OllamaBridge()
        bridge.register(OllamaEndpoint(name="test", model_name="llama3:8b"))

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(
            side_effect=httpx.ConnectError("refused"),
        )
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("src.runtime.ollama_bridge.httpx.AsyncClient", return_value=mock_client):
            result = await bridge.pull_model("qwen2.5:32b", "test")

        assert result is False


# --- Router Integration ---


class TestOllamaRouting:
    def _make_registry(self):
        from src.registry.models import (
            AgentModelConfig,
            AgentRole,
            GitConfig,
            ProjectMeta,
            ProjectRegistry,
        )

        return ProjectRegistry(
            project_meta=ProjectMeta(
                project_id="test-proj", project_name="Test",
            ),
            git_config=GitConfig(
                repo_url="https://example.com/repo.git",
            ),
            agent_config={
                AgentRole.BACKEND: AgentModelConfig(model="backend-agent"),
            },
        )

    def _make_handoff(self):
        from src.orchestrator.handoff import (
            Envelope,
            HandoffArtifact,
            ProjectContext,
            Task,
        )

        return HandoffArtifact(
            envelope=Envelope(
                handoff_id="hf_ollama",
                from_agent="orchestrator",
                to_agent="backend",
            ),
            project_context=ProjectContext(
                project_id="test-proj",
                project_name="Test",
                git_repo="/tmp/test",
                git_branch="develop",
                base_commit_sha="abc123",
            ),
            task=Task(
                task_id="T-001",
                completed_summary="",
                next_instructions="test task",
            ),
        )

    def test_get_model_with_ollama_no_bridge(self):
        from src.router.role_router import get_model_with_ollama

        registry = self._make_registry()
        handoff = self._make_handoff()

        model, config = get_model_with_ollama(
            "backend", handoff, registry, None,
        )
        assert model == "backend-agent"
        assert config is None

    def test_get_model_with_ollama_healthy(self):
        from src.router.role_router import get_model_with_ollama

        registry = self._make_registry()
        handoff = self._make_handoff()
        bridge = OllamaBridge()

        ep = OllamaEndpoint(
            name="backend-ollama",
            model_name="llama3:8b",
            tags=["backend"],
        )
        bridge.register(ep)
        bridge._healthy.add("backend-ollama")

        model, config = get_model_with_ollama(
            "backend", handoff, registry, bridge,
        )
        assert model == "ollama_chat/llama3:8b"
        assert config is not None
        assert config["api_base"] == DEFAULT_OLLAMA_BASE_URL

    def test_get_model_with_ollama_no_match(self):
        from src.router.role_router import get_model_with_ollama

        registry = self._make_registry()
        handoff = self._make_handoff()
        bridge = OllamaBridge()

        ep = OllamaEndpoint(
            name="docs-ollama",
            model_name="llama3:8b",
            tags=["docs"],
        )
        bridge.register(ep)
        bridge._healthy.add("docs-ollama")

        model, config = get_model_with_ollama(
            "backend", handoff, registry, bridge,
        )
        assert model == "backend-agent"
        assert config is None

    def test_get_model_with_provider_ollama_fallback(self):
        from src.router.role_router import get_model_with_provider

        registry = self._make_registry()
        handoff = self._make_handoff()
        ollama = OllamaBridge()

        ep = OllamaEndpoint(
            name="backend-ollama",
            model_name="qwen2.5:32b",
            tags=["backend"],
        )
        ollama.register(ep)
        ollama._healthy.add("backend-ollama")

        model, config = get_model_with_provider(
            "backend", handoff, registry,
            vllm_bridge=None, ollama_bridge=ollama,
        )
        assert model == "ollama_chat/qwen2.5:32b"
        assert config is not None

    def test_get_model_with_provider_default_fallback(self):
        from src.router.role_router import get_model_with_provider

        registry = self._make_registry()
        handoff = self._make_handoff()

        model, config = get_model_with_provider(
            "backend", handoff, registry,
            vllm_bridge=None, ollama_bridge=None,
        )
        assert model == "backend-agent"
        assert config is None
