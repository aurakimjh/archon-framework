"""MCP (Model Context Protocol) 서버 — 외부 도구 인터페이스.

외부 클라이언트(IDE, CLI 등)가 Archon 프레임워크와 상호작용할 수 있는
도구(tools)를 제공한다. MCP 프로토콜을 따르며, 각 도구는 JSON 기반
입출력을 사용한다.

실제 MCP SDK 연동은 Phase 3에서 진행하고, 여기서는 도구 정의와
핸들러를 먼저 구현한다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from src.registry.models import AgentRole, ProjectRegistry

logger = logging.getLogger(__name__)


class ToolName(StrEnum):
    """MCP 서버가 제공하는 도구 목록."""

    EXECUTE_TASK = "execute_task"
    GET_STATUS = "get_status"
    LIST_AGENTS = "list_agents"
    GET_PROJECT = "get_project"
    LIST_PROJECTS = "list_projects"


@dataclass
class ToolDefinition:
    """MCP 도구 정의."""

    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass
class ToolResult:
    """MCP 도구 실행 결과."""

    success: bool
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


# --- 도구 정의 ---

TOOL_DEFINITIONS: list[ToolDefinition] = [
    ToolDefinition(
        name=ToolName.EXECUTE_TASK,
        description="Submit a task for agent execution.",
        input_schema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Target project ID"},
                "task_id": {"type": "string", "description": "Unique task identifier"},
                "agent_role": {
                    "type": "string",
                    "enum": [r.value for r in AgentRole],
                    "description": "Target agent role",
                },
                "instructions": {"type": "string", "description": "Task instructions"},
            },
            "required": ["project_id", "task_id", "agent_role", "instructions"],
        },
    ),
    ToolDefinition(
        name=ToolName.GET_STATUS,
        description="Get the current status of a task or project.",
        input_schema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Project ID"},
                "task_id": {"type": "string", "description": "Task ID (optional)"},
            },
            "required": ["project_id"],
        },
    ),
    ToolDefinition(
        name=ToolName.LIST_AGENTS,
        description="List all available agents and their current status.",
        input_schema={
            "type": "object",
            "properties": {},
        },
    ),
    ToolDefinition(
        name=ToolName.GET_PROJECT,
        description="Get project registry details.",
        input_schema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Project ID"},
            },
            "required": ["project_id"],
        },
    ),
    ToolDefinition(
        name=ToolName.LIST_PROJECTS,
        description="List all registered projects.",
        input_schema={
            "type": "object",
            "properties": {},
        },
    ),
]


class MCPServer:
    """MCP 프로토콜 서버.

    도구(tool) 호출을 받아 Archon 프레임워크 기능을 실행한다.
    실제 전송 계층(stdio, SSE 등)은 Phase 3에서 MCP SDK로 연동.
    """

    def __init__(self) -> None:
        self._registries: dict[str, ProjectRegistry] = {}
        self._task_results: dict[str, ToolResult] = {}
        self._handlers = {
            ToolName.EXECUTE_TASK: self._handle_execute_task,
            ToolName.GET_STATUS: self._handle_get_status,
            ToolName.LIST_AGENTS: self._handle_list_agents,
            ToolName.GET_PROJECT: self._handle_get_project,
            ToolName.LIST_PROJECTS: self._handle_list_projects,
        }

    def register_project(self, registry: ProjectRegistry) -> None:
        """프로젝트를 MCP 서버에 등록한다."""
        self._registries[registry.project_meta.project_id] = registry
        logger.info(
            "MCP: registered project [%s]",
            registry.project_meta.project_id,
        )

    def get_tools(self) -> list[ToolDefinition]:
        """사용 가능한 도구 목록을 반환한다."""
        return list(TOOL_DEFINITIONS)

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        """도구를 호출한다."""
        handler = self._handlers.get(name)
        if not handler:
            return ToolResult(
                success=False,
                error=f"Unknown tool: {name}",
            )

        try:
            return await handler(arguments)
        except Exception as e:
            logger.error("MCP tool [%s] error: %s", name, e)
            return ToolResult(success=False, error=str(e))

    async def _handle_execute_task(self, args: dict[str, Any]) -> ToolResult:
        """태스크 실행 요청을 처리한다.

        실제 에이전트 실행은 Orchestrator를 통해 이루어지며,
        여기서는 태스크를 큐에 등록하고 확인을 반환한다.
        """
        project_id = args["project_id"]
        task_id = args["task_id"]
        agent_role = args["agent_role"]
        instructions = args["instructions"]

        if project_id not in self._registries:
            return ToolResult(
                success=False,
                error=f"Project not found: {project_id}",
            )

        # 태스크 등록 (실제 실행은 별도 파이프라인)
        result = ToolResult(
            success=True,
            data={
                "task_id": task_id,
                "project_id": project_id,
                "agent_role": agent_role,
                "status": "queued",
                "instructions_length": len(instructions),
                "queued_at": datetime.utcnow().isoformat(),
            },
        )
        self._task_results[task_id] = result
        return result

    async def _handle_get_status(self, args: dict[str, Any]) -> ToolResult:
        """프로젝트/태스크 상태를 반환한다."""
        project_id = args["project_id"]
        task_id = args.get("task_id")

        if project_id not in self._registries:
            return ToolResult(
                success=False,
                error=f"Project not found: {project_id}",
            )

        registry = self._registries[project_id]

        if task_id and task_id in self._task_results:
            return self._task_results[task_id]

        return ToolResult(
            success=True,
            data={
                "project_id": project_id,
                "status": str(registry.project_meta.status),
                "priority": registry.project_meta.priority,
                "overall_progress": registry.work_queue.overall_progress,
                "pending_tasks": len(registry.work_queue.pending_tasks),
                "active_agents": len(registry.work_queue.active_agents),
            },
        )

    async def _handle_list_agents(self, _args: dict[str, Any]) -> ToolResult:
        """사용 가능한 에이전트 목록을 반환한다."""
        agents = [
            {"role": role.value, "description": f"{role.value} agent"}
            for role in AgentRole
        ]
        return ToolResult(success=True, data={"agents": agents})

    async def _handle_get_project(self, args: dict[str, Any]) -> ToolResult:
        """프로젝트 상세 정보를 반환한다."""
        project_id = args["project_id"]

        if project_id not in self._registries:
            return ToolResult(
                success=False,
                error=f"Project not found: {project_id}",
            )

        registry = self._registries[project_id]
        return ToolResult(
            success=True,
            data={
                "project_id": project_id,
                "project_name": registry.project_meta.project_name,
                "status": str(registry.project_meta.status),
                "priority": registry.project_meta.priority,
                "agents": list(registry.agent_config.keys()),
                "metrics": registry.metrics.model_dump(),
            },
        )

    async def _handle_list_projects(self, _args: dict[str, Any]) -> ToolResult:
        """등록된 프로젝트 목록을 반환한다."""
        projects = [
            {
                "project_id": pid,
                "project_name": reg.project_meta.project_name,
                "status": str(reg.project_meta.status),
                "priority": reg.project_meta.priority,
            }
            for pid, reg in self._registries.items()
        ]
        return ToolResult(success=True, data={"projects": projects})
