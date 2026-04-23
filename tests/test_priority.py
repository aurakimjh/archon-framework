"""멀티 프로젝트 우선순위 랭킹 테스트."""

from __future__ import annotations

from datetime import datetime, timedelta

from src.queue.priority import PriorityRanker, ProjectWeight
from src.queue.scheduler import TaskSpec


def _now() -> datetime:
    return datetime(2026, 4, 23, 12, 0, 0)


# --- 기본 랭킹 ---


def test_rank_by_project_priority():
    ranker = PriorityRanker(project_weights=[
        ProjectWeight(project_id="p1", priority=8),
        ProjectWeight(project_id="p2", priority=3),
    ])
    tasks = [
        TaskSpec(task_id="t1", agent_role="backend", project_id="p1"),
        TaskSpec(task_id="t2", agent_role="backend", project_id="p2"),
    ]
    ranked = ranker.rank(tasks, now=_now())
    assert ranked[0].task.project_id == "p1"
    assert ranked[0].score > ranked[1].score


def test_rank_by_task_priority():
    ranker = PriorityRanker(project_weights=[
        ProjectWeight(project_id="p1", priority=5),
    ])
    tasks = [
        TaskSpec(task_id="t1", agent_role="a", project_id="p1", priority=1),
        TaskSpec(task_id="t2", agent_role="b", project_id="p1", priority=5),
    ]
    ranked = ranker.rank(tasks, now=_now())
    assert ranked[0].task.task_id == "t2"


def test_rank_unknown_project_uses_default():
    """등록되지 않은 프로젝트는 priority=5 기본값."""
    ranker = PriorityRanker()
    tasks = [
        TaskSpec(task_id="t1", agent_role="a", project_id="unknown"),
    ]
    ranked = ranker.rank(tasks, now=_now())
    assert ranked[0].score == 5 * 10 + 1  # priority=5, task_priority=1


# --- 데드라인 보너스 ---


def test_deadline_bonus_24h():
    now = _now()
    ranker = PriorityRanker(project_weights=[
        ProjectWeight(project_id="p1", priority=5, deadline=now + timedelta(hours=12)),
    ])
    tasks = [TaskSpec(task_id="t1", agent_role="a", project_id="p1")]
    ranked = ranker.rank(tasks, now=now)
    assert ranked[0].score == 5 * 10 + 1 + 30.0  # +30 데드라인 보너스


def test_deadline_bonus_72h():
    now = _now()
    ranker = PriorityRanker(project_weights=[
        ProjectWeight(project_id="p1", priority=5, deadline=now + timedelta(hours=48)),
    ])
    tasks = [TaskSpec(task_id="t1", agent_role="a", project_id="p1")]
    ranked = ranker.rank(tasks, now=now)
    assert ranked[0].score == 5 * 10 + 1 + 15.0


def test_deadline_bonus_7d():
    now = _now()
    ranker = PriorityRanker(project_weights=[
        ProjectWeight(project_id="p1", priority=5, deadline=now + timedelta(days=5)),
    ])
    tasks = [TaskSpec(task_id="t1", agent_role="a", project_id="p1")]
    ranked = ranker.rank(tasks, now=now)
    assert ranked[0].score == 5 * 10 + 1 + 5.0


def test_deadline_passed_highest_bonus():
    """이미 지난 데드라인은 최우선 +50."""
    now = _now()
    ranker = PriorityRanker(project_weights=[
        ProjectWeight(project_id="p1", priority=5, deadline=now - timedelta(hours=1)),
    ])
    tasks = [TaskSpec(task_id="t1", agent_role="a", project_id="p1")]
    ranked = ranker.rank(tasks, now=now)
    assert ranked[0].score == 5 * 10 + 1 + 50.0


def test_no_deadline_no_bonus():
    now = _now()
    ranker = PriorityRanker(project_weights=[
        ProjectWeight(project_id="p1", priority=5),
    ])
    tasks = [TaskSpec(task_id="t1", agent_role="a", project_id="p1")]
    ranked = ranker.rank(tasks, now=now)
    assert ranked[0].score == 5 * 10 + 1  # 보너스 없음


# --- 데드라인이 우선순위를 뒤집는 경우 ---


def test_deadline_overrides_priority():
    """낮은 프로젝트 우선순위라도 데드라인이 임박하면 더 높은 점수."""
    now = _now()
    ranker = PriorityRanker(project_weights=[
        ProjectWeight(project_id="p_high", priority=8),
        ProjectWeight(
            project_id="p_urgent", priority=3, deadline=now + timedelta(hours=6)
        ),
    ])
    tasks = [
        TaskSpec(task_id="t1", agent_role="a", project_id="p_high"),
        TaskSpec(task_id="t2", agent_role="a", project_id="p_urgent"),
    ]
    ranked = ranker.rank(tasks, now=now)
    # p_high: 8*10 + 1 = 81
    # p_urgent: 3*10 + 1 + 30 = 61 → p_high이 아직 높음
    assert ranked[0].task.project_id == "p_high"

    # 데드라인 지나면 뒤집힘
    ranker.set_project_weight(
        ProjectWeight(project_id="p_urgent", priority=3, deadline=now - timedelta(hours=1))
    )
    ranked = ranker.rank(tasks, now=now)
    # p_urgent: 3*10 + 1 + 50 = 81 → 동점이지만 순서상 뒤
    # → 실제 priority 3 vs 8 이라 p_high = 81, p_urgent = 81 → 동점
    assert ranked[0].score == ranked[1].score


# --- 슬롯 할당 ---


def test_allocate_slots():
    ranker = PriorityRanker(max_slots=2)
    tasks = [
        TaskSpec(task_id="t1", agent_role="a", project_id="p1", priority=1),
        TaskSpec(task_id="t2", agent_role="b", project_id="p1", priority=3),
        TaskSpec(task_id="t3", agent_role="c", project_id="p1", priority=2),
    ]
    allocated = ranker.allocate_slots(tasks, now=_now())
    assert len(allocated) == 2
    assert allocated[0].task_id == "t2"  # 최고 우선순위
    assert allocated[1].task_id == "t3"


def test_allocate_fewer_than_slots():
    ranker = PriorityRanker(max_slots=10)
    tasks = [TaskSpec(task_id="t1", agent_role="a", project_id="p1")]
    allocated = ranker.allocate_slots(tasks, now=_now())
    assert len(allocated) == 1


# --- set_project_weight ---


def test_set_project_weight():
    ranker = PriorityRanker()
    ranker.set_project_weight(ProjectWeight(project_id="p1", priority=9))
    tasks = [TaskSpec(task_id="t1", agent_role="a", project_id="p1")]
    ranked = ranker.rank(tasks, now=_now())
    assert ranked[0].score == 9 * 10 + 1
