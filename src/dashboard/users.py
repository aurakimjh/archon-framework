"""사용자·역할·토큰 디렉토리 — YAML 백드 단순 RBAC.

3단계 권한:
- admin     : 전체 관리, 사용자/토큰/예산/설정 변경
- operator  : 작업 실행·취소, Gate 결정
- viewer    : 읽기 전용

토큰 저장은 해시(sha256)만 기록한다. 평문은 발급 직후 1회만 반환.

하위호환: users.yaml 이 없으면
- ARCHON_DASHBOARD_TOKEN이 있으면: 그 토큰을 사용하는 단일 admin 사용자처럼 작동.
- 둘 다 없으면: 인증 비활성(개발/내부망 가정).
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import tempfile
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, ValidationError

logger = logging.getLogger(__name__)

_DEFAULT_PATH = "config/users.yaml"
_TOKEN_BYTES = 24
SCHEMA_VERSION = "1.0.0"


class Role(StrEnum):
    ADMIN = "admin"
    OPERATOR = "operator"
    VIEWER = "viewer"


_ROLE_RANK = {Role.VIEWER: 0, Role.OPERATOR: 1, Role.ADMIN: 2}


def role_meets(actual: Role, required: Role) -> bool:
    """`actual` 역할이 `required` 이상의 권한인가."""
    return _ROLE_RANK[actual] >= _ROLE_RANK[required]


class TokenEntry(BaseModel):
    id: str
    label: str = ""
    hash: str
    created_at: str
    last_used_at: str | None = None


class User(BaseModel):
    user_id: str
    name: str = ""
    role: Role = Role.VIEWER
    tokens: list[TokenEntry] = Field(default_factory=list)


class UserDirectory(BaseModel):
    schema_version: str = SCHEMA_VERSION
    users: dict[str, User] = Field(default_factory=dict)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def get_users_path() -> Path:
    return Path(os.environ.get("ARCHON_USERS_PATH", _DEFAULT_PATH))


class UserStore:
    """파일 기반 사용자 디렉토리 — atomic write."""

    def __init__(self, path: str | Path | None = None) -> None:
        self._path = Path(path) if path else get_users_path()

    @property
    def path(self) -> Path:
        return self._path

    @property
    def configured(self) -> bool:
        """users.yaml 파일이 존재하는가 (multi-user 모드 활성 여부)."""
        return self._path.exists()

    # --- 직렬화 ---

    def load(self) -> UserDirectory:
        if not self._path.exists():
            return UserDirectory()
        try:
            data = yaml.safe_load(self._path.read_text(encoding="utf-8")) or {}
            return UserDirectory.model_validate(data)
        except (yaml.YAMLError, ValidationError) as e:
            logger.warning("users.yaml invalid (%s): falling back to empty", e)
            return UserDirectory()

    def save(self, directory: UserDirectory) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = directory.model_dump(mode="json")
        text = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=self._path.parent,
            prefix=f".{self._path.name}.",
            suffix=".tmp",
            delete=False,
        ) as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
            tmp = Path(f.name)
        os.replace(tmp, self._path)

    # --- 사용자 CRUD ---

    def list_users(self) -> list[User]:
        return list(self.load().users.values())

    def get(self, user_id: str) -> User | None:
        return self.load().users.get(user_id)

    def upsert(self, user: User) -> User:
        d = self.load()
        existing = d.users.get(user.user_id)
        if existing:
            # 기존 토큰을 보존(메타만 갱신).
            user = User(
                user_id=user.user_id,
                name=user.name,
                role=user.role,
                tokens=existing.tokens,
            )
        d.users[user.user_id] = user
        self.save(d)
        return user

    def delete(self, user_id: str) -> bool:
        d = self.load()
        if user_id not in d.users:
            return False
        del d.users[user_id]
        self.save(d)
        return True

    # --- 토큰 ---

    def issue_token(
        self, user_id: str, label: str = ""
    ) -> tuple[User, str] | None:
        """새 토큰을 발급하고 (사용자, 평문토큰)을 반환한다. 평문은 이 호출 시 1회만 노출."""
        d = self.load()
        user = d.users.get(user_id)
        if user is None:
            return None
        plaintext = secrets.token_urlsafe(_TOKEN_BYTES)
        entry = TokenEntry(
            id=uuid.uuid4().hex[:12],
            label=label,
            hash=_hash_token(plaintext),
            created_at=_now_iso(),
        )
        user.tokens.append(entry)
        d.users[user_id] = user
        self.save(d)
        return user, plaintext

    def revoke_token(self, user_id: str, token_id: str) -> bool:
        d = self.load()
        user = d.users.get(user_id)
        if user is None:
            return False
        before = len(user.tokens)
        user.tokens = [t for t in user.tokens if t.id != token_id]
        if len(user.tokens) == before:
            return False
        d.users[user_id] = user
        self.save(d)
        return True

    def find_by_token(self, token: str) -> User | None:
        if not token:
            return None
        h = _hash_token(token)
        d = self.load()
        for user in d.users.values():
            for entry in user.tokens:
                if hmac.compare_digest(entry.hash, h):
                    return user
        return None


# ---------------------------------------------------------------------------
# 인증 단일 진입점 — 단일 토큰 모드 + multi-user 모드 통합
# ---------------------------------------------------------------------------


_LEGACY_USER_ID = "_legacy_admin"


def authenticate(token: str | None, store: UserStore | None = None) -> User | None:
    """토큰을 검사하여 User 컨텍스트를 반환하거나 None."""
    store = store or UserStore()
    legacy_token = os.environ.get("ARCHON_DASHBOARD_TOKEN") or None

    # 1) multi-user 모드(users.yaml 존재)
    if store.configured:
        if not token:
            return None
        return store.find_by_token(token)

    # 2) 단일 토큰 모드 — env 토큰만 인정, admin 권한.
    if legacy_token:
        if not token:
            return None
        if not hmac.compare_digest(token, legacy_token):
            return None
        return User(user_id=_LEGACY_USER_ID, name="legacy admin", role=Role.ADMIN)

    # 3) 인증 비활성 — 임시 admin 컨텍스트 (요청 메타 기록은 가능).
    return User(user_id="anonymous", name="anonymous", role=Role.ADMIN)


def auth_required(store: UserStore | None = None) -> bool:
    """인증을 요구하는 모드인지(=토큰 없으면 거부할지)."""
    store = store or UserStore()
    if store.configured:
        return True
    return bool(os.environ.get("ARCHON_DASHBOARD_TOKEN"))
