"""Tests for StaticAnalysisValidator."""

import asyncio
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, patch, MagicMock
import pytest

from determystic.validators.static_analysis import StaticAnalysisValidator
from determystic.configs.project import ProjectConfigManager


class TestStaticAnalysisValidator:
    """Test cases for StaticAnalysisValidator."""

    def test_init(self) -> None:
        """Test validator initialization."""
        path = Path("/test/path")
        command = ["ruff", "check", "/test/path", "--no-fix"]
        validator = StaticAnalysisValidator(path, command)
        
        assert validator.name == "static_analysis"
        assert validator.path == path
        assert validator.command == command

    def test_create_validators(self) -> None:
        """Test that create_validators returns correct validators."""
        path = Path("/test/path")
        
        # Mock ProjectConfigManager
        mock_config_manager = MagicMock(spec=ProjectConfigManager)
        mock_config_manager.project_root = path
        mock_config_manager.paths_exclude = []
        mock_config_manager.paths_include = []

        validators = StaticAnalysisValidator.create_validators(mock_config_manager)
        
        assert len(validators) == 2
        
        # Check ruff validator
        ruff_validator = validators[0]
        assert isinstance(ruff_validator, StaticAnalysisValidator)
        assert ruff_validator.command == ["ruff", "check", str(path), "--no-fix"]
        
        # Check ty validator  
        ty_validator = validators[1]
        assert isinstance(ty_validator, StaticAnalysisValidator)
        assert ty_validator.command == ["ty", "check", str(path)]

    def test_create_validators_passes_ignore_paths_to_tools(self) -> None:
        """Configured ignore paths are translated to external tool excludes."""
        path = Path("/test/path")

        mock_config_manager = MagicMock(spec=ProjectConfigManager)
        mock_config_manager.project_root = path
        mock_config_manager.paths_exclude = ["generated/", "vendor/client.py"]
        mock_config_manager.paths_include = []

        validators = StaticAnalysisValidator.create_validators(mock_config_manager)

        ruff_validator = cast(StaticAnalysisValidator, validators[0])
        ty_validator = cast(StaticAnalysisValidator, validators[1])

        assert ruff_validator.command == [
            "ruff",
            "check",
            str(path),
            "--no-fix",
            "--extend-exclude",
            "generated/",
            "--extend-exclude",
            "vendor/client.py",
            "--force-exclude",
        ]
        assert ty_validator.command == [
            "ty",
            "check",
            str(path),
            "--exclude",
            "generated/",
            "--exclude",
            "vendor/client.py",
            "--force-exclude",
        ]

    def test_create_validators_uses_paths_include_as_check_targets(self, tmp_path) -> None:
        """Include entries become the CLI check targets; missing paths are dropped."""
        (tmp_path / "api").mkdir()

        mock_config_manager = MagicMock(spec=ProjectConfigManager)
        mock_config_manager.project_root = tmp_path
        mock_config_manager.paths_exclude = []
        mock_config_manager.paths_include = ["api/", "missing/"]

        validators = StaticAnalysisValidator.create_validators(mock_config_manager)

        ruff_validator = cast(StaticAnalysisValidator, validators[0])
        ty_validator = cast(StaticAnalysisValidator, validators[1])
        assert ruff_validator.command == ["ruff", "check", str(tmp_path / "api"), "--no-fix"]
        assert ty_validator.command == ["ty", "check", str(tmp_path / "api")]

    def test_create_validators_glob_includes_fall_back_to_project_root(self, tmp_path) -> None:
        """Glob include entries cannot be CLI targets, so the whole project is checked."""
        mock_config_manager = MagicMock(spec=ProjectConfigManager)
        mock_config_manager.project_root = tmp_path
        mock_config_manager.paths_exclude = []
        mock_config_manager.paths_include = ["api/*.py"]

        validators = StaticAnalysisValidator.create_validators(mock_config_manager)

        ruff_validator = cast(StaticAnalysisValidator, validators[0])
        assert ruff_validator.command == ["ruff", "check", str(tmp_path), "--no-fix"]

    def test_create_validators_returns_nothing_when_no_include_targets_exist(self, tmp_path) -> None:
        """No existing include targets means there is nothing to check."""
        mock_config_manager = MagicMock(spec=ProjectConfigManager)
        mock_config_manager.project_root = tmp_path
        mock_config_manager.paths_exclude = []
        mock_config_manager.paths_include = ["missing/"]

        assert StaticAnalysisValidator.create_validators(mock_config_manager) == []

    @pytest.mark.asyncio
    async def test_validate_success(self) -> None:
        """Test successful validation."""
        path = Path("/test/path")
        command = ["echo", "success"]
        validator = StaticAnalysisValidator(path, command)
        
        with patch('asyncio.create_subprocess_exec') as mock_exec:
            # Mock a successful process
            mock_process = AsyncMock()
            mock_process.returncode = 0
            mock_process.communicate.return_value = (b"All checks passed", b"")
            mock_exec.return_value = mock_process
            
            result = await validator.validate()
            
            assert result.success is True
            assert result.output == "All checks passed"
            
            # Verify the command was called correctly
            mock_exec.assert_called_once_with(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=path
            )

    @pytest.mark.asyncio
    async def test_validate_failure(self) -> None:
        """Test validation failure."""
        path = Path("/test/path")
        command = ["false"]  # Command that always fails
        validator = StaticAnalysisValidator(path, command)
        
        with patch('asyncio.create_subprocess_exec') as mock_exec:
            # Mock a failed process
            mock_process = AsyncMock()
            mock_process.returncode = 1
            mock_process.communicate.return_value = (b"", b"Linting errors found")
            mock_exec.return_value = mock_process
            
            result = await validator.validate()
            
            assert result.success is False
            assert result.output == "Linting errors found"

    @pytest.mark.asyncio
    async def test_validate_stdout_fallback(self) -> None:
        """Test that stderr is used when stdout is empty."""
        path = Path("/test/path")
        command = ["test"]
        validator = StaticAnalysisValidator(path, command)
        
        with patch('asyncio.create_subprocess_exec') as mock_exec:
            # Mock process with empty stdout but stderr content
            mock_process = AsyncMock()
            mock_process.returncode = 0
            mock_process.communicate.return_value = (b"", b"Warning message")
            mock_exec.return_value = mock_process
            
            result = await validator.validate()
            
            assert result.success is True
            assert result.output == "Warning message"

    @pytest.mark.asyncio
    async def test_validate_empty_output(self) -> None:
        """Test validation with no output."""
        path = Path("/test/path")
        command = ["true"]  # Command that succeeds with no output
        validator = StaticAnalysisValidator(path, command)
        
        with patch('asyncio.create_subprocess_exec') as mock_exec:
            # Mock process with no output
            mock_process = AsyncMock()
            mock_process.returncode = 0
            mock_process.communicate.return_value = (b"", b"")
            mock_exec.return_value = mock_process
            
            result = await validator.validate()
            
            assert result.success is True
            assert result.output == ""

    @pytest.mark.asyncio
    async def test_validate_command_unpacking(self) -> None:
        """Test that command list is properly unpacked for subprocess."""
        path = Path("/test/path")
        command = ["ruff", "check", "file.py", "--no-fix"]
        validator = StaticAnalysisValidator(path, command)
        
        with patch('asyncio.create_subprocess_exec') as mock_exec:
            mock_process = AsyncMock()
            mock_process.returncode = 0
            mock_process.communicate.return_value = (b"", b"")
            mock_exec.return_value = mock_process
            
            await validator.validate()
            
            # Verify command was unpacked correctly (not passed as a list)
            mock_exec.assert_called_once_with(
                "ruff", "check", "file.py", "--no-fix",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=path
            )

    def test_display_name(self) -> None:
        """Test display name generation."""
        path = Path("/test/path")
        command = ["test"]
        validator = StaticAnalysisValidator(path, command)
        
        assert validator.display_name == "Static Analysis"
