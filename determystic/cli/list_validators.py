"""List validators command for showing all validators in a project."""

from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from determystic.cli.common import create_all_validators, load_project_config

console = Console()


@click.command()
@click.argument("path", type=click.Path(path_type=Path), required=False)
def list_validators_command(path: Path | None):
    """List all validators (built-in and custom) in a determystic project."""
    # Load project configuration
    config_manager = load_project_config(path)
    config_path = config_manager.get_config_path().parent if hasattr(config_manager, 'get_config_path') else None
    
    # Get all validators (built-in and custom)
    all_validators = create_all_validators(config_manager)
    
    if not all_validators:
        console.print(Panel(
            "[yellow]No validators found in this project.[/yellow]\n"
            "[dim]Run 'determystic new-validator' to create your first validator.[/dim]",
            title="Validators",
            border_style="yellow"
        ))
        return
    
    # Create table of validators
    table = Table(
        show_header=True,
        header_style="bold cyan",
        title="Validators",
        title_style="bold cyan"
    )
    
    table.add_column("Name", style="cyan", width=25)
    table.add_column("Type", width=12)
    table.add_column("Status", width=10)
    table.add_column("Description", width=40)
    table.add_column("Files", width=15)
    
    # Keep track of types for summary
    builtin_count = 0
    custom_count = 0
    
    for validator in all_validators:
        # Determine validator type and details
        is_custom = hasattr(validator, 'validator_path')
        validator_type = "[blue]Custom[/blue]" if is_custom else "[cyan]Built-in[/cyan]"
        
        if is_custom:
            custom_count += 1
        else:
            builtin_count += 1
        
        # Determine validator status (active vs ignored)
        is_excluded = validator.display_name in config_manager.exclude
        status_text = "[yellow]Ignored[/yellow]" if is_excluded else "[green]Active[/green]"
        
        # Handle description and files for custom vs built-in validators
        if is_custom:
            # Custom validator - check file existence
            validator_file = config_manager.validators.get(validator.name)
            if validator_file and config_path:
                validator_file_path = config_path / validator_file.validator_path
                test_file_path = config_path / validator_file.test_path if validator_file.test_path else None
                
                files_status = []
                if validator_file_path.exists():
                    files_status.append("[green]validator[/green]")
                else:
                    files_status.append("[red]validator[/red]")
                
                if validator_file.test_path:
                    if test_file_path and test_file_path.exists():
                        files_status.append("[green]test[/green]")
                    else:
                        files_status.append("[red]test[/red]")
                
                files_text = Text.from_markup(" + ".join(files_status))
                description = validator_file.description or "[dim]No description[/dim]"
            else:
                files_text = Text.from_markup("[red]missing[/red]")
                description = "[dim]No description[/dim]"
        else:
            # Built-in validator
            files_text = Text.from_markup("[blue]built-in[/blue]")
            # Add descriptions for built-in validators
            if "ruff" in validator.name:
                description = "Python linting with ruff"
            elif "ty" in validator.name:
                description = "Type checking with ty"
            elif "hanging_functions" in validator.name:
                description = "Detect hanging function calls"
            else:
                description = f"Built-in {validator.display_name} validator"
        
        # Truncate description if too long
        if len(description) > 37:
            description = description[:34] + "..."
        
        table.add_row(
            validator.display_name,
            validator_type,
            status_text,
            description,
            files_text
        )
    
    console.print(table)
    
    # Show summary
    total_validators = len(all_validators)
    active_count = len([v for v in all_validators if v.display_name not in config_manager.exclude])
    
    summary_parts = []
    if builtin_count > 0:
        summary_parts.append(f"{builtin_count} built-in")
    if custom_count > 0:
        summary_parts.append(f"{custom_count} custom")
    
    summary = " + ".join(summary_parts) if summary_parts else "no"
    
    console.print(f"\n[dim]Found {total_validators} validator(s) ({summary}) • {active_count} active[/dim]")