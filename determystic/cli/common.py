from pathlib import Path
from typing import TYPE_CHECKING

from determystic.configs.project import ProjectConfigManager
from determystic.validators import (
    DynamicASTValidator,
    HangingFunctionsValidator,
    StaticAnalysisValidator,
)

if TYPE_CHECKING:
    from determystic.validators.base import BaseValidator


def create_all_validators(project_config: ProjectConfigManager) -> list["BaseValidator"]:
    """Create all validators (both built-in and custom) for the project.
    
    Args:
        project_config: The project configuration manager
        
    Returns:
        List of all available validators
    """
    validators = [
        *DynamicASTValidator.create_validators(project_config),
        *StaticAnalysisValidator.create_validators(project_config),
        *HangingFunctionsValidator.create_validators(project_config),
    ]
    
    return validators


def get_active_validators(project_config: ProjectConfigManager) -> list["BaseValidator"]:
    """Get only the active validators (not excluded) for the project.
    
    Args:
        project_config: The project configuration manager
        
    Returns:
        List of active validators that will run during validation
    """
    all_validators = create_all_validators(project_config)
    return [v for v in all_validators if v.display_name not in project_config.exclude]


def load_project_config(path: Path | None = None) -> ProjectConfigManager:
    """Load project configuration, optionally setting a custom path.
    
    Args:
        path: Optional custom path to set for the project
        
    Returns:
        Loaded project configuration manager
    """
    if path is not None:
        ProjectConfigManager.set_runtime_custom_path(path)
    
    return ProjectConfigManager.load_from_disk()