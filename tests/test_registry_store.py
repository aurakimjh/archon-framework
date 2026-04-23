"""RegistryStore CRUD 테스트."""

import json
from pathlib import Path

import pytest

from src.registry.models import (
    GitConfig,
    ProjectMeta,
    ProjectRegistry,
    TaskRef,
    WorkQueue,
)
from src.registry.store import RegistryStore


@pytest.fixture()
def store(tmp_path: Path) -> RegistryStore:
    return RegistryStore(base_path=tmp_path / "registry")


@pytest.fixture()
def sample_registry() -> ProjectRegistry:
    return ProjectRegistry(
        project_meta=ProjectMeta(
            project_id="proj_001",
            project_name="Test Project",
            owner="dev_001",
        ),
        git_config=GitConfig(
            repo_url="https://github.com/test/repo.git",
        ),
    )


class TestSaveAndLoad:
    def test_save_creates_file(
        self, store: RegistryStore, sample_registry: ProjectRegistry
    ) -> None:
        store.save(sample_registry)
        path = store._registry_path("proj_001")
        assert path.exists()

    def test_load_returns_same_data(
        self, store: RegistryStore, sample_registry: ProjectRegistry
    ) -> None:
        store.save(sample_registry)
        loaded = store.load("proj_001")
        assert loaded.project_meta.project_id == "proj_001"
        assert loaded.project_meta.project_name == "Test Project"
        assert loaded.git_config.repo_url == "https://github.com/test/repo.git"

    def test_roundtrip_preserves_all_fields(
        self, store: RegistryStore, sample_registry: ProjectRegistry
    ) -> None:
        store.save(sample_registry)
        loaded = store.load("proj_001")
        assert loaded.model_dump() == sample_registry.model_dump()

    def test_load_nonexistent_raises(self, store: RegistryStore) -> None:
        with pytest.raises(FileNotFoundError):
            store.load("nonexistent")

    def test_saved_file_is_valid_json(
        self, store: RegistryStore, sample_registry: ProjectRegistry
    ) -> None:
        store.save(sample_registry)
        path = store._registry_path("proj_001")
        data = json.loads(path.read_text())
        assert data["project_meta"]["project_id"] == "proj_001"


class TestListAndDelete:
    def test_list_empty(self, store: RegistryStore) -> None:
        assert store.list_projects() == []

    def test_list_multiple(
        self, store: RegistryStore, sample_registry: ProjectRegistry
    ) -> None:
        store.save(sample_registry)

        reg2 = sample_registry.model_copy(deep=True)
        reg2.project_meta.project_id = "proj_002"
        store.save(reg2)

        projects = store.list_projects()
        assert "proj_001" in projects
        assert "proj_002" in projects
        assert len(projects) == 2

    def test_delete_removes_file(
        self, store: RegistryStore, sample_registry: ProjectRegistry
    ) -> None:
        store.save(sample_registry)
        store.delete("proj_001")
        assert not store.exists("proj_001")

    def test_delete_nonexistent_raises(self, store: RegistryStore) -> None:
        with pytest.raises(FileNotFoundError):
            store.delete("nonexistent")

    def test_exists(
        self, store: RegistryStore, sample_registry: ProjectRegistry
    ) -> None:
        assert not store.exists("proj_001")
        store.save(sample_registry)
        assert store.exists("proj_001")


class TestUpdateMetrics:
    def test_update_adds_delta(
        self, store: RegistryStore, sample_registry: ProjectRegistry
    ) -> None:
        store.save(sample_registry)
        metrics = store.update_metrics("proj_001", auto_commit_count=3)
        assert metrics.auto_commit_count == 3

    def test_update_accumulates(
        self, store: RegistryStore, sample_registry: ProjectRegistry
    ) -> None:
        store.save(sample_registry)
        store.update_metrics("proj_001", auto_commit_count=2)
        metrics = store.update_metrics("proj_001", auto_commit_count=5)
        assert metrics.auto_commit_count == 7

    def test_update_multiple_fields(
        self, store: RegistryStore, sample_registry: ProjectRegistry
    ) -> None:
        store.save(sample_registry)
        metrics = store.update_metrics(
            "proj_001",
            total_tokens_used=1000,
            human_gate_count=1,
        )
        assert metrics.total_tokens_used == 1000
        assert metrics.human_gate_count == 1

    def test_update_ignores_unknown_fields(
        self, store: RegistryStore, sample_registry: ProjectRegistry
    ) -> None:
        store.save(sample_registry)
        metrics = store.update_metrics("proj_001", nonexistent_field=42)
        assert metrics.auto_commit_count == 0  # unchanged


class TestUpdateWorkQueue:
    def test_update_replaces_queue(
        self, store: RegistryStore, sample_registry: ProjectRegistry
    ) -> None:
        store.save(sample_registry)

        new_queue = WorkQueue(
            current_task=TaskRef(task_id="t001", agent="backend"),
            overall_progress=25,
        )
        store.update_work_queue("proj_001", new_queue)

        loaded = store.load("proj_001")
        assert loaded.work_queue.current_task is not None
        assert loaded.work_queue.current_task.task_id == "t001"
        assert loaded.work_queue.overall_progress == 25
