"""Static analysis validators using ruff and ty."""

import asyncio
import asyncio.subprocess
from pathlib import Path

from determystic.configs.project import ProjectConfigManager
from determystic.path_filters import GLOB_CHARS
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
        check_targets = _check_targets(config_manager)
        if not check_targets:
            return []

        ruff_command = [
            "ruff",
            "check",
            *check_targets,
            "--no-fix",
            *_ruff_ignore_args(config_manager.paths_exclude),
        ]
        ty_command = [
            "ty",
            "check",
            *check_targets,
            *_ty_ignore_args(config_manager.paths_exclude),
        ]
        return [
            cls(config_manager.project_root, ruff_command),
            cls(config_manager.project_root, ty_command),
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


def _check_targets(config_manager: ProjectConfigManager) -> list[str]:
    """Resolve check targets from paths_include, falling back to the project root.

    Glob include entries cannot be expressed as CLI targets, so any glob falls
    back to checking the whole project (excludes still apply).
    """
    include_paths = [
        include_path.strip()
        for include_path in config_manager.paths_include
        if include_path.strip()
    ]
    has_glob = any(
        any(char in include_path for char in GLOB_CHARS)
        for include_path in include_paths
    )
    if not include_paths or has_glob:
        return [str(config_manager.project_root)]

    return [
        str(config_manager.project_root / _normalize_cli_ignore_path(include_path))
        for include_path in include_paths
        if (config_manager.project_root / _normalize_cli_ignore_path(include_path)).exists()
    ]


def _ruff_ignore_args(ignore_paths: list[str]) -> list[str]:
    args: list[str] = []
    for ignore_path in ignore_paths:
        if not ignore_path.strip():
            continue
        args.extend(["--extend-exclude", _normalize_cli_ignore_path(ignore_path)])
    if args:
        args.append("--force-exclude")
    return args


def _ty_ignore_args(ignore_paths: list[str]) -> list[str]:
    args: list[str] = []
    for ignore_path in ignore_paths:
        if not ignore_path.strip():
            continue
        args.extend(["--exclude", _normalize_cli_ignore_path(ignore_path)])
    if args:
        args.append("--force-exclude")
    return args


def _normalize_cli_ignore_path(ignore_path: str) -> str:
    return ignore_path.strip().replace("\\", "/")
