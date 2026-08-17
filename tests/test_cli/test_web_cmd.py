from click.testing import CliRunner

from onep.cli.web_cmd import web_cmd


def test_web_cmd_starts_server_with_flags(monkeypatch):
    calls = {}
    monkeypatch.setattr("onep.web.server.run_server",
                        lambda host=None, port=None: calls.update(host=host, port=port))
    result = CliRunner().invoke(web_cmd, ["--port", "9999"])
    assert result.exit_code == 0
    assert calls == {"host": None, "port": 9999}


def test_web_cmd_registered():
    from onep.cli import web_cmd as module
    assert any(command.name == "web" for command in module.COMMANDS)
