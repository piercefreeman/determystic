"""Main CLI entry point for the determystic tool."""

import sys
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel

from determystic.configs.global import get_settings

console = Console()


@click.group()
@click.version_option()
def cli():
    """Deterministic - Python code validation and AST analysis tools."""
    pass


def check_configuration() -> bool:
    """Check if the tool is configured, show error if not."""
    try:
        settings = get_settings()
        if not settings.is_configured():
            console.print(Panel(
                "[bold red]Configuration Required[/bold red]\n\n"
                "This tool requires an Anthropic API key to function.\n"
                "Please run the configuration wizard:\n\n"
                "[bold cyan]determystic configure[/bold cyan]",
                border_style="red"
            ))
            return False
        return True
    except Exception as e:
        console.print(f"[red]Error loading configuration: {e}[/red]")
        return False


# Import subcommands
from determystic.cli.validate import validate_command
from determystic.cli.new_validator import ast_validator_command
from determystic.cli.configure import configure_command

# Register subcommands
cli.add_command(validate_command, name="validate")
cli.add_command(ast_validator_command, name="create-ast-validator")
cli.add_command(configure_command, name="configure")


def main():
    """Main entry point for the CLI."""
    cli()


if __name__ == "__main__":
    main()