"""UserStore + authenticate 단위 테스트."""

from __future__ import annotations

import pytest

from src.dashboard.users import (
    Role,
    User,
    UserStore,
    auth_required,
    authenticate,
    role_meets,
)


class TestRoleMeets:
    def test_admin_meets_all(self):
        assert role_meets(Role.ADMIN, Role.VIEWER)
        assert role_meets(Role.ADMIN, Role.OPERATOR)
        assert role_meets(Role.ADMIN, Role.ADMIN)

    def test_operator_does_not_meet_admin(self):
        assert role_meets(Role.OPERATOR, Role.VIEWER)
        assert role_meets(Role.OPERATOR, Role.OPERATOR)
        assert not role_meets(Role.OPERATOR, Role.ADMIN)

    def test_viewer_only_meets_viewer(self):
        assert role_meets(Role.VIEWER, Role.VIEWER)
        assert not role_meets(Role.VIEWER, Role.OPERATOR)
        assert not role_meets(Role.VIEWER, Role.ADMIN)


class TestUserStore:
    def test_empty_when_missing(self, tmp_path):
        store = UserStore(tmp_path / "users.yaml")
        assert store.configured is False
        assert store.list_users() == []

    def test_upsert_and_load(self, tmp_path):
        store = UserStore(tmp_path / "users.yaml")
        store.upsert(User(user_id="alice", name="Alice", role=Role.OPERATOR))
        assert store.configured is True
        users = store.list_users()
        assert len(users) == 1
        assert users[0].user_id == "alice"
        assert users[0].role == Role.OPERATOR

    def test_upsert_preserves_tokens(self, tmp_path):
        store = UserStore(tmp_path / "users.yaml")
        store.upsert(User(user_id="alice", name="Alice", role=Role.OPERATOR))
        store.issue_token("alice", label="cli")

        # 동일 user_id로 다시 upsert — 토큰은 보존
        store.upsert(User(user_id="alice", name="Alice (renamed)", role=Role.ADMIN))
        u = store.get("alice")
        assert u.role == Role.ADMIN
        assert u.name == "Alice (renamed)"
        assert len(u.tokens) == 1

    def test_issue_and_revoke_token(self, tmp_path):
        store = UserStore(tmp_path / "users.yaml")
        store.upsert(User(user_id="alice", role=Role.OPERATOR))
        result = store.issue_token("alice", label="laptop")
        assert result is not None
        user, plaintext = result
        assert plaintext  # 비어있지 않은 평문 토큰
        assert len(user.tokens) == 1
        token_id = user.tokens[0].id

        # 평문이 디스크에 평문으로 저장되지 않는지 확인.
        raw = (tmp_path / "users.yaml").read_text(encoding="utf-8")
        assert plaintext not in raw

        # find_by_token 동작
        found = store.find_by_token(plaintext)
        assert found is not None and found.user_id == "alice"

        # revoke
        assert store.revoke_token("alice", token_id) is True
        assert store.find_by_token(plaintext) is None
        assert store.revoke_token("alice", token_id) is False

    def test_delete_user(self, tmp_path):
        store = UserStore(tmp_path / "users.yaml")
        store.upsert(User(user_id="alice", role=Role.VIEWER))
        assert store.delete("alice") is True
        assert store.delete("alice") is False

    def test_invalid_yaml_returns_empty(self, tmp_path):
        path = tmp_path / "users.yaml"
        path.write_text(":::garbage:::", encoding="utf-8")
        store = UserStore(path)
        assert store.list_users() == []


class TestAuthenticate:
    def test_no_config_no_token_returns_anonymous_admin(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.delenv("ARCHON_DASHBOARD_TOKEN", raising=False)
        store = UserStore(tmp_path / "absent.yaml")
        u = authenticate(None, store=store)
        assert u is not None
        assert u.role == Role.ADMIN
        assert u.user_id == "anonymous"
        assert auth_required(store) is False

    def test_legacy_token_mode(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ARCHON_DASHBOARD_TOKEN", "legacy-secret")
        store = UserStore(tmp_path / "absent.yaml")
        # 토큰 없이 → None
        assert authenticate(None, store=store) is None
        # 잘못된 토큰 → None
        assert authenticate("wrong", store=store) is None
        # 정확한 토큰 → admin
        u = authenticate("legacy-secret", store=store)
        assert u is not None
        assert u.role == Role.ADMIN
        assert u.user_id == "_legacy_admin"
        assert auth_required(store) is True

    def test_multi_user_mode(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ARCHON_DASHBOARD_TOKEN", raising=False)
        store = UserStore(tmp_path / "users.yaml")
        store.upsert(User(user_id="bob", role=Role.OPERATOR))
        _, plaintext = store.issue_token("bob", label="ci")  # type: ignore[misc]

        # 토큰 없으면 None
        assert authenticate(None, store=store) is None
        # 잘못된 토큰 None
        assert authenticate("nope", store=store) is None
        # 정확한 토큰 → 해당 사용자
        u = authenticate(plaintext, store=store)
        assert u is not None
        assert u.user_id == "bob"
        assert u.role == Role.OPERATOR
        assert auth_required(store) is True
