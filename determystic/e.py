"""Main CLI entry point for the determystic tool."""


import click

from determystic.cli.validate import validate_command
from determystic.cli.new_validator import ast_validator_command
from determystic.cli.configure import configure_command


@click.group()
@click.version_option()
def cli():
    """Deterministic - Python code validation and AST analysis tools."""
    pass


# Register subcommands
cli.add_command(validate_command, name="validate")
cli.add_command(ast_validator_command, name="create-ast-validator")
cli.add_command(configure_command, name="configure")

def main():
    cli()
