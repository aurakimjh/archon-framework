"""MemoryPolicy / MemoryAccessController 테스트."""

from __future__ import annotations

import pytest

from src.memory.policy import (
    MemoryAccessController,
    MemoryPolicy,
    MemorySharingMode,
)


class TestMemoryAccessController:
    # --- 자기 자신은 항상 허용 ---

    def test_self_access_always_allowed(self):
        policy = MemoryPolicy(sharing_mode=MemorySharingMode.ISOLATED)
        ctrl = MemoryAccessController("proj-a", policy)
        decision = ctrl.check_read("proj-a")
        assert decision.allowed
        assert decision.reason == "same project"

    # --- ISOLATED 모드 ---

    def test_isolated_blocks_other_read(self):
        policy = MemoryPolicy(sharing_mode=MemorySharingMode.ISOLATED)
        ctrl = MemoryAccessController("proj-a", policy)
        decision = ctrl.check_read("proj-b")
        assert not decision.allowed

    def test_isolated_blocks_other_write(self):
        policy = MemoryPolicy(sharing_mode=MemorySharingMode.ISOLATED)
        ctrl = MemoryAccessController("proj-a", policy)
        decision = ctrl.check_write("proj-b")
        assert not decision.allowed

    # --- SHARED_READ 모드 ---

    def test_shared_read_allows_read(self):
        policy = MemoryPolicy(sharing_mode=MemorySharingMode.SHARED_READ)
        ctrl = MemoryAccessController("proj-a", policy)
        assert ctrl.check_read("proj-b").allowed

    def test_shared_read_blocks_write(self):
        policy = MemoryPolicy(sharing_mode=MemorySharingMode.SHARED_READ)
        ctrl = MemoryAccessController("proj-a", policy)
        assert not ctrl.check_write("proj-b").allowed

    def test_shared_read_whitelist_allows(self):
        policy = MemoryPolicy(
            sharing_mode=MemorySharingMode.SHARED_READ,
            allowed_read_projects=["proj-b"],
        )
        ctrl = MemoryAccessController("proj-a", policy)
        assert ctrl.check_read("proj-b").allowed
        assert not ctrl.check_read("proj-c").allowed

    # --- FULL_SHARED 모드 ---

    def test_full_shared_allows_read_and_write(self):
        policy = MemoryPolicy(sharing_mode=MemorySharingMode.FULL_SHARED)
        ctrl = MemoryAccessController("proj-a", policy)
        assert ctrl.check_read("proj-b").allowed
        assert ctrl.check_write("proj-b").allowed

    def test_full_shared_write_whitelist(self):
        policy = MemoryPolicy(
            sharing_mode=MemorySharingMode.FULL_SHARED,
            allowed_write_projects=["proj-b"],
        )
        ctrl = MemoryAccessController("proj-a", policy)
        assert ctrl.check_write("proj-b").allowed
        assert not ctrl.check_write("proj-c").allowed

    # --- 민감 프로젝트 자동 격리 ---

    def test_sensitive_tag_forces_isolation(self):
        policy = MemoryPolicy(
            sharing_mode=MemorySharingMode.FULL_SHARED,
            sensitive_tags=["hipaa"],
        )
        ctrl = MemoryAccessController("proj-medical", policy, project_tags=["hipaa"])
        assert not ctrl.check_read("proj-other").allowed
        assert ctrl.is_self_sensitive()

    def test_no_sensitive_tag_not_isolated(self):
        policy = MemoryPolicy(
            sharing_mode=MemorySharingMode.FULL_SHARED,
            sensitive_tags=["hipaa"],
        )
        ctrl = MemoryAccessController("proj-a", policy, project_tags=["public"])
        assert not ctrl.is_self_sensitive()
        assert ctrl.check_read("proj-b").allowed

    # --- filter_projects ---

    def test_filter_projects_read(self):
        policy = MemoryPolicy(sharing_mode=MemorySharingMode.SHARED_READ)
        ctrl = MemoryAccessController("proj-a", policy)
        candidates = ["proj-a", "proj-b", "proj-c"]
        allowed = ctrl.filter_projects(candidates, operation="read")
        assert "proj-a" in allowed   # self
        assert "proj-b" in allowed   # SHARED_READ allows reads
        assert "proj-c" in allowed

    def test_filter_projects_write_shared_read(self):
        policy = MemoryPolicy(sharing_mode=MemorySharingMode.SHARED_READ)
        ctrl = MemoryAccessController("proj-a", policy)
        candidates = ["proj-a", "proj-b"]
        allowed = ctrl.filter_projects(candidates, operation="write")
        assert allowed == ["proj-a"]  # 자기 자신만

    def test_filter_projects_isolated(self):
        policy = MemoryPolicy(sharing_mode=MemorySharingMode.ISOLATED)
        ctrl = MemoryAccessController("proj-a", policy)
        candidates = ["proj-a", "proj-b", "proj-c"]
        allowed = ctrl.filter_projects(candidates, operation="read")
        assert allowed == ["proj-a"]  # 자기 자신만

    # --- AccessDecision 필드 ---

    def test_decision_contains_metadata(self):
        policy = MemoryPolicy(sharing_mode=MemorySharingMode.ISOLATED)
        ctrl = MemoryAccessController("proj-a", policy)
        decision = ctrl.check_read("proj-b")
        assert decision.source_project == "proj-a"
        assert decision.target_project == "proj-b"
        assert decision.operation == "read"
        assert not decision.allowed


class TestMemoryPolicyDefaults:
    def test_default_mode_is_isolated(self):
        policy = MemoryPolicy()
        assert policy.sharing_mode == MemorySharingMode.ISOLATED

    def test_sensitive_tags_populated(self):
        policy = MemoryPolicy()
        assert "hipaa" in policy.sensitive_tags
        assert "pci" in policy.sensitive_tags

    def test_custom_policy(self):
        policy = MemoryPolicy(
            sharing_mode=MemorySharingMode.SHARED_READ,
            allowed_read_projects=["proj-core"],
            cross_project_similarity_threshold=0.95,
        )
        assert policy.cross_project_similarity_threshold == 0.95
        assert policy.allowed_read_projects == ["proj-core"]
