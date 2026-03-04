"""Tests for collector module."""

from agentic_metric.collectors import CollectorRegistry, BaseCollector
from agentic_metric.models import LiveSession


class MockCollector(BaseCollector):
    @property
    def agent_type(self) -> str:
        return "mock"

    def get_live_sessions(self) -> list[LiveSession]:
        return [
            LiveSession(
                session_id="test-1",
                agent_type="mock",
                project_path="/test/project",
                user_turns=5,
                output_tokens=1000,
            )
        ]

    def sync_history(self, db) -> None:
        pass


def test_registry_register():
    registry = CollectorRegistry()
    collector = MockCollector()
    registry.register(collector)
    assert len(registry.get_all()) == 1
    assert registry.get_all()[0].agent_type == "mock"


def test_registry_get_live_sessions():
    registry = CollectorRegistry()
    registry.register(MockCollector())
    sessions = registry.get_live_sessions()
    assert len(sessions) == 1
    assert sessions[0].session_id == "test-1"
    assert sessions[0].agent_type == "mock"


def test_live_session_total_tokens():
    s = LiveSession(
        session_id="x",
        agent_type="test",
        project_path="/test",
        input_tokens=100,
        output_tokens=200,
    )
    assert s.total_tokens == 300


def test_live_session_duration():
    s = LiveSession(
        session_id="x",
        agent_type="test",
        project_path="/test",
        started="2025-01-01T10:00:00Z",
        last_active="2025-01-01T10:30:00Z",
    )
    assert abs(s.duration_minutes - 30.0) < 0.1
