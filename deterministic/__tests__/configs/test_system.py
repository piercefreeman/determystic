"""Parameterized tests for system configuration management."""

import tempfile
import tomli_w
from pathlib import Path
from typing import Type
from unittest.mock import patch

import pytest

from deterministic.configs.system import DeterministicSettings


@pytest.fixture(autouse=True)
def reset_class_state():
    """Reset the class state before each test."""
    DeterministicSettings._found_path = None
    yield
    DeterministicSettings._found_path = None


class TestDeterministicSettingsClassMethods:
    """Test class methods of DeterministicSettings."""
    
    def test_get_possible_config_paths_creates_directory(self) -> None:
        """Test that get_possible_config_paths creates the config directory."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            
            # Mock Path.home() to return our temp directory
            with patch('deterministic.configs.system.Path.home', return_value=temp_path):
                paths = DeterministicSettings.get_possible_config_paths()
                
                # Verify the directory was created
                config_dir = temp_path / ".deterministic"
                assert config_dir.exists()
                assert config_dir.is_dir()
                
                # Verify the returned path
                expected_path = config_dir / "config.toml"
                assert paths == [expected_path]

    def test_get_possible_config_paths_existing_directory(self) -> None:
        """Test get_possible_config_paths when directory already exists."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            config_dir = temp_path / ".deterministic"
            config_dir.mkdir()  # Pre-create the directory
            
            # Mock Path.home() to return our temp directory
            with patch('deterministic.configs.system.Path.home', return_value=temp_path):
                paths = DeterministicSettings.get_possible_config_paths()
                
                # Verify the directory still exists and path is correct
                assert config_dir.exists()
                expected_path = config_dir / "config.toml"
                assert paths == [expected_path]

    @pytest.mark.parametrize("config_data,expected_api_key", [
        ({"anthropic_api_key": "test-key-123"}, "test-key-123"),
        ({"anthropic_api_key": "sk-ant-api03-12345"}, "sk-ant-api03-12345"),
        ({}, None),  # No API key provided
    ])
    def test_load_from_disk_success(
        self, 
        config_data: dict, 
        expected_api_key: str | None
    ) -> None:
        """Test successful loading of configuration from disk."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            config_file = temp_path / "config.toml"
            
            # Write test config to file
            with config_file.open("wb") as f:
                tomli_w.dump(config_data, f)
            
            # Mock get_possible_config_paths to return our test file
            with patch.object(DeterministicSettings, 'get_possible_config_paths', return_value=[config_file]):
                config = DeterministicSettings.load_from_disk()
                
                assert isinstance(config, DeterministicSettings)
                assert config.anthropic_api_key == expected_api_key

    @pytest.mark.parametrize("exception_type,exception_message", [
        (FileNotFoundError, "Config file not found"),
        (ValueError, "Invalid TOML"),
        (PermissionError, "Permission denied"),
        (Exception, "Generic error"),
    ])
    def test_load_from_disk_failure_exits_system(
        self, 
        exception_type: Type[Exception], 
        exception_message: str
    ) -> None:
        """Test that load_from_disk exits system when loading fails."""
        # Mock the parent load_from_disk to raise an exception
        with patch.object(DeterministicSettings.__bases__[0], 'load_from_disk') as mock_parent_load:
            mock_parent_load.side_effect = exception_type(exception_message)
            
            # Mock sys.exit to prevent actual exit during test
            with patch('deterministic.configs.system.sys.exit') as mock_exit:
                # Mock CONSOLE.print to prevent actual output during test
                with patch('deterministic.configs.system.CONSOLE.print') as mock_print:
                    DeterministicSettings.load_from_disk()
                    
                    # Verify sys.exit was called with code 1
                    mock_exit.assert_called_once_with(1)
                    
                    # Verify error message was printed
                    mock_print.assert_called_once()
                    # Extract the Panel object and check its content
                    call_args = mock_print.call_args[0][0]
                    from rich.panel import Panel
                    assert isinstance(call_args, Panel)
                    panel_content = str(call_args.renderable)
                    assert "Configuration Required" in panel_content
                    assert "Anthropic API key" in panel_content
                    assert "deterministic configure" in panel_content

    def test_load_from_disk_prints_helpful_error_message(self) -> None:
        """Test that load_from_disk prints a helpful error message on failure."""
        # Mock the parent load_from_disk to raise an exception
        with patch.object(DeterministicSettings.__bases__[0], 'load_from_disk') as mock_parent_load:
            mock_parent_load.side_effect = FileNotFoundError("Config not found")
            
            # Mock sys.exit to prevent actual exit during test
            with patch('deterministic.configs.system.sys.exit'):
                # Mock CONSOLE.print to capture the output
                with patch('deterministic.configs.system.CONSOLE.print') as mock_print:
                    DeterministicSettings.load_from_disk()
                    
                    # Verify the error message was printed
                    mock_print.assert_called_once()
                    
                    # Extract the Panel object that was printed
                    panel_arg = mock_print.call_args[0][0]
                    
                    # Verify it's a Panel with expected content
                    from rich.panel import Panel
                    assert isinstance(panel_arg, Panel)
                    
                    # Check the panel content
                    panel_content = str(panel_arg.renderable)
                    assert "Configuration Required" in panel_content
                    assert "Anthropic API key" in panel_content
                    assert "deterministic configure" in panel_content
                    
                    # Check the panel style
                    assert panel_arg.border_style == "red"


class TestDeterministicSettingsModel:
    """Test the DeterministicSettings model itself."""
    
    @pytest.mark.parametrize("api_key", [
        "sk-ant-api03-12345678901234567890123456789012",
        "test-key-123",
        "another-valid-key",
        None,  # No API key is valid
    ])
    def test_model_creation_with_valid_api_key(self, api_key: str | None) -> None:
        """Test creating DeterministicSettings with various valid API keys."""
        if api_key is not None:
            settings = DeterministicSettings(anthropic_api_key=api_key)
            assert settings.anthropic_api_key == api_key
        else:
            settings = DeterministicSettings()
            assert settings.anthropic_api_key is None

    def test_model_with_explicit_values(self) -> None:
        """Test that model works correctly with explicit values."""
        settings = DeterministicSettings(anthropic_api_key="explicit-key")
        assert settings.anthropic_api_key == "explicit-key"
        
        # Test with None
        settings_none = DeterministicSettings(anthropic_api_key=None)
        assert settings_none.anthropic_api_key is None
        
        # Test default value
        settings_default = DeterministicSettings()
        assert settings_default.anthropic_api_key is None

    def test_model_ignores_extra_fields(self) -> None:
        """Test that extra fields are ignored due to model config."""
        # This should not raise an error due to extra="ignore"
        settings = DeterministicSettings(
            anthropic_api_key="test-key",
            extra_field="should_be_ignored",
            another_extra=123
        )
        assert settings.anthropic_api_key == "test-key"
        # Extra fields should not be accessible
        assert not hasattr(settings, 'extra_field')
        assert not hasattr(settings, 'another_extra')


class TestDeterministicSettingsIntegration:
    """Integration tests for DeterministicSettings."""
    
    @pytest.mark.parametrize("config_data", [
        {"anthropic_api_key": "test-key-integration-1"},
        {"anthropic_api_key": "sk-ant-api03-integration-test"},
    ])
    def test_save_and_load_roundtrip(self, config_data: dict) -> None:
        """Test that saving and loading preserves configuration data."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            config_file = temp_path / "config.toml"
            config_file.write_text("")
            
            with patch.object(DeterministicSettings, 'get_possible_config_paths', return_value=[config_file]):
                # Create and save config
                original_config = DeterministicSettings(**config_data)
                original_config.save_to_disk()
                
                # Load config back
                loaded_config = DeterministicSettings.load_from_disk()
                
                # Verify loaded config matches original
                assert loaded_config is not None
                assert loaded_config.anthropic_api_key == original_config.anthropic_api_key

    def test_config_directory_creation_integration(self) -> None:
        """Integration test for config directory creation."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            
            # Mock Path.home() to return our temp directory
            with patch('deterministic.configs.system.Path.home', return_value=temp_path):
                # This should create the directory
                paths = DeterministicSettings.get_possible_config_paths()
                
                config_dir = temp_path / ".deterministic"
                config_file = config_dir / "config.toml"
                
                # Directory should exist
                assert config_dir.exists()
                assert paths == [config_file]
                
                # Should be able to create a config in this directory
                settings = DeterministicSettings(anthropic_api_key="integration-test")
                
                # Create an empty config file first
                config_file.write_text("")
                
                # Mock get_possible_config_paths for save operation
                with patch.object(DeterministicSettings, 'get_possible_config_paths', return_value=[config_file]):
                    settings.save_to_disk()
                    
                    # File should be created and have content
                    assert config_file.exists()
                    assert config_file.stat().st_size > 0
                    
                    # Should be able to load it back
                    loaded_settings = DeterministicSettings.load_from_disk()
                    assert loaded_settings.anthropic_api_key == "integration-test"

    def test_error_handling_with_real_file_operations(self) -> None:
        """Test error handling with actual file operations."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            
            # Create a directory where we expect a file (this will cause an error)
            config_file = temp_path / "config.toml"
            config_file.mkdir()  # Create as directory instead of file
            
            with patch.object(DeterministicSettings, 'get_possible_config_paths', return_value=[config_file]):
                # Mock sys.exit to prevent actual exit during test
                with patch('deterministic.configs.system.sys.exit') as mock_exit:
                    # Mock CONSOLE.print to prevent actual output during test
                    with patch('deterministic.configs.system.CONSOLE.print'):
                        DeterministicSettings.load_from_disk()
                        
                        # Should exit due to the error
                        mock_exit.assert_called_once_with(1)