"""Dynamic AST validator that loads custom validators from .determystic files."""

import inspect
from pathlib import Path
from typing import Type

from determystic.configs.project import ProjectConfigManager
from determystic.external import DeterministicTraverser
from determystic.validators.base import BaseValidator, ValidationResult
from determystic.logging import CONSOLE


class DynamicASTValidator(BaseValidator):
    """Loads and runs custom AST validators from .determystic files."""
    
    def __init__(self, *, name: str, validator_path: Path, path: Path | None = None) -> None:
        super().__init__(name=name, path=path)
        self.validator_path = validator_path
        self.traverser_class = self._load_validator_module(validator_path)
    
    @classmethod
    def create_validators(cls, config_manager: ProjectConfigManager) -> list["BaseValidator"]:
        """Factory function that creates DynamicASTValidator instances for each determystic validator."""
        validators = []
        
        if not config_manager or not config_manager.validators:
            return validators

        # Load each validator file as a separate validator instance
        for validator_file in config_manager.validators.values():
            # The validator_path is relative to the .determystic directory, not the project root
            validator_path = config_manager.project_root / ".determystic" / validator_file.validator_path
            
            # Create a DynamicASTValidator for this specific validator
            validator = cls(
                name=validator_file.name,
                validator_path=validator_path,
                path=config_manager.project_root
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
        
        # Find all Python files
        python_files = list(self.path.rglob("*.py"))
        python_files = [f for f in python_files if not any(part.startswith('.') for part in f.parts)]
        
        if not python_files:
            return ValidationResult(success=True, output="No Python files found")
        
        all_issues = []
        
        for py_file in python_files:
            try:
                file_content = py_file.read_text()
                relative_path = py_file.relative_to(self.path)
                
                # Run traverser - check signature to handle different constructor patterns
                sig = inspect.signature(self.traverser_class.__init__)
                params = list(sig.parameters.keys())
                
                # If it only accepts 'self' and 'code', don't pass filename
                if len(params) == 2 and 'filename' not in params:
                    traverser = self.traverser_class(file_content)
                else:
                    traverser = self.traverser_class(file_content, str(relative_path))
                
                result = traverser.validate()
                
                if not result.is_valid and result.issues:
                    for issue in result.issues:
                        formatted_issue = f"{relative_path}:{issue.line_number}: {issue.message}"
                        if issue.code_snippet:
                            formatted_issue += f"\n{issue.code_snippet}"
                        all_issues.append(formatted_issue)
            
            except Exception as e:
                all_issues.append(f"{py_file.relative_to(self.path)}: Error: {e}")
        
        success = len(all_issues) == 0
        output = "\n\n".join(all_issues) if all_issues else "No issues found"
        
        return ValidationResult(success=success, output=output)
    
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
