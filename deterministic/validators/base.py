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
    
    def __init__(self, name: str) -> None:
        """Initialize the validator.
        
        Args:
            name: Name of the validator
        """
        self.name = name
    
    @abstractmethod
    async def validate(self, path: Path) -> ValidationResult:
        """Run validation on the given path.
        
        Args:
            path: Path to validate
            
        Returns:
            ValidationResult with success status and output
        """
        pass
    
    @property
    def display_name(self) -> str:
        """Get the display name for this validator.
        
        Returns:
            Display name for UI purposes
        """
        return self.name.replace("_", " ").title()