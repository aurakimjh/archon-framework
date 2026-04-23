"""태스크 스케줄러 — 의존성 기반 토폴로지 정렬 + asyncio.Queue 실행."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


class TaskStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class TaskSpec:
    """스케줄링 단위 태스크 정의.

    Attributes:
        task_id: 고유 태스크 ID.
        agent_role: 실행할 에이전트 역할.
        project_id: 소속 프로젝트 ID.
        depends_on: 선행 태스크 ID 목록.
        priority: 우선순위 (높을수록 먼저 실행).
        payload: 에이전트에 전달할 추가 데이터.
    """

    task_id: str
    agent_role: str
    project_id: str
    depends_on: list[str] = field(default_factory=list)
    priority: int = 1
    payload: dict[str, Any] = field(default_factory=dict)
    status: TaskStatus = TaskStatus.PENDING
    result: Any = None
    error: str | None = None


# 태스크 실행 함수 시그니처
TaskExecutor = Callable[[TaskSpec], Coroutine[Any, Any, Any]]


class CyclicDependencyError(Exception):
    """순환 의존성 발견."""


class TaskScheduler:
    """의존성 기반 토폴로지 정렬 + asyncio 큐 스케줄러.

    1. 태스크 등록 (add_task)
    2. 의존성 기반 토폴로지 정렬 (topological_sort)
    3. 의존성이 해소된 태스크를 자동으로 큐에 넣어 비동기 실행 (run)
    """

    def __init__(self, concurrency: int = 3) -> None:
        """
        Args:
            concurrency: 동시 실행 가능한 최대 태스크 수.
        """
        self._tasks: dict[str, TaskSpec] = {}
        self._concurrency = concurrency

    @property
    def tasks(self) -> dict[str, TaskSpec]:
        return self._tasks

    def add_task(self, task: TaskSpec) -> None:
        """태스크를 스케줄러에 등록."""
        if task.task_id in self._tasks:
            raise ValueError(f"Duplicate task_id: {task.task_id}")
        self._tasks[task.task_id] = task

    def add_tasks(self, tasks: list[TaskSpec]) -> None:
        """여러 태스크를 한 번에 등록."""
        for t in tasks:
            self.add_task(t)

    def topological_sort(self) -> list[str]:
        """등록된 태스크를 의존성 기반 토폴로지 정렬.

        Returns:
            실행 순서대로 정렬된 task_id 목록.

        Raises:
            CyclicDependencyError: 순환 의존성 발견 시.
        """
        in_degree: dict[str, int] = defaultdict(int)
        dependents: dict[str, list[str]] = defaultdict(list)

        for task_id, task in self._tasks.items():
            if task_id not in in_degree:
                in_degree[task_id] = 0
            for dep in task.depends_on:
                if dep not in self._tasks:
                    raise ValueError(
                        f"Task [{task_id}] depends on unknown task [{dep}]"
                    )
                in_degree[task_id] += 1
                dependents[dep].append(task_id)

        # 우선순위가 높은 것을 먼저 꺼내기 위해 정렬
        queue: list[str] = sorted(
            [tid for tid, deg in in_degree.items() if deg == 0],
            key=lambda tid: self._tasks[tid].priority,
            reverse=True,
        )
        result: list[str] = []

        while queue:
            current = queue.pop(0)
            result.append(current)

            for dep_tid in dependents[current]:
                in_degree[dep_tid] -= 1
                if in_degree[dep_tid] == 0:
                    queue.append(dep_tid)
                    queue.sort(
                        key=lambda tid: self._tasks[tid].priority,
                        reverse=True,
                    )

        if len(result) != len(self._tasks):
            missing = set(self._tasks.keys()) - set(result)
            raise CyclicDependencyError(
                f"Cyclic dependency detected among tasks: {missing}"
            )

        return result

    def get_ready_tasks(self) -> list[TaskSpec]:
        """현재 실행 가능한(의존성이 모두 완료된) 태스크 목록."""
        ready = []
        for task in self._tasks.values():
            if task.status != TaskStatus.PENDING:
                continue
            deps_met = all(
                self._tasks[dep].status == TaskStatus.COMPLETED
                for dep in task.depends_on
                if dep in self._tasks
            )
            if deps_met:
                ready.append(task)

        # 우선순위 정렬
        ready.sort(key=lambda t: t.priority, reverse=True)
        return ready

    async def run(self, executor: TaskExecutor) -> dict[str, TaskSpec]:
        """등록된 모든 태스크를 의존성 순서대로 비동기 실행.

        Args:
            executor: 각 TaskSpec을 받아 실행하는 코루틴.

        Returns:
            task_id → TaskSpec 매핑 (실행 결과 포함).
        """
        # 유효성 검사
        self.topological_sort()

        semaphore = asyncio.Semaphore(self._concurrency)
        completed_event = asyncio.Event()

        async def _run_task(task: TaskSpec) -> None:
            async with semaphore:
                task.status = TaskStatus.RUNNING
                logger.info("Task [%s] started (agent=%s)", task.task_id, task.agent_role)
                try:
                    task.result = await executor(task)
                    task.status = TaskStatus.COMPLETED
                    logger.info("Task [%s] completed", task.task_id)
                except Exception as e:
                    task.status = TaskStatus.FAILED
                    task.error = str(e)
                    logger.error("Task [%s] failed: %s", task.task_id, e)
                completed_event.set()

        running: set[asyncio.Task[None]] = set()

        while True:
            ready = self.get_ready_tasks()

            for task_spec in ready:
                task_spec.status = TaskStatus.READY
                t = asyncio.create_task(_run_task(task_spec))
                running.add(t)
                t.add_done_callback(running.discard)

            # 모두 완료되었는지 확인
            all_done = all(
                t.status in (TaskStatus.COMPLETED, TaskStatus.FAILED)
                for t in self._tasks.values()
            )
            if all_done:
                break

            # 아직 실행 중인 태스크가 있으면 완료를 기다림
            if running:
                completed_event.clear()
                await completed_event.wait()
            else:
                # ready도 없고 running도 없는데 all_done이 아닌 경우 → 의존성 문제
                break

        # 남은 러닝 태스크 대기
        if running:
            await asyncio.gather(*running, return_exceptions=True)

        return self._tasks

    def reset(self) -> None:
        """모든 태스크 상태를 PENDING으로 초기화."""
        for task in self._tasks.values():
            task.status = TaskStatus.PENDING
            task.result = None
            task.error = None
