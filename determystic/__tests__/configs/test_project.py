"""Parameterized tests for project configuration management."""

import tempfile
from determystic.compat import tomllib
from pathlib import Path
from typing import Type
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from determystic.configs.project import ProjectConfigManager, ProjectSettings, ValidatorFile


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
            assert ProjectConfigManager.runtime_custom_path == path.absolute()
            
            # Clean up
            ProjectConfigManager.runtime_custom_path = None

    @pytest.mark.parametrize("runtime_path_set,expected_paths_count", [
        (True, 1),   # With runtime path set, should return 1 path
        (False, 1),  # Without runtime path, should return the discovered pyproject
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
                    assert paths == [custom_path / "pyproject.toml"]
                    # Verify detect functions weren't called when runtime path is set
                    mock_git.assert_not_called()
                    mock_pyproject.assert_not_called()
                else:
                    expected_pyproject_path = temp_path / "pyproject_root" / "pyproject.toml"
                    assert paths == [expected_pyproject_path]
                    mock_git.assert_not_called()
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
            config_file = temp_path / "pyproject.toml"
            config_file.write_text("")
            
            with patch.object(ProjectConfigManager, 'get_possible_config_paths', return_value=[config_file]):
                config = ProjectConfigManager()
                
                # Test the new_validation method
                validator_file = config.new_validation(name, validator_script, test_script, description)
                
                # Verify ValidatorFile was created correctly
                assert isinstance(validator_file, ValidatorFile)
                assert validator_file.name == name
                assert validator_file.description == description
                # Verify paths are relative to the project root
                config_root = config_file.parent / ".determystic"
                expected_validator_path = f".determystic/validations/{name}.determystic"
                expected_test_path = f".determystic/tests/{name}.determystic"
                
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
            config_file = temp_path / "pyproject.toml"
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
                
                # Test deletion
                result = config.delete_validation(validator_to_delete)
                
                # Verify result
                assert result == expected_result
                
                if expected_result:
                    # Validator should be removed
                    assert validator_to_delete not in config.validators
                    assert len(config.validators) == original_count - 1
                else:
                    # Nothing should change
                    assert len(config.validators) == original_count

    def test_delete_validation_removes_discovered_validator_files(self) -> None:
        """Deleting a discovered validator removes its files even without config metadata."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            config_file = temp_path / "pyproject.toml"
            validator_file = temp_path / ".determystic" / "validations" / "custom.determystic"
            test_file = temp_path / ".determystic" / "tests" / "custom.determystic"
            validator_file.parent.mkdir(parents=True)
            test_file.parent.mkdir(parents=True)
            validator_file.write_text("# validator")
            test_file.write_text("# tests")
            config_file.write_text("[tool.determystic]\n")

            config = ProjectConfigManager.load_from_config_path(config_file)

            assert config.delete_validation("custom") is True
            assert not validator_file.exists()
            assert not test_file.exists()
            assert config.get_custom_validators() == {}

            # A second delete finds nothing left to remove
            assert config.delete_validation("custom") is False

    def test_new_validation_metadata_is_not_required_for_discovery(self) -> None:
        """New standard validator files are discoverable without persisted metadata."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            config_file = temp_path / "pyproject.toml"
            config_file.write_text("")
            
            with patch.object(ProjectConfigManager, 'get_possible_config_paths', return_value=[config_file]):
                config = ProjectConfigManager()
                config.new_validation("test", "# code", "# test", "description")

                custom_validators = config.get_custom_validators()

                assert set(custom_validators) == {"test"}
                assert custom_validators["test"].validator_path == ".determystic/validations/test.determystic"

    def test_new_validation_creates_directories(self) -> None:
        """Test that new_validation creates necessary directories."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            config_file = temp_path / "pyproject.toml"
            config_file.write_text("")
            
            with patch.object(ProjectConfigManager, 'get_possible_config_paths', return_value=[config_file]):
                config = ProjectConfigManager()
                
                # Ensure directories don't exist initially
                validations_dir = config_file.parent / ".determystic" / "validations"
                tests_dir = config_file.parent / ".determystic" / "tests"
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

    def test_load_from_pyproject_tool_section(self) -> None:
        """Test loading project config from [tool.determystic]."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            config_file = temp_path / "pyproject.toml"
            config_file.write_text("""
[project]
name = "sample"

[tool.determystic]
version = "2.0"
project_name = "configured_project"
validator_exclude = ["Static Analysis"]
validator_enabled = ["Function Visibility"]
paths_include = ["src/"]
paths_exclude = ["generated/", "vendor/client.py"]

[tool.determystic.settings]
debug = true
validator_agent = "Codex"

[tool.determystic.validators.exception_coverage.config]
strict = true

[tool.determystic.validators.hanging_functions]
allowed_names = ["framework_hook"]
""")

            with patch.object(ProjectConfigManager, 'get_possible_config_paths', return_value=[config_file]):
                config = ProjectConfigManager.load_from_disk()

                assert config.version == "2.0"
                assert config.project_name == "configured_project"
                assert config.validator_exclude == ["Static Analysis"]
                assert config.validator_enabled == ["Function Visibility"]
                assert config.paths_include == ["src/"]
                assert config.paths_exclude == ["generated/", "vendor/client.py"]
                assert config.settings.validator_agent == "codex"
                assert config.settings.model_extra == {"debug": True}
                assert config.validators == {}
                assert config._get_validator_config_data("exception_coverage") == {"strict": True}
                assert config._get_validator_config_data("hanging_functions") == {
                    "allowed_names": ["framework_hook"]
                }

    def test_load_from_config_path_can_validate_different_project_root(self) -> None:
        """Inherited configs keep file paths config-relative and validation root scoped."""
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace_root = Path(temp_dir)
            member_root = workspace_root / "packages" / "api"
            member_root.mkdir(parents=True)
            config_file = workspace_root / "pyproject.toml"
            config_file.write_text(
                """
[project]
name = "workspace"

[tool.determystic]
paths_exclude = ["generated/"]

[tool.determystic.validators.custom]
name = "custom"
validator_path = ".determystic/validations/custom.determystic"
"""
            )

            config = ProjectConfigManager.load_from_config_path(
                config_file,
                project_root=member_root,
                extra_ignore_paths=["vendor/"],
            )

            assert config.config_path == config_file.resolve()
            assert config.config_root == workspace_root.resolve()
            assert config.project_root == member_root.resolve()
            assert config.paths_exclude == ["generated/", "vendor/"]
            assert config.isolation_paths == ["vendor/"]
            assert config.resolve_project_path(
                ".determystic/validations/custom.determystic"
            ) == (
                workspace_root.resolve()
                / ".determystic"
                / "validations"
                / "custom.determystic"
            )

    def test_load_from_pyproject_ignores_legacy_keys(self) -> None:
        """Legacy key spellings are not aliased onto the new config fields."""
        config = ProjectConfigManager.model_validate(
            {
                "ignored_paths": ["generated/"],
                "ignore_paths": ["generated/"],
                "enabled": ["all"],
                "exclude": ["Static Analysis"],
            }
        )

        assert config.paths_exclude == []
        assert config.validator_enabled == []
        assert config.validator_exclude == []

    def test_validator_config_model_validation(self) -> None:
        """Validator config payloads can be validated against caller-provided models."""
        from pydantic import BaseModel

        class ExampleConfig(BaseModel):
            threshold: int = 3

        config = ProjectConfigManager.model_validate(
            {
                "validators": {
                    "example": {
                        "config": {
                            "threshold": 5,
                        }
                    }
                }
            }
        )

        validator_config = config.get_validator_config("example", ExampleConfig)

        assert validator_config.threshold == 5

    def test_custom_validator_config_is_preserved_with_metadata(self) -> None:
        """Custom validator metadata can carry an isolated config payload."""
        config = ProjectConfigManager.model_validate(
            {
                "validators": {
                    "custom": {
                        "name": "custom",
                        "validator_path": ".determystic/validations/custom.determystic",
                        "config": {
                            "forbidden_name": "bad_pattern",
                        },
                    }
                }
            }
        )

        assert set(config.validators) == {"custom"}
        assert config.validators["custom"].config == {"forbidden_name": "bad_pattern"}
        assert config._get_validator_config_data("custom") == {
            "forbidden_name": "bad_pattern"
        }

    def test_get_custom_validators_discovers_standard_validation_files(self) -> None:
        """Standard .determystic validation files are custom validators by convention."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            config_file = temp_path / "pyproject.toml"
            validator_file = temp_path / ".determystic" / "validations" / "custom.determystic"
            test_file = temp_path / ".determystic" / "tests" / "custom.determystic"
            validator_file.parent.mkdir(parents=True)
            test_file.parent.mkdir(parents=True)
            validator_file.write_text("# validator")
            test_file.write_text("# tests")
            config_file.write_text("[tool.determystic]\n")

            config = ProjectConfigManager.load_from_config_path(config_file)
            custom_validators = config.get_custom_validators()

        assert set(custom_validators) == {"custom"}
        assert custom_validators["custom"].validator_path == ".determystic/validations/custom.determystic"
        assert custom_validators["custom"].test_path == ".determystic/tests/custom.determystic"

    def test_save_to_pyproject_omits_standard_validator_metadata(self) -> None:
        """Generated validators should not create a pyproject registry entry."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            config_file = temp_path / "pyproject.toml"
            config_file.write_text("")

            with patch.object(ProjectConfigManager, 'get_possible_config_paths', return_value=[config_file]):
                config = ProjectConfigManager()
                config.new_validation("custom", "# validator", "# tests", "Generated validator")
                config.save_to_disk()

                with config_file.open("rb") as f:
                    saved_data = tomllib.load(f)

        determystic_data = saved_data["tool"]["determystic"]
        assert determystic_data == {}

    def test_save_to_pyproject_preserves_nonstandard_validator_paths(self) -> None:
        """Explicit metadata remains available for nonstandard validator locations."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            config_file = temp_path / "pyproject.toml"
            config_file.write_text("")

            with patch.object(ProjectConfigManager, 'get_possible_config_paths', return_value=[config_file]):
                config = ProjectConfigManager(
                    validators={
                        "custom": ValidatorFile(
                            name="custom",
                            validator_path="validators/custom.determystic",
                        )
                    }
                )
                config.save_to_disk()

                with config_file.open("rb") as f:
                    saved_data = tomllib.load(f)

        assert saved_data["tool"]["determystic"]["validators"]["custom"] == {
            "validator_path": "validators/custom.determystic"
        }

    def test_save_to_pyproject_serializes_validator_configs_under_validator_sections(self) -> None:
        """Config-only validator payloads are written under tool.determystic.validators."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            config_file = temp_path / "pyproject.toml"
            config_file.write_text("")

            with patch.object(ProjectConfigManager, 'get_possible_config_paths', return_value=[config_file]):
                config = ProjectConfigManager(
                    validator_configs={
                        "exception_coverage": {
                            "strict": True,
                        }
                    }
                )
                config.save_to_disk()

                with config_file.open("rb") as f:
                    saved_data = tomllib.load(f)

        assert saved_data["tool"]["determystic"]["validators"]["exception_coverage"]["config"] == {
            "strict": True
        }

    def test_project_settings_accepts_legacy_agent_alias(self) -> None:
        """Test loading the old agent key into the typed validator_agent setting."""
        settings = ProjectSettings.model_validate({"agent": " claude ", "debug": True})

        assert settings.validator_agent == "claude"
        assert settings.model_extra == {"debug": True}

    def test_save_to_pyproject_preserves_existing_sections(self) -> None:
        """Test saving config under [tool.determystic] without dropping pyproject metadata."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            config_file = temp_path / "pyproject.toml"
            config_file.write_text("""
[project]
name = "sample"

[tool.uv]
package = true
""")

            with patch.object(ProjectConfigManager, 'get_possible_config_paths', return_value=[config_file]):
                config = ProjectConfigManager(project_name="configured_project")
                config.save_to_disk()

                with config_file.open("rb") as f:
                    saved_data = tomllib.load(f)
                assert saved_data["project"]["name"] == "sample"
                assert saved_data["tool"]["uv"]["package"] is True
                assert saved_data["tool"]["determystic"]["project_name"] == "configured_project"
    
    @pytest.mark.parametrize("config_data", [
        {"version": "1.0", "project_name": "test_project"},
        {"version": "2.0", "project_name": "another_project", "settings": {"debug": True}},
    ])
    def test_save_and_load_roundtrip(self, config_data: dict) -> None:
        """Test that saving and loading a config preserves all data."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            config_file = temp_path / "pyproject.toml"
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
            config_file = temp_path / "pyproject.toml"
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
