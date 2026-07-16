from types import SimpleNamespace

import onep.llm.adapters as adapters
from onep.llm.adapters import LLMAdapter


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
