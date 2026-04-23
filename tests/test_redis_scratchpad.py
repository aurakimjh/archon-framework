"""Redis L1 스크래치패드 테스트 (fakeredis 사용)."""

from __future__ import annotations

import pytest
import fakeredis.aioredis

from src.memory.redis_scratchpad import RedisScratchpad


@pytest.fixture
def redis_client():
    return fakeredis.aioredis.FakeRedis()


@pytest.fixture
def scratchpad(redis_client):
    return RedisScratchpad(redis_client, ttl=60)


# --- 기본 CRUD ---


async def test_set_and_get(scratchpad: RedisScratchpad):
    await scratchpad.set("proj1", "task1", "notes", "hello world")
    result = await scratchpad.get("proj1", "task1", "notes")
    assert result == "hello world"


async def test_get_nonexistent_returns_none(scratchpad: RedisScratchpad):
    result = await scratchpad.get("proj1", "task1", "missing")
    assert result is None


async def test_set_complex_value(scratchpad: RedisScratchpad):
    value = {"files": ["a.py", "b.py"], "count": 3}
    await scratchpad.set("proj1", "task1", "context", value)
    result = await scratchpad.get("proj1", "task1", "context")
    assert result == value


async def test_overwrite_value(scratchpad: RedisScratchpad):
    await scratchpad.set("proj1", "task1", "key", "v1")
    await scratchpad.set("proj1", "task1", "key", "v2")
    result = await scratchpad.get("proj1", "task1", "key")
    assert result == "v2"


async def test_delete(scratchpad: RedisScratchpad):
    await scratchpad.set("proj1", "task1", "key", "value")
    deleted = await scratchpad.delete("proj1", "task1", "key")
    assert deleted is True
    result = await scratchpad.get("proj1", "task1", "key")
    assert result is None


async def test_delete_nonexistent(scratchpad: RedisScratchpad):
    deleted = await scratchpad.delete("proj1", "task1", "missing")
    assert deleted is False


# --- 격리 ---


async def test_project_isolation(scratchpad: RedisScratchpad):
    await scratchpad.set("proj1", "task1", "key", "proj1_val")
    await scratchpad.set("proj2", "task1", "key", "proj2_val")
    assert await scratchpad.get("proj1", "task1", "key") == "proj1_val"
    assert await scratchpad.get("proj2", "task1", "key") == "proj2_val"


async def test_task_isolation(scratchpad: RedisScratchpad):
    await scratchpad.set("proj1", "task1", "key", "task1_val")
    await scratchpad.set("proj1", "task2", "key", "task2_val")
    assert await scratchpad.get("proj1", "task1", "key") == "task1_val"
    assert await scratchpad.get("proj1", "task2", "key") == "task2_val"


# --- 키 목록 / 일괄 삭제 ---


async def test_list_keys(scratchpad: RedisScratchpad):
    await scratchpad.set("proj1", "task1", "a", 1)
    await scratchpad.set("proj1", "task1", "b", 2)
    await scratchpad.set("proj1", "task2", "c", 3)  # 다른 태스크
    keys = await scratchpad.list_keys("proj1", "task1")
    assert sorted(keys) == ["a", "b"]


async def test_clear_task(scratchpad: RedisScratchpad):
    await scratchpad.set("proj1", "task1", "x", 1)
    await scratchpad.set("proj1", "task1", "y", 2)
    await scratchpad.set("proj1", "task2", "z", 3)
    count = await scratchpad.clear_task("proj1", "task1")
    assert count == 2
    assert await scratchpad.get("proj1", "task1", "x") is None
    assert await scratchpad.get("proj1", "task2", "z") == 3
