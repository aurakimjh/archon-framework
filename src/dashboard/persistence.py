"""Dashboard 영속화 — SQLite 기반 Task/Gate 스토어.

단일 SQLite 파일에 tasks/gates 두 테이블을 저장한다.
경로: 환경변수 ARCHON_DASHBOARD_DB_PATH, 기본 .harness/dashboard.db.
WAL 저널로 동시 읽기 안전, 쓰기는 직렬화된다.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Iterator

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = ".harness/dashboard.db"
SCHEMA_VERSION = 2


def get_db_path() -> Path:
    return Path(os.environ.get("ARCHON_DASHBOARD_DB_PATH", _DEFAULT_DB_PATH))


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


# ---------------------------------------------------------------------------
# 모델
# ---------------------------------------------------------------------------


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


_ACTIVE_TASK_STATUSES: frozenset[str] = frozenset(
    {TaskStatus.PENDING.value, TaskStatus.RUNNING.value}
)


class TaskRecord(BaseModel):
    id: str
    project_id: str
    agent_role: str
    instructions: str
    status: TaskStatus
    handoff_id: str | None = None
    gate_decision: str | None = None
    review_score: int | None = None
    error: str | None = None
    result_summary: str | None = None
    cancelled_by: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    started_at: str | None = None
    completed_at: str | None = None
    updated_at: str


class GateStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class GateRecord(BaseModel):
    handoff_id: str
    project_id: str
    gate_level: str
    trigger_reason: str = ""
    agent_role: str = ""
    review_score: int | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    status: GateStatus = GateStatus.PENDING
    decision_comment: str | None = None
    decided_by: str | None = None
    created_at: str
    decided_at: str | None = None


class UsageEvent(BaseModel):
    """단일 LLM 호출 이벤트 — 비용·토큰 시계열 기반."""

    id: int | None = None
    timestamp: str
    project_id: str | None = None
    agent_role: str | None = None
    model: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    task_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class TimeseriesPoint(BaseModel):
    """시계열 한 포인트. group이 None이면 전체 합계."""

    bucket: str             # ISO date(daily) 또는 ISO hour(hourly)
    group: str | None = None
    cost_usd: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    events: int = 0


class UsageSummary(BaseModel):
    """오늘/이번 달 합계 + 직전 24시간 카운트."""

    today_cost_usd: float = 0.0
    today_tokens: int = 0
    month_cost_usd: float = 0.0
    month_tokens: int = 0
    last_24h_events: int = 0
    by_role_today: dict[str, float] = Field(default_factory=dict)
    by_project_today: dict[str, float] = Field(default_factory=dict)


class BudgetPeriod(StrEnum):
    DAILY = "daily"
    MONTHLY = "monthly"


class BudgetThreshold(BaseModel):
    """예산 임계치 — scope=`global` | `project:<id>` | `role:<role>`."""

    id: int | None = None
    scope: str = "global"
    period: BudgetPeriod = BudgetPeriod.DAILY
    limit_usd: float = Field(ge=0.0)
    notify_email: str | None = None
    notify_webhook: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class BudgetStatus(BaseModel):
    """현재 사용량 / 임계치 비교 결과."""

    threshold: BudgetThreshold
    used_usd: float
    usage_ratio: float          # 0.0 ~ ∞
    exceeded: bool


# ---------------------------------------------------------------------------
# Connection / 마이그레이션
# ---------------------------------------------------------------------------


class _Connection:
    """SQLite 연결 + 직렬화된 쓰기."""

    _SCHEMA = [
        """CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            agent_role TEXT NOT NULL,
            instructions TEXT NOT NULL,
            status TEXT NOT NULL,
            handoff_id TEXT,
            gate_decision TEXT,
            review_score INTEGER,
            error TEXT,
            result_summary TEXT,
            cancelled_by TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            started_at TEXT,
            completed_at TEXT,
            updated_at TEXT NOT NULL
        )""",
        "CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)",
        "CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project_id)",
        "CREATE INDEX IF NOT EXISTS idx_tasks_created ON tasks(created_at DESC)",
        """CREATE TABLE IF NOT EXISTS gates (
            handoff_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            gate_level TEXT NOT NULL,
            trigger_reason TEXT,
            agent_role TEXT,
            review_score INTEGER,
            payload_json TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'pending',
            decision_comment TEXT,
            decided_by TEXT,
            created_at TEXT NOT NULL,
            decided_at TEXT
        )""",
        "CREATE INDEX IF NOT EXISTS idx_gates_status ON gates(status)",
        "CREATE INDEX IF NOT EXISTS idx_gates_project ON gates(project_id)",
        """CREATE TABLE IF NOT EXISTS usage_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            project_id TEXT,
            agent_role TEXT,
            model TEXT,
            tokens_in INTEGER NOT NULL DEFAULT 0,
            tokens_out INTEGER NOT NULL DEFAULT 0,
            cost_usd REAL NOT NULL DEFAULT 0,
            task_id TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}'
        )""",
        "CREATE INDEX IF NOT EXISTS idx_usage_ts ON usage_events(timestamp DESC)",
        "CREATE INDEX IF NOT EXISTS idx_usage_project ON usage_events(project_id)",
        "CREATE INDEX IF NOT EXISTS idx_usage_role ON usage_events(agent_role)",
        """CREATE TABLE IF NOT EXISTS budget_thresholds (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scope TEXT NOT NULL,
            period TEXT NOT NULL,
            limit_usd REAL NOT NULL,
            notify_email TEXT,
            notify_webhook TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(scope, period)
        )""",
    ]

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            str(path),
            check_same_thread=False,
            detect_types=sqlite3.PARSE_DECLTYPES,
            isolation_level=None,  # autocommit; 명시 트랜잭션은 with self.tx() 사용
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._migrate()

    def _migrate(self) -> None:
        with self.tx() as cur:
            for stmt in self._SCHEMA:
                cur.execute(stmt)
            cur.execute(
                "CREATE TABLE IF NOT EXISTS _schema (version INTEGER NOT NULL)"
            )
            row = cur.execute("SELECT version FROM _schema LIMIT 1").fetchone()
            if row is None:
                cur.execute(
                    "INSERT INTO _schema(version) VALUES (?)", (SCHEMA_VERSION,)
                )

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Cursor]:
        """직렬화된 즉시-커밋 트랜잭션."""
        with self._lock:
            cur = self._conn.cursor()
            try:
                cur.execute("BEGIN IMMEDIATE")
                yield cur
                cur.execute("COMMIT")
            except Exception:
                cur.execute("ROLLBACK")
                raise
            finally:
                cur.close()

    def query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return list(self._conn.execute(sql, params))

    def query_one(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(sql, params).fetchone()

    def close(self) -> None:
        with self._lock:
            self._conn.close()


# ---------------------------------------------------------------------------
# TaskStore
# ---------------------------------------------------------------------------


class TaskStore:
    def __init__(self, conn: _Connection) -> None:
        self._c = conn

    def create(
        self,
        *,
        task_id: str,
        project_id: str,
        agent_role: str,
        instructions: str,
        handoff_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TaskRecord:
        now = _now_iso()
        record = TaskRecord(
            id=task_id,
            project_id=project_id,
            agent_role=agent_role,
            instructions=instructions,
            status=TaskStatus.PENDING,
            handoff_id=handoff_id,
            metadata=metadata or {},
            created_at=now,
            updated_at=now,
        )
        with self._c.tx() as cur:
            cur.execute(
                """INSERT INTO tasks
                (id, project_id, agent_role, instructions, status, handoff_id,
                 metadata_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    record.id,
                    record.project_id,
                    record.agent_role,
                    record.instructions,
                    record.status.value,
                    record.handoff_id,
                    json.dumps(record.metadata, ensure_ascii=False),
                    record.created_at,
                    record.updated_at,
                ),
            )
        return record

    def transition(
        self,
        task_id: str,
        *,
        status: TaskStatus,
        gate_decision: str | None = None,
        review_score: int | None = None,
        error: str | None = None,
        result_summary: str | None = None,
        cancelled_by: str | None = None,
        handoff_id: str | None = None,
    ) -> TaskRecord | None:
        """상태 전이 + 보조 필드 갱신. 알 수 없는 task_id면 None.

        - PENDING → RUNNING: started_at 자동 기록.
        - RUNNING → SUCCEEDED/FAILED/CANCELLED: completed_at 자동 기록.
        """
        now = _now_iso()
        sets: list[str] = ["status = ?", "updated_at = ?"]
        params: list[Any] = [status.value, now]

        if status == TaskStatus.RUNNING:
            sets.append("started_at = COALESCE(started_at, ?)")
            params.append(now)
        elif status in (TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.CANCELLED):
            sets.append("completed_at = ?")
            params.append(now)

        if gate_decision is not None:
            sets.append("gate_decision = ?")
            params.append(gate_decision)
        if review_score is not None:
            sets.append("review_score = ?")
            params.append(review_score)
        if error is not None:
            sets.append("error = ?")
            params.append(error)
        if result_summary is not None:
            sets.append("result_summary = ?")
            params.append(result_summary)
        if cancelled_by is not None:
            sets.append("cancelled_by = ?")
            params.append(cancelled_by)
        if handoff_id is not None:
            sets.append("handoff_id = ?")
            params.append(handoff_id)

        params.append(task_id)
        with self._c.tx() as cur:
            cur.execute(
                f"UPDATE tasks SET {', '.join(sets)} WHERE id = ?",
                tuple(params),
            )
            if cur.rowcount == 0:
                return None
        return self.get(task_id)

    def get(self, task_id: str) -> TaskRecord | None:
        row = self._c.query_one("SELECT * FROM tasks WHERE id = ?", (task_id,))
        return _row_to_task(row) if row else None

    def list(
        self,
        *,
        status: TaskStatus | str | None = None,
        project_id: str | None = None,
        active_only: bool = False,
        limit: int = 100,
    ) -> list[TaskRecord]:
        where: list[str] = []
        params: list[Any] = []
        if active_only:
            placeholders = ",".join(["?"] * len(_ACTIVE_TASK_STATUSES))
            where.append(f"status IN ({placeholders})")
            params.extend(sorted(_ACTIVE_TASK_STATUSES))
        elif status is not None:
            where.append("status = ?")
            params.append(status.value if isinstance(status, TaskStatus) else status)
        if project_id is not None:
            where.append("project_id = ?")
            params.append(project_id)
        clause = f" WHERE {' AND '.join(where)}" if where else ""
        rows = self._c.query(
            f"SELECT * FROM tasks{clause} ORDER BY created_at DESC LIMIT ?",
            (*params, max(1, min(limit, 500))),
        )
        return [_row_to_task(r) for r in rows]


def _row_to_task(row: sqlite3.Row) -> TaskRecord:
    return TaskRecord(
        id=row["id"],
        project_id=row["project_id"],
        agent_role=row["agent_role"],
        instructions=row["instructions"],
        status=TaskStatus(row["status"]),
        handoff_id=row["handoff_id"],
        gate_decision=row["gate_decision"],
        review_score=row["review_score"],
        error=row["error"],
        result_summary=row["result_summary"],
        cancelled_by=row["cancelled_by"],
        metadata=json.loads(row["metadata_json"] or "{}"),
        created_at=row["created_at"],
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        updated_at=row["updated_at"],
    )


# ---------------------------------------------------------------------------
# GateStore
# ---------------------------------------------------------------------------


class GateStore:
    def __init__(self, conn: _Connection) -> None:
        self._c = conn

    def enqueue(
        self,
        *,
        handoff_id: str,
        project_id: str,
        gate_level: str,
        trigger_reason: str = "",
        agent_role: str = "",
        review_score: int | None = None,
        payload: dict[str, Any] | None = None,
    ) -> GateRecord:
        now = _now_iso()
        record = GateRecord(
            handoff_id=handoff_id,
            project_id=project_id,
            gate_level=gate_level,
            trigger_reason=trigger_reason,
            agent_role=agent_role,
            review_score=review_score,
            payload=payload or {},
            created_at=now,
        )
        with self._c.tx() as cur:
            cur.execute(
                """INSERT OR REPLACE INTO gates
                (handoff_id, project_id, gate_level, trigger_reason, agent_role,
                 review_score, payload_json, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)""",
                (
                    record.handoff_id,
                    record.project_id,
                    record.gate_level,
                    record.trigger_reason,
                    record.agent_role,
                    record.review_score,
                    json.dumps(record.payload, ensure_ascii=False),
                    record.created_at,
                ),
            )
        return record

    def decide(
        self,
        handoff_id: str,
        *,
        status: GateStatus,
        comment: str | None,
        decided_by: str | None = None,
    ) -> GateRecord | None:
        if status == GateStatus.PENDING:
            raise ValueError("status must be approved or rejected")
        if status == GateStatus.REJECTED and not (comment and comment.strip()):
            raise ValueError("reject requires a non-empty comment")

        now = _now_iso()
        with self._c.tx() as cur:
            cur.execute(
                """UPDATE gates
                SET status = ?, decision_comment = ?, decided_by = ?, decided_at = ?
                WHERE handoff_id = ? AND status = 'pending'""",
                (status.value, comment, decided_by, now, handoff_id),
            )
            if cur.rowcount == 0:
                return None
        return self.get(handoff_id)

    def get(self, handoff_id: str) -> GateRecord | None:
        row = self._c.query_one(
            "SELECT * FROM gates WHERE handoff_id = ?", (handoff_id,)
        )
        return _row_to_gate(row) if row else None

    def list(
        self,
        *,
        status: GateStatus | str | None = GateStatus.PENDING,
        project_id: str | None = None,
        limit: int = 100,
    ) -> list[GateRecord]:
        where: list[str] = []
        params: list[Any] = []
        if status is not None:
            where.append("status = ?")
            params.append(status.value if isinstance(status, GateStatus) else status)
        if project_id is not None:
            where.append("project_id = ?")
            params.append(project_id)
        clause = f" WHERE {' AND '.join(where)}" if where else ""
        rows = self._c.query(
            f"SELECT * FROM gates{clause} ORDER BY created_at DESC LIMIT ?",
            (*params, max(1, min(limit, 500))),
        )
        return [_row_to_gate(r) for r in rows]


def _row_to_gate(row: sqlite3.Row) -> GateRecord:
    return GateRecord(
        handoff_id=row["handoff_id"],
        project_id=row["project_id"],
        gate_level=row["gate_level"],
        trigger_reason=row["trigger_reason"] or "",
        agent_role=row["agent_role"] or "",
        review_score=row["review_score"],
        payload=json.loads(row["payload_json"] or "{}"),
        status=GateStatus(row["status"]),
        decision_comment=row["decision_comment"],
        decided_by=row["decided_by"],
        created_at=row["created_at"],
        decided_at=row["decided_at"],
    )


# ---------------------------------------------------------------------------
# DashboardStore — facade
# ---------------------------------------------------------------------------


class UsageStore:
    """LLM 사용량/비용 시계열."""

    def __init__(self, conn: _Connection) -> None:
        self._c = conn

    def record_event(
        self,
        *,
        timestamp: str | None = None,
        project_id: str | None = None,
        agent_role: str | None = None,
        model: str | None = None,
        tokens_in: int = 0,
        tokens_out: int = 0,
        cost_usd: float = 0.0,
        task_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> UsageEvent:
        ts = timestamp or _now_iso()
        meta_json = json.dumps(metadata or {}, ensure_ascii=False)
        with self._c.tx() as cur:
            cur.execute(
                """INSERT INTO usage_events
                (timestamp, project_id, agent_role, model, tokens_in, tokens_out,
                 cost_usd, task_id, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    ts,
                    project_id,
                    agent_role,
                    model,
                    tokens_in,
                    tokens_out,
                    cost_usd,
                    task_id,
                    meta_json,
                ),
            )
            event_id = cur.lastrowid
        return UsageEvent(
            id=event_id,
            timestamp=ts,
            project_id=project_id,
            agent_role=agent_role,
            model=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost_usd,
            task_id=task_id,
            metadata=metadata or {},
        )

    def query_timeseries(
        self,
        *,
        period: str = "daily",
        start: str | None = None,
        end: str | None = None,
        group_by: str = "none",
        project_id: str | None = None,
    ) -> list[TimeseriesPoint]:
        """기간/그룹별 시계열 집계.

        - period: "daily" | "hourly"
        - group_by: "none" | "project" | "role" | "model"
        """
        if period not in {"daily", "hourly"}:
            raise ValueError(f"unknown period: {period}")
        if group_by not in {"none", "project", "role", "model"}:
            raise ValueError(f"unknown group_by: {group_by}")

        bucket_expr = (
            "substr(timestamp, 1, 10)"  # YYYY-MM-DD
            if period == "daily"
            else "substr(timestamp, 1, 13) || ':00:00'"  # YYYY-MM-DDTHH:00:00
        )
        group_col = {
            "none": "''",
            "project": "COALESCE(project_id, '')",
            "role": "COALESCE(agent_role, '')",
            "model": "COALESCE(model, '')",
        }[group_by]

        where: list[str] = []
        params: list[Any] = []
        if start is not None:
            where.append("timestamp >= ?")
            params.append(start)
        if end is not None:
            where.append("timestamp < ?")
            params.append(end)
        if project_id is not None:
            where.append("project_id = ?")
            params.append(project_id)
        clause = f" WHERE {' AND '.join(where)}" if where else ""

        sql = (
            f"SELECT {bucket_expr} AS bucket, {group_col} AS grp, "
            "SUM(cost_usd) AS cost, "
            "SUM(tokens_in) AS tin, "
            "SUM(tokens_out) AS tout, "
            "COUNT(*) AS evt "
            f"FROM usage_events{clause} "
            "GROUP BY bucket, grp "
            "ORDER BY bucket ASC, grp ASC"
        )
        rows = self._c.query(sql, tuple(params))
        return [
            TimeseriesPoint(
                bucket=r["bucket"],
                group=r["grp"] or None if group_by != "none" else None,
                cost_usd=float(r["cost"] or 0.0),
                tokens_in=int(r["tin"] or 0),
                tokens_out=int(r["tout"] or 0),
                events=int(r["evt"] or 0),
            )
            for r in rows
        ]

    def get_summary(self, *, now_iso: str | None = None) -> UsageSummary:
        """현재 시점 기준 today/month 합계."""
        now = datetime.fromisoformat(now_iso) if now_iso else datetime.now(UTC)
        today = now.strftime("%Y-%m-%d")
        month_prefix = now.strftime("%Y-%m")
        cutoff_24h = (
            datetime.fromtimestamp(now.timestamp() - 86400, tz=UTC)
        ).isoformat()

        sum_today = self._c.query_one(
            """SELECT COALESCE(SUM(cost_usd),0) AS c, COALESCE(SUM(tokens_in)+SUM(tokens_out),0) AS t
            FROM usage_events
            WHERE substr(timestamp, 1, 10) = ?""",
            (today,),
        )
        sum_month = self._c.query_one(
            """SELECT COALESCE(SUM(cost_usd),0) AS c, COALESCE(SUM(tokens_in)+SUM(tokens_out),0) AS t
            FROM usage_events
            WHERE substr(timestamp, 1, 7) = ?""",
            (month_prefix,),
        )
        last24 = self._c.query_one(
            "SELECT COUNT(*) AS n FROM usage_events WHERE timestamp >= ?",
            (cutoff_24h,),
        )
        by_role = self._c.query(
            """SELECT COALESCE(agent_role,'unknown') AS k, SUM(cost_usd) AS v
            FROM usage_events WHERE substr(timestamp, 1, 10) = ?
            GROUP BY k""",
            (today,),
        )
        by_project = self._c.query(
            """SELECT COALESCE(project_id,'unknown') AS k, SUM(cost_usd) AS v
            FROM usage_events WHERE substr(timestamp, 1, 10) = ?
            GROUP BY k""",
            (today,),
        )

        return UsageSummary(
            today_cost_usd=float(sum_today["c"] or 0.0) if sum_today else 0.0,
            today_tokens=int(sum_today["t"] or 0) if sum_today else 0,
            month_cost_usd=float(sum_month["c"] or 0.0) if sum_month else 0.0,
            month_tokens=int(sum_month["t"] or 0) if sum_month else 0,
            last_24h_events=int(last24["n"] or 0) if last24 else 0,
            by_role_today={r["k"]: float(r["v"] or 0.0) for r in by_role},
            by_project_today={r["k"]: float(r["v"] or 0.0) for r in by_project},
        )

    def purge_older_than(self, *, before: str) -> int:
        """주어진 ISO 시각보다 오래된 이벤트를 삭제하고 개수 반환."""
        with self._c.tx() as cur:
            cur.execute("DELETE FROM usage_events WHERE timestamp < ?", (before,))
            return cur.rowcount


class BudgetStore:
    def __init__(self, conn: _Connection, usage: UsageStore) -> None:
        self._c = conn
        self._usage = usage

    def list(self) -> list[BudgetThreshold]:
        rows = self._c.query(
            "SELECT * FROM budget_thresholds ORDER BY scope, period"
        )
        return [_row_to_budget(r) for r in rows]

    def upsert(self, t: BudgetThreshold) -> BudgetThreshold:
        now = _now_iso()
        with self._c.tx() as cur:
            existing = cur.execute(
                "SELECT id, created_at FROM budget_thresholds WHERE scope = ? AND period = ?",
                (t.scope, t.period.value),
            ).fetchone()
            if existing:
                cur.execute(
                    """UPDATE budget_thresholds
                    SET limit_usd = ?, notify_email = ?, notify_webhook = ?, updated_at = ?
                    WHERE id = ?""",
                    (
                        t.limit_usd,
                        t.notify_email,
                        t.notify_webhook,
                        now,
                        existing["id"],
                    ),
                )
                tid = int(existing["id"])
                created = existing["created_at"]
            else:
                cur.execute(
                    """INSERT INTO budget_thresholds
                    (scope, period, limit_usd, notify_email, notify_webhook,
                     created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        t.scope,
                        t.period.value,
                        t.limit_usd,
                        t.notify_email,
                        t.notify_webhook,
                        now,
                        now,
                    ),
                )
                tid = int(cur.lastrowid or 0)
                created = now
        return BudgetThreshold(
            id=tid,
            scope=t.scope,
            period=t.period,
            limit_usd=t.limit_usd,
            notify_email=t.notify_email,
            notify_webhook=t.notify_webhook,
            created_at=created,
            updated_at=now,
        )

    def delete(self, threshold_id: int) -> bool:
        with self._c.tx() as cur:
            cur.execute(
                "DELETE FROM budget_thresholds WHERE id = ?", (threshold_id,)
            )
            return cur.rowcount > 0

    def status(self, *, now_iso: str | None = None) -> list[BudgetStatus]:
        thresholds = self.list()
        if not thresholds:
            return []
        now = datetime.fromisoformat(now_iso) if now_iso else datetime.now(UTC)
        today = now.strftime("%Y-%m-%d")
        month = now.strftime("%Y-%m")

        results: list[BudgetStatus] = []
        for t in thresholds:
            project_id = (
                t.scope.split(":", 1)[1]
                if t.scope.startswith("project:")
                else None
            )
            agent_role = (
                t.scope.split(":", 1)[1]
                if t.scope.startswith("role:")
                else None
            )
            where = []
            params: list[Any] = []
            if t.period == BudgetPeriod.DAILY:
                where.append("substr(timestamp, 1, 10) = ?")
                params.append(today)
            else:
                where.append("substr(timestamp, 1, 7) = ?")
                params.append(month)
            if project_id:
                where.append("project_id = ?")
                params.append(project_id)
            if agent_role:
                where.append("agent_role = ?")
                params.append(agent_role)
            row = self._c.query_one(
                f"SELECT COALESCE(SUM(cost_usd),0) AS c FROM usage_events WHERE {' AND '.join(where)}",
                tuple(params),
            )
            used = float(row["c"] or 0.0) if row else 0.0
            ratio = used / t.limit_usd if t.limit_usd > 0 else 0.0
            results.append(
                BudgetStatus(
                    threshold=t,
                    used_usd=used,
                    usage_ratio=ratio,
                    exceeded=t.limit_usd > 0 and used > t.limit_usd,
                )
            )
        return results


def _row_to_budget(row: sqlite3.Row) -> BudgetThreshold:
    return BudgetThreshold(
        id=int(row["id"]),
        scope=row["scope"],
        period=BudgetPeriod(row["period"]),
        limit_usd=float(row["limit_usd"]),
        notify_email=row["notify_email"],
        notify_webhook=row["notify_webhook"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class DashboardStore:
    """tasks + gates + usage + budgets 의 facade."""

    def __init__(self, path: str | Path | None = None) -> None:
        self._conn = _Connection(Path(path) if path else get_db_path())
        self.tasks = TaskStore(self._conn)
        self.gates = GateStore(self._conn)
        self.usage = UsageStore(self._conn)
        self.budgets = BudgetStore(self._conn, self.usage)

    def close(self) -> None:
        self._conn.close()
