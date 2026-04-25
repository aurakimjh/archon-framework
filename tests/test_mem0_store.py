"""Mem0 L3 장기 메모리 테스트 — 모킹 기반 CRUD + 에러 처리."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.memory.mem0_store import Mem0Store


def _make_store(mock_client: MagicMock | None = None) -> tuple[Mem0Store, MagicMock]:
    client = mock_client or MagicMock()
    return Mem0Store(mem0_client=client), client


# ---------------------------------------------------------------------------
# add_memory
# ---------------------------------------------------------------------------


class TestAddMemory:
    def test_add_returns_dict(self):
        store, client = _make_store()
        client.add.return_value = {"id": "mem-001", "status": "ok"}
        result = store.add_memory("FastAPI에서 Pydantic v2 사용", user_id="archon")
        assert result["id"] == "mem-001"
        client.add.assert_called_once_with(
            "FastAPI에서 Pydantic v2 사용",
            user_id="archon",
            metadata={},
        )

    def test_add_with_metadata(self):
        store, client = _make_store()
        client.add.return_value = {"id": "mem-002"}
        meta = {"project_id": "proj-1", "agent_role": "backend"}
        result = store.add_memory("pattern", metadata=meta)
        client.add.assert_called_once_with("pattern", user_id="archon", metadata=meta)

    def test_add_non_dict_result(self):
        store, client = _make_store()
        client.add.return_value = "raw-string-result"
        result = store.add_memory("test")
        assert result == {"result": "raw-string-result"}

    def test_add_custom_user_id(self):
        store, client = _make_store()
        client.add.return_value = {}
        store.add_memory("test", user_id="custom-user")
        client.add.assert_called_once_with("test", user_id="custom-user", metadata={})


# ---------------------------------------------------------------------------
# search_memories
# ---------------------------------------------------------------------------


class TestSearchMemories:
    def test_search_returns_list(self):
        store, client = _make_store()
        client.search.return_value = [
            {"id": "m1", "memory": "pattern A", "metadata": {"project": "p1"}},
            {"id": "m2", "memory": "pattern B", "metadata": {}},
        ]
        results = store.search_memories("FastAPI pattern")
        assert len(results) == 2
        assert results[0]["id"] == "m1"
        assert results[0]["memory"] == "pattern A"

    def test_search_with_dict_wrapper(self):
        store, client = _make_store()
        client.search.return_value = {
            "results": [
                {"id": "m1", "memory": "result", "metadata": {}},
            ]
        }
        results = store.search_memories("query")
        assert len(results) == 1

    def test_search_respects_limit(self):
        store, client = _make_store()
        client.search.return_value = [
            {"id": f"m{i}", "memory": f"mem-{i}", "metadata": {}} for i in range(10)
        ]
        results = store.search_memories("query", limit=3)
        assert len(results) == 3

    def test_search_exception_returns_empty(self):
        store, client = _make_store()
        client.search.side_effect = RuntimeError("connection failed")
        results = store.search_memories("query")
        assert results == []

    def test_search_filters_non_dict_items(self):
        store, client = _make_store()
        client.search.return_value = [
            {"id": "m1", "memory": "ok", "metadata": {}},
            "invalid-item",
            42,
        ]
        results = store.search_memories("query")
        assert len(results) == 1

    def test_search_handles_missing_fields(self):
        store, client = _make_store()
        client.search.return_value = [{"extra": "data"}]
        results = store.search_memories("query")
        assert len(results) == 1
        assert results[0]["id"] == ""
        assert results[0]["memory"] == ""


# ---------------------------------------------------------------------------
# get_all
# ---------------------------------------------------------------------------


class TestGetAll:
    def test_get_all_list(self):
        store, client = _make_store()
        client.get_all.return_value = [
            {"id": "m1", "memory": "mem A", "metadata": {}},
        ]
        results = store.get_all()
        assert len(results) == 1
        client.get_all.assert_called_once_with(user_id="archon")

    def test_get_all_dict_wrapper(self):
        store, client = _make_store()
        client.get_all.return_value = {
            "results": [
                {"id": "m1", "memory": "mem A", "metadata": {}},
            ]
        }
        results = store.get_all()
        assert len(results) == 1

    def test_get_all_custom_user(self):
        store, client = _make_store()
        client.get_all.return_value = []
        store.get_all(user_id="custom")
        client.get_all.assert_called_once_with(user_id="custom")

    def test_get_all_exception_returns_empty(self):
        store, client = _make_store()
        client.get_all.side_effect = RuntimeError("fail")
        results = store.get_all()
        assert results == []

    def test_get_all_filters_non_dict(self):
        store, client = _make_store()
        client.get_all.return_value = [
            {"id": "m1", "memory": "ok", "metadata": {}},
            None,
            "bad",
        ]
        results = store.get_all()
        assert len(results) == 1


# ---------------------------------------------------------------------------
# delete_memory
# ---------------------------------------------------------------------------


class TestDeleteMemory:
    def test_delete_calls_client(self):
        store, client = _make_store()
        store.delete_memory("mem-001")
        client.delete.assert_called_once_with("mem-001")

    def test_delete_exception_logged(self):
        store, client = _make_store()
        client.delete.side_effect = RuntimeError("not found")
        # should not raise
        store.delete_memory("nonexistent")
