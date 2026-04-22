"""Ray 클러스터 초기화 — Phase별 스케일아웃."""

from __future__ import annotations

import logging

import ray

logger = logging.getLogger(__name__)


def init_cluster(mode: str = "local") -> None:
    """Ray 클러스터를 초기화한다.

    Args:
        mode: "local" (Phase 1), "cluster" (Phase 2), "kubernetes" (Phase 3)
    """
    if ray.is_initialized():
        logger.info("Ray already initialized")
        return

    match mode:
        case "local":
            # Phase 1: MacBook 단독
            ray.init()
            logger.info("Ray initialized in local mode")
        case "cluster":
            # Phase 2: 멀티 노드
            ray.init(address="auto")
            logger.info("Ray initialized in cluster mode")
        case "kubernetes":
            # Phase 3: KubeRay
            ray.init(address="ray://head-node:10001")
            logger.info("Ray initialized in kubernetes mode")
        case _:
            raise ValueError(f"Unknown cluster mode: {mode}")
