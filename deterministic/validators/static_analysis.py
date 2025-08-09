"""Static analysis validators using ruff and ty."""

import asyncio
import asyncio.subprocess
from pathlib import Path
from typing import List, Tuple

from .base import BaseValidator, ValidationResult


async def run_command(command: list[str], cwd: Path) -> Tuple[int, str, str]:
    """Run a command asynchronously and return exit code, stdout, and stderr.
    
    Args:
        command: Command and arguments to run
        cwd: Working directory for the command
        
    Returns:
        Tuple of (exit_code, stdout, stderr)
    """
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd
    )
    
    stdout, stderr = await process.communicate()
    return process.returncode or 0, stdout.decode(), stderr.decode()


class RuffValidator(BaseValidator):
    """Validator for running ruff linting."""
    
    def __init__(self) -> None:
        """Initialize the ruff validator."""
        super().__init__("ruff")
    
    async def validate(self, path: Path) -> ValidationResult:
        """Run ruff validation on the given path.
        
        Args:
            path: Path to the Python project
            
        Returns:
            ValidationResult with success status and output
        """
        command = ["ruff", "check", str(path), "--no-fix"]
        exit_code, stdout, stderr = await run_command(command, path)
        
        output = stdout if stdout else stderr
        success = exit_code == 0
        
        return ValidationResult(
            success=success,
            output=output,
            details={"exit_code": exit_code}
        )


class TypeValidator(BaseValidator):
    """Validator for running ty type checker."""
    
    def __init__(self) -> None:
        """Initialize the type validator."""
        super().__init__("ty")
    
    async def validate(self, path: Path) -> ValidationResult:
        """Run ty type validation on the given path.
        
        Args:
            path: Path to the Python project
            
        Returns:
            ValidationResult with success status and output
        """
        command = ["ty", "check", str(path)]
        exit_code, stdout, stderr = await run_command(command, path)
        
        output = stdout if stdout else stderr
        success = exit_code == 0
        
        return ValidationResult(
            success=success,
            output=output,
            details={"exit_code": exit_code}
        )


class StaticAnalysisValidator(BaseValidator):
    """Composite validator that runs all static analysis tools."""
    
    def __init__(self) -> None:
        """Initialize the static analysis validator."""
        super().__init__("static_analysis")
        self.validators: List[BaseValidator] = [
            RuffValidator(),
            TypeValidator()
        ]
    
    async def validate(self, path: Path) -> ValidationResult:
        """Run all static analysis validators in parallel.
        
        Args:
            path: Path to the Python project
            
        Returns:
            ValidationResult with combined results
        """
        # Run all validators in parallel
        results = await asyncio.gather(
            *[validator.validate(path) for validator in self.validators]
        )
        
        # Combine results
        all_success = all(result.success for result in results)
        combined_output = []
        details = {}
        
        for validator, result in zip(self.validators, results):
            if not result.success or result.output.strip():
                combined_output.append(f"[{validator.display_name}]")
                combined_output.append(result.output)
                combined_output.append("")
            details[validator.name] = {
                "success": result.success,
                "output": result.output
            }
        
        return ValidationResult(
            success=all_success,
            output="\n".join(combined_output).strip(),
            details=details
        )