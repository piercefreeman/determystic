"""AST validator creation command."""

import sys
from pathlib import Path
import re
from random import randint

import click
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.syntax import Syntax

from determystic.configs.project import ProjectConfigManager
from determystic.agents.local_agent import (
    LocalAgentSelectionError,
    select_local_agent,
    stream_create_validator_with_local_agent,
)
from determystic.cli.interactive import get_multiline_input, render_agent_stream
from determystic.io import async_to_sync

console = Console()


@click.command()
@click.argument("path", type=click.Path(path_type=Path), required=False)
@async_to_sync
async def new_validator_command(path: Path | None):
    """Run the interactive validator creation workflow."""
    
    if path:
        ProjectConfigManager.set_runtime_custom_path(path)

    config_manager = ProjectConfigManager.load_from_disk()
    try:
        selected_agent = select_local_agent(config_manager.settings.validator_agent)
    except LocalAgentSelectionError as e:
        console.print(f"[red]{e}[/red]")
        sys.exit(1)

    # Get code snippet from user
    console.print("\n[bold]Step 1: Provide the code snippet[/bold]")
    code_snippet = await get_multiline_input("Enter the bad Python code that your Agent generated:")
    
    if not code_snippet:
        console.print("[red]No code provided. Exiting.[/red]")
        sys.exit(1)
    
    # Display the code
    console.print("\n[bold]Your code:[/bold]")
    syntax = Syntax(code_snippet, "python", theme="monokai", line_numbers=True)
    console.print(Panel(syntax, border_style="blue"))
    
    # Get description of issues
    console.print("\n[bold]Step 2: Describe the issues[/bold]")
    console.print("[dim]What problems or issues should the validator detect in this code?[/dim]")
    issue_description = Prompt.ask("\nDescription", default="Detect all potential issues")
    
    # Get validator name
    console.print("\n[bold]Step 3: Name your validator[/bold]")
    console.print("[dim]Choose a descriptive name for this validator (e.g., 'unused_variable_detector')[/dim]")
    raw_validator_name = Prompt.ask("\nValidator name", default="custom_validator")
    
    validator_name = _format_validator_name(raw_validator_name)
    
    # Show the formatted name if it changed
    if validator_name != raw_validator_name:
        console.print(f"[dim]Formatted validator name: {validator_name}[/dim]")
    
    # Check if validator already exists
    existing_validators = list(config_manager.get_custom_validators().values())
    if any(v.name == validator_name for v in existing_validators):
        if not Prompt.ask(f"\n[yellow]Validator '{validator_name}' already exists. Overwrite?[/yellow]", choices=["y", "n"], default="n") == "y":
            console.print("[red]Operation cancelled.[/red]")
            sys.exit(0)
    
    # Confirm before proceeding
    console.print("\n[bold]Summary:[/bold]")
    console.print(f"  • Validator name: {validator_name}")
    console.print(f"  • Code length: {len(code_snippet)} characters")
    console.print(f"  • Issues to detect: {issue_description}")
    
    if not Prompt.ask("\n[yellow]Proceed with creating the validator?[/yellow]", choices=["y", "n"], default="y") == "y":
        console.print("[red]Operation cancelled.[/red]")
        sys.exit(0)
    
    # Run the agent
    console.print(f"\n[bold cyan]🤖 Starting AST Validator Agent ({selected_agent})...[/bold cyan]")
    console.print("[dim]This may take a few moments as the agent creates and tests the validator.[/dim]\n")
    
    final_event = await render_agent_stream(
        stream_create_validator_with_local_agent(
            user_code=code_snippet,
            requirements=issue_description,
            agent_name=selected_agent,
        )
    )

    if not final_event:
        console.print("\n[red]Error: No final event received from the agent.[/red]")
        sys.exit(1)
    
    console.print("\n[bold green]✅ Agent completed successfully![/bold green]")
    console.print(Panel(final_event.content, title="Final Result", border_style="green"))
    
    validation_contents = final_event.deps.validation_contents
    test_contents = final_event.deps.test_contents
    
    # Process generated files from agent virtual contents
    if validation_contents or test_contents:
        console.print("\n[bold]Processing generated files...[/bold]")
        
        if validation_contents:
            console.print("  • Generated validator code")
        if test_contents:
            console.print("  • Generated test code")
        
        # Save validator files and track them in pyproject.toml
        if validation_contents:
            try:
                validator_file = config_manager.new_validation(
                    name=validator_name,
                    validator_script=validation_contents,
                    test_script=test_contents or "",
                    description=issue_description
                )
                
                # Save the config to disk
                config_manager.save_to_disk()
                
                console.print("\n[bold green]✅ Validator saved successfully![/bold green]")
                console.print(f"  • Validator: {validator_file.validator_path}")
                if validator_file.test_path:
                    console.print(f"  • Test: {validator_file.test_path}")
                
                # Show preview of the validator
                lines = validation_contents.split("\n")[:10]
                preview = "\n".join(lines)
                if len(validation_contents.split("\n")) > 10:
                    preview += "\n..."
                
                syntax = Syntax(preview, "python", theme="monokai", line_numbers=False)
                console.print(Panel(syntax, title=f"Preview: {validator_name}", border_style="green"))
                
            except Exception as e:
                console.print(f"[red]Error saving validator files: {e}[/red]")
    else:
        console.print("\n[yellow]Warning: No files were generated by the agent.[/yellow]")


def _format_validator_name(raw_validator_name: str) -> str:
    """
    Auto-format the name to be valid (replace spaces with hyphens, keep only valid chars)
    """
    # Replace spaces with hyphens, keep only letters, numbers, hyphens, and underscores
    validator_name = re.sub(r'[^a-zA-Z0-9_-]', '-', raw_validator_name.strip())
    # Replace multiple consecutive hyphens with single hyphen
    validator_name = re.sub(r'-+', '-', validator_name)
    # Remove leading/trailing hyphens
    validator_name = validator_name.strip('-')

    # Ensure the name is not empty after formatting
    if not validator_name:
        validator_name = f"custom_validator_{randint(1000, 9999)}"

    return validator_name
