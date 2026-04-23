"""Ray 클러스터 관리 — 워커 노드 등록, 헬스체크, 스케일아웃."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

logger = logging.getLogger(__name__)


class WorkerStatus(StrEnum):
    """워커 노드 상태."""

    ONLINE = "online"
    OFFLINE = "offline"
    DEGRADED = "degraded"  # 일부 기능 제한
    DRAINING = "draining"  # 작업 완료 후 종료 예정


class WorkerType(StrEnum):
    """워커 노드 유형."""

    CPU = "cpu"
    GPU = "gpu"
    HYBRID = "hybrid"


@dataclass
class WorkerConfig:
    """워커 노드 설정.

    Attributes:
        worker_id: 고유 워커 식별자.
        address: 워커 노드 주소 (e.g. "192.168.1.10:6379").
        worker_type: 노드 유형 (CPU/GPU/HYBRID).
        gpu_count: 사용 가능한 GPU 수.
        gpu_model: GPU 모델명 (e.g. "RTX 4090").
        cpu_cores: CPU 코어 수.
        memory_gb: 메모리 용량 (GB).
        vllm_port: vLLM 서버 포트 (GPU 노드).
        tags: 라우팅/필터링용 태그.
    """

    worker_id: str
    address: str
    worker_type: WorkerType = WorkerType.CPU
    gpu_count: int = 0
    gpu_model: str = ""
    cpu_cores: int = 4
    memory_gb: float = 16.0
    vllm_port: int | None = None
    tags: list[str] = field(default_factory=list)


@dataclass
class WorkerNode:
    """런타임 워커 노드 상태."""

    config: WorkerConfig
    status: WorkerStatus = WorkerStatus.OFFLINE
    registered_at: datetime = field(default_factory=datetime.utcnow)
    last_heartbeat: datetime | None = None
    current_tasks: int = 0
    total_tasks_completed: int = 0


class ClusterManager:
    """Ray 클러스터 + 워커 노드 관리자.

    워커 노드를 등록/해제하고, 헬스체크를 수행하며,
    GPU 워커에서 실행 중인 vLLM 서버와의 연동을 관리한다.
    """

    def __init__(self, mode: str = "local") -> None:
        self._mode = mode
        self._workers: dict[str, WorkerNode] = {}
        self._initialized = False

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def worker_count(self) -> int:
        return len(self._workers)

    def init_cluster(self) -> None:
        """Ray 클러스터를 초기화한다."""
        import ray

        if self._initialized:
            logger.info("Cluster already initialized")
            return

        if ray.is_initialized():
            logger.info("Ray already initialized")
            self._initialized = True
            return

        match self._mode:
            case "local":
                ray.init(ignore_reinit_error=True)
                logger.info("Ray initialized in local mode")
            case "cluster":
                ray.init(address="auto")
                logger.info("Ray initialized in cluster mode")
            case "kubernetes":
                ray.init(address="ray://head-node:10001")
                logger.info("Ray initialized in kubernetes mode")
            case _:
                raise ValueError(f"Unknown cluster mode: {self._mode}")

        self._initialized = True

    def register_worker(self, config: WorkerConfig) -> WorkerNode:
        """워커 노드를 클러스터에 등록한다."""
        if config.worker_id in self._workers:
            logger.warning(
                "Worker [%s] already registered, updating config",
                config.worker_id,
            )
            existing = self._workers[config.worker_id]
            existing.config = config
            existing.status = WorkerStatus.ONLINE
            existing.last_heartbeat = datetime.utcnow()
            return existing

        node = WorkerNode(
            config=config,
            status=WorkerStatus.ONLINE,
            last_heartbeat=datetime.utcnow(),
        )
        self._workers[config.worker_id] = node
        logger.info(
            "Worker [%s] registered: type=%s, gpu=%d, addr=%s",
            config.worker_id,
            config.worker_type,
            config.gpu_count,
            config.address,
        )
        return node

    def unregister_worker(self, worker_id: str) -> bool:
        """워커 노드를 클러스터에서 제거한다."""
        if worker_id in self._workers:
            del self._workers[worker_id]
            logger.info("Worker [%s] unregistered", worker_id)
            return True
        return False

    def get_worker(self, worker_id: str) -> WorkerNode | None:
        """워커 노드를 조회한다."""
        return self._workers.get(worker_id)

    def list_workers(
        self,
        worker_type: WorkerType | None = None,
        status: WorkerStatus | None = None,
    ) -> list[WorkerNode]:
        """워커 노드 목록을 반환한다.

        worker_type, status로 필터링 가능.
        """
        workers = list(self._workers.values())

        if worker_type:
            workers = [w for w in workers if w.config.worker_type == worker_type]
        if status:
            workers = [w for w in workers if w.status == status]

        return workers

    def get_gpu_workers(self) -> list[WorkerNode]:
        """GPU 워커만 반환한다."""
        return [
            w
            for w in self._workers.values()
            if w.config.worker_type in (WorkerType.GPU, WorkerType.HYBRID)
            and w.config.gpu_count > 0
        ]

    def get_online_workers(self) -> list[WorkerNode]:
        """온라인 워커만 반환한다."""
        return [w for w in self._workers.values() if w.status == WorkerStatus.ONLINE]

    def heartbeat(self, worker_id: str) -> bool:
        """워커 하트비트를 갱신한다."""
        node = self._workers.get(worker_id)
        if not node:
            return False
        node.last_heartbeat = datetime.utcnow()
        if node.status == WorkerStatus.OFFLINE:
            node.status = WorkerStatus.ONLINE
            logger.info("Worker [%s] back online via heartbeat", worker_id)
        return True

    def mark_offline(self, worker_id: str) -> bool:
        """워커를 오프라인으로 전환한다."""
        node = self._workers.get(worker_id)
        if not node:
            return False
        node.status = WorkerStatus.OFFLINE
        logger.warning("Worker [%s] marked offline", worker_id)
        return True

    def drain_worker(self, worker_id: str) -> bool:
        """워커를 드레이닝 상태로 전환한다 (신규 태스크 불가, 기존 완료 후 종료)."""
        node = self._workers.get(worker_id)
        if not node:
            return False
        node.status = WorkerStatus.DRAINING
        logger.info("Worker [%s] set to draining", worker_id)
        return True

    def get_cluster_summary(self) -> dict:
        """클러스터 요약 정보를 반환한다."""
        total = len(self._workers)
        online = sum(1 for w in self._workers.values() if w.status == WorkerStatus.ONLINE)
        gpu_total = sum(w.config.gpu_count for w in self._workers.values())
        gpu_online = sum(
            w.config.gpu_count
            for w in self._workers.values()
            if w.status == WorkerStatus.ONLINE
        )
        total_memory = sum(w.config.memory_gb for w in self._workers.values())

        return {
            "mode": self._mode,
            "initialized": self._initialized,
            "total_workers": total,
            "online_workers": online,
            "gpu_total": gpu_total,
            "gpu_online": gpu_online,
            "total_memory_gb": total_memory,
            "total_tasks_running": sum(w.current_tasks for w in self._workers.values()),
            "total_tasks_completed": sum(
                w.total_tasks_completed for w in self._workers.values()
            ),
        }


# --- 하위 호환: 기존 init_cluster 함수 유지 ---


def init_cluster(mode: str = "local") -> None:
    """Ray 클러스터를 초기화한다 (하위 호환 함수).

    Args:
        mode: "local" (Phase 1), "cluster" (Phase 2), "kubernetes" (Phase 3)
    """
    manager = ClusterManager(mode=mode)
    manager.init_cluster()
