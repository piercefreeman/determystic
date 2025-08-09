"""AST validator creation command."""

import asyncio
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.syntax import Syntax

from deterministic.settings import get_settings, check_configuration
from deterministic.agents.create_validator import create_ast_validator, create_ast_validator_stream

console = Console()


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
def ast_validator_command():
    """Create comprehensive AST validators and tests for Python code."""
    # Check configuration first
    if not check_configuration():
        sys.exit(1)
    
    console.print("\n")
    console.print(Panel.fit(
        "[bold magenta]AST Validator Agent[/bold magenta]\n"
        "Create comprehensive validators and tests for Python code",
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
    
    # Confirm before proceeding
    console.print("\n[bold]Summary:[/bold]")
    console.print(f"  • Code length: {len(code_snippet)} characters")
    console.print(f"  • Issues to detect: {issue_description}")
    
    if not Prompt.ask("\n[yellow]Proceed with creating the validator?[/yellow]", choices=["y", "n"], default="y") == "y":
        console.print("[red]Operation cancelled.[/red]")
        sys.exit(0)
    
    # Run the agent
    console.print("\n[bold cyan]🤖 Starting AST Validator Agent...[/bold cyan]")
    console.print("[dim]This may take a few moments as the agent creates and tests the validator.[/dim]\n")
    
    try:
        # Set environment variable for the agent
        settings = get_settings()
        import os
        os.environ["ANTHROPIC_API_KEY"] = settings.anthropic_api_key
        
        console.print("\n[bold green]🤖 Starting AST Validator Agent...[/bold green]")
        console.print("[dim]This may take a few moments as the agent creates and tests the validator.[/dim]\n")
        
        final_result = None
        
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
                nonlocal final_result
                final_result = event.metadata.get('output', event.content)
                console.print(f"\n[bold green]{event.content}[/bold green]")
        
        # Run the streaming agent
        async def run_streaming_agent():
            async for event in create_ast_validator_stream(
                user_code=code_snippet,
                requirements=issue_description,
                callback=stream_callback
            ):
                # Events are handled by the callback
                pass
            return final_result
        
        result = asyncio.run(run_streaming_agent())
        
        console.print("\n[bold green]✅ Agent completed successfully![/bold green]")
        if result:
            console.print(Panel(result, title="Final Result", border_style="green"))
        
        # Show where files were saved
        output_dir = Path("output")
        if output_dir.exists():
            console.print("\n[bold]Generated files:[/bold]")
            for file in output_dir.iterdir():
                if file.suffix == ".py":
                    console.print(f"  • {file.name}")
                    
                    # Show a preview of the file
                    content = file.read_text()
                    lines = content.split("\n")[:10]  # First 10 lines
                    preview = "\n".join(lines)
                    if len(content.split("\n")) > 10:
                        preview += "\n..."
                    
                    syntax = Syntax(preview, "python", theme="monokai", line_numbers=False)
                    console.print(Panel(syntax, title=f"Preview: {file.name}", border_style="dim"))
        
    except KeyboardInterrupt:
        console.print("\n[yellow]Operation interrupted by user.[/yellow]")
        sys.exit(1)
    except Exception as e:
        console.print(f"\n[red]Error: {e}[/red]")
        console.print("[dim]Please check your configuration and try again.[/dim]")
        sys.exit(1)