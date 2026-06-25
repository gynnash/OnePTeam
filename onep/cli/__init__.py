"""CLI command modules. Each file exports a COMMANDS list, auto-discovered by main.py."""
from __future__ import annotations

import importlib
import pkgutil


def register_commands(cli) -> None:
    """Auto-discover all command modules and register their exported commands."""
    package = __package__  # "onep.cli"
    for _, module_name, _ in pkgutil.iter_modules([__path__[0]]):
        mod = importlib.import_module(f".{module_name}", package)
        if hasattr(mod, "COMMANDS"):
            for cmd in mod.COMMANDS:
                cli.add_command(cmd)
