"""하네스 기능 테스트 — 스냅샷, 정밀 압축, 자가 교정."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.base import BaseAgent
from src.orchestrator.handoff import (
    ChangedFile,
    Decision,
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

# --- 헬퍼 ---


class _TestAgent(BaseAgent):
    """테스트용 구체 에이전트."""

    def _build_system_prompt(self, handoff, registry):
        return "You are a test agent."


def _make_registry() -> ProjectRegistry:
    return ProjectRegistry(
        project_meta=ProjectMeta(
            project_id="proj_test",
            project_name="Test",
        ),
        git_config=GitConfig(repo_url="https://github.com/test/repo"),
    )


def _make_handoff() -> HandoffArtifact:
    return HandoffArtifact(
        envelope=Envelope(
            handoff_id="hf_test",
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
            task_id="task_001",
            completed_summary="",
            next_instructions="Do something.",
        ),
    )


# --- _parse_structured_output ---


class TestParseStructuredOutput:
    def test_valid_output(self):
        agent = _TestAgent(role=AgentRole.BACKEND)
        text = (
            'Some text\n<archon-output>\n'
            '{"summary": "Did the thing", '
            '"changed_files": [{"path": "a.py", "change_type": "added", "reason": "new"}], '
            '"decisions": [{"decision": "use X", "reason": "faster"}]}'
            '\n</archon-output>'
        )
        result = agent._parse_structured_output(text)
        assert result["summary"] == "Did the thing"
        assert len(result["changed_files"]) == 1
        assert len(result["decisions"]) == 1

    def test_no_tag_returns_empty(self):
        agent = _TestAgent(role=AgentRole.BACKEND)
        result = agent._parse_structured_output("plain text output")
        assert result == {}

    def test_malformed_json_returns_empty(self):
        agent = _TestAgent(role=AgentRole.BACKEND)
        text = "<archon-output>{not valid json}</archon-output>"
        result = agent._parse_structured_output(text)
        assert result == {}


# --- _extract_structured_fields ---


class TestExtractStructuredFields:
    def test_extracts_all_fields(self):
        data = {
            "summary": "test summary",
            "changed_files": [
                {"path": "src/a.py", "change_type": "modified", "reason": "fix"},
            ],
            "decisions": [
                {"decision": "use pattern X", "reason": "reliable"},
            ],
        }
        result = BaseAgent._extract_structured_fields(data)
        assert result["summary"] == "test summary"
        assert len(result["changed_files"]) == 1
        assert isinstance(result["changed_files"][0], ChangedFile)
        assert len(result["decisions"]) == 1
        assert isinstance(result["decisions"][0], Decision)

    def test_summary_truncated(self):
        data = {"summary": "x" * 1000}
        result = BaseAgent._extract_structured_fields(data)
        assert len(result["summary"]) == 500

    def test_invalid_changed_files_filtered(self):
        data = {
            "changed_files": [
                {"path": "a.py", "change_type": "added"},
                {"no_path": True},
                "not a dict",
            ],
        }
        result = BaseAgent._extract_structured_fields(data)
        assert len(result["changed_files"]) == 1

    def test_empty_data(self):
        result = BaseAgent._extract_structured_fields({})
        assert result == {}


# --- _self_correct_output ---


class TestSelfCorrectOutput:
    @pytest.mark.asyncio
    async def test_successful_correction(self):
        agent = _TestAgent(role=AgentRole.BACKEND)
        registry = _make_registry()

        corrected_json = json.dumps({
            "summary": "Corrected output",
            "changed_files": [],
            "decisions": [],
        })
        corrected_text = f"<archon-output>{corrected_json}</archon-output>"

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = corrected_text

        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = mock_response
            result = await agent._self_correct_output(
                "malformed text", "test-model", registry,
            )

        assert result["summary"] == "Corrected output"
        mock_llm.assert_called_once()

    @pytest.mark.asyncio
    async def test_correction_failure_returns_empty(self):
        agent = _TestAgent(role=AgentRole.BACKEND)
        registry = _make_registry()

        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_llm:
            mock_llm.side_effect = Exception("LLM error")
            result = await agent._self_correct_output(
                "malformed text", "test-model", registry,
            )

        assert result == {}

    @pytest.mark.asyncio
    async def test_correction_still_malformed_returns_empty(self):
        agent = _TestAgent(role=AgentRole.BACKEND)
        registry = _make_registry()

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "still broken"

        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = mock_response
            result = await agent._self_correct_output(
                "malformed text", "test-model", registry,
            )

        assert result == {}


# --- _build_handoff_from_parsed ---


class TestBuildHandoffFromParsed:
    def test_builds_from_parsed(self):
        agent = _TestAgent(role=AgentRole.BACKEND)
        input_ho = _make_handoff()
        parsed = {
            "summary": "parsed summary",
            "changed_files": [
                ChangedFile(path="a.py", change_type="added", reason="new"),
            ],
            "decisions": [
                Decision(decision="did X", reason="good"),
            ],
        }
        result = agent._build_handoff_from_parsed(input_ho, parsed, "fallback")
        assert result.task.completed_summary == "parsed summary"
        assert len(result.artifacts.changed_files) == 1
        assert len(result.task.decisions_made) == 1

    def test_fallback_text_used(self):
        agent = _TestAgent(role=AgentRole.BACKEND)
        input_ho = _make_handoff()
        result = agent._build_handoff_from_parsed(input_ho, {}, "fallback text here")
        assert result.task.completed_summary == "fallback text here"


# --- _load_prompt_overlay ---


class TestPromptOverlay:
    def test_no_config_returns_empty(self):
        agent = _TestAgent(role=AgentRole.BACKEND)
        registry = _make_registry()
        assert agent._load_prompt_overlay(registry) == ""

    def test_no_path_returns_empty(self):
        agent = _TestAgent(role=AgentRole.BACKEND)
        registry = _make_registry()
        registry.agent_config["backend"] = AgentModelConfig(
            model="test-model",
            prompt_overlay_path=None,
        )
        assert agent._load_prompt_overlay(registry) == ""

    def test_nonexistent_path_returns_empty(self):
        agent = _TestAgent(role=AgentRole.BACKEND)
        registry = _make_registry()
        registry.agent_config["backend"] = AgentModelConfig(
            model="test-model",
            prompt_overlay_path="/tmp/nonexistent-prompt.md",
        )
        assert agent._load_prompt_overlay(registry) == ""

    def test_loads_overlay_from_file(self, tmp_path):
        overlay_file = tmp_path / "backend-prompt.md"
        overlay_file.write_text("## Extra Instructions\nBe very careful.", encoding="utf-8")

        agent = _TestAgent(role=AgentRole.BACKEND)
        registry = _make_registry()
        registry.agent_config["backend"] = AgentModelConfig(
            model="test-model",
            prompt_overlay_path=str(overlay_file),
        )
        result = agent._load_prompt_overlay(registry)
        assert "Extra Instructions" in result
        assert "Be very careful" in result

    def test_overlay_merged_into_system_prompt(self, tmp_path):
        overlay_file = tmp_path / "backend-overlay.md"
        overlay_file.write_text("## Private Knowledge\nUse FastAPI patterns.", encoding="utf-8")

        agent = _TestAgent(role=AgentRole.BACKEND)
        registry = _make_registry()
        registry.agent_config["backend"] = AgentModelConfig(
            model="test-model",
            prompt_overlay_path=str(overlay_file),
        )
        handoff = _make_handoff()

        base_prompt = agent._build_system_prompt(handoff, registry)
        overlay = agent._load_prompt_overlay(registry)
        combined = base_prompt + "\n\n" + overlay

        assert "You are a test agent." in combined
        assert "Private Knowledge" in combined
        assert "FastAPI patterns" in combined
