import json
from types import SimpleNamespace

import pytest
import yaml

from onep.application import RequestContext
from onep.application.defaults import _run_handler
from onep.application.settings import global_settings_read, global_settings_update
from onep.domain import Problem
from onep.infrastructure import ControlStore


def test_global_settings_redact_secrets_and_preserve_unknown_sections(tmp_path, monkeypatch):
    monkeypatch.setattr("onep.config._config_dir", lambda: tmp_path)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump({
            "llm": {
                "default_model": "provider/model",
                "default_provider": "provider",
                "complex_model": "provider/model-pro",
                "complex_provider": "provider",
                "models": {"provider": {"api_key": "never-return-this"}},
            },
            "web": {"custom_key": "keep-me"},
        }),
        encoding="utf-8",
    )
    store = ControlStore(tmp_path / "control.db")

    read = global_settings_read({}, RequestContext())
    assert "never-return-this" not in json.dumps(read)
    assert read["settings"]["llm"]["providers"]["provider"]["configured"] is True

    global_settings_update(store)(
        {"revision": read["revision"], "patch": {"run_defaults": {"max_rounds": 12}}},
        RequestContext(),
    )

    saved = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert saved["web"] == {"custom_key": "keep-me"}
    assert saved["llm"]["models"]["provider"]["api_key"] == "never-return-this"
    assert saved["run_defaults"]["max_rounds"] == 12
    assert config_path.stat().st_mode & 0o777 == 0o600


def test_global_settings_are_locked_while_jobs_are_active(tmp_path, monkeypatch):
    monkeypatch.setattr("onep.config._config_dir", lambda: tmp_path)
    store = ControlStore(tmp_path / "control.db")
    store.enqueue_job("analysis.start", {}, action_id="queued")

    with pytest.raises(Problem) as error:
        global_settings_update(store)(
            {"patch": {"pipeline": {"test_timeout": 60}}}, RequestContext()
        )

    assert error.value.code == "settings_locked_by_active_jobs"


def test_resume_without_options_does_not_override_project_defaults(tmp_path, monkeypatch):
    store = ControlStore(tmp_path / "control.db")
    project = SimpleNamespace(
        id="project-1",
        name="demo",
        status=SimpleNamespace(value="completed"),
        current_stage="stop",
    )
    captured = []
    monkeypatch.setattr("onep.application.defaults.resolve_project", lambda _ref: project)
    monkeypatch.setattr(
        "onep.orchestrator.runner.run_pipeline",
        lambda _name, options=None: captured.append(options) or True,
    )

    result = _run_handler(store, resume=True)(
        {"project": project.id}, RequestContext(trace_id="trace")
    )

    assert result["completed"] is True
    assert captured == [None]
