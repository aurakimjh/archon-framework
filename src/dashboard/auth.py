"""Dashboard 인증 — 토큰 기반 Bearer / WebSocket 쿼리 파라미터 인증.

ARCHON_DASHBOARD_TOKEN 환경변수가 설정되면 인증을 강제한다.
미설정 시 모든 요청을 허용한다 (내부망 사용 전제).
"""

from __future__ import annotations

import hmac
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


def get_dashboard_token() -> str | None:
    """환경변수에서 대시보드 인증 토큰을 가져온다. 미설정이면 None."""
    return os.environ.get("ARCHON_DASHBOARD_TOKEN") or None


def verify_token(provided: str | None, expected: str | None) -> bool:
    """토큰을 검증한다.

    - expected가 None이면 인증 비활성 → 항상 True.
    - provided가 None이거나 불일치 → False.
    """
    if expected is None:
        return True
    if provided is None:
        return False
    return hmac.compare_digest(provided, expected)


def extract_bearer_token(authorization: str | None) -> str | None:
    """Authorization 헤더에서 Bearer 토큰을 추출한다."""
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return None


def extract_ws_token(query_string: str | None = None, params: dict[str, Any] | None = None) -> str | None:
    """WebSocket 연결의 쿼리 파라미터에서 토큰을 추출한다.

    Args:
        query_string: raw query string (e.g. "token=abc&foo=bar")
        params: 파싱된 쿼리 파라미터 딕셔너리
    """
    if params and "token" in params:
        val = params["token"]
        return val[0] if isinstance(val, list) else val

    if query_string:
        for pair in query_string.split("&"):
            if "=" in pair:
                key, _, value = pair.partition("=")
                if key.strip() == "token":
                    return value.strip()

    return None
