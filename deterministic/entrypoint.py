"""Main CLI entry point for the deterministic tool."""


import click

from deterministic.cli.validate import validate_command
from deterministic.cli.new_validator import new_validator_command
from deterministic.cli.configure import configure_command
from deterministic.cli.list_validators import list_validators_command


@click.group()
@click.version_option()
def cli():
    """Deterministic - Python code validation and AST analysis tools."""
    pass


# Register subcommands
cli.add_command(validate_command, name="validate")
cli.add_command(new_validator_command, name="new-validator")
cli.add_command(configure_command, name="configure")
cli.add_command(list_validators_command, name="list-validators")
