"""Dynamic AST validator that loads custom validators from .deterministic files."""

import importlib.util
import inspect
from pathlib import Path
from typing import Type

from deterministic.configs.project import ProjectConfigManager
from deterministic.external import DeterministicTraverser
from deterministic.validators.base import BaseValidator, ValidationResult
from deterministic.logging import CONSOLE


class DynamicASTValidator(BaseValidator):
    """Loads and runs custom AST validators from .deterministic files."""
    
    def __init__(self, *, name: str, validator_path: Path, path: Path | None = None) -> None:
        super().__init__(name=name, path=path)
        self.validator_path = validator_path
        self.traverser_class = self._load_validator_module(validator_path)
    
    @classmethod
    def create_validators(cls, path: Path) -> list["BaseValidator"]:
        """Factory function that creates DynamicASTValidator instances for each deterministic validator."""
        validators = []
        
        # Find .deterministic config
        config_manager = ProjectConfigManager.load_from_disk()

        # Load each validator file as a separate validator instance
        for validator_file in config_manager.validators.values():
            validator_path = path / validator_file.validator_path
            
            # Create a DynamicASTValidator for this specific validator
            validator = cls(
                name=validator_file.name,
                validator_path=validator_path,
                path=path
            )
            
            # Only add if the traverser class was successfully loaded
            if validator.traverser_class is not None:
                validators.append(validator)
        
        return validators
    
    async def validate(self, path: Path) -> ValidationResult:
        """Run this validator against Python files."""
        # Check if the traverser class was loaded successfully
        if self.traverser_class is None:
            return ValidationResult(
                success=False, 
                output=f"Failed to load validator from {self.validator_path}"
            )
        
        # Find all Python files
        python_files = list(path.rglob("*.py"))
        python_files = [f for f in python_files if not any(part.startswith('.') for part in f.parts)]
        
        if not python_files:
            return ValidationResult(success=True, output="No Python files found")
        
        all_issues = []
        
        for py_file in python_files:
            try:
                file_content = py_file.read_text()
                relative_path = py_file.relative_to(path)
                
                # Run traverser
                traverser = self.traverser_class(file_content, str(relative_path))
                result = traverser.validate()
                
                if not result.is_valid and result.issues:
                    for issue in result.issues:
                        formatted_issue = f"{relative_path}:{issue.line_number}: {issue.message}"
                        if issue.code_snippet:
                            formatted_issue += f"\n{issue.code_snippet}"
                        all_issues.append(formatted_issue)
            
            except Exception as e:
                all_issues.append(f"{py_file.relative_to(path)}: Error: {e}")
        
        success = len(all_issues) == 0
        output = "\n\n".join(all_issues) if all_issues else "No issues found"
        
        return ValidationResult(success=success, output=output)
    
    def _load_validator_module(self, validator_path: Path) -> Type[DeterministicTraverser] | None:
        """Helper function to load a validator module using importlib and find DeterministicTraverser subclass."""
        if not validator_path.exists():
            return None
        
        try:
            # Load the module using importlib
            spec = importlib.util.spec_from_file_location("validator_module", validator_path)
            if spec is None or spec.loader is None:
                return None
            
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            
            # Find DeterministicTraverser subclasses
            for name in dir(module):
                obj = getattr(module, name)
                if (inspect.isclass(obj) and 
                    issubclass(obj, DeterministicTraverser) and 
                    obj is not DeterministicTraverser):
                    return obj
            
            return None
            
        except Exception:
            CONSOLE.print(f"[red]Error loading validator module: {e}[/red]")
            return None
