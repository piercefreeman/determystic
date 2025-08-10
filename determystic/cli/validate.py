"""Validation command for running various validators on Python projects."""

import asyncio
import sys
from pathlib import Path

import click
from rich import box
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

from determystic.configs.project import ProjectConfigManager
from determystic.io import detect_pyproject_path
from determystic.validators import (
    DynamicASTValidator,
    StaticAnalysisValidator,
)

console = Console()


@click.command()
@click.argument("path", type=click.Path(path_type=Path), required=False)
@click.option(
    "--verbose",
    is_flag=True,
    help="Show detailed output",
)
def validate_command(path: Path | None, verbose: bool):
    """Run validation on a Python project."""
    # Note: This command doesn't require API configuration
    
    # Use path detection logic to determine the target path
    target_path = detect_pyproject_path(path or Path.cwd())
    
    # Ensure the target path exists
    if not target_path or not target_path.exists():
        console.print(f"[red]Error: Path '{target_path}' does not exist.[/red]")
        sys.exit(1)
    
    # At this point target_path is guaranteed to exist
    assert target_path is not None
    asyncio.run(run_validation(target_path, verbose))


def create_status_table(validators: list, results: dict) -> Table:
    """Create a status table showing validation progress."""
    table = Table(
        show_header=True,
        header_style="bold cyan",
        box=box.ROUNDED,
        title="Validation Status",
        title_style="bold",
        expand=False,
    )
    
    table.add_column("Validator", style="cyan", width=20)
    table.add_column("Status", width=15)
    table.add_column("Result", width=60)
    
    for validator in validators:
        name = validator.display_name
        
        if validator.name in results:
            result = results[validator.name]
            if result.success:
                status = Text("✓ Passed", style="green")
                output = Text("No issues found", style="dim green")
            else:
                status = Text("✗ Failed", style="red")
                # Get first line of output for summary
                lines = result.output.strip().split("\n")
                if lines and lines[0]:
                    output = Text(lines[0][:57] + "..." if len(lines[0]) > 57 else lines[0], style="yellow")
                else:
                    output = Text("Issues detected", style="yellow")
        else:
            status = Spinner("dots", style="yellow")
            output = Text("Running...", style="dim")
        
        table.add_row(name, status, output)
    
    return table


async def run_validation(path: Path, verbose: bool):
    """Run the validation process."""
    console.print(Panel.fit(
        f"[bold cyan]Validating:[/bold cyan] {path.absolute()}",
        border_style="cyan"
    ))
    
    if path:
        ProjectConfigManager.set_runtime_custom_path(path / ".determystic")

    # Get all validators using the create_validators class method pattern
    validators = []
    
    # Add dynamic AST validators
    validators.extend(DynamicASTValidator.create_validators(path))
    
    # Add static analysis validators
    validators.extend(StaticAnalysisValidator.create_validators(path))
    
    display_validators = validators
    
    # Check if we have any validators to run
    if not display_validators:
        console.print("[yellow]No validators found to run.[/yellow]")
        return
    
    results = {}
    
    # Create live display
    with Live(create_status_table(display_validators, results), console=console, refresh_per_second=4):
        # Run validation in parallel
        tasks = []
        for validator in validators:
            async def run_and_store(v):
                result = await v.validate(path)
                results[v.name] = result
                return v.name, result
            tasks.append(run_and_store(validator))
        
        # Wait for all validations to complete
        await asyncio.gather(*tasks)
    
    # Display final results
    console.print()  # Add spacing
    
    all_passed = all(r.success for r in results.values())
    
    if all_passed:
        console.print(Panel(
            "[bold green]✓ All validations passed![/bold green]",
            border_style="green",
            box=box.ROUNDED
        ))
    else:
        console.print(Panel(
            "[bold red]✗ Some validations failed[/bold red]",
            border_style="red",
            box=box.ROUNDED
        ))
    
    # Show detailed output if verbose or if there were failures
    if verbose or not all_passed:
        console.print("\n[bold]Detailed Results:[/bold]\n")
        
        for name, result in results.items():
            validator_display = name.replace("_", " ").title()
            
            if result.success:
                if verbose:  # Only show passed validators in verbose mode
                    console.print(f"[green]✓[/green] [bold]{validator_display}[/bold]")
                    if result.output.strip():
                        console.print(f"[dim]{result.output.strip()}[/dim]")
                    console.print()
            else:
                console.print(f"[red]✗[/red] [bold]{validator_display}[/bold]")
                if result.output.strip():
                    # Indent the output for better readability
                    for line in result.output.strip().split("\n"):
                        console.print(f"  {line}")
                console.print()
    
    # Set exit code based on results
    if not all_passed:
        sys.exit(1)  # type: ignore