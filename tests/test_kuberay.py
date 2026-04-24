"""KubeRay 모듈 테스트 — 설정, 매니페스트 생성, 클러스터 관리."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.runtime.kuberay import (
    AutoScaleConfig,
    ClusterStatus,
    KubeRayConfig,
    KubeRayManager,
    WorkerGroupConfig,
)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class TestWorkerGroupConfig:
    def test_defaults(self):
        wg = WorkerGroupConfig(name="cpu")
        assert wg.replicas == 1
        assert wg.gpu_count == 0
        assert wg.max_replicas == 10

    def test_gpu_worker(self):
        wg = WorkerGroupConfig(name="gpu", gpu_count=2, gpu_type="A100")
        assert wg.gpu_count == 2
        assert wg.gpu_type == "A100"


class TestAutoScaleConfig:
    def test_defaults(self):
        asc = AutoScaleConfig()
        assert asc.enabled is True
        assert asc.idle_timeout_seconds == 300
        assert asc.target_utilization == 0.7


class TestKubeRayConfig:
    def test_defaults(self):
        cfg = KubeRayConfig()
        assert cfg.namespace == "archon"
        assert cfg.cluster_name == "archon-ray"
        assert cfg.worker_groups == []
        assert cfg.autoscaling.enabled is True

    def test_with_workers(self):
        cfg = KubeRayConfig(
            worker_groups=[
                WorkerGroupConfig(name="cpu", replicas=2),
                WorkerGroupConfig(name="gpu", replicas=1, gpu_count=1),
            ]
        )
        assert len(cfg.worker_groups) == 2

    def test_custom_labels(self):
        cfg = KubeRayConfig(labels={"env": "prod"})
        assert cfg.labels["env"] == "prod"


# ---------------------------------------------------------------------------
# Manifest Generation
# ---------------------------------------------------------------------------


class TestManifestGeneration:
    def test_basic_manifest(self):
        cfg = KubeRayConfig()
        mgr = KubeRayManager(cfg)
        manifest = mgr.generate_manifests()
        assert manifest["apiVersion"] == "ray.io/v1"
        assert manifest["kind"] == "RayCluster"
        assert manifest["metadata"]["name"] == "archon-ray"
        assert manifest["metadata"]["namespace"] == "archon"

    def test_manifest_with_cpu_workers(self):
        cfg = KubeRayConfig(
            worker_groups=[WorkerGroupConfig(name="cpu", replicas=3, cpu=8, memory_gb=16)]
        )
        mgr = KubeRayManager(cfg)
        manifest = mgr.generate_manifests()
        workers = manifest["spec"]["workerGroupSpecs"]
        assert len(workers) == 1
        assert workers[0]["groupName"] == "cpu"
        assert workers[0]["replicas"] == 3

    def test_manifest_with_gpu_workers(self):
        cfg = KubeRayConfig(
            worker_groups=[WorkerGroupConfig(name="gpu", gpu_count=2)]
        )
        mgr = KubeRayManager(cfg)
        manifest = mgr.generate_manifests()
        workers = manifest["spec"]["workerGroupSpecs"]
        container = workers[0]["template"]["spec"]["containers"][0]
        assert "nvidia.com/gpu" in container["resources"]["requests"]

    def test_head_resources(self):
        cfg = KubeRayConfig(head_cpu=8, head_memory_gb=16)
        mgr = KubeRayManager(cfg)
        manifest = mgr.generate_manifests()
        head = manifest["spec"]["headGroupSpec"]["template"]["spec"]["containers"][0]
        assert head["resources"]["limits"]["cpu"] == "8"
        assert head["resources"]["limits"]["memory"] == "16Gi"


# ---------------------------------------------------------------------------
# KubeRayManager
# ---------------------------------------------------------------------------


class TestKubeRayManager:
    def test_initial_status(self):
        mgr = KubeRayManager(KubeRayConfig())
        assert mgr.status == ClusterStatus.UNKNOWN

    @pytest.mark.asyncio
    async def test_deploy_without_client(self):
        mgr = KubeRayManager(KubeRayConfig())
        result = await mgr.deploy_cluster()
        assert result["status"] == "created"
        assert mgr.status == ClusterStatus.RUNNING

    @pytest.mark.asyncio
    async def test_deploy_with_client_success(self):
        client = AsyncMock()
        client.post.return_value = MagicMock(status_code=201, text="ok")
        mgr = KubeRayManager(KubeRayConfig(), http_client=client)
        result = await mgr.deploy_cluster()
        assert result["status"] == "created"
        assert mgr.status == ClusterStatus.RUNNING

    @pytest.mark.asyncio
    async def test_deploy_with_client_failure(self):
        client = AsyncMock()
        client.post.return_value = MagicMock(status_code=500, text="error")
        mgr = KubeRayManager(KubeRayConfig(), http_client=client)
        result = await mgr.deploy_cluster()
        assert result["status"] == "failed"
        assert mgr.status == ClusterStatus.FAILED

    @pytest.mark.asyncio
    async def test_scale_workers(self):
        cfg = KubeRayConfig(
            worker_groups=[WorkerGroupConfig(name="cpu", replicas=1, max_replicas=5)]
        )
        mgr = KubeRayManager(cfg)
        result = await mgr.scale_workers("cpu", 3)
        assert result is True
        assert cfg.worker_groups[0].replicas == 3

    @pytest.mark.asyncio
    async def test_scale_clamps_to_bounds(self):
        cfg = KubeRayConfig(
            worker_groups=[WorkerGroupConfig(name="cpu", min_replicas=1, max_replicas=5)]
        )
        mgr = KubeRayManager(cfg)
        await mgr.scale_workers("cpu", 10)
        assert cfg.worker_groups[0].replicas == 5
        await mgr.scale_workers("cpu", 0)
        assert cfg.worker_groups[0].replicas == 1

    @pytest.mark.asyncio
    async def test_scale_unknown_group(self):
        mgr = KubeRayManager(KubeRayConfig())
        result = await mgr.scale_workers("unknown", 3)
        assert result is False

    @pytest.mark.asyncio
    async def test_get_cluster_status(self):
        cfg = KubeRayConfig(
            worker_groups=[WorkerGroupConfig(name="cpu", replicas=2)]
        )
        mgr = KubeRayManager(cfg)
        status = await mgr.get_cluster_status()
        assert status["cluster_name"] == "archon-ray"
        assert len(status["worker_groups"]) == 1

    @pytest.mark.asyncio
    async def test_delete_without_client(self):
        mgr = KubeRayManager(KubeRayConfig())
        result = await mgr.delete_cluster()
        assert result is True
        assert mgr.status == ClusterStatus.DELETED

    @pytest.mark.asyncio
    async def test_delete_with_client(self):
        client = AsyncMock()
        client.delete.return_value = MagicMock(status_code=200)
        mgr = KubeRayManager(KubeRayConfig(), http_client=client)
        result = await mgr.delete_cluster()
        assert result is True
