"""SchemaMigrator — HandoffArtifact 버전 간 자동 마이그레이션."""

from __future__ import annotations

import importlib
import logging
from collections.abc import Callable
from dataclasses import dataclass

from src.errors import ArchonError

logger = logging.getLogger(__name__)

# 현재 최신 스키마 버전
CURRENT_VERSION = "1.1.0"


class MigrationError(ArchonError):
    """마이그레이션 실패."""


@dataclass
class MigrationStep:
    from_version: str
    to_version: str
    upgrade: Callable[[dict], dict]
    downgrade: Callable[[dict], dict]


class SchemaMigrator:
    """HandoffArtifact 딕셔너리의 버전을 자동으로 마이그레이션한다.

    마이그레이션 경로는 버전 체인으로 자동 계산된다.
    예: 1.0.0 → 1.2.0은 1.0→1.1→1.2 순서로 적용된다.
    """

    def __init__(self) -> None:
        # (from_ver, to_ver) → MigrationStep
        self._steps: dict[tuple[str, str], MigrationStep] = {}
        # 정렬된 버전 목록 (오름차순)
        self._versions: list[str] = []
        self._register_builtin_migrations()

    # --- 공개 API ---

    def migrate(self, data: dict, target_version: str = CURRENT_VERSION) -> dict:
        """data를 target_version으로 마이그레이션한다.

        data["envelope"]["schema_version"]을 기준으로 업그레이드/다운그레이드 경로를 계산한다.
        이미 target_version이면 data를 그대로 반환한다.
        """
        current = self._get_version(data)
        if current == target_version:
            return data

        path = self._resolve_path(current, target_version)
        if not path:
            raise MigrationError(
                f"No migration path from {current} to {target_version}"
            )

        logger.info(
            "SchemaMigrator: migrating %s → %s (steps: %s)",
            current,
            target_version,
            " → ".join(path),
        )

        result = data
        pairs = list(zip(path[:-1], path[1:]))
        for from_v, to_v in pairs:
            step = self._steps.get((from_v, to_v))
            if step is None:
                raise MigrationError(f"Missing migration step: {from_v} → {to_v}")
            going_up = self._version_tuple(to_v) > self._version_tuple(from_v)
            fn = step.upgrade if going_up else step.downgrade
            result = fn(result)
            logger.debug("  applied %s → %s", from_v, to_v)

        return result

    def migrate_to_latest(self, data: dict) -> dict:
        """data를 현재 최신 버전(CURRENT_VERSION)으로 마이그레이션한다."""
        return self.migrate(data, CURRENT_VERSION)

    def rollback(self, data: dict, target_version: str) -> dict:
        """data를 이전 버전으로 롤백한다."""
        return self.migrate(data, target_version)

    def register(self, step: MigrationStep) -> None:
        """외부에서 마이그레이션 스텝을 추가한다."""
        self._steps[(step.from_version, step.to_version)] = step
        self._steps[(step.to_version, step.from_version)] = step
        for v in (step.from_version, step.to_version):
            if v not in self._versions:
                self._versions.append(v)
        self._versions.sort(key=self._version_tuple)

    # --- 내부 구현 ---

    def _register_builtin_migrations(self) -> None:
        """내장 마이그레이션 스텝을 등록한다."""
        try:
            mod = importlib.import_module("src.migration.migrations.v1_0_to_v1_1")
            self.register(MigrationStep(
                from_version="1.0.0",
                to_version="1.1.0",
                upgrade=mod.upgrade,
                downgrade=mod.downgrade,
            ))
        except ImportError as e:
            logger.warning("Failed to load built-in migration v1_0_to_v1_1: %s", e)

    def _get_version(self, data: dict) -> str:
        try:
            return data["envelope"]["schema_version"]
        except (KeyError, TypeError) as e:
            raise MigrationError("Cannot read schema_version from data") from e

    def _resolve_path(self, from_v: str, to_v: str) -> list[str] | None:
        """BFS로 버전 그래프에서 마이그레이션 경로를 탐색한다."""
        if from_v not in self._versions or to_v not in self._versions:
            return None

        from collections import deque

        queue: deque[list[str]] = deque([[from_v]])
        visited: set[str] = {from_v}

        while queue:
            path = queue.popleft()
            current = path[-1]
            if current == to_v:
                return path
            for (f, t), _ in self._steps.items():
                neighbor = t if f == current else (f if t == current else None)
                if neighbor and neighbor not in visited:
                    visited.add(neighbor)
                    queue.append([*path, neighbor])
        return None

    @staticmethod
    def _version_tuple(v: str) -> tuple[int, ...]:
        try:
            return tuple(int(x) for x in v.split("."))
        except ValueError:
            return (0,)


# 싱글턴 인스턴스
_migrator: SchemaMigrator | None = None


def get_migrator() -> SchemaMigrator:
    """프로세스 전역 SchemaMigrator 인스턴스를 반환한다."""
    global _migrator
    if _migrator is None:
        _migrator = SchemaMigrator()
    return _migrator
