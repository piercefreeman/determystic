"""Static analysis validators using ruff and ty."""

import asyncio
import asyncio.subprocess
from pathlib import Path

from determystic.configs.project import ProjectConfigManager
from .base import BaseValidator, ValidationResult


class StaticAnalysisValidator(BaseValidator):
    """
    Composite validator that runs all static analysis tools. Since these are CLI
    driven, this static analyzer operates via CLI calls where we passthrough
    the validated output for each file.
    
    """
    
    def __init__(self, path: Path, command: list[str]) -> None:
        super().__init__(name="static_analysis", path=path)
        self.command = command
    
    @classmethod
    def create_validators(cls, config_manager: ProjectConfigManager) -> list[BaseValidator]:
        return [
            cls(config_manager.project_root, ["ruff", "check", str(config_manager.project_root), "--no-fix"]),
            cls(config_manager.project_root, ["ty", "check", str(config_manager.project_root)])
        ]   
    
    async def validate(self) -> ValidationResult:
        """Run the static analysis command on the given path."""
        process = await asyncio.create_subprocess_exec(
            *self.command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self.path
        )
        
        stdout, stderr = await process.communicate()
        return ValidationResult(
            success=process.returncode == 0,
            output=stdout.decode() if stdout else stderr.decode()
        )
