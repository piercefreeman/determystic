"""Tests for the create_validator agent."""

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch
from typing import Any, Dict, List, Optional

import pytest
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from deterministic.agents.create_validator import create_ast_validator, stream_create_validator


# Test responses that the mock model will return
VALIDATOR_CODE = '''"""AST validator for detecting Optional type hints."""

import ast
from deterministic.external import DeterministicTraverser


class OptionalTypeHintTraverser(DeterministicTraverser):
    """Traverser to detect Optional[T] type hints."""
    
    def visit_Subscript(self, node):
        """Visit subscript nodes to check for Optional usage."""
        if (isinstance(node.value, ast.Name) and 
            node.value.id == "Optional"):
            self.add_error(
                node,
                "Use 'T | None' instead of 'Optional[T]' for type hints"
            )
        self.generic_visit(node)
    
    def visit_ImportFrom(self, node):
        """Check for Optional imports."""
        if node.module == "typing":
            for alias in node.names:
                if alias.name == "Optional":
                    self.add_error(
                        node,
                        "Avoid importing Optional, use union types instead"
                    )
        self.generic_visit(node)
'''

TEST_CODE = '''"""Tests for Optional type hint validator."""

import pytest


def test_detects_optional_type_hint():
    """Test that Optional[str] is flagged as problematic."""
    code = """
from typing import Optional

def process(value: Optional[str]) -> None:
    pass
"""
    # Mock test - in real implementation would call validator
    assert True  # Simplified for testing


def test_allows_union_syntax():
    """Test that union syntax is allowed.""" 
    code = """
def process(value: str | None) -> None:
    pass
"""
    # Mock test - in real implementation would call validator
    assert True  # Simplified for testing
'''


@pytest.fixture
def mock_anthropic_client():
    """Fixture providing a mock Anthropic client."""
    # Use the basic TestModel which will call all tools automatically
    return TestModel(call_tools='all')


@pytest.fixture 
def project_root(tmp_path):
    """Fixture providing a temporary project root."""
    return tmp_path


@pytest.fixture
def sample_user_code():
    """Sample problematic code for testing."""
    return '''from typing import Optional

def process_data(value: Optional[str]) -> str:
    """Process optional data."""
    if value is None:
        return "empty"
    return value.upper()
'''


@pytest.fixture
def sample_requirements():
    """Sample requirements for the validator."""
    return "Don't use Optional[T], use T | None instead"


class TestCreateValidator:
    """Tests for the create_ast_validator function."""
    
    @pytest.mark.asyncio
    async def test_create_ast_validator_success(
        self, 
        mock_anthropic_client,
        project_root, 
        sample_user_code,
        sample_requirements
    ):
        """Test successful creation of AST validator."""
        
        # Mock the isolated environment run_tests method
        with patch('deterministic.agents.create_validator.IsolatedEnv') as mock_env:
            mock_env_instance = mock_env.return_value.__enter__.return_value
            mock_env_instance.run_tests.return_value = (True, "All tests passed")
            
            # Run the agent
            result, validation_contents, test_contents = await create_ast_validator(
                user_code=sample_user_code,
                requirements=sample_requirements,
                anthropic_client=mock_anthropic_client,
                project_root=project_root
            )
            
            # Verify results
            assert result is not None
            assert "implementation complete" in result.lower()
            assert len(validation_contents) > 0
            assert len(test_contents) > 0
            
            # The TestModel will use default content, so just verify we got some content
            assert validation_contents.strip() != ""
            assert test_contents.strip() != ""
            
            # Verify isolated environment was used
            mock_env.assert_called_once_with(project_root)
            mock_env_instance.run_tests.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_stream_create_validator_events(
        self,
        mock_anthropic_client,
        project_root,
        sample_user_code, 
        sample_requirements
    ):
        """Test that streaming version emits expected events."""
        
        events = []
        
        async def capture_events(event):
            """Capture events for verification."""
            events.append(event)
        
        # Mock the isolated environment
        with patch('deterministic.agents.create_validator.IsolatedEnv') as mock_env:
            mock_env_instance = mock_env.return_value.__enter__.return_value
            mock_env_instance.run_tests.return_value = (True, "All tests passed")
            
            # Collect all events
            async for event in stream_create_validator(
                user_code=sample_user_code,
                requirements=sample_requirements,
                anthropic_client=mock_anthropic_client,
                project_root=project_root,
                callback=capture_events
            ):
                pass
            
            # Verify we got events
            assert len(events) > 0
            
            # Verify event types - just check that we got some events
            event_types = {event.event_type for event in events}
            assert len(event_types) > 0

    @pytest.mark.asyncio
    async def test_agent_dependencies_behavior(
        self,
        mock_anthropic_client,
        project_root,
        sample_user_code,
        sample_requirements
    ):
        """Test that agent dependencies are properly managed."""
        
        with patch('deterministic.agents.create_validator.IsolatedEnv') as mock_env:
            mock_env_instance = mock_env.return_value.__enter__.return_value
            mock_env_instance.run_tests.return_value = (True, "Tests passed successfully")
            
            # Run the agent and verify dependencies are updated correctly
            result, validation_contents, test_contents = await create_ast_validator(
                user_code=sample_user_code,
                requirements=sample_requirements,
                anthropic_client=mock_anthropic_client,
                project_root=project_root
            )
            
            # Verify that the agent executed successfully
            assert result is not None
            assert isinstance(result, str)
            assert len(result) > 0
            
            # Verify file contents are captured
            assert isinstance(validation_contents, str)
            assert isinstance(test_contents, str)
            
            # Verify the isolated environment interaction
            mock_env.assert_called_once_with(project_root)
            mock_env_instance.run_tests.assert_called_once()
            
            # Verify the run_tests call used the file contents
            call_args = mock_env_instance.run_tests.call_args
            assert call_args is not None
            assert 'validator_code' in call_args.kwargs
            assert 'test_code' in call_args.kwargs
            assert call_args.kwargs['validator_code'] == validation_contents
            assert call_args.kwargs['test_code'] == test_contents


if __name__ == "__main__":
    # Run the test
    pytest.main([__file__, "-v"])