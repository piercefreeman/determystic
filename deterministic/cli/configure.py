"""Configuration command for setting up API keys and other settings."""

import sys
from typing import Any, Dict

import click
from pydantic.fields import FieldInfo
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

from deterministic.configs.system import DeterministicSettings

console = Console()


def _is_sensitive_field(field_name: str) -> bool:
    """Determine if a field contains sensitive information."""
    return any(term in field_name.lower() for term in ["key", "password", "secret", "token"])


def _mask_sensitive_value(value: str, field_name: str) -> str:
    """Mask sensitive values for display."""
    if _is_sensitive_field(field_name):
        return value[:7] + "..." + value[-4:] if len(value) > 10 else "***"
    return value


@click.command()
def configure_command():
    """Configure API keys and other settings for the deterministic tool."""
    console.print(Panel.fit(
        "[bold cyan]Deterministic Configuration[/bold cyan]\n"
        "Set up your API keys and preferences",
        border_style="cyan"
    ))
    
    # Load existing settings or create new ones
    settings = DeterministicSettings.load_from_disk()
    
    # Convert existing values to a simple dict
    existing_values = settings.model_dump()
    
    console.print("\n[dim]Configuring settings...[/dim]")
    
    # Iterate through all model fields
    for field_name, field_info in settings.model_fields.items():
        current_value = existing_values.get(field_name)
        description = field_info.description or f"Enter {field_name.replace('_', ' ')}"
        
        # Show field description
        console.print(f"\n[bold]{field_name.replace('_', ' ').title()}[/bold]")
        console.print(f"[dim]{description}[/dim]")
        
        # Show current value if it exists
        current_display = ""
        if current_value:
            masked_value = _mask_sensitive_value(str(current_value), field_name)
            current_display = f" [dim](current: {masked_value})[/dim]"
        
        # Get new value
        new_value = Prompt.ask(
            f"Enter {field_name.replace('_', ' ')}{current_display}",
            password=_is_sensitive_field(field_name),
            default=current_value if current_value else None
        )
        
        # Update the settings if a value was provided
        if new_value:
            setattr(settings, field_name, new_value)
    
    # Save configuration
    settings.save_to_disk()
    config_path = settings.get_config_path()
    
    console.print("\n[bold green]✅ Configuration saved successfully![/bold green]")
    console.print(f"[dim]Configuration file: {config_path}[/dim]")
    
    # Show what was configured
    console.print("\n[bold]Configured settings:[/bold]")
    for field_name, field_info in settings.model_fields.items():
        current_value = getattr(settings, field_name)
        if current_value:
            masked_value = _mask_sensitive_value(str(current_value), field_name)
            console.print(f"  • {field_name.replace('_', ' ').title()}: {masked_value}")
    
    console.print("\n[green]You can now use the deterministic tools![/green]")
    console.print("[dim]Try: deterministic new-validator[/dim]")
    