"""Dynamic AST validator that loads custom validators from .determystic files."""

import inspect
from pathlib import Path
from typing import Any, Type

from pydantic import BaseModel
from determystic.configs.project import ProjectConfigManager
from determystic.external import DeterministicTraverser
from determystic.path_filters import iter_python_files
from determystic.suppressions import SuppressionComments
from determystic.validators.base import BaseValidator, ValidationResult
from determystic.logging import CONSOLE


class DynamicASTValidator(BaseValidator):
    """Loads and runs custom AST validators from .determystic files."""
    
    def __init__(
        self,
        *,
        name: str,
        validator_path: Path,
        path: Path | None = None,
        ignore_paths: list[str] | None = None,
        include_paths: list[str] | None = None,
        isolation_paths: list[str] | None = None,
        config_data: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(name=name, path=path)
        self.validator_path = validator_path
        self.ignore_paths = ignore_paths or []
        self.include_paths = include_paths or []
        self.isolation_paths = isolation_paths or []
        self.config_data = config_data or {}
        self.traverser_class = self._load_validator_module(validator_path)
        self.traverser_config: BaseModel | None = None
        self.config_error: str | None = None
        self._load_traverser_config()
    
    @classmethod
    def create_validators(cls, config_manager: ProjectConfigManager) -> list["BaseValidator"]:
        """Factory function that creates DynamicASTValidator instances for each determystic validator."""
        validators = []
        
        if not config_manager:
            return validators

        # Load each validator file as a separate validator instance
        for validator_file in config_manager.get_custom_validators().values():
            validator_path = config_manager.resolve_project_path(validator_file.validator_path)
            
            # Create a DynamicASTValidator for this specific validator
            validator = cls(
                name=validator_file.name,
                validator_path=validator_path,
                path=config_manager.project_root,
                ignore_paths=config_manager.paths_exclude,
                include_paths=config_manager.paths_include,
                isolation_paths=config_manager.isolation_paths,
                config_data=config_manager._get_validator_config_data(validator_file.name),
            )
            
            # Only add if the traverser class was successfully loaded
            if validator.traverser_class is not None:
                validators.append(validator)
        
        return validators
    
    async def validate(self) -> ValidationResult:
        """Run this validator against Python files."""
        # Check if the traverser class was loaded successfully
        if self.traverser_class is None:
            return ValidationResult(
                success=False, 
                output=f"Failed to load validator from {self.validator_path}"
            )
        if self.config_error is not None:
            return ValidationResult(
                success=False,
                output=f"Invalid config for validator '{self.name}': {self.config_error}",
            )
        
        # Find all Python files
        python_files = iter_python_files(
            self.path,
            self.ignore_paths,
            include_paths=self.include_paths,
            isolation_paths=self.isolation_paths,
        )
        
        if not python_files:
            return ValidationResult(success=True, output="No Python files found")
        
        all_issues = []
        
        for py_file in python_files:
            try:
                file_content = py_file.read_text()
                relative_path = py_file.relative_to(self.path)
                suppressions = SuppressionComments.from_source(file_content)
                
                traverser = self._create_traverser(file_content, str(relative_path))
                
                result = traverser.validate()
                
                if not result.is_valid and result.issues:
                    for issue in result.issues:
                        if (
                            suppressions.suppresses(issue.line_number, self.name)
                            or suppressions.suppresses(issue.line_number, "dynamic_ast")
                        ):
                            continue
                        formatted_issue = f"{relative_path}:{issue.line_number}: {issue.message}"
                        if issue.code_snippet:
                            formatted_issue += f"\n{issue.code_snippet}"
                        all_issues.append(formatted_issue)
            
            except Exception as e:
                all_issues.append(f"{py_file.relative_to(self.path)}: Error: {e}")
        
        success = len(all_issues) == 0
        output = "\n\n".join(all_issues) if all_issues else "No issues found"
        
        return ValidationResult(success=success, output=output)

    def _create_traverser(
        self,
        file_content: str,
        relative_path: str,
    ) -> DeterministicTraverser:
        assert self.traverser_class is not None
        sig = inspect.signature(self.traverser_class.__init__)
        params = sig.parameters

        accepts_filename = "filename" in params
        accepts_config = "config" in params

        if accepts_filename and accepts_config:
            return self.traverser_class(
                file_content,
                relative_path,
                config=self.traverser_config,
            )
        if accepts_filename:
            return self.traverser_class(file_content, relative_path)
        if accepts_config:
            return self.traverser_class(file_content, config=self.traverser_config)
        return self.traverser_class(file_content)

    def _load_traverser_config(self) -> None:
        if self.traverser_class is None:
            return

        config_model = getattr(self.traverser_class, "config_model", None)
        if config_model is None:
            return
        if not inspect.isclass(config_model) or not issubclass(config_model, BaseModel):
            self.config_error = "config_model must be a pydantic BaseModel subclass"
            return

        try:
            self.traverser_config = config_model.model_validate(self.config_data)
        except Exception as error:
            self.config_error = str(error)
    
    def _load_validator_module(self, validator_path: Path) -> Type[DeterministicTraverser] | None:
        """Helper function to load a validator module using importlib and find DeterministicTraverser subclass."""
        if not validator_path.exists():
            return None
        
        try:
            # Read the file content and execute it as Python code
            code_content = validator_path.read_text()
            
            # Create a temporary module
            import types
            module = types.ModuleType("validator_module")
            module.__file__ = str(validator_path)
            
            # Execute the code in the module's namespace
            exec(code_content, module.__dict__)
            
            # Find DeterministicTraverser subclasses
            for name in dir(module):
                obj = getattr(module, name)
                if (inspect.isclass(obj) and 
                    issubclass(obj, DeterministicTraverser) and 
                    obj is not DeterministicTraverser):
                    return obj
            
            return None
            
        except Exception as e:
            CONSOLE.print(f"[red]Error loading validator module: {e}[/red]")
            return None
