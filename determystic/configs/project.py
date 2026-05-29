"""Project configuration management for determystic validators."""

import tomllib
from datetime import datetime
from typing import Any, ClassVar
from pathlib import Path

import tomli_w
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
    """Configuration for a determystic project stored in pyproject.toml."""

    TOOL_SECTION: ClassVar[str] = "determystic"
    
    version: str = Field(default="1.0", description="Configuration version")
    project_name: str | None = Field(default=None, description="Name of the project")
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    exclude: list[str] = Field(default_factory=list, description="List of validators to exclude from validation")
    
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
        cls.runtime_custom_path = detect_pyproject_path(path) or path
        cls._found_path = None

    @classmethod
    def get_possible_config_paths(cls):
        """
        Get the custom path set by the CLI layer.
        """
        if cls.runtime_custom_path is not None:
            return [cls.runtime_custom_path / "pyproject.toml"]

        pyproject_root = detect_pyproject_path(Path.cwd())
        if pyproject_root:
            return [pyproject_root / "pyproject.toml"]

        git_root = detect_git_root(Path.cwd())
        if git_root:
            return [git_root / "pyproject.toml"]

        return [Path.cwd() / "pyproject.toml"]

    @classmethod
    def get_config_path(cls) -> Path:
        """Get the project pyproject.toml path."""
        if cls._found_path is None:
            possible_paths = cls.get_possible_config_paths()
            for path in possible_paths:
                if path.exists():
                    cls._found_path = path
                    break
            else:
                cls._found_path = possible_paths[0]
        return cls._found_path

    @classmethod
    def load_from_disk(cls) -> "ProjectConfigManager":
        """Load determystic configuration from [tool.determystic]."""
        config_path = cls.get_config_path()
        config_data: dict[str, Any] = {}

        if config_path.exists():
            with config_path.open("rb") as f:
                pyproject_data = tomllib.load(f)
            tool_data = pyproject_data.get("tool", {})
            config_data = tool_data.get(cls.TOOL_SECTION, {})

        return cls.model_validate(config_data)

    def save_to_disk(self) -> None:
        """Save determystic configuration under [tool.determystic]."""
        config_path = self.__class__.get_config_path()
        config_path.parent.mkdir(parents=True, exist_ok=True)

        pyproject_data: dict[str, Any] = {}
        if config_path.exists():
            with config_path.open("rb") as f:
                pyproject_data = tomllib.load(f)

        tool_data = pyproject_data.setdefault("tool", {})
        tool_data[self.TOOL_SECTION] = self.model_dump(mode="json", exclude_none=True)

        with config_path.open("wb") as f:
            tomli_w.dump(pyproject_data, f)
    
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
        project_root = self.project_root
        config_root = project_root / ".determystic"
        
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
            validator_path=str(validator_path.relative_to(project_root)),
            test_path=str(test_path.relative_to(project_root)),
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

    def resolve_project_path(self, path: str | Path) -> Path:
        """Resolve a project-relative path from the pyproject configuration."""
        path = Path(path)
        if path.is_absolute():
            return path
        return self.project_root / path

    @property
    def project_root(self) -> Path:
        """
        Get the project root.
        """
        return self.get_config_path().parent
