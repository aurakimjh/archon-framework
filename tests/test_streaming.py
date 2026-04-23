"""Async Streaming 테스트 — execute_streaming / execute_with_streaming."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.backend import BackendAgent
from src.orchestrator.handoff import (
    Envelope,
    HandoffArtifact,
    ProjectContext,
    Task,
    TechStack,
)
from src.registry.models import (
    AgentModelConfig,
    AgentRole,
    GitConfig,
    ProjectMeta,
    ProjectRegistry,
)


# --- 헬퍼 ---


def _make_handoff() -> HandoffArtifact:
    return HandoffArtifact(
        envelope=Envelope(
            handoff_id="hf_stream_001",
            from_agent="orchestrator",
            to_agent="backend",
        ),
        project_context=ProjectContext(
            project_id="proj_test",
            project_name="Test",
            git_repo="/tmp/test",
            git_branch="develop",
            base_commit_sha="abc123",
            tech_stack=TechStack(language="Python", framework="FastAPI"),
        ),
        task=Task(
            task_id="task_stream",
            completed_summary="",
            next_instructions="Create an API endpoint.",
        ),
    )


def _make_registry(streaming: bool = False, timeout: int = 300) -> ProjectRegistry:
    return ProjectRegistry(
        project_meta=ProjectMeta(project_id="proj_test", project_name="Test"),
        git_config=GitConfig(repo_url="https://example.com/repo.git"),
        agent_config={
            AgentRole.BACKEND: AgentModelConfig(
                model="test-model",
                streaming=streaming,
                timeout_seconds=timeout,
            ),
        },
    )


# --- AgentModelConfig 스키마 ---


class TestAgentModelConfigSchema:
    def test_streaming_default_false(self):
        cfg = AgentModelConfig(model="test")
        assert cfg.streaming is False

    def test_timeout_default_300(self):
        cfg = AgentModelConfig(model="test")
        assert cfg.timeout_seconds == 300

    def test_custom_streaming(self):
        cfg = AgentModelConfig(model="test", streaming=True, timeout_seconds=120)
        assert cfg.streaming is True
        assert cfg.timeout_seconds == 120


# --- execute_with_streaming ---


class TestExecuteWithStreaming:
    @patch("src.agents.base.litellm.acompletion")
    async def test_fallback_to_execute_when_streaming_disabled(self, mock_completion):
        """streaming=False일 때 기존 execute()로 폴백."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "result text"
        mock_completion.return_value = mock_response

        agent = BackendAgent()
        registry = _make_registry(streaming=False)
        handoff = _make_handoff()

        result = await agent.execute_with_streaming(handoff, registry)
        assert result.task.completed_summary == "result text"[:500]
        # stream=True가 아닌 일반 호출 확인
        call_kwargs = mock_completion.call_args
        assert "stream" not in call_kwargs.kwargs or call_kwargs.kwargs.get("stream") is not True

    @patch("src.agents.base.litellm.acompletion")
    async def test_streaming_collects_chunks(self, mock_completion):
        """streaming=True일 때 청크를 수집하여 결과 조립."""
        # 스트리밍 응답 모킹
        chunks = []
        for text in ["Hello", " World", "!"]:
            chunk = MagicMock()
            chunk.choices = [MagicMock()]
            chunk.choices[0].delta.content = text
            chunks.append(chunk)

        async def mock_aiter():
            for c in chunks:
                yield c

        mock_completion.return_value = mock_aiter()

        agent = BackendAgent()
        registry = _make_registry(streaming=True)
        handoff = _make_handoff()

        result = await agent.execute_with_streaming(handoff, registry)
        assert result.task.completed_summary == "Hello World!"

    @patch("src.agents.base.litellm.acompletion")
    async def test_streaming_with_empty_chunks(self, mock_completion):
        """빈 청크는 무시된다."""
        chunks = []
        for text in ["data", None, "", "end"]:
            chunk = MagicMock()
            chunk.choices = [MagicMock()]
            chunk.choices[0].delta.content = text
            chunks.append(chunk)

        async def mock_aiter():
            for c in chunks:
                yield c

        mock_completion.return_value = mock_aiter()

        agent = BackendAgent()
        registry = _make_registry(streaming=True)
        handoff = _make_handoff()

        result = await agent.execute_with_streaming(handoff, registry)
        assert result.task.completed_summary == "dataend"


# --- execute_streaming generator ---


class TestExecuteStreaming:
    @patch("src.agents.base.litellm.acompletion")
    async def test_yields_chunks(self, mock_completion):
        chunks = []
        for text in ["chunk1", "chunk2"]:
            chunk = MagicMock()
            chunk.choices = [MagicMock()]
            chunk.choices[0].delta.content = text
            chunks.append(chunk)

        async def mock_aiter():
            for c in chunks:
                yield c

        mock_completion.return_value = mock_aiter()

        agent = BackendAgent()
        registry = _make_registry(streaming=True)
        handoff = _make_handoff()

        collected = []
        async for text in agent.execute_streaming(handoff, registry):
            collected.append(text)

        assert collected == ["chunk1", "chunk2"]
