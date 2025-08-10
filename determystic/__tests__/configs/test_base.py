"""Parameterized tests for base configuration management."""

import tempfile
import tomllib
import tomli_w
from pathlib import Path
from typing import Type
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from determystic.configs.base import BaseConfig


@pytest.fixture(autouse=True)
def reset_class_state():
    """Reset the class state before each test."""
    ConcreteTestConfig._found_path = None
    yield
    ConcreteTestConfig._found_path = None


class ConcreteTestConfig(BaseConfig):
    """Concrete implementation of BaseConfig for testing."""
    
    name: str
    version: str = "1.0.0"
    
    @classmethod
    def get_possible_config_paths(cls) -> list[Path]:
        """Return test config paths."""
        return [
            Path("test_config.toml"),
            Path(".test_config.toml"),
            Path("config/test.toml")
        ]


class TestGetPossibleConfigPaths:
    """Test the get_possible_config_paths abstract method."""
    
    @pytest.mark.parametrize("config_class,expected_paths", [
        (ConcreteTestConfig, [Path("test_config.toml"), Path(".test_config.toml"), Path("config/test.toml")]),
    ])
    def test_get_possible_config_paths_implementation(
        self, 
        config_class: Type[BaseConfig], 
        expected_paths: list[Path]
    ) -> None:
        """Test that concrete implementations return expected config paths."""
        actual_paths = config_class.get_possible_config_paths()
        assert actual_paths == expected_paths
        assert all(isinstance(path, Path) for path in actual_paths)


class TestGetConfigPath:
    """Test the get_config_path method."""
    
    @pytest.mark.parametrize("existing_files,expected_file", [
        (["test_config.toml"], "test_config.toml"),
        ([".test_config.toml"], ".test_config.toml"),
        (["config/test.toml"], "config/test.toml"),
        (["test_config.toml", ".test_config.toml"], "test_config.toml"),  # First match wins
        ([".test_config.toml", "config/test.toml"], ".test_config.toml"),  # First match wins
    ])
    def test_get_config_path_finds_existing_file(
        self, 
        existing_files: list[str], 
        expected_file: str
    ) -> None:
        """Test that get_config_path finds the first existing config file."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            
            # Create the existing files in temp directory
            for file_name in existing_files:
                file_path = temp_path / file_name
                file_path.parent.mkdir(parents=True, exist_ok=True)
                file_path.write_text("[test]\nname = 'test'\n")
            
            # Mock get_possible_config_paths to return paths in temp directory  
            # The existing files should match the paths returned by the mock
            mock_paths = [
                temp_path / "test_config.toml",
                temp_path / ".test_config.toml", 
                temp_path / "config/test.toml"
            ]
            
            with patch.object(ConcreteTestConfig, 'get_possible_config_paths', return_value=mock_paths):

                result_path = ConcreteTestConfig.get_config_path()
                
                assert result_path == temp_path / expected_file
                assert result_path.exists()

    @pytest.mark.parametrize("missing_files", [
        [],
        ["other_file.toml"],
        ["wrong_config.toml", "another_wrong.toml"],
    ])
    def test_get_config_path_raises_when_no_file_found(self, missing_files: list[str]) -> None:
        """Test that get_config_path raises FileNotFoundError when no config file exists."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            
            # Create some files that are NOT in the expected config paths
            for file_name in missing_files:
                (temp_path / file_name).write_text("[test]\nname = 'test'\n")
            
            # Mock get_possible_config_paths to return paths in temp directory
            mock_paths = [
                temp_path / "test_config.toml",
                temp_path / ".test_config.toml",
                temp_path / "config/test.toml"
            ]
            
            with patch.object(ConcreteTestConfig, 'get_possible_config_paths', return_value=mock_paths):

                
                with pytest.raises(FileNotFoundError) as exc_info:
                    ConcreteTestConfig.get_config_path()
                
                assert "No configuration file found" in str(exc_info.value)

    def test_get_config_path_caches_found_path(self) -> None:
        """Test that get_config_path caches the found path for subsequent calls."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            config_file = temp_path / "test_config.toml"
            config_file.write_text("[test]\nname = 'test'\n")
            
            # Mock get_possible_config_paths AND use the actual file so Path.exists() works
            with patch.object(ConcreteTestConfig, 'get_possible_config_paths', return_value=[config_file]):
                # First call should find and cache the path
                first_result = ConcreteTestConfig.get_config_path()
                assert first_result == config_file
                
                # Second call should return cached path without searching again
                second_result = ConcreteTestConfig.get_config_path()
                assert second_result == config_file
                assert first_result == second_result
                
                # Verify the path was cached
                assert ConcreteTestConfig._found_path == config_file


class TestLoadFromDisk:
    """Test the load_from_disk class method."""
    
    @pytest.mark.parametrize("config_data,expected_name,expected_version", [
        ({"name": "test_app", "version": "1.0.0"}, "test_app", "1.0.0"),
        ({"name": "my_project", "version": "2.1.3"}, "my_project", "2.1.3"),
        ({"name": "simple"}, "simple", "1.0.0"),  # Uses default version
    ])
    def test_load_from_disk_valid_config(
        self, 
        config_data: dict, 
        expected_name: str, 
        expected_version: str
    ) -> None:
        """Test loading valid configuration from disk."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            config_file = temp_path / "test_config.toml"
            
            # Write test config to file
            with config_file.open("wb") as f:
                tomli_w.dump(config_data, f)
            
            # Mock get_possible_config_paths to return our test file
            with patch.object(ConcreteTestConfig, 'get_possible_config_paths', return_value=[config_file]):

                
                # Load config from disk
                config = ConcreteTestConfig.load_from_disk()
                
                assert config is not None
                assert config.name == expected_name
                assert config.version == expected_version

    @pytest.mark.parametrize("invalid_data,error_type", [
        ({}, ValidationError),  # Missing required 'name' field
        ({"version": "1.0.0"}, ValidationError),  # Missing required 'name' field
        ({"name": 123}, ValidationError),  # Invalid type for 'name'
    ])
    def test_load_from_disk_invalid_config(
        self, 
        invalid_data: dict, 
        error_type: Type[Exception]
    ) -> None:
        """Test loading invalid configuration raises appropriate errors."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            config_file = temp_path / "test_config.toml"
            
            # Write invalid config to file
            with config_file.open("wb") as f:
                tomli_w.dump(invalid_data, f)
            
            # Mock get_possible_config_paths to return our test file
            with patch.object(ConcreteTestConfig, 'get_possible_config_paths', return_value=[config_file]):

                
                with pytest.raises(error_type):
                    ConcreteTestConfig.load_from_disk()

    def test_load_from_disk_file_not_found(self) -> None:
        """Test that load_from_disk raises FileNotFoundError when config file doesn't exist."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            
            # Mock get_possible_config_paths to return non-existent files
            with patch.object(ConcreteTestConfig, 'get_possible_config_paths', return_value=[temp_path / "nonexistent.toml"]):

                
                with pytest.raises(FileNotFoundError):
                    ConcreteTestConfig.load_from_disk()


class TestSaveToDisk:
    """Test the save_to_disk method."""
    
    @pytest.mark.parametrize("name,version", [
        ("test_app", "1.0.0"),
        ("my_project", "2.1.3"),
        ("simple_name", "0.1.0"),
        ("complex-name_with.chars", "1.2.3-beta"),
    ])
    def test_save_to_disk_creates_valid_file(self, name: str, version: str) -> None:
        """Test that save_to_disk creates a valid TOML file with correct content."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            config_file = temp_path / "test_config.toml"
            
            # Create initial empty file so get_config_path can find it
            config_file.write_text("")
            
            # Mock get_possible_config_paths to return our test file
            with patch.object(ConcreteTestConfig, 'get_possible_config_paths', return_value=[config_file]):

                
                # Create config and save to disk
                config = ConcreteTestConfig(name=name, version=version)
                config.save_to_disk()
                
                # Verify file was created and has correct content
                assert config_file.exists()
                
                # Load and verify content
                with config_file.open("rb") as f:
                    saved_data = tomllib.load(f)
                
                assert saved_data["name"] == name
                assert saved_data["version"] == version

    def test_save_to_disk_overwrites_existing_file(self) -> None:
        """Test that save_to_disk overwrites existing configuration file."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            config_file = temp_path / "test_config.toml"
            
            # Create initial config file with different content
            initial_data = {"name": "old_name", "version": "0.0.1"}
            with config_file.open("wb") as f:
                tomli_w.dump(initial_data, f)
            
            # Mock get_possible_config_paths to return our test file
            with patch.object(ConcreteTestConfig, 'get_possible_config_paths', return_value=[config_file]):

                
                # Create new config and save to disk
                new_config = ConcreteTestConfig(name="new_name", version="2.0.0")
                new_config.save_to_disk()
                
                # Verify file was overwritten with new content
                with config_file.open("rb") as f:
                    saved_data = tomllib.load(f)
                
                assert saved_data["name"] == "new_name"
                assert saved_data["version"] == "2.0.0"
                assert saved_data != initial_data

    @pytest.mark.parametrize("config_data", [
        {"name": "test", "version": "1.0.0"},
        {"name": "complex", "version": "1.2.3-alpha+build.1"},
    ])
    def test_save_and_load_roundtrip(self, config_data: dict) -> None:
        """Test that saving and loading a config preserves all data."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            config_file = temp_path / "test_config.toml"
            
            # Create initial empty file
            config_file.write_text("")
            
            # Mock get_possible_config_paths to return our test file
            with patch.object(ConcreteTestConfig, 'get_possible_config_paths', return_value=[config_file]):

                
                # Create config, save to disk, then load back
                original_config = ConcreteTestConfig(**config_data)
                original_config.save_to_disk()
                
                # Reset again to test the load functionality
                ConcreteTestConfig._found_path = None
                loaded_config = ConcreteTestConfig.load_from_disk()
                
                # Verify loaded config matches original
                assert loaded_config is not None
                assert loaded_config.name == original_config.name
                assert loaded_config.version == original_config.version
                assert loaded_config.model_dump() == original_config.model_dump()
