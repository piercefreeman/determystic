"""List validators command for showing configured validators in a project."""

from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from determystic.configs.project import ProjectConfigManager

console = Console()


@click.command()
@click.argument("path", type=click.Path(path_type=Path), required=False)
def list_validators_command(path: Path | None):
    """List all validators in a determystic project."""
    # Determine target path
    if path is not None:
        ProjectConfigManager.set_runtime_custom_path(path)
    
    # Initialize project config manager
    config_manager = ProjectConfigManager.load_from_disk()
    config_path = ProjectConfigManager.get_config_path().parent
    
    # Get validator files from config
    validator_files = list(config_manager.validators.values())
    if not validator_files:
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
    table.add_column("Status", width=10)
    table.add_column("Description", width=45)
    table.add_column("Files", width=20)
    table.add_column("Created", style="dim", width=12)
    
    for validator_file in validator_files:
        # Determine file status - paths are relative to .determystic directory
        validator_file_path = config_path / validator_file.validator_path
        test_file_path = config_path / validator_file.test_path if validator_file.test_path else None
        
        # Determine validator status (active vs ignored)
        is_excluded = validator_file.name in config_manager.exclude
        status_text = "[yellow]Ignored[/yellow]" if is_excluded else "[green]Active[/green]"
        
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
        
        # Format creation date
        created_date = validator_file.created_at.strftime("%m/%d/%Y")
        
        # Truncate description if too long
        description = validator_file.description or "[dim]No description[/dim]"
        if len(description) > 42:
            description = description[:39] + "..."
        
        table.add_row(
            validator_file.name,
            status_text,
            description,
            files_text,
            created_date
        )
    
    console.print(table)
    
    # Show summary
    console.print(f"\n[dim]Found {len(validator_files)} validator(s) in {config_path}[/dim]")