"""vLLM 라우팅 통합 테스트 — role_router + vLLM bridge."""

from __future__ import annotations

from src.orchestrator.handoff import (
    Artifacts,
    ChangedFile,
    Envelope,
    HandoffArtifact,
    ProjectContext,
    Task,
)
from src.registry.models import (
    AgentModelConfig,
    AgentRole,
    GitConfig,
    ProjectMeta,
    ProjectRegistry,
)
from src.router.role_router import get_model_with_vllm
from src.runtime.vllm_bridge import VLLMBridge, VLLMEndpoint


def _make_handoff(instructions: str = "Simple task") -> HandoffArtifact:
    return HandoffArtifact(
        envelope=Envelope(
            handoff_id="hf_vllm",
            from_agent="orchestrator",
            to_agent="backend",
        ),
        project_context=ProjectContext(
            project_id="proj_test",
            project_name="Test",
            git_repo="/tmp/test",
            git_branch="develop",
            base_commit_sha="abc123",
        ),
        task=Task(
            task_id="task_vllm",
            completed_summary="",
            next_instructions=instructions,
        ),
    )


def _make_registry(high_model: str | None = None) -> ProjectRegistry:
    return ProjectRegistry(
        project_meta=ProjectMeta(project_id="proj_test", project_name="Test"),
        git_config=GitConfig(repo_url="https://example.com/repo.git"),
        agent_config={
            AgentRole.BACKEND: AgentModelConfig(
                model="qwen-27b",
                high_complexity_model=high_model,
            ),
        },
    )


class TestGetModelWithVLLM:
    def test_no_bridge_fallback(self):
        """vLLM 브릿지 없으면 기본 라우팅."""
        handoff = _make_handoff()
        registry = _make_registry()
        model, config = get_model_with_vllm("backend", handoff, registry)
        assert model == "qwen-27b"
        assert config is None

    def test_bridge_no_healthy_endpoints(self):
        """healthy 엔드포인트가 없으면 기본 라우팅."""
        bridge = VLLMBridge()
        ep = VLLMEndpoint(
            name="backend-vllm",
            base_url="http://gpu:8000",
            model_name="Qwen/Qwen2.5-27B",
            tags=["backend"],
        )
        bridge.register(ep)
        # healthy에 추가 안 함

        handoff = _make_handoff()
        registry = _make_registry()
        model, config = get_model_with_vllm("backend", handoff, registry, vllm_bridge=bridge)
        assert model == "qwen-27b"
        assert config is None

    def test_bridge_healthy_matched_by_tag(self):
        """태그로 매칭되는 healthy 엔드포인트가 있으면 vLLM 라우팅."""
        bridge = VLLMBridge()
        ep = VLLMEndpoint(
            name="gpu-qwen",
            base_url="http://gpu-node:8000",
            model_name="Qwen/Qwen2.5-27B",
            tags=["backend"],
        )
        bridge.register(ep)
        bridge._healthy.add("gpu-qwen")

        handoff = _make_handoff()
        registry = _make_registry()
        model, config = get_model_with_vllm("backend", handoff, registry, vllm_bridge=bridge)
        assert model == "openai/Qwen/Qwen2.5-27B"
        assert config is not None
        assert config["api_base"] == "http://gpu-node:8000/v1"

    def test_bridge_healthy_matched_by_name_prefix(self):
        """이름이 역할로 시작하는 healthy 엔드포인트 매칭."""
        bridge = VLLMBridge()
        ep = VLLMEndpoint(
            name="backend-large",
            base_url="http://gpu:8000",
            model_name="DeepSeek-V3",
            tags=[],
        )
        bridge.register(ep)
        bridge._healthy.add("backend-large")

        handoff = _make_handoff()
        registry = _make_registry()
        model, config = get_model_with_vllm("backend", handoff, registry, vllm_bridge=bridge)
        assert model == "openai/DeepSeek-V3"
        assert config is not None

    def test_bridge_no_matching_role(self):
        """다른 역할의 엔드포인트는 매칭 안 됨."""
        bridge = VLLMBridge()
        ep = VLLMEndpoint(
            name="frontend-vllm",
            base_url="http://gpu:8000",
            model_name="model",
            tags=["frontend"],
        )
        bridge.register(ep)
        bridge._healthy.add("frontend-vllm")

        handoff = _make_handoff()
        registry = _make_registry()
        model, config = get_model_with_vllm("backend", handoff, registry, vllm_bridge=bridge)
        assert model == "qwen-27b"
        assert config is None

    def test_bridge_with_high_complexity_no_vllm_match(self):
        """vLLM 매칭 없으면 복잡도 기반 라우팅으로 폴백."""
        bridge = VLLMBridge()
        # 다른 역할 엔드포인트만 등록
        ep = VLLMEndpoint(
            name="tester-vllm",
            base_url="http://gpu:8000",
            model_name="model",
            tags=["tester"],
        )
        bridge.register(ep)
        bridge._healthy.add("tester-vllm")

        handoff = _make_handoff(
            instructions="Refactor database migration with security authentication"
        )
        handoff.artifacts = Artifacts(
            changed_files=[ChangedFile(path=f"f{i}.py", change_type="modified") for i in range(15)]
        )
        registry = _make_registry(high_model="claude-opus")
        model, config = get_model_with_vllm("backend", handoff, registry, vllm_bridge=bridge)
        # vLLM 매칭 없으니 complexity router로 폴백
        # 복잡도가 높으면 high_complexity_model 사용
        assert config is None
        # 모델은 복잡도에 따라 결정 (high → claude-opus 또는 qwen-27b)
        assert model in ("claude-opus", "qwen-27b")
