from click.testing import CliRunner

from onep.main import cli


def test_status_no_projects():
    runner = CliRunner()
    result = runner.invoke(cli, ["status"])
    assert result.exit_code == 0


def test_show_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["show", "--help"])
    assert result.exit_code == 0
