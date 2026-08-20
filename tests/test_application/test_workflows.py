from types import SimpleNamespace

import pytest

from onep.application import RequestContext
from onep.application.workflows import analysis_handler, optimization_handler
from onep.domain import Problem
from onep.infrastructure import ControlStore


class Process:
    def __init__(self, code=0):
        self.stdout = iter(["first line\n", "done\n"])
        self.code = code

    def wait(self):
        return self.code


def test_analysis_uses_fixed_argument_list_and_streams_events(tmp_path, monkeypatch):
    store = ControlStore(tmp_path / "control.db")
    captured = {}
    monkeypatch.setattr(
        "onep.application.workflows.subprocess.Popen",
        lambda command, **kwargs: captured.update(command=command, kwargs=kwargs)
        or Process(),
    )

    result = analysis_handler(store)(
        {"source": "repo; echo unsafe", "name": "review"},
        RequestContext(trace_id="trace"),
    )

    assert captured["command"][-2:] == ["--name", "review"]
    assert "repo; echo unsafe" in captured["command"]
    assert captured["kwargs"].get("shell") is None
    assert result["exit_code"] == 0
    assert [event["type"] for event in store.events()] == [
        "workflow.output", "workflow.output"
    ]


def test_optimization_failure_returns_stable_problem(tmp_path, monkeypatch):
    store = ControlStore(tmp_path / "control.db")
    monkeypatch.setattr(
        "onep.application.workflows.subprocess.Popen",
        lambda *args, **kwargs: Process(2),
    )

    with pytest.raises(Problem) as error:
        optimization_handler(store)(
            {"source": str(tmp_path)}, SimpleNamespace(
                trace_id="trace", project_id="", run_id=""
            )
        )

    assert error.value.code == "workflow_failed"
    assert "done" in error.value.detail
