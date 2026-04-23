"""ChromaDB L2 벡터 스토어 — 프로젝트별 핸드오프 기록 벡터 검색."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_SIMILARITY_THRESHOLD = 0.85


class VectorStore:
    """ChromaDB 기반 L2 중기 메모리.

    프로젝트별 컬렉션을 격리하고, 핸드오프 기록을 벡터로 저장/검색한다.
    chromadb.Client 또는 chromadb.PersistentClient를 주입받는다.
    """

    def __init__(
        self,
        chroma_client: Any,
        collection_prefix: str = "archon",
    ) -> None:
        """
        Args:
            chroma_client: chromadb.Client 인스턴스.
            collection_prefix: 컬렉션 이름 접두사.
        """
        self._client = chroma_client
        self._prefix = collection_prefix

    def _collection_name(self, project_id: str) -> str:
        return f"{self._prefix}_{project_id}"

    def _get_or_create_collection(self, project_id: str) -> Any:
        return self._client.get_or_create_collection(
            name=self._collection_name(project_id),
            metadata={"hnsw:space": "cosine"},
        )

    def store_handoff(
        self,
        project_id: str,
        handoff_id: str,
        summary: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """핸드오프 요약을 벡터로 저장."""
        collection = self._get_or_create_collection(project_id)
        meta = metadata or {}
        # ChromaDB metadata는 str/int/float/bool만 허용, 빈 dict 금지
        safe_meta = {
            k: v for k, v in meta.items() if isinstance(v, (str, int, float, bool))
        }
        upsert_kwargs: dict[str, Any] = {
            "ids": [handoff_id],
            "documents": [summary],
        }
        if safe_meta:
            upsert_kwargs["metadatas"] = [safe_meta]
        collection.upsert(**upsert_kwargs)

    def search(
        self,
        project_id: str,
        query: str,
        n_results: int = 5,
        threshold: float = _SIMILARITY_THRESHOLD,
    ) -> list[dict[str, Any]]:
        """유사 핸드오프 검색. cosine similarity > threshold만 반환.

        Returns:
            각 결과: {"id": str, "document": str, "metadata": dict, "distance": float}
        """
        collection = self._get_or_create_collection(project_id)

        if collection.count() == 0:
            return []

        results = collection.query(
            query_texts=[query],
            n_results=min(n_results, collection.count()),
        )

        matched: list[dict[str, Any]] = []
        ids = results.get("ids", [[]])[0]
        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        for i, doc_id in enumerate(ids):
            # ChromaDB cosine distance: 0 = identical, 2 = opposite
            # similarity = 1 - distance
            distance = distances[i] if i < len(distances) else 1.0
            similarity = 1.0 - distance
            if similarity >= threshold:
                matched.append({
                    "id": doc_id,
                    "document": documents[i] if i < len(documents) else "",
                    "metadata": metadatas[i] if i < len(metadatas) else {},
                    "similarity": round(similarity, 4),
                })

        return matched

    def delete_handoff(self, project_id: str, handoff_id: str) -> None:
        """특정 핸드오프 기록 삭제."""
        collection = self._get_or_create_collection(project_id)
        collection.delete(ids=[handoff_id])

    def delete_project(self, project_id: str) -> None:
        """프로젝트 컬렉션 전체 삭제."""
        name = self._collection_name(project_id)
        try:
            self._client.delete_collection(name=name)
        except Exception:
            logger.debug("Collection %s does not exist, skip delete", name)

    def count(self, project_id: str) -> int:
        """프로젝트 내 저장된 핸드오프 수."""
        collection = self._get_or_create_collection(project_id)
        return collection.count()
