from types import SimpleNamespace

import onep.llm.adapters as adapters
from onep.llm.adapters import LLMAdapter, _is_broad_pytest_command


class Tool:
    name = "file_read"
    description = "read"

    def __init__(self):
        self.calls = 0

    def _run(self, path: str):
        return path

    def run(self, **kwargs):
        self.calls += 1
        return "same result"


def chunk(call_id):
    function = SimpleNamespace(
        name="file_read", arguments='{"path": "a.py"}'
    )
    tool_call = SimpleNamespace(index=0, id=call_id, function=function)
    delta = SimpleNamespace(content=None, tool_calls=[tool_call])
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta)])


def test_adapter_stops_before_third_identical_tool_call(monkeypatch):
    counter = {"value": 0}

    def completion(**kwargs):
        counter["value"] += 1
        return [chunk(f"call-{counter['value']}")]

    monkeypatch.setattr(adapters, "completion", completion)
    monkeypatch.setattr(adapters, "resolve_model", lambda stage: ("model", "provider"))
    monkeypatch.setattr(adapters, "get_api_key", lambda provider: "")
    monkeypatch.setattr(adapters, "get_api_base", lambda provider: "")
    tool = Tool()
    trajectory = []
    events = list(LLMAdapter().invoke_with_tools_stream(
        system_prompt="system",
        user_prompt="user",
        tools=[tool],
        stage_name="developer",
        trajectory_sink=trajectory.append,
    ))
    assert tool.calls == 2
    assert any(event["type"] == "stuck" for event in events)
    assert trajectory[-1]["type"] == "loop_stuck"


def test_broad_pytest_detection_allows_focused_files():
    assert _is_broad_pytest_command("pytest -q")
    assert _is_broad_pytest_command(
        "cd /tmp/project && python -m pytest tests/ -q | tail -20"
    )
    assert _is_broad_pytest_command(
        "python -m pytest tests/ -q --tb=short 2>&1 | tail -40"
    )
    assert not _is_broad_pytest_command(
        "python -m pytest tests/test_api.py::test_create -q"
    )


class ShellTool:
    name = "shell"
    description = "shell"

    def __init__(self):
        self.calls = 0

    def _run(self, command: str):
        return command

    def run(self, **kwargs):
        self.calls += 1
        return "executed"


def test_adapter_blocks_full_suite_and_nudges_toward_implementation(monkeypatch):
    counter = {"value": 0}

    def shell_chunk(call_id):
        function = SimpleNamespace(
            name="shell", arguments='{"command": "pytest -q"}'
        )
        tool_call = SimpleNamespace(index=0, id=call_id, function=function)
        delta = SimpleNamespace(content="先检查现状。", tool_calls=[tool_call])
        return SimpleNamespace(choices=[SimpleNamespace(delta=delta)])

    def completion(**kwargs):
        counter["value"] += 1
        if counter["value"] == 1:
            return [shell_chunk("call-1")]
        delta = SimpleNamespace(content="现在开始批量实现。", tool_calls=None)
        return [SimpleNamespace(choices=[SimpleNamespace(delta=delta)])]

    monkeypatch.setattr(adapters, "completion", completion)
    monkeypatch.setattr(adapters, "resolve_model", lambda stage: ("model", "provider"))
    monkeypatch.setattr(adapters, "get_api_key", lambda provider: "")
    monkeypatch.setattr(adapters, "get_api_base", lambda provider: "")
    tool = ShellTool()
    trajectory = []

    list(LLMAdapter().invoke_with_tools_stream(
        system_prompt="system", user_prompt="user", tools=[tool],
        stage_name="developer", trajectory_sink=trajectory.append,
        mutation_nudge_round=1, block_full_test_commands=True,
    ))

    assert tool.calls == 0
    event_types = [event["type"] for event in trajectory]
    assert "full_test_blocked" in event_types
    assert "implementation_nudge" in event_types
    assert event_types.count("model_message") == 2
