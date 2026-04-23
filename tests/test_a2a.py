"""A2A 프로토콜 테스트 — 메시지, 라우터, 에이전트 통합."""

from __future__ import annotations

import pytest

from src.mcp.a2a import A2AMessage, A2AMessageType, A2APriority, A2ARouter
from src.registry.models import AgentRole


# --- A2AMessage ---


class TestA2AMessage:
    def test_create_message(self):
        msg = A2AMessage(
            message_id="a2a_001",
            from_agent="backend",
            to_agent="tester",
            subject="Test request",
            body="Please write unit tests for auth module",
        )
        assert msg.message_id == "a2a_001"
        assert msg.message_type == A2AMessageType.REQUEST
        assert msg.priority == A2APriority.NORMAL

    def test_message_with_context(self):
        msg = A2AMessage(
            message_id="a2a_002",
            from_agent="backend",
            to_agent="frontend",
            subject="API schema changed",
            body="Updated user endpoint",
            context={"endpoint": "/api/users", "method": "POST"},
            project_id="proj_1",
            task_id="task_42",
        )
        assert msg.context["endpoint"] == "/api/users"
        assert msg.project_id == "proj_1"

    def test_reply_message(self):
        msg = A2AMessage(
            message_id="a2a_003",
            from_agent="tester",
            to_agent="backend",
            message_type=A2AMessageType.RESPONSE,
            subject="Tests ready",
            body="12 tests written",
            reply_to="a2a_001",
        )
        assert msg.reply_to == "a2a_001"
        assert msg.message_type == A2AMessageType.RESPONSE


# --- A2ARouter ---


class TestA2ARouter:
    def test_send_and_receive(self):
        router = A2ARouter()
        msg = A2AMessage(
            message_id="a2a_001",
            from_agent="backend",
            to_agent="tester",
            subject="Test",
            body="Hello",
        )
        router.send(msg)
        messages = router.receive("tester")
        assert len(messages) == 1
        assert messages[0].subject == "Test"

    def test_receive_consumes_messages(self):
        router = A2ARouter()
        msg = A2AMessage(
            message_id="a2a_001",
            from_agent="backend",
            to_agent="tester",
            subject="Test",
        )
        router.send(msg)
        router.receive("tester")
        assert router.receive("tester") == []

    def test_peek_does_not_consume(self):
        router = A2ARouter()
        msg = A2AMessage(
            message_id="a2a_001",
            from_agent="backend",
            to_agent="tester",
            subject="Test",
        )
        router.send(msg)
        peeked = router.peek("tester")
        assert len(peeked) == 1
        # peek 후에도 메시지는 남아있다
        assert router.pending_count("tester") == 1

    def test_pending_count(self):
        router = A2ARouter()
        assert router.pending_count("tester") == 0

        for i in range(3):
            msg = A2AMessage(
                message_id=f"a2a_{i}",
                from_agent="backend",
                to_agent="tester",
                subject=f"Test {i}",
            )
            router.send(msg)

        assert router.pending_count("tester") == 3

    def test_broadcast(self):
        router = A2ARouter()
        # 먼저 메일박스 존재하도록 메시지를 보내 놓음
        for role in ["backend", "frontend", "tester"]:
            router._mailboxes[role] = []

        msg = A2AMessage(
            message_id="a2a_broadcast",
            from_agent="orchestrator",
            to_agent="",  # broadcast는 to_agent 무시
            message_type=A2AMessageType.BROADCAST,
            subject="System announcement",
            body="Maintenance in 10 minutes",
        )
        router.send(msg)

        # orchestrator 본인에겐 안 감
        assert router.pending_count("orchestrator") == 0
        # 나머지에겐 전달
        assert router.pending_count("backend") == 1
        assert router.pending_count("frontend") == 1
        assert router.pending_count("tester") == 1

    def test_history(self):
        router = A2ARouter()
        for i in range(5):
            msg = A2AMessage(
                message_id=f"a2a_{i}",
                from_agent="backend",
                to_agent="tester",
                subject=f"Test {i}",
                project_id="proj_1" if i < 3 else "proj_2",
            )
            router.send(msg)

        all_history = router.get_history()
        assert len(all_history) == 5

        proj1_history = router.get_history(project_id="proj_1")
        assert len(proj1_history) == 3

    def test_history_limit(self):
        router = A2ARouter()
        for i in range(10):
            msg = A2AMessage(
                message_id=f"a2a_{i}",
                from_agent="backend",
                to_agent="tester",
                subject=f"Test {i}",
            )
            router.send(msg)

        limited = router.get_history(limit=3)
        assert len(limited) == 3
        # 최근 3개
        assert limited[0].message_id == "a2a_7"

    def test_clear_specific_agent(self):
        router = A2ARouter()
        msg1 = A2AMessage(
            message_id="a2a_1",
            from_agent="backend",
            to_agent="tester",
            subject="T1",
        )
        msg2 = A2AMessage(
            message_id="a2a_2",
            from_agent="backend",
            to_agent="frontend",
            subject="T2",
        )
        router.send(msg1)
        router.send(msg2)

        router.clear("tester")
        assert router.pending_count("tester") == 0
        assert router.pending_count("frontend") == 1

    def test_clear_all(self):
        router = A2ARouter()
        for i in range(5):
            msg = A2AMessage(
                message_id=f"a2a_{i}",
                from_agent="backend",
                to_agent="tester",
                subject=f"Test {i}",
            )
            router.send(msg)

        router.clear()
        assert router.pending_count("tester") == 0
        assert router.get_history() == []


# --- BaseAgent A2A 통합 ---


class TestBaseAgentA2A:
    def test_send_a2a_without_router(self):
        from src.agents.backend import BackendAgent

        agent = BackendAgent()
        result = agent.send_a2a(
            to_agent="tester",
            subject="Test",
            body="Hello",
        )
        assert result is False

    def test_send_a2a_with_router(self):
        from src.agents.backend import BackendAgent

        router = A2ARouter()
        agent = BackendAgent(a2a_router=router)
        result = agent.send_a2a(
            to_agent="tester",
            subject="Test request",
            body="Please run tests",
            project_id="proj_1",
            task_id="task_1",
        )
        assert result is True
        messages = router.receive("tester")
        assert len(messages) == 1
        assert messages[0].subject == "Test request"
        assert messages[0].from_agent == AgentRole.BACKEND

    def test_receive_a2a_without_router(self):
        from src.agents.backend import BackendAgent

        agent = BackendAgent()
        assert agent.receive_a2a() == []

    def test_receive_a2a_with_router(self):
        from src.agents.backend import BackendAgent

        router = A2ARouter()
        agent = BackendAgent(a2a_router=router)

        # 외부에서 메시지 보냄
        msg = A2AMessage(
            message_id="a2a_ext",
            from_agent="tester",
            to_agent=AgentRole.BACKEND,
            subject="Results ready",
            body="All tests passed",
        )
        router.send(msg)

        received = agent.receive_a2a()
        assert len(received) == 1
        assert received[0].body == "All tests passed"

    def test_send_broadcast(self):
        from src.agents.backend import BackendAgent

        router = A2ARouter()
        # 메일박스 초기화
        router._mailboxes["tester"] = []
        router._mailboxes["frontend"] = []

        agent = BackendAgent(a2a_router=router)
        result = agent.send_a2a(
            to_agent="",
            subject="API changed",
            body="New endpoints added",
            message_type=A2AMessageType.BROADCAST,
        )
        assert result is True
        assert router.pending_count("tester") == 1
        assert router.pending_count("frontend") == 1
