"""Collector plugin architecture."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import LiveSession


class BaseCollector(ABC):
    """Abstract base class for agent collectors."""

    @property
    @abstractmethod
    def agent_type(self) -> str:
        """Unique identifier for this agent type (e.g., 'claude_code')."""

    @abstractmethod
    def get_live_sessions(self) -> list[LiveSession]:
        """Return currently active sessions."""

    @abstractmethod
    def sync_history(self, db) -> None:
        """Sync historical data into the database."""


class CollectorRegistry:
    """Registry of all available collectors."""

    def __init__(self) -> None:
        self._collectors: list[BaseCollector] = []

    def register(self, collector: BaseCollector) -> None:
        self._collectors.append(collector)

    def get_all(self) -> list[BaseCollector]:
        return list(self._collectors)

    def get_live_sessions(self) -> list[LiveSession]:
        """Get live sessions from all registered collectors."""
        sessions: list[LiveSession] = []
        for collector in self._collectors:
            try:
                sessions.extend(collector.get_live_sessions())
            except Exception:
                pass
        sessions.sort(key=lambda s: s.last_active, reverse=True)
        return sessions

    def sync_all(self, db) -> None:
        """Sync all collectors' history into the database."""
        for collector in self._collectors:
            try:
                collector.sync_history(db)
            except Exception:
                pass


def create_default_registry() -> CollectorRegistry:
    """Create a registry with all available collectors."""
    registry = CollectorRegistry()

    from .claude_code import ClaudeCodeCollector
    registry.register(ClaudeCodeCollector())

    from .cursor import CursorCollector
    registry.register(CursorCollector())

    return registry
