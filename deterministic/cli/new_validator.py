"""AST validator creation command."""

import asyncio
import os
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.syntax import Syntax

from deterministic.io import detect_project_path
from deterministic.configs.project import ProjectConfigManager
from deterministic.configs.system import DeterministicSettings
from deterministic.agents.create_validator import stream_create_validator

console = Console()


def check_configuration() -> bool:
    """Check if the system configuration is valid."""
    try:
        settings = DeterministicSettings.load_from_disk()
        return bool(settings.anthropic_api_key)
    except Exception:
        return False


def get_settings() -> DeterministicSettings:
    """Get the system settings."""
    return DeterministicSettings.load_from_disk()


def get_multiline_input(prompt_text: str) -> str:
    """Get multiline input from the user.
    
    Args:
        prompt_text: The prompt to display
        
    Returns:
        The user's multiline input
    """
    console.print(f"\n[bold cyan]{prompt_text}[/bold cyan]")
    console.print("[dim]Press Enter twice (empty line) to finish, or Ctrl+D to end input:[/dim]\n")
    
    lines = []
    empty_line_count = 0
    
    while True:
        try:
            line = input()
            if line == "":
                empty_line_count += 1
                if empty_line_count >= 2:
                    break
                lines.append("")
            else:
                empty_line_count = 0
                lines.append(line)
        except EOFError:
            break
    
    return "\n".join(lines).strip()


@click.command()
@click.argument("path", type=click.Path(path_type=Path), required=False)
def new_validator_command(path: Path):
    """Run the interactive validator creation workflow."""
    # Check configuration first
    if not check_configuration():
        sys.exit(1)
    
    # Use path detection logic to determine the target path
    target_path = detect_project_path(path)
    
    # Ensure the target path exists
    if not target_path.exists():
        console.print(f"[red]Error: Path '{target_path}' does not exist.[/red]")
        sys.exit(1)
    
    # Initialize project config manager
    config_path = target_path / ".deterministic" / "config.toml"
    if config_path.exists():
        console.print("[green]✓[/green] Found existing deterministic project")
        ProjectConfigManager.set_runtime_custom_path(target_path / ".deterministic")
        config_manager = ProjectConfigManager.load_from_disk()
    else:
        console.print("[yellow]Initializing new deterministic project...[/yellow]")
        # Ensure directory exists
        (target_path / ".deterministic").mkdir(parents=True, exist_ok=True)
        ProjectConfigManager.set_runtime_custom_path(target_path / ".deterministic")
        config_manager = ProjectConfigManager()
        config_manager.save_to_disk()
        console.print("[green]✓[/green] Created .deterministic directory structure")
    
    console.print("\n")
    console.print(Panel.fit(
        f"[bold magenta]AST Validator Agent[/bold magenta]\n"
        f"Create comprehensive validators and tests for Python code\n"
        f"[dim]Project: {target_path}[/dim]\n"
        f"[dim]Config: {config_manager.config_dir}[/dim]",
        border_style="magenta"
    ))
    
    # Get code snippet from user
    console.print("\n[bold]Step 1: Provide the code snippet[/bold]")
    code_snippet = get_multiline_input("Enter the bad Python code that your Agent generated:")
    
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
    validator_name = Prompt.ask("\nValidator name", default="custom_validator")
    
    # Validate the name (basic validation)
    if not validator_name.replace("_", "").replace("-", "").isalnum():
        console.print("[red]Error: Validator name must contain only letters, numbers, hyphens, and underscores.[/red]")
        sys.exit(1)
    
    # Check if validator already exists
    existing_validators = list(config_manager.validators.values())
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
    console.print("\n[bold cyan]🤖 Starting AST Validator Agent...[/bold cyan]")
    console.print("[dim]This may take a few moments as the agent creates and tests the validator.[/dim]\n")
    
    try:
        # Get system settings and create Anthropic client
        settings = get_settings()
        
        # Import Anthropic model
        from pydantic_ai.models.anthropic import AnthropicModel
        anthropic_client = AnthropicModel("claude-sonnet-4-20250514")
        
        # Set API key for the client
        if settings.anthropic_api_key:
            os.environ["ANTHROPIC_API_KEY"] = settings.anthropic_api_key
        
        final_result = None
        validation_contents = ""
        test_contents = ""
        
        async def stream_callback(event):
            """Handle streaming events from the agent."""
            if event.event_type == 'user_prompt':
                console.print(f"[bold blue]📝 {event.content}[/bold blue]")
            elif event.event_type == 'model_request_start':
                console.print(f"[bold yellow]{event.content}[/bold yellow]")
            elif event.event_type == 'text_chunk':
                # Print text chunks as they arrive
                console.print(event.content, end="", style="white")
            elif event.event_type == 'tool_processing_start':
                console.print(f"\n[bold cyan]{event.content}[/bold cyan]")
            elif event.event_type == 'tool_call_start':
                tool_name = event.metadata.get('tool_name', 'unknown')
                console.print(f"[cyan]🔧 Calling {tool_name}[/cyan]")
            elif event.event_type == 'tool_call_end':
                console.print(f"[green]{event.content}[/green]")
            elif event.event_type == 'final_result':
                nonlocal final_result, validation_contents, test_contents
                final_result = event.metadata.get('output', event.content)
                validation_contents = event.metadata.get('validation_contents', '')
                test_contents = event.metadata.get('test_contents', '')
                console.print(f"\n[bold green]{event.content}[/bold green]")
        
        # Run the streaming agent in the target directory
        async def run_streaming_agent():
            # Save current working directory
            original_cwd = Path.cwd()
            try:
                # Change to target directory for agent execution
                os.chdir(target_path)
                
                async for event in stream_create_validator(
                    user_code=code_snippet,
                    requirements=issue_description,
                    anthropic_client=anthropic_client,
                    project_root=target_path,
                    callback=stream_callback
                ):
                    # Events are handled by the callback
                    pass
                return final_result
            finally:
                # Restore original working directory
                os.chdir(original_cwd)
        
        result = asyncio.run(run_streaming_agent())
        
        console.print("\n[bold green]✅ Agent completed successfully![/bold green]")
        if result:
            console.print(Panel(result, title="Final Result", border_style="green"))
        
        # Process generated files from agent virtual contents
        if validation_contents or test_contents:
            console.print("\n[bold]Processing generated files...[/bold]")
            
            if validation_contents:
                console.print("  • Generated validator code")
            if test_contents:
                console.print("  • Generated test code")
            
            # Save files to .deterministic structure using config manager
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
        
    except KeyboardInterrupt:
        console.print("\n[yellow]Operation interrupted by user.[/yellow]")
        sys.exit(1)
    except Exception as e:
        console.print(f"\n[red]Error: {e}[/red]")
        console.print("[dim]Please check your configuration and try again.[/dim]")
        sys.exit(1)
