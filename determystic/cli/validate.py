"""Validation command for running various validators on Python projects."""

import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path

import click
from rich import box
from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.panel import Panel
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

from determystic.cli.common import get_active_validators
from determystic.configs.project import ProjectConfigManager
from determystic.project_discovery import ValidationTarget, discover_validation_targets
from determystic.validators.base import BaseValidator, ValidationResult

console = Console()


@dataclass(frozen=True)
class ValidationJob:
    """One validator running against one project scope."""

    key: str
    validator: BaseValidator
    target_label: str


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

    target_path = (path or Path.cwd()).resolve()

    # Ensure the target path exists
    if not target_path.exists():
        console.print(f"[red]Error: Path '{target_path}' does not exist.[/red]")
        sys.exit(1)

    targets = discover_validation_targets(target_path)
    if not targets:
        console.print(
            f"[red]Error: No pyproject.toml found for '{target_path}'.[/red]"
        )
        sys.exit(1)

    asyncio.run(_run_validation_targets(targets, verbose, target_path))


def _create_status_table(
    jobs: list[ValidationJob],
    results: dict[str, ValidationResult],
    *,
    include_scope: bool,
) -> Table | Group:
    """Create a status table showing validation progress."""
    if include_scope:
        renderables: list[RenderableType] = [Text("Validation Status", style="bold")]
        for scope, scope_jobs in _jobs_by_scope(jobs).items():
            if len(renderables) > 1:
                renderables.append(Text(""))
            renderables.append(
                _create_scope_status_table(
                    scope_jobs,
                    results,
                    title=f"Scope: {scope}",
                )
            )
        return Group(*renderables)

    return _create_scope_status_table(
        jobs,
        results,
        title="Validation Status",
    )


def _create_scope_status_table(
    jobs: list[ValidationJob],
    results: dict[str, ValidationResult],
    *,
    title: str,
) -> Table:
    """Create a status table for one validation scope."""
    table = Table(
        show_header=True,
        header_style="bold cyan",
        box=box.ROUNDED,
        title=title,
        title_style="bold",
        expand=False,
    )

    table.add_column("Validator", style="cyan", width=20, no_wrap=True)
    table.add_column("Status", width=6, min_width=6, no_wrap=True)
    table.add_column("Result", ratio=1)

    for job in jobs:
        name = job.validator.display_name

        if job.key in results:
            result = results[job.key]
            if result.success:
                status = Text("✓", style="green")
                output = Text("No issues found", style="dim green")
            else:
                status = Text("✗", style="red")
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


def _jobs_by_scope(jobs: list[ValidationJob]) -> dict[str, list[ValidationJob]]:
    grouped_jobs: dict[str, list[ValidationJob]] = {}
    for job in jobs:
        grouped_jobs.setdefault(job.target_label, []).append(job)
    return grouped_jobs


async def _run_validation_targets(
    targets: list[ValidationTarget],
    verbose: bool,
    requested_path: Path,
) -> None:
    """Run the validation process."""
    if not targets:
        console.print("[yellow]No project scopes found to validate.[/yellow]")
        return

    include_scope = len(targets) > 1
    if include_scope:
        scope_lines = "\n".join(
            f"  • {_target_label(target, requested_path)}"
            for target in targets
        )
        console.print(
            Panel.fit(
                (
                    f"[bold cyan]Validating {len(targets)} project scopes under:[/bold cyan] "
                    f"{requested_path.absolute()}\n{scope_lines}"
                ),
                border_style="cyan",
            )
        )
    else:
        console.print(
            Panel.fit(
                f"[bold cyan]Validating:[/bold cyan] {targets[0].project_root.absolute()}",
                border_style="cyan",
            )
        )

    jobs = _create_validation_jobs(targets, requested_path)

    # Check if we have any validators to run
    if not jobs:
        console.print("[yellow]No validators found to run.[/yellow]")
        return

    results: dict[str, ValidationResult] = {}

    # Create live display
    with Live(
        _create_status_table(jobs, results, include_scope=include_scope),
        console=console,
        refresh_per_second=4,
    ) as live:
        # Run validation in parallel
        tasks = []
        for job in jobs:
            async def run_and_store(current_job):
                result = await current_job.validator.validate()
                results[current_job.key] = result
                # Update the live display immediately when a validator completes
                live.update(
                    _create_status_table(
                        jobs,
                        results,
                        include_scope=include_scope,
                    )
                )
                return current_job.key, result

            tasks.append(run_and_store(job))

        # Wait for all validations to complete
        await asyncio.gather(*tasks)

        # Final update to ensure all results are displayed
        live.update(
            _create_status_table(jobs, results, include_scope=include_scope)
        )

        # Give a brief moment for users to see the final status
        await asyncio.sleep(0.5)

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
        _print_detailed_results(
            jobs,
            results,
            verbose=verbose,
            include_scope=include_scope,
        )

    # Set exit code based on results
    if not all_passed:
        sys.exit(1)


def _create_validation_jobs(
    targets: list[ValidationTarget],
    requested_path: Path,
) -> list[ValidationJob]:
    jobs: list[ValidationJob] = []
    for target in targets:
        project_config = ProjectConfigManager.load_from_config_path(
            target.config_path,
            project_root=target.project_root,
            extra_ignore_paths=target.extra_ignore_paths,
        )
        validators = get_active_validators(project_config)
        target_label = _target_label(target, requested_path)
        for validator_index, validator in enumerate(validators):
            jobs.append(
                ValidationJob(
                    key=f"{len(jobs)}:{target_label}:{validator_index}:{validator.name}",
                    validator=validator,
                    target_label=target_label,
                )
            )
    return jobs


def _print_detailed_results(
    jobs: list[ValidationJob],
    results: dict[str, ValidationResult],
    *,
    verbose: bool,
    include_scope: bool,
) -> None:
    console.print("\n[bold]Detailed Results:[/bold]\n")

    grouped_jobs = _jobs_by_scope(jobs) if include_scope else {"": jobs}
    for scope_index, (scope, scope_jobs) in enumerate(grouped_jobs.items()):
        if include_scope:
            if scope_index > 0:
                console.print()
            console.print(f"[bold cyan]Scope: {scope}[/bold cyan]")

        for job in scope_jobs:
            result = results[job.key]
            validator_display = job.validator.display_name

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


def _target_label(target: ValidationTarget, requested_path: Path) -> str:
    base_path = requested_path if requested_path.is_dir() else requested_path.parent
    try:
        relative_path = target.project_root.relative_to(base_path.resolve())
    except ValueError:
        return str(target.project_root)

    if relative_path == Path("."):
        return "."
    return relative_path.as_posix()
