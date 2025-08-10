"""Project configuration management for determystic validators."""

from datetime import datetime
from typing import Any, ClassVar
from pathlib import Path

from pydantic import BaseModel, Field
from determystic.configs.base import BaseConfig
from determystic.io import detect_git_root, detect_pyproject_path


class ValidatorFile(BaseModel):
    """Represents a validator file in the project."""
    name: str = Field(description="Name of the validator file (without extension)")
    validator_path: str = Field(description="Relative path to the validator file")
    test_path: str | None = Field(default=None, description="Relative path to the test file")
    created_at: datetime = Field(default_factory=datetime.now)
    description: str | None = Field(default=None, description="Description of what this validator checks")


class ProjectConfigManager(BaseConfig):
    """Configuration for a determystic project."""
    
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

    runtime_custom_path: ClassVar[Path | None] = None

    @classmethod
    def set_runtime_custom_path(cls, path: Path) -> None:
        """
        Set by the CLI layer to allow for custom paths to be set at runtime.

        """
        path = path.absolute()
        cls.runtime_custom_path = path

        # If set, we need to initialize it explicitly
        if not path.exists():
            config = cls()
            config.save_to_disk()

    @classmethod
    def get_possible_config_paths(cls):
        """
        Get the custom path set by the CLI layer.
        """
        if cls.runtime_custom_path is not None:
            return [cls.runtime_custom_path / "config.toml"]

        return [
            detect_git_root(Path.cwd()) / ".determystic" / "config.toml",
            detect_pyproject_path(Path.cwd()) / ".determystic" / "config.toml",
        ]
    
    def new_validation(self, name: str, validator_script: str, test_script: str, description: str | None = None) -> ValidatorFile:
        """Add a new validator to the project configuration.
        
        Args:
            name: Name of the validator file (without extension)
            validator_path: Relative path to the validator file
            test_path: Optional relative path to the test file
            description: Optional description of what this validator checks
            
        Returns:
            The created ValidatorFile instance
        """
        config_root = self.get_config_path().parent
        
        # We don't want to bundle .py files since these get picked up by the static analysis validators
        validator_path = config_root / "validations" / f"{name}.determystic"
        validator_path.parent.mkdir(parents=True, exist_ok=True)

        test_path = config_root / "tests" / f"{name}.determystic"
        test_path.parent.mkdir(parents=True, exist_ok=True)

        # Write the validator script to the validator path
        validator_path.write_text(validator_script)
        test_path.write_text(test_script)

        validator_file = ValidatorFile(
            name=name,
            validator_path=str(validator_path.relative_to(config_root)),
            test_path=str(test_path.relative_to(config_root)),
            description=description
        )
        
        self.validators[name] = validator_file
        self.updated_at = datetime.now()
        
        return validator_file
    
    def delete_validation(self, name: str) -> bool:
        """Remove a validator from the project configuration.
        
        Args:
            name: Name of the validator to remove
            
        Returns:
            True if the validator was removed, False if it didn't exist
        """
        if name in self.validators:
            del self.validators[name]
            self.updated_at = datetime.now()
            return True
        return False
