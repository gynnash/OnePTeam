"""Agent registry maps agent names to CrewAI Agent factories."""
from __future__ import annotations

from typing import Callable

from crewai import Agent

AgentFactory = Callable[[], Agent]

_registry: dict[str, AgentFactory] = {}


def register(name: str) -> Callable[[AgentFactory], AgentFactory]:
    """Decorator to register an agent factory."""
    def decorator(fn: AgentFactory) -> AgentFactory:
        _registry[name] = fn
        return fn
    return decorator


def get_agent(name: str) -> Agent:
    """Get a CrewAI Agent instance by name."""
    factory = _registry.get(name)
    if factory is None:
        raise KeyError(f"Agent '{name}' not registered. Available: {list(_registry.keys())}")
    return factory()


def list_agents() -> list[str]:
    """Return names of all registered agents."""
    return list(_registry.keys())


def clear_registry() -> None:
    """Clear the registry (for testing)."""
    _registry.clear()
