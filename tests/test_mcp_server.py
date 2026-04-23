"""MCP 서버 테스트 — 도구 정의, 등록, 호출."""

from __future__ import annotations

import pytest

from src.mcp.server import MCPServer, ToolName, ToolResult, TOOL_DEFINITIONS
from src.registry.models import (
    AgentModelConfig,
    AgentRole,
    GitConfig,
    ProjectMeta,
    ProjectRegistry,
)


def _make_registry(project_id: str = "proj_test", name: str = "Test") -> ProjectRegistry:
    return ProjectRegistry(
        project_meta=ProjectMeta(project_id=project_id, project_name=name),
        git_config=GitConfig(repo_url="https://example.com/repo.git"),
        agent_config={
            AgentRole.BACKEND: AgentModelConfig(model="qwen-27b"),
        },
    )


# --- ToolDefinitions ---


class TestToolDefinitions:
    def test_all_tools_defined(self):
        names = {t.name for t in TOOL_DEFINITIONS}
        assert ToolName.EXECUTE_TASK in names
        assert ToolName.GET_STATUS in names
        assert ToolName.LIST_AGENTS in names
        assert ToolName.GET_PROJECT in names
        assert ToolName.LIST_PROJECTS in names

    def test_execute_task_schema(self):
        tool = next(t for t in TOOL_DEFINITIONS if t.name == ToolName.EXECUTE_TASK)
        props = tool.input_schema["properties"]
        assert "project_id" in props
        assert "task_id" in props
        assert "agent_role" in props
        assert "instructions" in props
        assert set(tool.input_schema["required"]) == {
            "project_id", "task_id", "agent_role", "instructions",
        }


# --- MCPServer ---


class TestMCPServer:
    def test_register_project(self):
        server = MCPServer()
        registry = _make_registry()
        server.register_project(registry)
        assert "proj_test" in server._registries

    def test_get_tools(self):
        server = MCPServer()
        tools = server.get_tools()
        assert len(tools) == len(TOOL_DEFINITIONS)

    @pytest.mark.asyncio
    async def test_unknown_tool(self):
        server = MCPServer()
        result = await server.call_tool("unknown_tool", {})
        assert result.success is False
        assert "Unknown tool" in result.error

    @pytest.mark.asyncio
    async def test_execute_task(self):
        server = MCPServer()
        server.register_project(_make_registry())
        result = await server.call_tool(ToolName.EXECUTE_TASK, {
            "project_id": "proj_test",
            "task_id": "task_1",
            "agent_role": "backend",
            "instructions": "Add user authentication",
        })
        assert result.success is True
        assert result.data["task_id"] == "task_1"
        assert result.data["status"] == "queued"

    @pytest.mark.asyncio
    async def test_execute_task_unknown_project(self):
        server = MCPServer()
        result = await server.call_tool(ToolName.EXECUTE_TASK, {
            "project_id": "unknown",
            "task_id": "task_1",
            "agent_role": "backend",
            "instructions": "test",
        })
        assert result.success is False
        assert "not found" in result.error

    @pytest.mark.asyncio
    async def test_get_status_project(self):
        server = MCPServer()
        server.register_project(_make_registry())
        result = await server.call_tool(ToolName.GET_STATUS, {
            "project_id": "proj_test",
        })
        assert result.success is True
        assert result.data["project_id"] == "proj_test"
        assert result.data["status"] == "active"

    @pytest.mark.asyncio
    async def test_get_status_unknown_project(self):
        server = MCPServer()
        result = await server.call_tool(ToolName.GET_STATUS, {
            "project_id": "unknown",
        })
        assert result.success is False

    @pytest.mark.asyncio
    async def test_get_status_with_task(self):
        server = MCPServer()
        server.register_project(_make_registry())
        # 먼저 태스크 실행
        await server.call_tool(ToolName.EXECUTE_TASK, {
            "project_id": "proj_test",
            "task_id": "task_1",
            "agent_role": "backend",
            "instructions": "test",
        })
        # 태스크 상태 조회
        result = await server.call_tool(ToolName.GET_STATUS, {
            "project_id": "proj_test",
            "task_id": "task_1",
        })
        assert result.success is True
        assert result.data["task_id"] == "task_1"

    @pytest.mark.asyncio
    async def test_list_agents(self):
        server = MCPServer()
        result = await server.call_tool(ToolName.LIST_AGENTS, {})
        assert result.success is True
        agents = result.data["agents"]
        roles = {a["role"] for a in agents}
        assert "backend" in roles
        assert "frontend" in roles
        assert "tester" in roles

    @pytest.mark.asyncio
    async def test_get_project(self):
        server = MCPServer()
        server.register_project(_make_registry())
        result = await server.call_tool(ToolName.GET_PROJECT, {
            "project_id": "proj_test",
        })
        assert result.success is True
        assert result.data["project_name"] == "Test"
        assert "backend" in result.data["agents"]

    @pytest.mark.asyncio
    async def test_get_project_unknown(self):
        server = MCPServer()
        result = await server.call_tool(ToolName.GET_PROJECT, {
            "project_id": "unknown",
        })
        assert result.success is False

    @pytest.mark.asyncio
    async def test_list_projects(self):
        server = MCPServer()
        server.register_project(_make_registry("proj_1", "Project A"))
        server.register_project(_make_registry("proj_2", "Project B"))
        result = await server.call_tool(ToolName.LIST_PROJECTS, {})
        assert result.success is True
        assert len(result.data["projects"]) == 2

    @pytest.mark.asyncio
    async def test_list_projects_empty(self):
        server = MCPServer()
        result = await server.call_tool(ToolName.LIST_PROJECTS, {})
        assert result.success is True
        assert result.data["projects"] == []

    @pytest.mark.asyncio
    async def test_tool_handler_exception(self):
        """핸들러 내부에서 예외 발생 시 에러 결과를 반환한다."""
        server = MCPServer()
        # project 없이 필수 키 누락 → KeyError
        result = await server.call_tool(ToolName.EXECUTE_TASK, {})
        assert result.success is False
        assert result.error is not None
