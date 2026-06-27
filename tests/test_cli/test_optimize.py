from click.testing import CliRunner
from onep.cli.optimize_cmd import optimize_cmd


def test_optimize_help():
    runner = CliRunner()
    result = runner.invoke(optimize_cmd, ["--help"])
    assert result.exit_code == 0
    assert "--max-rounds" in result.output
    assert "--auto-approve" in result.output
    assert "--max-cost" in result.output
