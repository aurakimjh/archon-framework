"""ClusterManager 테스트 — 워커 등록, 헬스체크, 상태 관리."""

from __future__ import annotations

import importlib

import pytest

from src.runtime.cluster import (
    ClusterManager,
    WorkerConfig,
    WorkerNode,
    WorkerStatus,
    WorkerType,
)


def _has_ray() -> bool:
    return importlib.util.find_spec("ray") is not None


def _make_config(
    worker_id: str = "w1",
    worker_type: WorkerType = WorkerType.CPU,
    gpu_count: int = 0,
    gpu_model: str = "",
    memory_gb: float = 16.0,
) -> WorkerConfig:
    return WorkerConfig(
        worker_id=worker_id,
        address=f"192.168.1.{hash(worker_id) % 255}:6379",
        worker_type=worker_type,
        gpu_count=gpu_count,
        gpu_model=gpu_model,
        memory_gb=memory_gb,
    )


class TestWorkerConfig:
    def test_create_cpu_worker(self):
        cfg = _make_config()
        assert cfg.worker_type == WorkerType.CPU
        assert cfg.gpu_count == 0
        assert cfg.vllm_port is None

    def test_create_gpu_worker(self):
        cfg = _make_config(
            worker_type=WorkerType.GPU,
            gpu_count=2,
            gpu_model="RTX 4090",
        )
        assert cfg.gpu_count == 2
        assert cfg.gpu_model == "RTX 4090"


class TestClusterManager:
    def test_init(self):
        mgr = ClusterManager(mode="local")
        assert mgr.mode == "local"
        assert mgr.worker_count == 0

    def test_register_worker(self):
        mgr = ClusterManager()
        cfg = _make_config("w1")
        node = mgr.register_worker(cfg)
        assert isinstance(node, WorkerNode)
        assert node.status == WorkerStatus.ONLINE
        assert mgr.worker_count == 1

    def test_register_duplicate_updates(self):
        mgr = ClusterManager()
        cfg1 = _make_config("w1", memory_gb=16.0)
        mgr.register_worker(cfg1)

        cfg2 = _make_config("w1", memory_gb=32.0)
        node = mgr.register_worker(cfg2)
        assert node.config.memory_gb == 32.0
        assert mgr.worker_count == 1  # 중복 등록 안 됨

    def test_unregister_worker(self):
        mgr = ClusterManager()
        mgr.register_worker(_make_config("w1"))
        assert mgr.unregister_worker("w1") is True
        assert mgr.worker_count == 0

    def test_unregister_nonexistent(self):
        mgr = ClusterManager()
        assert mgr.unregister_worker("no-such") is False

    def test_get_worker(self):
        mgr = ClusterManager()
        mgr.register_worker(_make_config("w1"))
        node = mgr.get_worker("w1")
        assert node is not None
        assert node.config.worker_id == "w1"

    def test_get_worker_not_found(self):
        mgr = ClusterManager()
        assert mgr.get_worker("no-such") is None

    def test_list_workers(self):
        mgr = ClusterManager()
        mgr.register_worker(_make_config("w1", worker_type=WorkerType.CPU))
        mgr.register_worker(_make_config("w2", worker_type=WorkerType.GPU, gpu_count=1))
        mgr.register_worker(_make_config("w3", worker_type=WorkerType.GPU, gpu_count=2))

        all_workers = mgr.list_workers()
        assert len(all_workers) == 3

        gpu_only = mgr.list_workers(worker_type=WorkerType.GPU)
        assert len(gpu_only) == 2

    def test_list_workers_by_status(self):
        mgr = ClusterManager()
        mgr.register_worker(_make_config("w1"))
        mgr.register_worker(_make_config("w2"))
        mgr.mark_offline("w2")

        online = mgr.list_workers(status=WorkerStatus.ONLINE)
        assert len(online) == 1
        assert online[0].config.worker_id == "w1"

    def test_get_gpu_workers(self):
        mgr = ClusterManager()
        mgr.register_worker(_make_config("cpu1", worker_type=WorkerType.CPU))
        mgr.register_worker(
            _make_config("gpu1", worker_type=WorkerType.GPU, gpu_count=2)
        )
        mgr.register_worker(
            _make_config("hybrid1", worker_type=WorkerType.HYBRID, gpu_count=1)
        )

        gpu = mgr.get_gpu_workers()
        assert len(gpu) == 2

    def test_get_online_workers(self):
        mgr = ClusterManager()
        mgr.register_worker(_make_config("w1"))
        mgr.register_worker(_make_config("w2"))
        mgr.mark_offline("w1")

        online = mgr.get_online_workers()
        assert len(online) == 1

    def test_heartbeat(self):
        mgr = ClusterManager()
        mgr.register_worker(_make_config("w1"))
        mgr.mark_offline("w1")
        assert mgr.get_worker("w1").status == WorkerStatus.OFFLINE

        # 하트비트로 복구
        assert mgr.heartbeat("w1") is True
        assert mgr.get_worker("w1").status == WorkerStatus.ONLINE

    def test_heartbeat_nonexistent(self):
        mgr = ClusterManager()
        assert mgr.heartbeat("no-such") is False

    def test_mark_offline(self):
        mgr = ClusterManager()
        mgr.register_worker(_make_config("w1"))
        assert mgr.mark_offline("w1") is True
        assert mgr.get_worker("w1").status == WorkerStatus.OFFLINE

    def test_mark_offline_nonexistent(self):
        mgr = ClusterManager()
        assert mgr.mark_offline("no-such") is False

    def test_drain_worker(self):
        mgr = ClusterManager()
        mgr.register_worker(_make_config("w1"))
        assert mgr.drain_worker("w1") is True
        assert mgr.get_worker("w1").status == WorkerStatus.DRAINING

    def test_drain_nonexistent(self):
        mgr = ClusterManager()
        assert mgr.drain_worker("no-such") is False

    def test_cluster_summary(self):
        mgr = ClusterManager(mode="cluster")
        mgr.register_worker(_make_config("cpu1", memory_gb=16.0))
        mgr.register_worker(
            _make_config("gpu1", worker_type=WorkerType.GPU, gpu_count=2, memory_gb=64.0)
        )
        mgr.mark_offline("cpu1")

        summary = mgr.get_cluster_summary()
        assert summary["mode"] == "cluster"
        assert summary["total_workers"] == 2
        assert summary["online_workers"] == 1
        assert summary["gpu_total"] == 2
        assert summary["gpu_online"] == 2
        assert summary["total_memory_gb"] == 80.0

    def test_cluster_summary_empty(self):
        mgr = ClusterManager()
        summary = mgr.get_cluster_summary()
        assert summary["total_workers"] == 0
        assert summary["online_workers"] == 0

    @pytest.mark.skipif(
        not _has_ray(),
        reason="ray not installed",
    )
    def test_invalid_mode(self):
        mgr = ClusterManager(mode="invalid")
        with pytest.raises(ValueError, match="Unknown cluster mode"):
            mgr.init_cluster()
