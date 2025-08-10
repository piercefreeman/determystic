"""Base configuration management for the determystic tool."""

import tomllib
import tomli_w
from abc import ABC, abstractmethod
from pathlib import Path
from typing import ClassVar, Optional, Type, TypeVar

from pydantic import BaseModel

T = TypeVar('T', bound='BaseConfig')


class BaseConfig(BaseModel, ABC):
    """Abstract base class for configuration management with TOML support."""
    _found_path: ClassVar[Path | None] = None
    
    @classmethod
    @abstractmethod
    def get_possible_config_paths(cls) -> list[Path]:
        """Return a list of possible paths where the config file might be found.
        
        :return: List of Path objects to search for configuration files

        """
        pass
        
    @classmethod
    def get_config_path(cls) -> Path:
        """Get the path to the configuration file."""
        possible_paths = cls.get_possible_config_paths()
        if cls._found_path is None:
            for path in possible_paths:
                if path.exists():
                    cls._found_path = path
                    break
            else:
                # Assume the first path is the one we want
                cls._found_path = possible_paths[0]
                cls._found_path.parent.mkdir(parents=True, exist_ok=True)
                cls().save_to_disk()
        return cls._found_path
    
    @classmethod
    def load_from_disk(cls: Type[T]) -> Optional[T]:
        """Load configuration from disk.
        
        :return: Configuration instance, or None if not found 

        """
        config_data = tomllib.load(cls.get_config_path().open("rb"))
        return cls.model_validate(config_data)

    def save_to_disk(self) -> None:
        """Save configuration to disk.
        
        :param config_path: Path to save the configuration

        """
        # Get the config path, but handle the case where we're creating it for the first time
        try:
            config_path = self.__class__.get_config_path()
        except FileNotFoundError:
            # Take the first possible path
            config_path = self.__class__.get_possible_config_paths()[0]
            config_path.parent.mkdir(parents=True, exist_ok=True)
     
        with config_path.open("wb") as f:
            tomli_w.dump(self.model_dump(mode="json", exclude_none=True), f)
    