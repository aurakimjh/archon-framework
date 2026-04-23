"""Redis L1 스크래치패드 — TTL 24시간 단기 메모리."""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_TTL = 86400  # 24시간
_KEY_PREFIX = "archon:scratch"


def _make_key(project_id: str, task_id: str, key: str) -> str:
    return f"{_KEY_PREFIX}:{project_id}:{task_id}:{key}"


class RedisScratchpad:
    """Redis 기반 L1 단기 메모리.

    TTL 24시간으로 자동 만료되는 태스크별 스크래치패드.
    redis.asyncio 클라이언트를 주입받는다.
    """

    def __init__(self, redis_client: Any, ttl: int = _DEFAULT_TTL) -> None:
        """
        Args:
            redis_client: redis.asyncio.Redis 인스턴스.
            ttl: 키 만료 시간(초). 기본 24시간.
        """
        self._redis = redis_client
        self._ttl = ttl

    async def set(
        self,
        project_id: str,
        task_id: str,
        key: str,
        value: Any,
        ttl: int | None = None,
    ) -> None:
        """스크래치 값 저장."""
        full_key = _make_key(project_id, task_id, key)
        serialized = json.dumps(value, ensure_ascii=False)
        await self._redis.set(full_key, serialized, ex=ttl or self._ttl)

    async def get(
        self,
        project_id: str,
        task_id: str,
        key: str,
    ) -> Any | None:
        """스크래치 값 조회. 없으면 None."""
        full_key = _make_key(project_id, task_id, key)
        raw = await self._redis.get(full_key)
        if raw is None:
            return None
        return json.loads(raw)

    async def delete(
        self,
        project_id: str,
        task_id: str,
        key: str,
    ) -> bool:
        """스크래치 값 삭제. 삭제 성공 시 True."""
        full_key = _make_key(project_id, task_id, key)
        result = await self._redis.delete(full_key)
        return result > 0

    async def list_keys(
        self,
        project_id: str,
        task_id: str,
    ) -> list[str]:
        """특정 태스크의 모든 스크래치 키 목록 반환."""
        pattern = _make_key(project_id, task_id, "*")
        prefix = _make_key(project_id, task_id, "")
        keys: list[str] = []
        async for raw_key in self._redis.scan_iter(match=pattern):
            k = raw_key.decode() if isinstance(raw_key, bytes) else raw_key
            keys.append(k.removeprefix(prefix))
        return keys

    async def clear_task(
        self,
        project_id: str,
        task_id: str,
    ) -> int:
        """특정 태스크의 모든 스크래치 데이터 삭제. 삭제된 키 수 반환."""
        pattern = _make_key(project_id, task_id, "*")
        count = 0
        async for raw_key in self._redis.scan_iter(match=pattern):
            await self._redis.delete(raw_key)
            count += 1
        return count
