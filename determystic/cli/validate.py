"""Validation command for running various validators on Python projects."""

import asyncio
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import rich_click as click
from rich.console import Group, RenderableType
from rich.live import Live
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

from determystic.cli import ui
from determystic.cli.common import get_active_validators
from determystic.configs.project import ProjectConfigManager
from determystic.project_discovery import ValidationTarget, discover_validation_targets
from determystic.validators.base import BaseValidator, ValidationResult

console = ui.console


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
        ui.error(f"Path '{target_path}' does not exist.")
        sys.exit(1)

    targets = discover_validation_targets(target_path)
    if not targets:
        ui.error(f"No pyproject.toml found for '{target_path}'.")
        sys.exit(1)

    asyncio.run(_run_validation_targets(targets, verbose, target_path))


def _create_status_table(
    jobs: list[ValidationJob],
    results: dict[str, ValidationResult],
    *,
    include_scope: bool,
    durations: dict[str, float] | None = None,
) -> Group:
    """Create the live checklist showing validation progress."""
    durations = durations or {}
    renderables: list[RenderableType] = []

    grouped_jobs = _jobs_by_scope(jobs) if include_scope else {"": jobs}
    for scope, scope_jobs in grouped_jobs.items():
        if include_scope:
            if renderables:
                renderables.append(Text(""))
            renderables.append(Text.assemble(("▸ ", "accent"), (scope, "bold")))

        grid = Table.grid(padding=(0, 1))
        grid.add_column(width=1, no_wrap=True)  # indent
        grid.add_column(width=1, no_wrap=True)
        grid.add_column(no_wrap=True)
        grid.add_column(overflow="ellipsis")

        for job in scope_jobs:
            name = job.validator.display_name

            if job.key in results:
                result = results[job.key]
                duration = _format_duration(durations.get(job.key))
                if result.success:
                    icon: RenderableType = Text("✓", style="success")
                    detail = Text.assemble(("no issues", "muted"), (duration, "muted"))
                else:
                    icon = Text("✗", style="error")
                    first_line = result.output.strip().split("\n")[0]
                    detail = Text.assemble((first_line, "warning"), (duration, "muted"))
            else:
                icon = Spinner("dots", style="accent")
                detail = Text("running…", style="muted")

            grid.add_row(Text(""), icon, Text(name), detail)

        renderables.append(grid)

    return Group(*renderables)


async def _run_validation_targets(
    targets: list[ValidationTarget],
    verbose: bool,
    requested_path: Path,
) -> None:
    """Run the validation process."""
    if not targets:
        ui.warning("No project scopes found to validate.")
        return

    include_scope = len(targets) > 1
    subtitle = str(requested_path.absolute())
    if include_scope:
        subtitle += f" · {len(targets)} scopes"
    ui.banner("validate", subtitle=subtitle)

    jobs = _create_validation_jobs(targets, requested_path)

    # Check if we have any validators to run
    if not jobs:
        ui.warning("No validators found to run.")
        return

    results: dict[str, ValidationResult] = {}
    durations: dict[str, float] = {}
    started_at = time.monotonic()

    # Create live display
    with Live(
        _create_status_table(jobs, results, include_scope=include_scope, durations=durations),
        console=console,
        refresh_per_second=12,
    ) as live:
        # Run validation in parallel
        tasks = []
        for job in jobs:
            async def run_and_store(current_job):
                job_started_at = time.monotonic()
                result = await current_job.validator.validate()
                durations[current_job.key] = time.monotonic() - job_started_at
                results[current_job.key] = result
                # Update the live display immediately when a validator completes
                live.update(
                    _create_status_table(
                        jobs,
                        results,
                        include_scope=include_scope,
                        durations=durations,
                    )
                )
                return current_job.key, result

            tasks.append(run_and_store(job))

        # Wait for all validations to complete
        await asyncio.gather(*tasks)

        # Final update to ensure all results are displayed
        live.update(
            _create_status_table(jobs, results, include_scope=include_scope, durations=durations)
        )

    elapsed = time.monotonic() - started_at
    failed_count = sum(1 for result in results.values() if not result.success)
    all_passed = failed_count == 0

    # Display final results
    console.print()
    if all_passed:
        console.print(Text.assemble(
            ("✓ ", "success.bold"),
            (f"{len(results)} checks passed ", "bold"),
            (f"in {elapsed:.1f}s", "muted"),
        ))
    else:
        console.print(Text.assemble(
            ("✗ ", "error.bold"),
            (f"{failed_count} of {len(results)} checks failed ", "bold"),
            (f"in {elapsed:.1f}s", "muted"),
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
    grouped_jobs = _jobs_by_scope(jobs) if include_scope else {"": jobs}
    for scope, scope_jobs in grouped_jobs.items():
        if include_scope:
            console.print()
            console.print(Text.assemble(("▸ ", "accent"), (scope, "bold")))

        for job in scope_jobs:
            result = results[job.key]
            validator_display = job.validator.display_name

            if result.success:
                if verbose:  # Only show passed validators in verbose mode
                    console.print()
                    console.print(Text.assemble(("✓ ", "success"), (validator_display, "bold")))
                    if result.output.strip():
                        console.print(Text(result.output.strip(), style="muted"))
            else:
                console.print()
                console.print(Text.assemble(("✗ ", "error"), (validator_display, "bold")))
                if result.output.strip():
                    # Indent the output for better readability
                    for line in result.output.strip().split("\n"):
                        console.print(f"  {line}")


def _jobs_by_scope(jobs: list[ValidationJob]) -> dict[str, list[ValidationJob]]:
    grouped_jobs: dict[str, list[ValidationJob]] = {}
    for job in jobs:
        grouped_jobs.setdefault(job.target_label, []).append(job)
    return grouped_jobs


def _format_duration(seconds: float | None) -> str:
    if seconds is None:
        return ""
    if seconds < 1:
        return f" · {seconds * 1000:.0f}ms"
    return f" · {seconds:.1f}s"


def _target_label(target: ValidationTarget, requested_path: Path) -> str:
    base_path = requested_path if requested_path.is_dir() else requested_path.parent
    try:
        relative_path = target.project_root.relative_to(base_path.resolve())
    except ValueError:
        return str(target.project_root)

    if relative_path == Path("."):
        return "."
    return relative_path.as_posix()
