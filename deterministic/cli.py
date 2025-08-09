"""CLI for the deterministic validation tool."""

import asyncio
import sys
from pathlib import Path
from typing import List

import click
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from .validators import BaseValidator, StaticAnalysisValidator, ValidationResult


console = Console()


def display_results(validators: List[BaseValidator], path: Path) -> bool:
    """Display validation results in a formatted way.
    
    Args:
        validators: List of validators that were run
        path: Path that was validated
        
    Returns:
        True if all validations passed, False otherwise
    """
    # Create a summary table
    table = Table(title=f"Validation Results for {path}", show_header=True, header_style="bold magenta")
    table.add_column("Validator", style="cyan", no_wrap=True)
    table.add_column("Status", justify="center")
    table.add_column("Details", style="dim")
    
    all_success = True
    
    for validator in validators:
        if hasattr(validator, '_result'):
            result: ValidationResult = validator._result  # type: ignore
            status = "✅ Passed" if result.success else "❌ Failed"
            status_style = "green" if result.success else "red"
            all_success = all_success and result.success
            
            # Get first line of output for summary
            output_lines = result.output.strip().split("\n") if result.output else []
            details = output_lines[0][:50] + "..." if output_lines and len(output_lines[0]) > 50 else (output_lines[0] if output_lines else "No issues found")
            
            table.add_row(
                validator.display_name,
                f"[{status_style}]{status}[/{status_style}]",
                details
            )
    
    console.print("\n")
    console.print(table)
    console.print("\n")
    
    # Show detailed output for failures
    for validator in validators:
        if hasattr(validator, '_result'):
            result: ValidationResult = validator._result  # type: ignore
            if not result.success and result.output:
                console.print(Panel(
                    result.output.strip(),
                    title=f"[red]{validator.display_name} Output[/red]",
                    border_style="red",
                    expand=False
                ))
                console.print("\n")
    
    return all_success


async def run_validators(validators: List[BaseValidator], path: Path) -> bool:
    """Run all validators and store their results.
    
    Args:
        validators: List of validators to run
        path: Path to validate
        
    Returns:
        True if all validations passed, False otherwise
    """
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        transient=True,
        console=console,
    ) as progress:
        tasks = []
        for validator in validators:
            task = progress.add_task(f"[cyan]Running {validator.display_name}...", start=True)
            tasks.append(task)
        
        # Run all validators in parallel
        results = await asyncio.gather(
            *[validator.validate(path) for validator in validators]
        )
        
        # Store results on validators for display
        for validator, result, task in zip(validators, results, tasks):
            validator._result = result
            progress.update(task, completed=True)
    
    return all(result.success for result in results)


@click.command()
@click.option(
    "--path",
    type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path),
    required=True,
    help="Path to the Python project to validate"
)
def main(path: Path) -> None:
    """Validate a Python project with static analysis and AST parsing.
    
    This command runs multiple validation tools:
    - ruff: Python linter for code quality
    - ty: Fast type checker written in Rust
    - AST parser: (Coming soon)
    
    Args:
        path: Path to the Python project directory
    """
    console.print(f"\n[bold cyan]🔍 Validating Python project at:[/bold cyan] {path}\n")
    
    try:
        # Initialize validators
        validators: List[BaseValidator] = [
            StaticAnalysisValidator(),
            # ASTParserValidator() can be added when ready
        ]
        
        # Run validators
        all_success = asyncio.run(run_validators(validators, path))
        
        # Display results
        display_success = display_results(validators, path)
        
        # Exit with appropriate code
        if all_success and display_success:
            console.print("[bold green]✨ All validations passed![/bold green]\n")
            sys.exit(0)
        else:
            console.print("[bold red]❌ Some validations failed. Please review the output above.[/bold red]\n")
            sys.exit(1)
            
    except FileNotFoundError as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        console.print("\n[yellow]Make sure ruff and ty are installed:[/yellow]")
        console.print("  uv sync")
        sys.exit(1)
    except Exception as e:
        console.print(f"[bold red]Unexpected error:[/bold red] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()