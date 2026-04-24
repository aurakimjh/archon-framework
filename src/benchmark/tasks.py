"""역할별 사전 정의 벤치마크 태스크."""

from __future__ import annotations

from src.benchmark.models import BenchmarkTask

# ---------------------------------------------------------------------------
# 역할별 벤치마크 태스크 정의
# ---------------------------------------------------------------------------

BACKEND_TASKS: list[BenchmarkTask] = [
    BenchmarkTask(
        task_id="bench-backend-001",
        role="backend",
        description="REST API 엔드포인트 생성",
        prompt="Write a Python FastAPI endpoint that accepts a POST request with a JSON body "
        "containing 'name' and 'email' fields, validates them, and returns a 201 response.",
        expected_keywords=["fastapi", "post", "pydantic", "201"],
        expected_patterns=[r"@app\.(post|router\.post)", r"class\s+\w+.*BaseModel"],
    ),
    BenchmarkTask(
        task_id="bench-backend-002",
        role="backend",
        description="데이터베이스 마이그레이션 스크립트",
        prompt="Write an Alembic migration script that adds a 'last_login' timestamp column "
        "to the 'users' table with a default value of the current timestamp.",
        expected_keywords=["alembic", "upgrade", "downgrade", "column"],
        expected_patterns=[r"op\.(add_column|create_table)", r"sa\.Column"],
    ),
]

FRONTEND_TASKS: list[BenchmarkTask] = [
    BenchmarkTask(
        task_id="bench-frontend-001",
        role="frontend",
        description="React 폼 컴포넌트",
        prompt="Write a React component with a login form that has email and password fields, "
        "client-side validation, and a submit handler that calls an API endpoint.",
        expected_keywords=["react", "usestate", "onsubmit", "validation"],
        expected_patterns=[r"(useState|useForm)", r"<form"],
    ),
]

TESTER_TASKS: list[BenchmarkTask] = [
    BenchmarkTask(
        task_id="bench-tester-001",
        role="tester",
        description="pytest 테스트 작성",
        prompt="Write pytest tests for a UserService class that has create_user, get_user, "
        "and delete_user methods. Include happy path and error cases.",
        expected_keywords=["pytest", "assert", "test_create", "test_get"],
        expected_patterns=[r"def test_\w+", r"@pytest\.(mark|fixture)"],
    ),
]

DEVOPS_TASKS: list[BenchmarkTask] = [
    BenchmarkTask(
        task_id="bench-devops-001",
        role="devops",
        description="Dockerfile 작성",
        prompt="Write a multi-stage Dockerfile for a Python FastAPI application that uses "
        "uv for package management, has a build stage and a runtime stage.",
        expected_keywords=["dockerfile", "from", "copy", "expose"],
        expected_patterns=[r"FROM\s+\w+", r"(WORKDIR|COPY|RUN)"],
    ),
]

DOCS_TASKS: list[BenchmarkTask] = [
    BenchmarkTask(
        task_id="bench-docs-001",
        role="docs",
        description="API 문서 작성",
        prompt="Write API documentation in Markdown for a /users endpoint that supports "
        "GET (list), POST (create), GET/:id (detail), PUT/:id (update), DELETE/:id (delete).",
        expected_keywords=["get", "post", "put", "delete", "endpoint"],
        expected_patterns=[r"##\s+", r"\|.*\|"],
    ),
]

REVIEWER_TASKS: list[BenchmarkTask] = [
    BenchmarkTask(
        task_id="bench-reviewer-001",
        role="reviewer",
        description="코드 리뷰",
        prompt="Review this Python code and identify issues:\n\n"
        "```python\n"
        "def process(data):\n"
        "    result = eval(data['expression'])\n"
        "    password = 'admin123'\n"
        "    conn = sqlite3.connect('db.sqlite')\n"
        "    conn.execute(f'INSERT INTO results VALUES ({result})')\n"
        "    return result\n"
        "```",
        expected_keywords=["eval", "sql injection", "hardcoded", "security"],
        expected_patterns=[r"(security|vulnerability|injection|eval)"],
    ),
]

# 전체 태스크 목록
ALL_BENCHMARK_TASKS: list[BenchmarkTask] = (
    BACKEND_TASKS + FRONTEND_TASKS + TESTER_TASKS + DEVOPS_TASKS + DOCS_TASKS + REVIEWER_TASKS
)


def get_tasks_for_role(role: str) -> list[BenchmarkTask]:
    """특정 역할의 벤치마크 태스크를 반환한다."""
    role_map: dict[str, list[BenchmarkTask]] = {
        "backend": BACKEND_TASKS,
        "frontend": FRONTEND_TASKS,
        "tester": TESTER_TASKS,
        "devops": DEVOPS_TASKS,
        "docs": DOCS_TASKS,
        "reviewer": REVIEWER_TASKS,
    }
    return role_map.get(role.lower(), [])
