"""Parameterized tests for project configuration management."""

import tempfile
from datetime import datetime
from pathlib import Path
from typing import Type
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from determystic.configs.project import ProjectConfigManager, ValidatorFile


@pytest.fixture(autouse=True)
def reset_class_state():
    """Reset the class state before each test."""
    ProjectConfigManager._found_path = None
    ProjectConfigManager.runtime_custom_path = None
    yield
    ProjectConfigManager._found_path = None
    ProjectConfigManager.runtime_custom_path = None


class TestValidatorFile:
    """Test the ValidatorFile model."""
    
    @pytest.mark.parametrize("name,validator_path,test_path,description", [
        ("test_validator", "validators/test_validator.py", "tests/test_validator.py", "Test description"),
        ("simple", "simple.py", None, None),
        ("complex_validator", "validators/complex.py", "tests/complex.py", "Complex validation logic"),
        ("no_test", "validators/no_test.py", None, "Validator without test"),
    ])
    def test_validator_file_creation(
        self, 
        name: str, 
        validator_path: str, 
        test_path: str | None, 
        description: str | None
    ) -> None:
        """Test ValidatorFile creation with various parameter combinations."""
        # Create with all fields
        validator_file = ValidatorFile(
            name=name,
            validator_path=validator_path,
            test_path=test_path,
            description=description
        )
        
        assert validator_file.name == name
        assert validator_file.validator_path == validator_path
        assert validator_file.test_path == test_path
        assert validator_file.description == description
        assert isinstance(validator_file.created_at, datetime)

    @pytest.mark.parametrize("invalid_data,error_type", [
        ({}, ValidationError),  # Missing required fields
        ({"validator_path": "test.py"}, ValidationError),  # Missing name
        ({"name": "test"}, ValidationError),  # Missing validator_path
        ({"name": 123, "validator_path": "test.py"}, ValidationError),  # Invalid name type
    ])
    def test_validator_file_validation_errors(
        self, 
        invalid_data: dict, 
        error_type: Type[Exception]
    ) -> None:
        """Test ValidatorFile validation with invalid data."""
        with pytest.raises(error_type):
            ValidatorFile(**invalid_data)


class TestProjectConfigManagerClassMethods:
    """Test class methods of ProjectConfigManager."""
    
    @pytest.mark.parametrize("custom_path", [
        "custom/path",
        "existing/path",
    ])
    def test_set_runtime_custom_path(
        self, 
        custom_path: str
    ) -> None:
        """Test setting runtime custom path."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            path = temp_path / custom_path
            
            # set_runtime_custom_path only sets the path, it doesn't create config files
            ProjectConfigManager.set_runtime_custom_path(path)
            
            # Verify the runtime path was set
            assert ProjectConfigManager.runtime_custom_path == path / ".determystic"
            
            # Clean up
            ProjectConfigManager.runtime_custom_path = None

    @pytest.mark.parametrize("runtime_path_set,expected_paths_count", [
        (True, 1),   # With runtime path set, should return 1 path
        (False, 2),  # Without runtime path, should return 2 paths (git root + pyproject)
    ])
    def test_get_possible_config_paths(
        self, 
        runtime_path_set: bool, 
        expected_paths_count: int
    ) -> None:
        """Test getting possible config paths with and without runtime path."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            
            if runtime_path_set:
                custom_path = temp_path / "custom"
                ProjectConfigManager.runtime_custom_path = custom_path
            
            # Mock the detect functions to return predictable paths
            with patch('determystic.configs.project.detect_git_root') as mock_git, \
                 patch('determystic.configs.project.detect_pyproject_path') as mock_pyproject:
                
                mock_git.return_value = temp_path / "git_root"
                mock_pyproject.return_value = temp_path / "pyproject_root"
                
                paths = ProjectConfigManager.get_possible_config_paths()
                
                assert len(paths) == expected_paths_count
                
                if runtime_path_set:
                    assert paths == [custom_path / "config.toml"]
                    # Verify detect functions weren't called when runtime path is set
                    mock_git.assert_not_called()
                    mock_pyproject.assert_not_called()
                else:
                    expected_git_path = temp_path / "git_root" / ".determystic" / "config.toml"
                    expected_pyproject_path = temp_path / "pyproject_root" / ".determystic" / "config.toml"
                    assert paths == [expected_git_path, expected_pyproject_path]
                    # Verify detect functions were called
                    mock_git.assert_called_once()
                    mock_pyproject.assert_called_once()
                
                # Clean up
                if runtime_path_set:
                    ProjectConfigManager.runtime_custom_path = None


class TestProjectConfigManagerInstanceMethods:
    """Test instance methods of ProjectConfigManager."""
    
    @pytest.mark.parametrize("name,validator_script,test_script,description", [
        ("simple_validator", "# Simple validator", "# Simple test", "Simple description"),
        ("complex_validator", "def validate():\n    pass", "def test_validate():\n    pass", "Complex validator"),
        ("no_description", "# Code", "# Test", None),
        ("unicode_name", "# Unicode content 🔍", "# Unicode test 🧪", "Unicode description 📝"),
    ])
    def test_new_validation_creates_validator_file(
        self, 
        name: str, 
        validator_script: str, 
        test_script: str, 
        description: str | None
    ) -> None:
        """Test creating new validation files with various parameters."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            config_file = temp_path / "config.toml"
            config_file.write_text("")
            
            with patch.object(ProjectConfigManager, 'get_possible_config_paths', return_value=[config_file]):
                config = ProjectConfigManager()
                
                # Test the new_validation method
                validator_file = config.new_validation(name, validator_script, test_script, description)
                
                # Verify ValidatorFile was created correctly
                assert isinstance(validator_file, ValidatorFile)
                assert validator_file.name == name
                assert validator_file.description == description
                assert isinstance(validator_file.created_at, datetime)
                
                # Verify paths are relative to config root
                config_root = config_file.parent
                expected_validator_path = f"validations/{name}.determystic"
                expected_test_path = f"tests/{name}.determystic"
                
                assert validator_file.validator_path == expected_validator_path
                assert validator_file.test_path == expected_test_path
                
                # Verify files were actually created with correct content
                actual_validator_path = config_root / "validations" / f"{name}.determystic"
                actual_test_path = config_root / "tests" / f"{name}.determystic"
                
                assert actual_validator_path.exists()
                assert actual_test_path.exists()
                assert actual_validator_path.read_text() == validator_script
                assert actual_test_path.read_text() == test_script
                
                # Verify validator was added to config
                assert name in config.validators
                assert config.validators[name] == validator_file
                
                # Verify updated_at was set
                assert isinstance(config.updated_at, datetime)

    @pytest.mark.parametrize("existing_validators,validator_to_delete,expected_result", [
        (["validator1", "validator2"], "validator1", True),
        (["validator1", "validator2"], "validator2", True),
        (["validator1"], "validator1", True),
        (["validator1", "validator2"], "nonexistent", False),
        ([], "any_name", False),
    ])
    def test_delete_validation(
        self, 
        existing_validators: list[str], 
        validator_to_delete: str, 
        expected_result: bool
    ) -> None:
        """Test deleting validators with various scenarios."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            config_file = temp_path / "config.toml"
            config_file.write_text("")
            
            with patch.object(ProjectConfigManager, 'get_possible_config_paths', return_value=[config_file]):
                config = ProjectConfigManager()
                
                # Set up existing validators
                for validator_name in existing_validators:
                    validator_file = ValidatorFile(
                        name=validator_name,
                        validator_path=f"validators/{validator_name}.py"
                    )
                    config.validators[validator_name] = validator_file
                
                original_count = len(config.validators)
                original_updated_at = config.updated_at
                
                # Test deletion
                result = config.delete_validation(validator_to_delete)
                
                # Verify result
                assert result == expected_result
                
                if expected_result:
                    # Validator should be removed
                    assert validator_to_delete not in config.validators
                    assert len(config.validators) == original_count - 1
                    # updated_at should be changed
                    assert config.updated_at > original_updated_at
                else:
                    # Nothing should change
                    assert len(config.validators) == original_count
                    # updated_at should remain the same (allowing for small time differences)
                    time_diff = abs((config.updated_at - original_updated_at).total_seconds())
                    assert time_diff < 0.1

    def test_new_validation_updates_timestamp(self) -> None:
        """Test that new_validation updates the updated_at timestamp."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            config_file = temp_path / "config.toml"
            config_file.write_text("")
            
            with patch.object(ProjectConfigManager, 'get_possible_config_paths', return_value=[config_file]):
                config = ProjectConfigManager()
                original_updated_at = config.updated_at
                
                # Small delay to ensure timestamp difference
                import time
                time.sleep(0.01)
                
                config.new_validation("test", "# code", "# test", "description")
                
                # Verify timestamp was updated
                assert config.updated_at > original_updated_at

    def test_new_validation_creates_directories(self) -> None:
        """Test that new_validation creates necessary directories."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            config_file = temp_path / "config.toml"
            config_file.write_text("")
            
            with patch.object(ProjectConfigManager, 'get_possible_config_paths', return_value=[config_file]):
                config = ProjectConfigManager()
                
                # Ensure directories don't exist initially
                validations_dir = config_file.parent / "validations"
                tests_dir = config_file.parent / "tests"
                assert not validations_dir.exists()
                assert not tests_dir.exists()
                
                config.new_validation("test", "# code", "# test")
                
                # Verify directories were created
                assert validations_dir.exists()
                assert tests_dir.exists()
                assert validations_dir.is_dir()
                assert tests_dir.is_dir()


class TestProjectConfigManagerIntegration:
    """Integration tests for ProjectConfigManager."""
    
    @pytest.mark.parametrize("config_data", [
        {"version": "1.0", "project_name": "test_project"},
        {"version": "2.0", "project_name": "another_project", "settings": {"debug": True}},
    ])
    def test_save_and_load_roundtrip(self, config_data: dict) -> None:
        """Test that saving and loading a config preserves all data."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            config_file = temp_path / "config.toml"
            config_file.write_text("")
            
            with patch.object(ProjectConfigManager, 'get_possible_config_paths', return_value=[config_file]):
                # Create config with test data
                original_config = ProjectConfigManager(**config_data)
                original_config.save_to_disk()
                
                # Load config back
                loaded_config = ProjectConfigManager.load_from_disk()
                
                # Verify loaded config matches original
                assert loaded_config is not None
                assert loaded_config.version == original_config.version
                assert loaded_config.project_name == original_config.project_name
                assert loaded_config.settings == original_config.settings

    def test_multiple_validators_workflow(self) -> None:
        """Test a complete workflow with multiple validators."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            config_file = temp_path / "config.toml"
            config_file.write_text("")
            
            with patch.object(ProjectConfigManager, 'get_possible_config_paths', return_value=[config_file]):
                config = ProjectConfigManager(project_name="test_project")
                
                # Add multiple validators
                config.new_validation("validator1", "# code1", "# test1", "First validator")
                config.new_validation("validator2", "# code2", "# test2", "Second validator")
                
                # Verify both exist
                assert len(config.validators) == 2
                assert "validator1" in config.validators
                assert "validator2" in config.validators
                
                # Delete one validator
                result = config.delete_validation("validator1")
                assert result is True
                assert len(config.validators) == 1
                assert "validator1" not in config.validators
                assert "validator2" in config.validators
                
                # Try to delete non-existent validator
                result = config.delete_validation("nonexistent")
                assert result is False
                assert len(config.validators) == 1