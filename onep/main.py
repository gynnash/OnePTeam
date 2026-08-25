"""OnePTeam CLI entry point."""
import click

from onep.cli import register_commands


@click.group()
@click.version_option(version="0.1.0", prog_name="onep")
def cli():
    """OnePTeam -- from one sentence to product, code, and reusable knowledge."""
    pass


register_commands(cli)


if __name__ == "__main__":
    cli()
