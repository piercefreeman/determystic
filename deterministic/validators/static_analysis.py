"""Static analysis validators using ruff and ty."""

import asyncio
import asyncio.subprocess
from pathlib import Path

from .base import BaseValidator, ValidationResult


class StaticAnalysisValidator(BaseValidator):
    """
    Composite validator that runs all static analysis tools. Since these are CLI
    driven, this static analyzer operates via CLI calls where we passthrough
    the validated output for each file.
    
    """
    
    def __init__(self, *, name: str, command: list[str], path: Path | None = None) -> None:
        super().__init__(name=name, path=path)
        self.command = command
    
    @classmethod
    def create_validators(cls, path: Path) -> list[BaseValidator]:
        return [
            cls(name="ruff_check", command=["ruff", "check", str(path), "--no-fix"], path=path),
            cls(name="typos_check", command=["typos", "check", str(path)], path=path)
        ]   
    
    async def validate(self, path: Path) -> ValidationResult:
        """Run the static analysis command on the given path."""
        try:
            process = await asyncio.create_subprocess_exec(
                *self.command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=path
            )
            
            stdout, stderr = await process.communicate()
            return ValidationResult(
                success=process.returncode == 0,
                output=stdout.decode() if stdout else stderr.decode()
            )
        except Exception as e:
            return ValidationResult(
                success=False,
                output=f"Error running {' '.join(self.command)}: {e}"
            )
