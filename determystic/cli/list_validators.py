"""List validators command for showing all validators in a project."""

from pathlib import Path

import rich_click as click
from rich.table import Table
from rich.text import Text

from determystic.cli import ui
from determystic.cli.common import create_all_validators, is_validator_enabled, load_project_config

console = ui.console


@click.command()
@click.argument("path", type=click.Path(path_type=Path), required=False)
def list_validators_command(path: Path | None):
    """List all validators (built-in and custom) in a determystic project."""
    # Load project configuration
    config_manager = load_project_config(path)

    ui.banner("list-validators", subtitle=str(config_manager.project_root))

    # Get all validators (built-in and custom)
    all_validators = create_all_validators(config_manager)
    custom_validators = config_manager.get_custom_validators()

    if not all_validators:
        ui.warning("No validators found in this project.")
        ui.hint("run 'determystic new-validator' to create your first validator")
        return

    # Create table of validators
    table = Table(
        box=None,
        show_header=True,
        header_style="muted.bold",
        pad_edge=False,
        padding=(0, 2, 0, 0),
    )

    table.add_column("")
    table.add_column("NAME")
    table.add_column("TYPE")
    table.add_column("DESCRIPTION", overflow="ellipsis", max_width=48)

    # Keep track of types for summary
    builtin_count = 0
    custom_count = 0

    for validator in all_validators:
        # Determine validator type and details
        is_custom = hasattr(validator, 'validator_path')
        validator_type = Text("custom", style="accent") if is_custom else Text("built-in", style="muted")

        if is_custom:
            custom_count += 1
        else:
            builtin_count += 1

        # Determine validator status (active vs ignored)
        if is_validator_enabled(validator, config_manager):
            status = Text("●", style="success")
            name_text = Text(validator.display_name)
        else:
            status = Text("○", style="muted")
            name_text = Text(validator.display_name, style="muted")

        description = _validator_description(validator, config_manager, custom_validators)

        table.add_row(status, name_text, validator_type, description)

    console.print(table)

    # Show summary
    total_validators = len(all_validators)
    active_count = len([v for v in all_validators if is_validator_enabled(v, config_manager)])

    summary_parts = []
    if builtin_count > 0:
        summary_parts.append(f"{builtin_count} built-in")
    if custom_count > 0:
        summary_parts.append(f"{custom_count} custom")

    summary = " + ".join(summary_parts) if summary_parts else "no"

    console.print()
    ui.hint(f"{total_validators} validators ({summary}) · {active_count} active")


def _validator_description(validator, config_manager, custom_validators) -> Text:
    """Build the description cell, flagging custom validators with missing files."""
    if not hasattr(validator, 'validator_path'):
        # Built-in validator
        if validator.name == "static_analysis":
            command = getattr(validator, "command", [])
            if command and command[0] == "ruff":
                return Text("Python linting with ruff", style="muted")
            if command and command[0] == "ty":
                return Text("Type checking with ty", style="muted")
            return Text("Static analysis", style="muted")
        if "hanging_functions" in validator.name:
            return Text("Detect unused definitions and unreachable code", style="muted")
        if "function_visibility" in validator.name:
            return Text("Enforce public-before-private function layout", style="muted")
        if "exception_coverage" in validator.name:
            return Text("Require test markers for except handlers", style="muted")
        return Text(f"Built-in {validator.display_name} validator", style="muted")

    # Custom validator - check file existence
    validator_file = custom_validators.get(validator.name)
    if validator_file is None:
        return Text("missing files", style="error")

    description = Text(validator_file.description or "no description", style="muted")

    missing = []
    if not config_manager.resolve_project_path(validator_file.validator_path).exists():
        missing.append("validator")
    if validator_file.test_path and not config_manager.resolve_project_path(validator_file.test_path).exists():
        missing.append("tests")
    if missing:
        description.append(f"  missing {', '.join(missing)}", style="error")

    return description
