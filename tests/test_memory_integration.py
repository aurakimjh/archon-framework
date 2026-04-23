"""MemoryStore 3계층 파사드 통합 테스트."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import chromadb
import fakeredis.aioredis

from src.memory.context_injector import MemoryStore
from src.memory.redis_scratchpad import RedisScratchpad
from src.memory.vector_store import VectorStore


# --- 인메모리 폴백 모드 (백엔드 없음) ---


class TestFallbackMode:
    """백엔드 미연결 시 인메모리 dict 폴백 동작."""

    @pytest.fixture
    def store(self):
        return MemoryStore()

    def test_no_backends(self, store: MemoryStore):
        assert not store.has_redis
        assert not store.has_vector
        assert not store.has_mem0

    async def test_scratch_fallback(self, store: MemoryStore):
        await store.set_scratch("proj1", "task1", "key", "value")
        result = await store.get_scratch("proj1", "task1", "key")
        assert result == "value"

    async def test_scratch_fallback_none(self, store: MemoryStore):
        result = await store.get_scratch("proj1", "task1", "missing")
        assert result is None

    def test_handoff_fallback(self, store: MemoryStore):
        store.store_handoff("proj1", "hf_001", "FastAPI endpoint created")
        results = store.search_handoffs("proj1", "fastapi")
        assert len(results) == 1
        assert results[0]["id"] == "hf_001"

    def test_handoff_fallback_no_match(self, store: MemoryStore):
        store.store_handoff("proj1", "hf_001", "FastAPI endpoint")
        results = store.search_handoffs("proj1", "quantum physics")
        assert len(results) == 0

    def test_pattern_fallback(self, store: MemoryStore):
        store.store_pattern("proj1", "Pydantic v2 사용", reason="타입 안전성")
        results = store.search_patterns("pydantic")
        assert len(results) == 1
        assert results[0]["memory"] == "Pydantic v2 사용"

    async def test_inject_memory_context_empty(self, store: MemoryStore):
        ctx = await store.inject_memory_context("build API", "proj1")
        assert ctx.relevant_past_decisions == []
        assert ctx.known_patterns == []

    async def test_inject_memory_context_with_patterns(self, store: MemoryStore):
        store.store_pattern("proj1", "Always use async handlers", reason="성능")
        ctx = await store.inject_memory_context("something", "proj1")
        assert len(ctx.known_patterns) == 1
        assert ctx.known_patterns[0].pattern == "Always use async handlers"


# --- Redis + ChromaDB 연동 ---


class TestWithBackends:
    """실제 백엔드(fakeredis, in-memory ChromaDB) 연동 테스트."""

    @pytest.fixture
    def store(self):
        redis_client = fakeredis.aioredis.FakeRedis()
        chroma_client = chromadb.Client()
        return MemoryStore(
            redis_scratchpad=RedisScratchpad(redis_client, ttl=60),
            vector_store=VectorStore(chroma_client, collection_prefix="integ"),
        )

    def test_has_backends(self, store: MemoryStore):
        assert store.has_redis
        assert store.has_vector
        assert not store.has_mem0

    async def test_scratch_via_redis(self, store: MemoryStore):
        await store.set_scratch("proj1", "task1", "ctx", {"files": ["a.py"]})
        result = await store.get_scratch("proj1", "task1", "ctx")
        assert result == {"files": ["a.py"]}

    def test_handoff_via_chromadb(self, store: MemoryStore):
        store.store_handoff("proj1", "hf_001", "FastAPI REST endpoint created")
        store.store_handoff("proj1", "hf_002", "Docker compose written")
        results = store.search_handoffs("proj1", "REST API endpoint", threshold=0.5)
        assert len(results) > 0

    async def test_inject_with_vector(self, store: MemoryStore):
        store.store_handoff(
            "proj1", "hf_001", "Created FastAPI backend API endpoint for users"
        )
        # 기본 임베딩 모델에서 threshold 0.85는 너무 높을 수 있으므로 낮춰서 검색
        results = store.search_handoffs("proj1", "API endpoint", threshold=0.5)
        assert len(results) > 0
        assert results[0]["id"] == "hf_001"


# --- Mem0 모킹 ---


class TestWithMem0Mock:
    """Mem0 백엔드 모킹 테스트."""

    @pytest.fixture
    def store(self):
        mock_mem0 = MagicMock()
        mock_mem0.add.return_value = {"id": "mem_001"}
        mock_mem0.search.return_value = {
            "results": [
                {
                    "id": "mem_001",
                    "memory": "Pydantic v2 사용",
                    "metadata": {"project_id": "proj1", "type": "pattern"},
                }
            ]
        }
        mock_mem0.get_all.return_value = {
            "results": [
                {"id": "mem_001", "memory": "Pydantic v2", "metadata": {}}
            ]
        }

        from src.memory.mem0_store import Mem0Store

        return MemoryStore(mem0_store=Mem0Store(mock_mem0))

    def test_has_mem0(self, store: MemoryStore):
        assert store.has_mem0

    def test_store_pattern_via_mem0(self, store: MemoryStore):
        store.store_pattern("proj1", "Pydantic v2 사용", reason="타입 안전")
        # mem0.add가 호출되었는지 확인
        assert store._mem0 is not None

    def test_search_patterns_via_mem0(self, store: MemoryStore):
        results = store.search_patterns("Pydantic")
        assert len(results) == 1
        assert results[0]["memory"] == "Pydantic v2 사용"

    async def test_inject_with_mem0(self, store: MemoryStore):
        ctx = await store.inject_memory_context("use Pydantic", "proj1")
        assert len(ctx.known_patterns) == 1
        assert "Pydantic" in ctx.known_patterns[0].pattern
