"""태스크 스케줄러 테스트 — 토폴로지 정렬 + asyncio 실행."""

from __future__ import annotations

import asyncio

import pytest

from src.queue.scheduler import (
    CyclicDependencyError,
    TaskScheduler,
    TaskSpec,
    TaskStatus,
)


# --- 등록 ---


def test_add_task():
    scheduler = TaskScheduler()
    scheduler.add_task(TaskSpec(task_id="t1", agent_role="backend", project_id="p1"))
    assert "t1" in scheduler.tasks


def test_add_duplicate_raises():
    scheduler = TaskScheduler()
    scheduler.add_task(TaskSpec(task_id="t1", agent_role="backend", project_id="p1"))
    with pytest.raises(ValueError, match="Duplicate"):
        scheduler.add_task(TaskSpec(task_id="t1", agent_role="frontend", project_id="p1"))


def test_add_tasks_bulk():
    scheduler = TaskScheduler()
    scheduler.add_tasks([
        TaskSpec(task_id="t1", agent_role="backend", project_id="p1"),
        TaskSpec(task_id="t2", agent_role="frontend", project_id="p1"),
    ])
    assert len(scheduler.tasks) == 2


# --- 토폴로지 정렬 ---


def test_topological_sort_no_deps():
    scheduler = TaskScheduler()
    scheduler.add_tasks([
        TaskSpec(task_id="t1", agent_role="backend", project_id="p1", priority=2),
        TaskSpec(task_id="t2", agent_role="frontend", project_id="p1", priority=1),
    ])
    order = scheduler.topological_sort()
    assert order == ["t1", "t2"]  # 높은 우선순위 먼저


def test_topological_sort_with_deps():
    scheduler = TaskScheduler()
    scheduler.add_tasks([
        TaskSpec(task_id="t1", agent_role="backend", project_id="p1"),
        TaskSpec(task_id="t2", agent_role="tester", project_id="p1", depends_on=["t1"]),
        TaskSpec(task_id="t3", agent_role="docs", project_id="p1", depends_on=["t2"]),
    ])
    order = scheduler.topological_sort()
    assert order == ["t1", "t2", "t3"]


def test_topological_sort_diamond():
    """다이아몬드 의존성: t1 → t2, t3 → t4."""
    scheduler = TaskScheduler()
    scheduler.add_tasks([
        TaskSpec(task_id="t1", agent_role="backend", project_id="p1"),
        TaskSpec(task_id="t2", agent_role="tester", project_id="p1", depends_on=["t1"]),
        TaskSpec(task_id="t3", agent_role="docs", project_id="p1", depends_on=["t1"]),
        TaskSpec(
            task_id="t4", agent_role="devops", project_id="p1", depends_on=["t2", "t3"]
        ),
    ])
    order = scheduler.topological_sort()
    assert order[0] == "t1"
    assert order[-1] == "t4"
    assert set(order[1:3]) == {"t2", "t3"}


def test_cyclic_dependency_raises():
    scheduler = TaskScheduler()
    scheduler.add_tasks([
        TaskSpec(task_id="t1", agent_role="a", project_id="p1", depends_on=["t2"]),
        TaskSpec(task_id="t2", agent_role="b", project_id="p1", depends_on=["t1"]),
    ])
    with pytest.raises(CyclicDependencyError):
        scheduler.topological_sort()


def test_unknown_dependency_raises():
    scheduler = TaskScheduler()
    scheduler.add_task(
        TaskSpec(task_id="t1", agent_role="a", project_id="p1", depends_on=["unknown"])
    )
    with pytest.raises(ValueError, match="unknown task"):
        scheduler.topological_sort()


# --- get_ready_tasks ---


def test_get_ready_tasks_all_pending():
    scheduler = TaskScheduler()
    scheduler.add_tasks([
        TaskSpec(task_id="t1", agent_role="backend", project_id="p1", priority=1),
        TaskSpec(task_id="t2", agent_role="frontend", project_id="p1", priority=3),
    ])
    ready = scheduler.get_ready_tasks()
    assert [t.task_id for t in ready] == ["t2", "t1"]  # 우선순위 정렬


def test_get_ready_tasks_with_deps():
    scheduler = TaskScheduler()
    scheduler.add_tasks([
        TaskSpec(task_id="t1", agent_role="backend", project_id="p1"),
        TaskSpec(task_id="t2", agent_role="tester", project_id="p1", depends_on=["t1"]),
    ])
    ready = scheduler.get_ready_tasks()
    assert [t.task_id for t in ready] == ["t1"]  # t2는 t1에 의존

    # t1 완료 후
    scheduler.tasks["t1"].status = TaskStatus.COMPLETED
    ready = scheduler.get_ready_tasks()
    assert [t.task_id for t in ready] == ["t2"]


# --- 비동기 실행 ---


async def test_run_simple():
    scheduler = TaskScheduler(concurrency=2)
    results: list[str] = []

    async def executor(task: TaskSpec):
        results.append(task.task_id)
        return f"done_{task.task_id}"

    scheduler.add_tasks([
        TaskSpec(task_id="t1", agent_role="backend", project_id="p1"),
        TaskSpec(task_id="t2", agent_role="frontend", project_id="p1"),
    ])
    tasks = await scheduler.run(executor)
    assert tasks["t1"].status == TaskStatus.COMPLETED
    assert tasks["t2"].status == TaskStatus.COMPLETED
    assert tasks["t1"].result == "done_t1"


async def test_run_with_deps():
    execution_order: list[str] = []

    async def executor(task: TaskSpec):
        execution_order.append(task.task_id)
        await asyncio.sleep(0.01)

    scheduler = TaskScheduler(concurrency=1)
    scheduler.add_tasks([
        TaskSpec(task_id="t1", agent_role="backend", project_id="p1"),
        TaskSpec(task_id="t2", agent_role="tester", project_id="p1", depends_on=["t1"]),
        TaskSpec(task_id="t3", agent_role="docs", project_id="p1", depends_on=["t2"]),
    ])
    await scheduler.run(executor)
    assert execution_order == ["t1", "t2", "t3"]


async def test_run_parallel_independent():
    """독립 태스크는 병렬 실행."""
    started: list[str] = []

    async def executor(task: TaskSpec):
        started.append(task.task_id)
        await asyncio.sleep(0.05)

    scheduler = TaskScheduler(concurrency=3)
    scheduler.add_tasks([
        TaskSpec(task_id="t1", agent_role="a", project_id="p1"),
        TaskSpec(task_id="t2", agent_role="b", project_id="p1"),
        TaskSpec(task_id="t3", agent_role="c", project_id="p1"),
    ])
    await scheduler.run(executor)
    # 모두 완료
    assert all(t.status == TaskStatus.COMPLETED for t in scheduler.tasks.values())


async def test_run_handles_failure():
    async def executor(task: TaskSpec):
        if task.task_id == "t2":
            raise RuntimeError("boom")
        return "ok"

    scheduler = TaskScheduler()
    scheduler.add_tasks([
        TaskSpec(task_id="t1", agent_role="a", project_id="p1"),
        TaskSpec(task_id="t2", agent_role="b", project_id="p1"),
    ])
    await scheduler.run(executor)
    assert scheduler.tasks["t1"].status == TaskStatus.COMPLETED
    assert scheduler.tasks["t2"].status == TaskStatus.FAILED
    assert "boom" in scheduler.tasks["t2"].error


# --- reset ---


def test_reset():
    scheduler = TaskScheduler()
    scheduler.add_task(TaskSpec(task_id="t1", agent_role="a", project_id="p1"))
    scheduler.tasks["t1"].status = TaskStatus.COMPLETED
    scheduler.tasks["t1"].result = "done"
    scheduler.reset()
    assert scheduler.tasks["t1"].status == TaskStatus.PENDING
    assert scheduler.tasks["t1"].result is None
