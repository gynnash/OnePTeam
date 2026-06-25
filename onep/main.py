"""OnePTeam CLI entry point."""
import click


@click.group()
@click.version_option(version="0.1.0", prog_name="onep")
def cli():
    """OnePTeam -- Multi-Agent Full-Stack Software Development Team."""
    pass
