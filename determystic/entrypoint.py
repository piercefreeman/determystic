"""Main CLI entry point for the determystic tool."""


import importlib

import click


# Subcommand modules are imported on first use: some of them pull in heavy
# dependencies (the agent stack, prompt_toolkit) that would otherwise slow
# down every CLI invocation.
_LAZY_COMMANDS = {
    "validate": ("determystic.cli.validate", "validate_command"),
    "new-validator": ("determystic.cli.new_validator", "new_validator_command"),
    "configure": ("determystic.cli.configure", "configure_command"),
    "list-validators": ("determystic.cli.list_validators", "list_validators_command"),
}


class LazyCommandGroup(click.Group):
    """Click group that defers importing subcommand modules until needed."""

    def list_commands(self, ctx: click.Context) -> list[str]:  # determystic: used
        return sorted(_LAZY_COMMANDS)

    def get_command(self, ctx: click.Context, cmd_name: str) -> click.Command | None:  # determystic: used
        target = _LAZY_COMMANDS.get(cmd_name)
        if target is None:
            return None
        module_name, attribute = target
        return getattr(importlib.import_module(module_name), attribute)


@click.group(cls=LazyCommandGroup)
@click.version_option()
def cli():
    """Deterministic - Python code validation and AST analysis tools."""
    pass
