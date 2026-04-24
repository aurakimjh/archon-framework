"""KubeRay 통합 — Kubernetes 기반 Ray 클러스터 관리."""

from __future__ import annotations

import logging
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from src.log import get_logger

logger = logging.getLogger(__name__)
_slog = get_logger(__name__)


class WorkerGroupConfig(BaseModel):
    """워커 그룹 설정."""

    name: str
    replicas: int = 1
    min_replicas: int = 0
    max_replicas: int = 10
    cpu: int = 4
    memory_gb: int = 8
    gpu_count: int = 0
    gpu_type: str = ""
    image: str = "rayproject/ray:2.30.0"
    tolerations: list[str] = Field(default_factory=list)
    node_selector: dict[str, str] = Field(default_factory=dict)


class AutoScaleConfig(BaseModel):
    """오토스케일링 설정."""

    enabled: bool = True
    idle_timeout_seconds: int = 300
    upscaling_mode: str = "Default"
    target_utilization: float = Field(default=0.7, ge=0.0, le=1.0)


class KubeRayConfig(BaseModel):
    """KubeRay 클러스터 설정."""

    namespace: str = "archon"
    cluster_name: str = "archon-ray"
    ray_version: str = "2.30.0"
    image: str = "rayproject/ray:2.30.0"
    head_cpu: int = 4
    head_memory_gb: int = 8
    worker_groups: list[WorkerGroupConfig] = Field(default_factory=list)
    autoscaling: AutoScaleConfig = Field(default_factory=AutoScaleConfig)
    labels: dict[str, str] = Field(default_factory=lambda: {"app": "archon"})


class ClusterStatus(StrEnum):
    """클러스터 상태."""

    UNKNOWN = "unknown"
    CREATING = "creating"
    RUNNING = "running"
    SCALING = "scaling"
    FAILED = "failed"
    DELETED = "deleted"


class KubeRayManager:
    """KubeRay 클러스터 라이프사이클을 관리한다.

    실제 k8s API 호출은 httpx로 수행하며,
    테스트 시 http_client를 모킹할 수 있다.
    """

    def __init__(
        self,
        config: KubeRayConfig,
        http_client: Any = None,
        api_server: str = "https://kubernetes.default.svc",
    ) -> None:
        self._config = config
        self._http_client = http_client
        self._api_server = api_server.rstrip("/")
        self._status = ClusterStatus.UNKNOWN

    @property
    def config(self) -> KubeRayConfig:
        return self._config

    @property
    def status(self) -> ClusterStatus:
        return self._status

    def generate_manifests(self) -> dict[str, Any]:
        """RayCluster CRD 매니페스트를 생성한다."""
        cfg = self._config
        worker_specs = []
        for wg in cfg.worker_groups:
            resources = {
                "requests": {"cpu": str(wg.cpu), "memory": f"{wg.memory_gb}Gi"},
                "limits": {"cpu": str(wg.cpu), "memory": f"{wg.memory_gb}Gi"},
            }
            if wg.gpu_count > 0:
                resources["requests"]["nvidia.com/gpu"] = str(wg.gpu_count)
                resources["limits"]["nvidia.com/gpu"] = str(wg.gpu_count)

            worker_specs.append({
                "groupName": wg.name,
                "replicas": wg.replicas,
                "minReplicas": wg.min_replicas,
                "maxReplicas": wg.max_replicas,
                "rayStartParams": {
                    "num-cpus": str(wg.cpu),
                    **({"num-gpus": str(wg.gpu_count)} if wg.gpu_count > 0 else {}),
                },
                "template": {
                    "spec": {
                        "containers": [{
                            "name": "ray-worker",
                            "image": wg.image,
                            "resources": resources,
                        }],
                    },
                },
            })

        return {
            "apiVersion": "ray.io/v1",
            "kind": "RayCluster",
            "metadata": {
                "name": cfg.cluster_name,
                "namespace": cfg.namespace,
                "labels": cfg.labels,
            },
            "spec": {
                "rayVersion": cfg.ray_version,
                "headGroupSpec": {
                    "rayStartParams": {"dashboard-host": "0.0.0.0", "num-cpus": "0"},
                    "template": {
                        "spec": {
                            "containers": [{
                                "name": "ray-head",
                                "image": cfg.image,
                                "resources": {
                                    "requests": {
                                        "cpu": str(cfg.head_cpu // 2),
                                        "memory": f"{cfg.head_memory_gb // 2}Gi",
                                    },
                                    "limits": {
                                        "cpu": str(cfg.head_cpu),
                                        "memory": f"{cfg.head_memory_gb}Gi",
                                    },
                                },
                            }],
                        },
                    },
                },
                "workerGroupSpecs": worker_specs,
            },
        }

    async def deploy_cluster(self) -> dict[str, Any]:
        """클러스터를 배포한다."""
        manifest = self.generate_manifests()
        self._status = ClusterStatus.CREATING

        if self._http_client:
            url = (
                f"{self._api_server}/apis/ray.io/v1/namespaces/"
                f"{self._config.namespace}/rayclusters"
            )
            response = await self._http_client.post(url, json=manifest)
            if response.status_code in (200, 201):
                self._status = ClusterStatus.RUNNING
                _slog.info("kuberay_deployed", cluster=self._config.cluster_name)
                return {"status": "created", "cluster": self._config.cluster_name}
            self._status = ClusterStatus.FAILED
            return {"status": "failed", "error": response.text}

        self._status = ClusterStatus.RUNNING
        return {"status": "created", "cluster": self._config.cluster_name}

    async def scale_workers(self, group_name: str, replicas: int) -> bool:
        """워커 그룹을 스케일한다."""
        for wg in self._config.worker_groups:
            if wg.name == group_name:
                replicas = max(wg.min_replicas, min(wg.max_replicas, replicas))
                wg.replicas = replicas
                self._status = ClusterStatus.SCALING
                _slog.info(
                    "kuberay_scaling",
                    group=group_name,
                    replicas=replicas,
                )

                if self._http_client:
                    url = (
                        f"{self._api_server}/apis/ray.io/v1/namespaces/"
                        f"{self._config.namespace}/rayclusters/{self._config.cluster_name}"
                    )
                    patch = {"spec": {"workerGroupSpecs": [
                        {"groupName": group_name, "replicas": replicas}
                    ]}}
                    await self._http_client.patch(url, json=patch)

                self._status = ClusterStatus.RUNNING
                return True
        return False

    async def get_cluster_status(self) -> dict[str, Any]:
        """클러스터 상태를 조회한다."""
        return {
            "cluster_name": self._config.cluster_name,
            "namespace": self._config.namespace,
            "status": str(self._status),
            "worker_groups": [
                {
                    "name": wg.name,
                    "replicas": wg.replicas,
                    "min": wg.min_replicas,
                    "max": wg.max_replicas,
                    "gpu_count": wg.gpu_count,
                }
                for wg in self._config.worker_groups
            ],
            "autoscaling": self._config.autoscaling.enabled,
        }

    async def delete_cluster(self) -> bool:
        """클러스터를 삭제한다."""
        if self._http_client:
            url = (
                f"{self._api_server}/apis/ray.io/v1/namespaces/"
                f"{self._config.namespace}/rayclusters/{self._config.cluster_name}"
            )
            response = await self._http_client.delete(url)
            if response.status_code not in (200, 204):
                return False

        self._status = ClusterStatus.DELETED
        _slog.info("kuberay_deleted", cluster=self._config.cluster_name)
        return True
