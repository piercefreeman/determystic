"""Base abstract class for all validators."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, Dict, Optional

from pydantic import BaseModel
from determystic.configs.project import ProjectConfigManager


@dataclass
class ValidationResult:
    """Result from a validation run."""
    
    success: bool
    output: str
    details: Optional[Dict[str, Any]] = None


class BaseValidator(ABC):
    """Abstract base class for all validators."""
    config_model: ClassVar[type[BaseModel] | None] = None
    
    def __init__(
        self,
        *,
        name: str,
        path: Path | None = None,
        config: BaseModel | None = None,
    ) -> None:
        """Initialize the validator.
        
        :param name: Name of the validator
        :param path: Optional path to the project/directory being validated
        :param config: Optional typed validator configuration

        """
        self.name = name
        self.path = path or Path.cwd()
        self.config = config

    @classmethod
    def parse_config(
        cls,
        config_manager: ProjectConfigManager,
        name: str,
    ) -> BaseModel | None:
        """Parse this validator's project config if it declares a config model."""
        if cls.config_model is None:
            return None
        return config_manager.get_validator_config(name, cls.config_model)
    
    @classmethod
    @abstractmethod
    def create_validators(cls, config_manager: ProjectConfigManager) -> list["BaseValidator"]:
        """
        Factory function that can create multiple validators for a given path.
        """
        pass
    
    @abstractmethod
    async def validate(self) -> ValidationResult:
        pass
    
    @property
    def display_name(self) -> str:
        return self.name.replace("_", " ").title()
