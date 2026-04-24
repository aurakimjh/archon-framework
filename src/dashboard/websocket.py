"""WebSocket 관리자 — 실시간 대시보드 이벤트 브로드캐스트."""

from __future__ import annotations

import logging
from typing import Any

from src.dashboard.models import DashboardEvent
from src.log import get_logger

logger = logging.getLogger(__name__)
_slog = get_logger(__name__)

try:
    import fastapi as _fastapi  # noqa: F401

    _HAS_FASTAPI = True
except ImportError:
    _HAS_FASTAPI = False


class WebSocketManager:
    """활성 WebSocket 연결을 관리하고 이벤트를 브로드캐스트한다."""

    def __init__(self) -> None:
        self._connections: list[Any] = []

    @property
    def connection_count(self) -> int:
        return len(self._connections)

    async def connect(self, websocket: Any) -> None:
        """새 WebSocket 연결을 등록한다."""
        if _HAS_FASTAPI and hasattr(websocket, "accept"):
            await websocket.accept()
        self._connections.append(websocket)
        _slog.debug("websocket_connected", count=self.connection_count)

    async def disconnect(self, websocket: Any) -> None:
        """WebSocket 연결을 해제한다."""
        if websocket in self._connections:
            self._connections.remove(websocket)
        _slog.debug("websocket_disconnected", count=self.connection_count)

    async def broadcast(self, event: DashboardEvent) -> int:
        """모든 연결에 이벤트를 브로드캐스트한다.

        Returns:
            성공적으로 전송한 연결 수.
        """
        if not self._connections:
            return 0

        data = event.model_dump_json()
        sent = 0
        dead: list[Any] = []

        for ws in self._connections:
            try:
                if hasattr(ws, "send_text"):
                    await ws.send_text(data)
                elif hasattr(ws, "send"):
                    await ws.send(data)
                sent += 1
            except Exception:
                dead.append(ws)

        for ws in dead:
            self._connections.remove(ws)

        return sent

    async def broadcast_dict(self, event_type: str, payload: dict[str, Any]) -> int:
        """딕셔너리로부터 이벤트를 생성하여 브로드캐스트한다."""
        event = DashboardEvent(event_type=event_type, payload=payload)
        return await self.broadcast(event)
