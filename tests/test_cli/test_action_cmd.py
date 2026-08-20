import json

from click.testing import CliRunner

from onep.main import cli


def test_capabilities_lists_shared_contract(tmp_path, monkeypatch):
    monkeypatch.setattr("onep.persistence.database._config_dir", lambda: tmp_path)

    result = CliRunner().invoke(cli, ["capabilities"])

    assert result.exit_code == 0
    ids = {item["id"] for item in json.loads(result.output)["capabilities"]}
    assert {"project.create", "run.start", "artifact.read"} <= ids


def test_action_rejects_non_object_payload(tmp_path, monkeypatch):
    monkeypatch.setattr("onep.persistence.database._config_dir", lambda: tmp_path)

    result = CliRunner().invoke(
        cli, ["action", "project.list", "--payload", "[]"]
    )

    assert result.exit_code != 0
    assert "JSON object" in result.output
