import pytest
from crewai import Agent
import onep.agents.registry as registry_module

from onep.agents.registry import register, get_agent, list_agents, clear_registry


@pytest.fixture(autouse=True)
def preserve_registry():
    snapshot = dict(registry_module._registry)
    yield
    registry_module._registry.clear()
    registry_module._registry.update(snapshot)


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


def test_developer_profiles_are_mode_specific():
    from onep.agents.developer import create_developer

    brownfield = create_developer(mode="brownfield")
    repair = create_developer(mode="repair")
    assert "minimal" in brownfield.goal
    assert "Repair" in repair.goal
