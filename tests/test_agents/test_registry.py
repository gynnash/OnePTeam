import pytest
from crewai import Agent

from onep.agents.registry import register, get_agent, list_agents, clear_registry


def test_register_and_get_agent():
    clear_registry()

    @register("test_agent")
    def make_test_agent():
        return Agent(
            role="Test Role",
            goal="Test Goal",
            backstory="Test backstory",
        )

    agent = get_agent("test_agent")
    assert agent.role == "Test Role"
    assert agent.goal == "Test Goal"
    assert "test_agent" in list_agents()


def test_get_unregistered_raises():
    clear_registry()
    with pytest.raises(KeyError, match="unknown_agent"):
        get_agent("unknown_agent")


def test_list_agents():
    clear_registry()

    @register("a")
    def make_a():
        return Agent(role="A", goal="A", backstory="A")

    @register("b")
    def make_b():
        return Agent(role="B", goal="B", backstory="B")

    agents = list_agents()
    assert "a" in agents
    assert "b" in agents
