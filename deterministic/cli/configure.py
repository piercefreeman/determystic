"""Configuration command for setting up API keys and other settings."""

import sys

import click
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

from deterministic.settings import DeterministicSettings

console = Console()


@click.command()
@click.option(
    "--api-key",
    help="Anthropic API key (will prompt if not provided)",
    hide_input=True
)
def configure_command(api_key: str | None):
    """Configure API keys and other settings for the deterministic tool."""
    console.print(Panel.fit(
        "[bold cyan]Deterministic Configuration[/bold cyan]\n"
        "Set up your API keys and preferences",
        border_style="cyan"
    ))
    
    # Load existing settings
    try:
        settings = DeterministicSettings.load_from_config()
        console.print("\n[dim]Loading existing configuration...[/dim]")
    except Exception:
        settings = DeterministicSettings()
        console.print("\n[dim]Creating new configuration...[/dim]")
    
    # Get API key
    if not api_key:
        console.print("\n[bold]Anthropic API Key[/bold]")
        console.print("[dim]Required for AST validator creation and AI-powered features.[/dim]")
        console.print("[dim]Get your API key from: https://console.anthropic.com/[/dim]\n")
        
        # Show current value if exists
        if settings.anthropic_api_key:
            masked_key = settings.anthropic_api_key[:7] + "..." + settings.anthropic_api_key[-4:]
            current_value = f" [dim](current: {masked_key})[/dim]"
        else:
            current_value = ""
        
        api_key = Prompt.ask(
            f"Enter your Anthropic API key{current_value}",
            password=True,
            default=settings.anthropic_api_key if settings.anthropic_api_key else None
        )
    
    if api_key:
        settings.anthropic_api_key = api_key
    
    # Save configuration
    try:
        settings.save_to_config()
        config_path = settings.get_config_path()
        
        console.print("\n[bold green]✅ Configuration saved successfully![/bold green]")
        console.print(f"[dim]Configuration file: {config_path}[/dim]")
        
        # Show what was configured
        console.print("\n[bold]Configured settings:[/bold]")
        if settings.anthropic_api_key:
            masked_key = settings.anthropic_api_key[:7] + "..." + settings.anthropic_api_key[-4:]
            console.print(f"  • Anthropic API Key: {masked_key}")
        
        console.print("\n[green]You can now use the deterministic tools![/green]")
        console.print("[dim]Try: deterministic new-validator[/dim]")
        
    except Exception as e:
        console.print(f"\n[red]Error saving configuration: {e}[/red]")
        sys.exit(1)