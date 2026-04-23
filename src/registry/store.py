"""Registry Store — 프로젝트 레지스트리 파일 기반 CRUD."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from .models import ProjectMetrics, ProjectRegistry, WorkQueue

logger = logging.getLogger(__name__)

_DEFAULT_REGISTRY_DIR = ".harness/registry"


class RegistryStore:
    """`.harness/registry/` 디렉토리의 JSON 파일로 ProjectRegistry를 관리한다."""

    def __init__(self, base_path: str | Path | None = None) -> None:
        self._base = Path(base_path or _DEFAULT_REGISTRY_DIR)

    def _registry_path(self, project_id: str) -> Path:
        return self._base / f"{project_id}.json"

    def _ensure_dir(self) -> None:
        self._base.mkdir(parents=True, exist_ok=True)

    def load(self, project_id: str) -> ProjectRegistry:
        """프로젝트 레지스트리를 JSON에서 로드한다.

        Raises:
            FileNotFoundError: 프로젝트 파일이 없을 때.
        """
        path = self._registry_path(project_id)
        if not path.exists():
            raise FileNotFoundError(f"Registry not found: {path}")

        data = json.loads(path.read_text(encoding="utf-8"))
        return ProjectRegistry.model_validate(data)

    def save(self, registry: ProjectRegistry) -> None:
        """프로젝트 레지스트리를 JSON으로 저장한다."""
        self._ensure_dir()
        path = self._registry_path(registry.project_meta.project_id)
        path.write_text(
            registry.model_dump_json(indent=2),
            encoding="utf-8",
        )
        logger.info("Registry saved: %s", path)

    def list_projects(self) -> list[str]:
        """저장된 모든 프로젝트 ID 목록을 반환한다."""
        if not self._base.exists():
            return []
        return [
            p.stem
            for p in sorted(self._base.glob("*.json"))
            if p.is_file()
        ]

    def delete(self, project_id: str) -> None:
        """프로젝트 레지스트리 파일을 삭제한다.

        Raises:
            FileNotFoundError: 프로젝트 파일이 없을 때.
        """
        path = self._registry_path(project_id)
        if not path.exists():
            raise FileNotFoundError(f"Registry not found: {path}")
        path.unlink()
        logger.info("Registry deleted: %s", path)

    def exists(self, project_id: str) -> bool:
        """프로젝트 레지스트리 파일 존재 여부를 확인한다."""
        return self._registry_path(project_id).exists()

    def update_metrics(
        self,
        project_id: str,
        **kwargs: int | float,
    ) -> ProjectMetrics:
        """프로젝트 메트릭스를 부분 업데이트한다.

        지원하는 키: total_tokens_used, estimated_cost_usd,
        auto_commit_count, human_gate_count, l3_halt_count, average_review_score.
        정수/실수 값은 기존 값에 더해진다 (delta).
        """
        registry = self.load(project_id)
        metrics = registry.metrics

        for key, delta in kwargs.items():
            if not hasattr(metrics, key):
                continue
            current = getattr(metrics, key)
            if isinstance(current, (int, float)):
                setattr(metrics, key, current + delta)

        self.save(registry)
        return metrics

    def update_work_queue(
        self,
        project_id: str,
        work_queue: WorkQueue,
    ) -> None:
        """프로젝트의 워크큐 상태를 교체한다."""
        registry = self.load(project_id)
        registry.work_queue = work_queue
        self.save(registry)
