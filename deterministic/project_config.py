"""Project configuration management for deterministic validators."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ValidatorFile(BaseModel):
    """Represents a validator file in the project."""
    name: str = Field(description="Name of the validator file (without extension)")
    validator_path: str = Field(description="Relative path to the validator file")
    test_path: Optional[str] = Field(default=None, description="Relative path to the test file")
    created_at: datetime = Field(default_factory=datetime.now)
    description: Optional[str] = Field(default=None, description="Description of what this validator checks")


class ProjectConfig(BaseModel):
    """Configuration for a deterministic project."""
    
    version: str = Field(default="1.0", description="Configuration version")
    project_name: Optional[str] = Field(default=None, description="Name of the project")
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    
    # Validator files tracking
    validators: Dict[str, ValidatorFile] = Field(
        default_factory=dict,
        description="Map of validator names to their file information"
    )
    
    # Project settings
    settings: Dict[str, Any] = Field(
        default_factory=dict,
        description="Project-specific settings"
    )
    
    def add_validator(
        self, 
        name: str, 
        validator_path: str, 
        test_path: Optional[str] = None,
        description: Optional[str] = None
    ) -> None:
        """Add a new validator to the project configuration."""
        self.validators[name] = ValidatorFile(
            name=name,
            validator_path=validator_path,
            test_path=test_path,
            description=description
        )
        self.updated_at = datetime.now()
    
    def remove_validator(self, name: str) -> bool:
        """Remove a validator from the project configuration."""
        if name in self.validators:
            del self.validators[name]
            self.updated_at = datetime.now()
            return True
        return False
    
    def get_validator_names(self) -> List[str]:
        """Get a list of all validator names."""
        return list(self.validators.keys())
    
    def get_validator_files(self) -> List[ValidatorFile]:
        """Get a list of all validator files."""
        return list(self.validators.values())


class ProjectConfigManager:
    """Manages the lifecycle of project configuration."""
    
    CONFIG_DIR_NAME = ".deterministic"
    CONFIG_FILE_NAME = "config.json"
    VALIDATORS_DIR_NAME = "validators"
    TESTS_DIR_NAME = "tests"
    
    def __init__(self, project_root: Path):
        """
        Initialize the project config manager.
        
        Args:
            project_root: Root directory of the project
        """
        self.project_root = Path(project_root).resolve()
        self.config_dir = self.project_root / self.CONFIG_DIR_NAME
        self.config_file = self.config_dir / self.CONFIG_FILE_NAME
        self.validators_dir = self.config_dir / self.VALIDATORS_DIR_NAME
        self.tests_dir = self.config_dir / self.TESTS_DIR_NAME
    
    def initialize_project(self, project_name: Optional[str] = None) -> ProjectConfig:
        """
        Initialize a new deterministic project.
        
        Args:
            project_name: Optional name for the project
            
        Returns:
            The created project configuration
        """
        # Create .deterministic directory structure
        self.config_dir.mkdir(exist_ok=True)
        self.validators_dir.mkdir(exist_ok=True)
        self.tests_dir.mkdir(exist_ok=True)
        
        # Create initial configuration
        config = ProjectConfig(
            project_name=project_name or self.project_root.name
        )
        
        # Save configuration
        self.save_config(config)
        return config
    
    def load_config(self) -> Optional[ProjectConfig]:
        """
        Load the project configuration.
        
        Returns:
            The project configuration, or None if not found
        """
        if not self.config_file.exists():
            return None
        
        try:
            with open(self.config_file, 'r') as f:
                config_data = json.load(f)
            return ProjectConfig.model_validate(config_data)
        except Exception:
            return None
    
    def save_config(self, config: ProjectConfig) -> None:
        """
        Save the project configuration.
        
        Args:
            config: The project configuration to save
        """
        # Ensure directory exists
        self.config_dir.mkdir(exist_ok=True)
        
        # Update timestamp
        config.updated_at = datetime.now()
        
        # Save to file
        with open(self.config_file, 'w') as f:
            json.dump(config.model_dump(), f, indent=2, default=str)
    
    def get_or_create_config(self, project_name: Optional[str] = None) -> ProjectConfig:
        """
        Get existing configuration or create a new one.
        
        Args:
            project_name: Optional name for the project if creating new
            
        Returns:
            The project configuration
        """
        config = self.load_config()
        if config is None:
            config = self.initialize_project(project_name)
        return config
    
    def add_validator_files(
        self,
        validator_name: str,
        validator_content: str,
        test_content: Optional[str] = None,
        description: Optional[str] = None
    ) -> tuple[Path, Optional[Path]]:
        """
        Add validator and test files to the project.
        
        Args:
            validator_name: Name of the validator
            validator_content: Content of the validator file
            test_content: Optional content of the test file
            description: Optional description of the validator
            
        Returns:
            Tuple of (validator_path, test_path)
        """
        # Ensure directories exist
        self.validators_dir.mkdir(exist_ok=True)
        self.tests_dir.mkdir(exist_ok=True)
        
        # Create file paths
        validator_filename = f"{validator_name}.py"
        validator_path = self.validators_dir / validator_filename
        test_path = None
        
        # Write validator file
        validator_path.write_text(validator_content)
        
        # Write test file if provided
        if test_content:
            test_filename = f"test_{validator_name}.py"
            test_path = self.tests_dir / test_filename
            test_path.write_text(test_content)
        
        # Update configuration
        config = self.get_or_create_config()
        config.add_validator(
            name=validator_name,
            validator_path=str(validator_path.relative_to(self.project_root)),
            test_path=str(test_path.relative_to(self.project_root)) if test_path else None,
            description=description
        )
        self.save_config(config)
        
        return validator_path, test_path
    
    def remove_validator_files(self, validator_name: str) -> bool:
        """
        Remove validator and test files from the project.
        
        Args:
            validator_name: Name of the validator to remove
            
        Returns:
            True if validator was found and removed
        """
        config = self.load_config()
        if not config or validator_name not in config.validators:
            return False
        
        validator_info = config.validators[validator_name]
        
        # Remove files if they exist
        if validator_info.validator_path:
            validator_file = self.project_root / validator_info.validator_path
            if validator_file.exists():
                validator_file.unlink()
        
        if validator_info.test_path:
            test_file = self.project_root / validator_info.test_path
            if test_file.exists():
                test_file.unlink()
        
        # Update configuration
        config.remove_validator(validator_name)
        self.save_config(config)
        
        return True
    
    def list_validators(self) -> List[ValidatorFile]:
        """
        List all validators in the project.
        
        Returns:
            List of validator files
        """
        config = self.load_config()
        if not config:
            return []
        return config.get_validator_files()
    
    def exists(self) -> bool:
        """Check if the project is already initialized."""
        return self.config_file.exists()