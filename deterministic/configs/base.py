"""Base configuration management for the deterministic tool."""

import tomllib
import tomli_w
from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Optional, Type, TypeVar

from pydantic import BaseModel

T = TypeVar('T', bound='BaseConfig')


class BaseConfig(BaseModel, ABC):
    """Abstract base class for configuration management with TOML support."""
    
    @classmethod
    @abstractmethod
    def get_possible_config_paths(cls) -> List[Path]:
        """Return a list of possible paths where the config file might be found.
        
        :return: List of Path objects to search for configuration files
        :rtype: List[Path]
        """
        pass
    
    @classmethod
    def load_from_disk(cls: Type[T]) -> Optional[T]:
        """Load configuration from disk.
        
        :return: Configuration instance, or None if not found
        :rtype: Optional[T]
        """
        for config_path in cls.get_possible_config_paths():
            if config_path.exists():
                try:
                    with open(config_path, "rb") as f:
                        config_data = tomllib.load(f)
                    return cls.model_validate(config_data)
                except Exception:
                    continue
        return None
    
    def save_to_disk(self, config_path: Path) -> None:
        """Save configuration to disk.
        
        :param config_path: Path to save the configuration to
        :type config_path: Path
        """
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_dict = self.model_dump(mode="json")
        
        with open(config_path, "wb") as f:
            tomli_w.dump(config_dict, f)
    