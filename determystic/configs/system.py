"""Configuration management for the determystic tool."""

import sys
from pathlib import Path

from pydantic import Field
from pydantic_settings import SettingsConfigDict
from determystic.logging import CONSOLE
from rich.panel import Panel
from determystic.configs.base import BaseConfig

class DeterministicSettings(BaseConfig):
    """Settings for the determystic tool."""
    
    anthropic_api_key: str | None = Field(
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
    def get_possible_config_paths(cls) -> list[Path]:
        """Get the configuration file paths."""
        config_dir = Path.home() / ".determystic"
        config_dir.mkdir(exist_ok=True)
        return [config_dir / "config.toml"]

    @classmethod
    def load_from_disk(cls, required: bool = True) -> "DeterministicSettings":
        try:
            return super().load_from_disk()
        except Exception:
            if not required:
                return None
            CONSOLE.print(Panel(
                "[bold red]Configuration Required[/bold red]\n\n"
                "This tool requires an Anthropic API key to function.\n"
                "Please run the configuration wizard:\n\n"
                "[bold cyan]determystic configure[/bold cyan]",
                border_style="red"
            ))
            sys.exit(1)
