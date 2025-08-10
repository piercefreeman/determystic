"""Base configuration management for the deterministic tool."""

import tomllib
import tomli_w
from abc import ABC, abstractmethod
from pathlib import Path
from typing import ClassVar, Optional, Type, TypeVar

from pydantic import BaseModel

T = TypeVar('T', bound='BaseConfig')


class BaseConfig(BaseModel, ABC):
    """Abstract base class for configuration management with TOML support."""
    _found_path: Path | None = None
    
    @classmethod
    @abstractmethod
    def get_possible_config_paths(cls) -> list[Path]:
        """Return a list of possible paths where the config file might be found.
        
        :return: List of Path objects to search for configuration files
        :rtype: List[Path]
        """
        pass

    def get_config_path(self) -> Path:
        """Get the path to the configuration file."""
        possible_paths = self.get_possible_config_paths()
        if self._found_path is None:
            for path in possible_paths:
                if path.exists():
                    self._found_path = path
                    break
            raise FileNotFoundError(f"No configuration file found in {possible_paths}")
        return self._found_path
    
    @classmethod
    def load_from_disk(cls: Type[T]) -> Optional[T]:
        """Load configuration from disk.
        
        :return: Configuration instance, or None if not found
        :rtype: Optional[T]
        """
        config_data = tomllib.load(cls.get_config_path().open("rb"))
        return cls.model_validate(config_data)
    
    def save_to_disk(self) -> None:
        """Save configuration to disk.
        
        :param config_path: Path to save the configuration to
        :type config_path: Path
        """
        current_config = self.get_config_path()        
        with current_config.open("wb") as f:
            tomli_w.dump(self.model_dump(mode="json"), f)
    