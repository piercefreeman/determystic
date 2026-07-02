"""Main CLI entry point for the determystic tool."""


import importlib

import rich_click as click

# Match the shared palette in determystic.cli.ui without importing it here:
# subcommand modules pull in heavy dependencies (the agent stack,
# prompt_toolkit) that would otherwise slow down every CLI invocation.
_ACCENT = "#a78bfa"

click.rich_click.MAX_WIDTH = 100
click.rich_click.SHOW_ARGUMENTS = True
click.rich_click.STYLE_OPTION = f"bold {_ACCENT}"
click.rich_click.STYLE_ARGUMENT = f"bold {_ACCENT}"
click.rich_click.STYLE_COMMAND = f"bold {_ACCENT}"
click.rich_click.STYLE_SWITCH = "bold cyan"
click.rich_click.STYLE_USAGE = f"bold {_ACCENT}"
click.rich_click.STYLE_HELPTEXT = ""
click.rich_click.STYLE_OPTIONS_PANEL_BORDER = "grey35"
click.rich_click.STYLE_COMMANDS_PANEL_BORDER = "grey35"


# Subcommand modules are imported on first use: some of them pull in heavy
# dependencies (the agent stack, prompt_toolkit) that would otherwise slow
# down every CLI invocation.
_LAZY_COMMANDS = {
    "validate": ("determystic.cli.validate", "validate_command"),
    "new-validator": ("determystic.cli.new_validator", "new_validator_command"),
    "edit-validator": ("determystic.cli.edit_validator", "edit_validator_command"),
    "configure": ("determystic.cli.configure", "configure_command"),
    "list-validators": ("determystic.cli.list_validators", "list_validators_command"),
}


class LazyCommandGroup(click.RichGroup):
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
