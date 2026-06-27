"""Smoke test: verify all components wire together."""
import importlib
from pathlib import Path
from unittest import mock

import pytest

from onep.config import load_config
from onep.agents.registry import get_agent, list_agents, clear_registry
from onep.orchestrator.greenfield import GREENFIELD_STAGES, STAGE_PROMPTS
from onep.persistence.models import Project, ProjectMode, PipelineState, StageRun, StageStatus
from onep.persistence.state import load_state, save_state
from onep.persistence.database import init_db, insert_project, get_project, list_projects
from onep.subflows.code_review import build_code_review_graph
from onep.subflows.test_retry import build_test_retry_graph
from onep.main import cli


def test_config_loads():
    config = load_config()
    assert config.llm.default_model is not None
    assert config.pipeline.max_retries > 0


def test_all_agents_registered():
    clear_registry()
    import sys
    for mod_name in ["onep.agents.pm", "onep.agents.designer", "onep.agents.architect",
                     "onep.agents.developer", "onep.agents.tester", "onep.agents.devops",
                     "onep.agents.analyzer", "onep.agents.strategy_architect"]:
        importlib.reload(sys.modules[mod_name])

    agents = list_agents()
    for name in ["pm", "designer", "architect", "developer", "tester", "devops", "analyzer", "strategy_architect"]:
        assert name in agents, f"Agent {name} not registered"


def test_agent_instantiation():
    clear_registry()
    for mod_name in ["onep.agents.pm", "onep.agents.designer", "onep.agents.architect",
                     "onep.agents.developer", "onep.agents.tester", "onep.agents.devops",
                     "onep.agents.analyzer", "onep.agents.strategy_architect"]:
        importlib.reload(importlib.import_module(mod_name))

    for name in ["pm", "designer", "architect", "developer", "tester", "devops", "analyzer", "strategy_architect"]:
        agent = get_agent(name)
        assert agent.role is not None
        assert agent.goal is not None


def test_pipeline_stages_have_prompts():
    for stage in GREENFIELD_STAGES:
        assert stage["name"] in STAGE_PROMPTS


def test_state_save_and_load(tmp_path: Path):
    state = PipelineState(
        mode=ProjectMode.GREENFIELD,
        current_stage="developer",
        stages_completed=["pm", "designer", "architect"],
    )
    save_state(tmp_path, state)
    loaded = load_state(tmp_path)
    assert loaded.current_stage == "developer"
    assert len(loaded.stages_completed) == 3


@mock.patch("onep.persistence.database._config_dir")
def test_project_crud(mock_config_dir, tmp_path: Path):
    mock_config_dir.return_value = tmp_path
    init_db()
    p = Project(
        name="smoke-test",
        mode=ProjectMode.GREENFIELD,
        workspace_path="/tmp/test-ws",
    )
    insert_project(p)
    loaded = get_project(p.id)
    assert loaded is not None
    assert loaded.name == "smoke-test"


def test_subflow_graphs_compile():
    cr = build_code_review_graph()
    assert cr is not None

    tr = build_test_retry_graph()
    assert tr is not None


def test_cli_shows_help():
    from click.testing import CliRunner

    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "OnePTeam" in result.output


def test_cli_create_and_status_registered():
    from click.testing import CliRunner

    runner = CliRunner()
    result = runner.invoke(cli, ["create", "--help"])
    assert result.exit_code == 0
    result = runner.invoke(cli, ["status", "--help"])
    assert result.exit_code == 0
