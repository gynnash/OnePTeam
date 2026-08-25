import json

import pytest
import yaml

from onep.application import RequestContext
from onep.application.studio_model_settings import (
    global_settings_read,
    global_settings_update,
)
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
        {
            "revision": read["revision"],
            "patch": {"llm": {"default_model": "provider/next-model"}},
        },
        RequestContext(),
    )

    saved = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert saved["web"] == {"custom_key": "keep-me"}
    assert saved["llm"]["models"]["provider"]["api_key"] == "never-return-this"
    assert saved["llm"]["default_model"] == "provider/next-model"
    assert "run_defaults" not in saved
    assert "pipeline" not in saved
    assert config_path.stat().st_mode & 0o777 == 0o600


def test_global_settings_are_locked_while_jobs_are_active(tmp_path, monkeypatch):
    monkeypatch.setattr("onep.config._config_dir", lambda: tmp_path)
    store = ControlStore(tmp_path / "control.db")
    store.enqueue_job("analysis.start", {}, action_id="queued")

    with pytest.raises(Problem) as error:
        global_settings_update(store)(
            {"patch": {"execution": {"codex_model": "gpt-test"}}},
            RequestContext(),
        )

    assert error.value.code == "settings_locked_by_active_jobs"


def test_global_settings_persist_single_codex_app_server_configuration(tmp_path, monkeypatch):
    monkeypatch.setattr("onep.config._config_dir", lambda: tmp_path)
    store = ControlStore(tmp_path / "control.db")

    updated = global_settings_update(store)(
        {
            "patch": {
                "execution": {
                    "codex_model": "gpt-test",
                    "codex_auth_mode": "api_key",
                    "codex_api_key_env": "ONEP_CODEX_KEY",
                    "codex_approval_policy": "never",
                }
            }
        },
        RequestContext(),
    )

    execution = updated["settings"]["execution"]
    assert execution["codex_model"] == "gpt-test"
    assert execution["codex_api_key_env"] == "ONEP_CODEX_KEY"
    assert "api_key" not in execution


def test_global_settings_reject_removed_runtime_selectors(tmp_path, monkeypatch):
    monkeypatch.setattr("onep.config._config_dir", lambda: tmp_path)
    store = ControlStore(tmp_path / "control.db")

    with pytest.raises(Problem) as backend_error:
        global_settings_update(store)(
            {"patch": {"execution": {"backend": "legacy"}}},
            RequestContext(),
        )
    with pytest.raises(Problem) as transport_error:
        global_settings_update(store)(
            {"patch": {"execution": {"codex_transport": "sdk"}}},
            RequestContext(),
        )

    assert backend_error.value.title == "Unknown settings"
    assert transport_error.value.title == "Unknown settings"


def test_global_settings_reject_shell_invalid_api_key_environment_name(
    tmp_path, monkeypatch
):
    monkeypatch.setattr("onep.config._config_dir", lambda: tmp_path)
    store = ControlStore(tmp_path / "control.db")

    with pytest.raises(Problem) as error:
        global_settings_update(store)(
            {"patch": {"execution": {"codex_api_key_env": "1_INVALID"}}},
            RequestContext(),
        )

    assert error.value.code == "invalid_settings"
    assert error.value.title == "Invalid environment variable name"
