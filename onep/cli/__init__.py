"""Web-first CLI surface for the direct-cutover Product Studio."""


def register_commands(cli) -> None:
    """Register the Product Studio command surface."""
    from onep.cli.studio_cmd import COMMANDS as STUDIO_COMMANDS
    from onep.cli.web_cmd import COMMANDS as WEB_COMMANDS

    for command in (*WEB_COMMANDS, *STUDIO_COMMANDS):
        cli.add_command(command)
