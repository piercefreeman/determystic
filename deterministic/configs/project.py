"""Project configuration management for deterministic validators."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ValidatorFile(BaseModel):
    """Represents a validator file in the project."""
    name: str = Field(description="Name of the validator file (without extension)")
    validator_path: str = Field(description="Relative path to the validator file")
    test_path: str | None = Field(default=None, description="Relative path to the test file")
    created_at: datetime = Field(default_factory=datetime.now)
    description: str | None = Field(default=None, description="Description of what this validator checks")


class ProjectConfig(BaseModel):
    """Configuration for a deterministic project."""
    
    version: str = Field(default="1.0", description="Configuration version")
    project_name: str | None = Field(default=None, description="Name of the project")
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    
    # Validator files tracking
    validators: dict[str, ValidatorFile] = Field(
        default_factory=dict,
        description="Map of validator names to their file information"
    )
    
    # Project settings
    settings: dict[str, Any] = Field(
        default_factory=dict,
        description="Project-specific settings"
    )
