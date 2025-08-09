"""Configuration management for the deterministic tool."""

from pathlib import Path
from typing import Optional
import yaml

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from deterministic.logging import CONSOLE
from rich.panel import Panel

class DeterministicSettings(BaseSettings):
    """Settings for the deterministic tool."""
    
    anthropic_api_key: Optional[str] = Field(
        default=None,
        description="Anthropic API key for Claude models"
    )
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        # Also check environment variables
        env_prefix="",
        # Case insensitive for env vars
        case_sensitive=False,
        # Extra fields are ignored
        extra="ignore",
    )
    
    @classmethod
    def load_from_config(cls) -> "DeterministicSettings":
        """Load settings from config file and environment."""
        config_path = cls.get_config_path()
        
        # Load from config file if it exists
        config_data = {}
        if config_path.exists():
            with open(config_path, "r") as f:
                config_data = yaml.safe_load(f) or {}
        
        # Create settings (will also check env vars)
        return cls(**config_data)
    
    @classmethod
    def get_config_dir(cls) -> Path:
        """Get the configuration directory path."""
        config_dir = Path.home() / ".deterministic"
        config_dir.mkdir(exist_ok=True)
        return config_dir
    
    @classmethod
    def get_config_path(cls) -> Path:
        """Get the configuration file path."""
        return cls.get_config_dir() / "config.yml"
    
    def save_to_config(self) -> None:
        """Save current settings to config file."""
        config_path = self.get_config_path()
        
        # Prepare data to save (exclude None values)
        data = {}
        if self.anthropic_api_key:
            data["anthropic_api_key"] = self.anthropic_api_key
        
        # Save to YAML
        with open(config_path, "w") as f:
            yaml.safe_dump(data, f, default_flow_style=False)
    
    def is_configured(self) -> bool:
        """Check if the minimum required configuration is present."""
        return bool(self.anthropic_api_key)


def get_settings() -> DeterministicSettings:
    """Get the current settings, loading from config and environment."""
    return DeterministicSettings.load_from_config()


def check_configuration() -> bool:
    """Check if the tool is configured, show error if not."""
    try:
        settings = get_settings()
        if not settings.is_configured():
            CONSOLE.print(Panel(
                "[bold red]Configuration Required[/bold red]\n\n"
                "This tool requires an Anthropic API key to function.\n"
                "Please run the configuration wizard:\n\n"
                "[bold cyan]deterministic configure[/bold cyan]",
                border_style="red"
            ))
            return False
        return True
    except Exception as e:
        CONSOLE.print(f"[red]Error loading configuration: {e}[/red]")
        raise
