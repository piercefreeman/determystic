"""List validators command for showing configured validators in a project."""

import sys
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from deterministic.io import detect_project_path
from deterministic.configs.project import ProjectConfigManager

console = Console()


@click.command()
@click.argument("path", type=click.Path(path_type=Path), required=False)
def list_validators_command(path: Path | None):
    """List all validators in a deterministic project."""
    # Use path detection logic to determine the target path
    target_path = detect_project_path(path)
    
    # Ensure the target path exists
    if not target_path.exists():
        console.print(f"[red]Error: Path '{target_path}' does not exist.[/red]")
        sys.exit(1)
    
    # Initialize project config manager
    config_manager = ProjectConfigManager(target_path)
    
    # Check if project is initialized
    if not config_manager.exists():
        console.print(f"[yellow]No deterministic project found at {target_path}[/yellow]")
        console.print("[dim]Run 'deterministic new-validator' to initialize a project.[/dim]")
        sys.exit(0)
    
    # Load validators
    validators = config_manager.list_validators()
    
    if not validators:
        console.print(Panel(
            "[yellow]No validators found in this project.[/yellow]\n"
            "[dim]Run 'deterministic new-validator' to create your first validator.[/dim]",
            title="Validators",
            border_style="yellow"
        ))
        return
    
    # Create table of validators
    table = Table(
        show_header=True,
        header_style="bold cyan",
        title=f"Validators in {target_path.name}",
        title_style="bold cyan"
    )
    
    table.add_column("Name", style="cyan", width=25)
    table.add_column("Description", width=50)
    table.add_column("Files", width=20)
    table.add_column("Created", style="dim", width=12)
    
    for validator in validators:
        # Determine file status
        validator_file_path = target_path / validator.validator_path
        test_file_path = target_path / validator.test_path if validator.test_path else None
        
        files_status = []
        if validator_file_path.exists():
            files_status.append("[green]validator[/green]")
        else:
            files_status.append("[red]validator[/red]")
        
        if validator.test_path:
            if test_file_path and test_file_path.exists():
                files_status.append("[green]test[/green]")
            else:
                files_status.append("[red]test[/red]")
        
        files_text = Text.from_markup(" + ".join(files_status))
        
        # Format creation date
        created_date = validator.created_at.strftime("%m/%d/%Y")
        
        # Truncate description if too long
        description = validator.description or "[dim]No description[/dim]"
        if len(description) > 47:
            description = description[:44] + "..."
        
        table.add_row(
            validator.name,
            description,
            files_text,
            created_date
        )
    
    console.print(table)
    
    # Show summary
    console.print(f"\n[dim]Found {len(validators)} validator(s) in {config_manager.config_dir}[/dim]")