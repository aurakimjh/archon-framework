"""ChromaDB L2 벡터 스토어 테스트 (인메모리 ChromaDB 사용)."""

from __future__ import annotations

import uuid

import pytest
import chromadb

from src.memory.vector_store import VectorStore


@pytest.fixture
def store():
    client = chromadb.Client()
    prefix = f"test_{uuid.uuid4().hex[:8]}"
    return VectorStore(client, collection_prefix=prefix)


# --- 기본 저장/검색 ---


def test_store_and_count(store: VectorStore):
    store.store_handoff("proj1", "hf_001", "FastAPI 엔드포인트 생성")
    store.store_handoff("proj1", "hf_002", "PostgreSQL 마이그레이션 작성")
    assert store.count("proj1") == 2


def test_search_returns_similar(store: VectorStore):
    store.store_handoff("proj1", "hf_001", "FastAPI REST API endpoint created")
    store.store_handoff("proj1", "hf_002", "PostgreSQL migration script written")
    store.store_handoff("proj1", "hf_003", "Docker compose configuration added")

    results = store.search("proj1", "REST API endpoint", threshold=0.5)
    assert len(results) > 0
    assert results[0]["id"] == "hf_001"


def test_search_empty_collection(store: VectorStore):
    results = store.search("proj1", "anything")
    assert results == []


def test_search_with_high_threshold(store: VectorStore):
    store.store_handoff("proj1", "hf_001", "FastAPI endpoint")
    results = store.search("proj1", "completely unrelated quantum physics", threshold=0.99)
    assert results == []


# --- 메타데이터 ---


def test_store_with_metadata(store: VectorStore):
    store.store_handoff(
        "proj1",
        "hf_001",
        "Backend API endpoint",
        metadata={"agent": "backend", "score": 85},
    )
    results = store.search("proj1", "API endpoint", threshold=0.5)
    assert len(results) > 0
    assert results[0]["metadata"]["agent"] == "backend"


def test_metadata_filters_non_primitive(store: VectorStore):
    """dict/list 같은 비원시 타입 메타데이터는 필터링된다."""
    store.store_handoff(
        "proj1",
        "hf_001",
        "test doc",
        metadata={"valid": "yes", "invalid_list": [1, 2, 3]},
    )
    results = store.search("proj1", "test doc", threshold=0.5)
    assert len(results) > 0
    assert "invalid_list" not in results[0]["metadata"]


# --- 프로젝트 격리 ---


def test_project_isolation(store: VectorStore):
    store.store_handoff("proj1", "hf_001", "Project 1 work")
    store.store_handoff("proj2", "hf_001", "Project 2 work")
    assert store.count("proj1") == 1
    assert store.count("proj2") == 1


# --- 삭제 ---


def test_delete_handoff(store: VectorStore):
    store.store_handoff("proj1", "hf_001", "to delete")
    store.store_handoff("proj1", "hf_002", "to keep")
    store.delete_handoff("proj1", "hf_001")
    assert store.count("proj1") == 1


def test_delete_project(store: VectorStore):
    store.store_handoff("proj1", "hf_001", "doc1")
    store.store_handoff("proj1", "hf_002", "doc2")
    store.delete_project("proj1")
    assert store.count("proj1") == 0


def test_delete_nonexistent_project(store: VectorStore):
    """존재하지 않는 프로젝트 삭제 시 에러 없이 통과."""
    store.delete_project("nonexistent")


# --- Upsert ---


def test_upsert_overwrites(store: VectorStore):
    store.store_handoff("proj1", "hf_001", "version 1")
    store.store_handoff("proj1", "hf_001", "version 2 updated")
    assert store.count("proj1") == 1
    results = store.search("proj1", "version 2", threshold=0.5)
    assert len(results) > 0
