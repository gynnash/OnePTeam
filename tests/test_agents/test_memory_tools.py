import pytest

from onep.agents.analyzer import create_analyzer
from onep.agents.architect import create_architect
from onep.agents.designer import create_designer
from onep.agents.developer import create_developer
from onep.agents.devops import create_devops
from onep.agents.pm import create_pm
from onep.agents.strategy_architect import create_strategy_architect
from onep.agents.tester import create_tester


@pytest.mark.parametrize("factory", [
    create_pm,
    create_designer,
    create_architect,
    create_developer,
    create_tester,
    create_devops,
    create_analyzer,
    create_strategy_architect,
])
def test_business_agents_accept_context_and_have_memory_tool(factory, tmp_path):
    agent = factory(
        workspace=str(tmp_path),
        source_id="greenfield:demo",
    )

    assert any(tool.name == "memory" for tool in agent.tools)
