"""vLLM Bridge 테스트 — 엔드포인트 등록, 헬스체크, LiteLLM 설정 생성."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.runtime.vllm_bridge import VLLMBridge, VLLMEndpoint

# --- VLLMEndpoint ---


class TestVLLMEndpoint:
    def test_create_endpoint(self):
        ep = VLLMEndpoint(
            name="backend-vllm",
            base_url="http://gpu-node:8000",
            model_name="Qwen/Qwen2.5-27B",
        )
        assert ep.name == "backend-vllm"
        assert ep.api_key == "EMPTY"
        assert ep.gpu_memory_utilization == 0.9

    def test_litellm_model(self):
        ep = VLLMEndpoint(
            name="test",
            base_url="http://localhost:8000",
            model_name="meta-llama/Llama-3-8B",
        )
        assert ep.litellm_model == "openai/meta-llama/Llama-3-8B"

    def test_health_url(self):
        ep = VLLMEndpoint(
            name="test",
            base_url="http://gpu:8000/",
            model_name="model",
        )
        assert ep.health_url == "http://gpu:8000/health"

    def test_models_url(self):
        ep = VLLMEndpoint(
            name="test",
            base_url="http://gpu:8000",
            model_name="model",
        )
        assert ep.models_url == "http://gpu:8000/v1/models"

    def test_tags(self):
        ep = VLLMEndpoint(
            name="test",
            base_url="http://gpu:8000",
            model_name="model",
            tags=["backend", "high-complexity"],
        )
        assert "backend" in ep.tags


# --- VLLMBridge ---


class TestVLLMBridge:
    def _make_endpoint(self, name: str = "test-ep") -> VLLMEndpoint:
        return VLLMEndpoint(
            name=name,
            base_url="http://gpu-node:8000",
            model_name="Qwen/Qwen2.5-27B",
            tags=["backend"],
        )

    def test_register(self):
        bridge = VLLMBridge()
        ep = self._make_endpoint()
        bridge.register(ep)
        assert len(bridge.list_endpoints()) == 1
        assert bridge.get_endpoint("test-ep") is ep

    def test_register_multiple(self):
        bridge = VLLMBridge()
        bridge.register(self._make_endpoint("ep1"))
        bridge.register(self._make_endpoint("ep2"))
        assert len(bridge.list_endpoints()) == 2

    def test_unregister(self):
        bridge = VLLMBridge()
        bridge.register(self._make_endpoint())
        assert bridge.unregister("test-ep") is True
        assert bridge.get_endpoint("test-ep") is None
        assert len(bridge.list_endpoints()) == 0

    def test_unregister_nonexistent(self):
        bridge = VLLMBridge()
        assert bridge.unregister("no-such") is False

    def test_get_endpoint_not_found(self):
        bridge = VLLMBridge()
        assert bridge.get_endpoint("no-such") is None

    def test_is_healthy_default_false(self):
        bridge = VLLMBridge()
        bridge.register(self._make_endpoint())
        assert bridge.is_healthy("test-ep") is False

    def test_list_healthy_empty(self):
        bridge = VLLMBridge()
        bridge.register(self._make_endpoint())
        assert bridge.list_healthy() == []

    def test_list_healthy_after_check(self):
        bridge = VLLMBridge()
        ep = self._make_endpoint()
        bridge.register(ep)
        bridge._healthy.add("test-ep")
        healthy = bridge.list_healthy()
        assert len(healthy) == 1
        assert healthy[0].name == "test-ep"

    @pytest.mark.asyncio
    async def test_health_check_success(self):
        bridge = VLLMBridge()
        bridge.register(self._make_endpoint())

        with patch("src.runtime.vllm_bridge.httpx.AsyncClient") as mock_cls:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            result = await bridge.health_check("test-ep")
            assert result is True
            assert bridge.is_healthy("test-ep")

    @pytest.mark.asyncio
    async def test_health_check_failure(self):
        bridge = VLLMBridge()
        bridge.register(self._make_endpoint())

        with patch("src.runtime.vllm_bridge.httpx.AsyncClient") as mock_cls:
            mock_response = MagicMock()
            mock_response.status_code = 503
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            result = await bridge.health_check("test-ep")
            assert result is False
            assert not bridge.is_healthy("test-ep")

    @pytest.mark.asyncio
    async def test_health_check_not_found(self):
        bridge = VLLMBridge()
        result = await bridge.health_check("no-such")
        assert result is False

    @pytest.mark.asyncio
    async def test_health_check_network_error(self):
        bridge = VLLMBridge()
        bridge.register(self._make_endpoint())

        import httpx as httpx_mod

        with patch("src.runtime.vllm_bridge.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get.side_effect = httpx_mod.ConnectError("Connection refused")
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            result = await bridge.health_check("test-ep")
            assert result is False

    @pytest.mark.asyncio
    async def test_health_check_all(self):
        bridge = VLLMBridge()
        bridge.register(self._make_endpoint("ep1"))
        bridge.register(self._make_endpoint("ep2"))

        with patch("src.runtime.vllm_bridge.httpx.AsyncClient") as mock_cls:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            results = await bridge.health_check_all()
            assert results == {"ep1": True, "ep2": True}

    def test_get_litellm_config(self):
        bridge = VLLMBridge()
        ep = VLLMEndpoint(
            name="test",
            base_url="http://gpu:8000",
            model_name="Qwen/Qwen2.5-27B",
            api_key="my-key",
            max_tokens=8192,
        )
        bridge.register(ep)
        config = bridge.get_litellm_config("test")
        assert config is not None
        assert config["model"] == "openai/Qwen/Qwen2.5-27B"
        assert config["api_base"] == "http://gpu:8000/v1"
        assert config["api_key"] == "my-key"
        assert config["max_tokens"] == 8192

    def test_get_litellm_config_not_found(self):
        bridge = VLLMBridge()
        assert bridge.get_litellm_config("no-such") is None

    def test_get_all_litellm_configs(self):
        bridge = VLLMBridge()
        bridge.register(self._make_endpoint("ep1"))
        bridge.register(self._make_endpoint("ep2"))
        # 하나만 healthy
        bridge._healthy.add("ep1")
        configs = bridge.get_all_litellm_configs()
        assert len(configs) == 1

    @pytest.mark.asyncio
    async def test_list_models_success(self):
        bridge = VLLMBridge()
        bridge.register(self._make_endpoint())

        with patch("src.runtime.vllm_bridge.httpx.AsyncClient") as mock_cls:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "data": [{"id": "model-a"}, {"id": "model-b"}],
            }
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            models = await bridge.list_models("test-ep")
            assert models == ["model-a", "model-b"]

    @pytest.mark.asyncio
    async def test_list_models_not_found(self):
        bridge = VLLMBridge()
        assert await bridge.list_models("no-such") == []

    def test_unregister_removes_healthy(self):
        bridge = VLLMBridge()
        bridge.register(self._make_endpoint())
        bridge._healthy.add("test-ep")
        bridge.unregister("test-ep")
        assert not bridge.is_healthy("test-ep")
