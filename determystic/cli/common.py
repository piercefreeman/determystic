from pathlib import Path
from typing import TYPE_CHECKING

from determystic.configs.project import ProjectConfigManager
from determystic.validators import (
    DynamicASTValidator,
    FunctionVisibilityValidator,
    HangingFunctionsValidator,
    StaticAnalysisValidator,
)

if TYPE_CHECKING:
    from determystic.validators.base import BaseValidator


BUNDLED_VALIDATOR_NAMES = {
    "static_analysis",
    "hanging_functions",
    "function_visibility",
}


def is_validator_enabled(
    validator: "BaseValidator",
    project_config: ProjectConfigManager,
) -> bool:
    """Return whether a validator should run for this project."""
    validator_selectors = _validator_selectors(validator)
    excluded = {
        _normalize_validator_selector(value)
        for value in project_config.exclude
    }
    if validator_selectors & excluded:
        return False

    if not _is_bundled_validator(validator):
        return True

    enabled = {
        _normalize_validator_selector(value)
        for value in project_config.enabled
    }
    return bool(validator_selectors & enabled or enabled & {"*", "all", "bundled"})


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
        *FunctionVisibilityValidator.create_validators(project_config),
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
    return [v for v in all_validators if is_validator_enabled(v, project_config)]


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


def _normalize_validator_selector(value: str) -> str:
    return value.strip().lower().replace("-", "_").replace(" ", "_")


def _validator_selectors(validator: "BaseValidator") -> set[str]:
    return {
        _normalize_validator_selector(validator.name),
        _normalize_validator_selector(validator.display_name),
    }


def _is_bundled_validator(validator: "BaseValidator") -> bool:
    """Return whether a validator is bundled with determystic."""
    return _normalize_validator_selector(validator.name) in BUNDLED_VALIDATOR_NAMES
