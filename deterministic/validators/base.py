"""Base abstract class for all validators."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass
class ValidationResult:
    """Result from a validation run."""
    
    success: bool
    output: str
    details: Optional[Dict[str, Any]] = None


class BaseValidator(ABC):
    """Abstract base class for all validators."""
    
    def __init__(self, *, name: str, path: Path | None = None) -> None:
        """Initialize the validator.
        
        :param name: Name of the validator
        :param path: Optional path to the project/directory being validated

        """
        self.name = name
        self.path = path
    
    @classmethod
    @abstractmethod
    def create_validators(cls, path: Path) -> list["BaseValidator"]:
        """
        Factory function that can create multiple validators for a given path.
        """
        pass
    
    @abstractmethod
    async def validate(self, path: Path) -> ValidationResult:
        pass
    
    @property
    def display_name(self) -> str:
        return self.name.replace("_", " ").title()
