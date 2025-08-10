"""AST validator creation command."""

import sys
from pathlib import Path
import re
from random import randint
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.providers.anthropic import AnthropicProvider

import click
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.syntax import Syntax
from prompt_toolkit import PromptSession
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.lexers import PygmentsLexer
from pygments.lexers import PythonLexer # type: ignore
from prompt_toolkit.patch_stdout import patch_stdout

from determystic.configs.project import ProjectConfigManager
from determystic.configs.system import DeterministicSettings
from determystic.agents.create_validator import stream_create_validator, StreamEvent
from determystic.io import async_to_sync

console = Console()



async def get_multiline_input(prompt_text: str) -> str:
    """Get multiline input from the user with bracketed paste support.
    
    This function properly handles pasted content with multiple newlines
    by using prompt_toolkit's built-in bracketed paste support.
    
    Args:
        prompt_text: The prompt to display
        
    Returns:
        The user's multiline input
    """
    console.print(f"\n[bold cyan]{prompt_text}[/bold cyan]")
    console.print("[dim]You can paste code directly (even with multiple newlines).[/dim]")
    console.print("[dim]Press Enter twice (empty line) to finish input:[/dim]\n")
    
    # Create key bindings for double enter submission
    bindings = KeyBindings()
    
    @bindings.add('enter')
    def _(event):
        """Handle Enter key - submit if current line is empty and previous line was also empty."""
        buffer = event.current_buffer
        
        # Get current line content
        current_line = buffer.document.current_line
        
        # If current line is empty, check if we should submit
        if not current_line.strip():
            # Get all text and split into lines
            all_text = buffer.document.text
            lines = all_text.split('\n')
            
            # If we have at least one line and the last line is empty
            if len(lines) >= 2 and not lines[-1].strip():
                # Check if previous line was also empty (double enter condition)
                if not lines[-2].strip():
                    # Submit the input by accepting the buffer
                    buffer.validate_and_handle()
                    return
        
        # Otherwise, just insert a newline
        buffer.insert_text('\n')
    
    # Create a prompt session
    session = PromptSession(
        message="> ",
        multiline=True,
        key_bindings=bindings,
        enable_history_search=False,
        mouse_support=True,
        lexer=PygmentsLexer(PythonLexer),  # Python syntax highlighting
        # Bracketed paste is enabled by default in prompt_toolkit
        # It automatically handles pasted content properly
    )
    
    try:
        # Use async prompt session to avoid event loop conflicts
        with patch_stdout():
            result = await session.prompt_async()
        # Handle case where result is None (when user exits via our custom key binding)
        if result is None:
            return ""
        return result.strip()
    except (EOFError, KeyboardInterrupt):
        # Handle Ctrl+D, Ctrl+C gracefully
        return ""

def format_validator_name(raw_validator_name: str) -> str:
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

@click.command()
@click.argument("path", type=click.Path(path_type=Path), required=False)
@async_to_sync
async def new_validator_command(path: Path | None):
    """Run the interactive validator creation workflow."""

    # Try to load the system config before we kick off
    settings = DeterministicSettings.load_from_disk()
    if not settings.anthropic_api_key:
        console.print("[red]Anthropic API key not found. Please run `uvx determystic configure` to set it.[/red]")
        sys.exit(1)
    
    if path:
        ProjectConfigManager.set_runtime_custom_path(path)

    config_manager = ProjectConfigManager.load_from_disk()

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
    
    validator_name = format_validator_name(raw_validator_name)
    
    # Show the formatted name if it changed
    if validator_name != raw_validator_name:
        console.print(f"[dim]Formatted validator name: {validator_name}[/dim]")
    
    # Check if validator already exists
    existing_validators = list(config_manager.validators.values())  # type: ignore
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
    
    # Import Anthropic model
    anthropic_provider = AnthropicProvider(api_key=settings.anthropic_api_key)
    anthropic_client = AnthropicModel("claude-sonnet-4-20250514", provider=anthropic_provider)
    
    # Save current working directory
    final_event: StreamEvent | None = None
    async for event in stream_create_validator(
        user_code=code_snippet,
        requirements=issue_description,
        anthropic_client=anthropic_client,
    ):
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
            console.print(f"[cyan]🔧 Calling {event.content}[/cyan]")
        elif event.event_type == 'tool_call_end':
            console.print(f"[green]{event.content}[/green]")
        elif event.event_type == 'final_result':
            console.print(f"\n[bold green]{event.content}[/bold green]")
            final_event = event

    if not final_event:
        console.print("\n[red]Error: No final event received from the agent.[/red]")
        sys.exit(1)
    
    console.print("\n[bold green]✅ Agent completed successfully![/bold green]")
    console.print(Panel(final_event.content, title="Final Result", border_style="green"))  # type: ignore
    
    validation_contents = final_event.deps.validation_contents  # type: ignore
    test_contents = final_event.deps.test_contents  # type: ignore
    
    # Process generated files from agent virtual contents
    if validation_contents or test_contents:
        console.print("\n[bold]Processing generated files...[/bold]")
        
        if validation_contents:
            console.print("  • Generated validator code")
        if test_contents:
            console.print("  • Generated test code")
        
        # Save files to .determystic structure using config manager
        if validation_contents:
            try:
                validator_file = config_manager.new_validation(  # type: ignore
                    name=validator_name,
                    validator_script=validation_contents,
                    test_script=test_contents or "",
                    description=issue_description
                )
                
                # Save the config to disk
                config_manager.save_to_disk()  # type: ignore
                
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
