"""Tests for the create_validator agent."""

from unittest.mock import patch

import pytest
from pydantic_ai.models.test import TestModel

from determystic.agents.create_validator import create_ast_validator, stream_create_validator


# Test responses that the mock model will return
VALIDATOR_CODE = '''"""AST validator for detecting Optional type hints."""

import ast
from determystic.external import DeterministicTraverser


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
        with patch('determystic.agents.create_validator.IsolatedEnv') as mock_env:
            mock_env_instance = mock_env.return_value.__enter__.return_value
            mock_env_instance.run_tests.return_value = (True, "All tests passed")
            
            # Run the agent
            result, validation_contents, test_contents = await create_ast_validator(
                user_code=sample_user_code,
                requirements=sample_requirements,
                anthropic_client=mock_anthropic_client
            )
            
            # Verify results - TestModel returns basic responses
            assert result is not None
            assert isinstance(result, str)
            assert isinstance(validation_contents, str)
            assert isinstance(test_contents, str)
            
            # TestModel doesn't actually execute tools, so just verify we got some output
            # Real tool integration is tested in test_real_tool_integration_end_to_end
    
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
        
        # Mock the isolated environment
        with patch('determystic.agents.create_validator.IsolatedEnv') as mock_env:
            mock_env_instance = mock_env.return_value.__enter__.return_value
            mock_env_instance.run_tests.return_value = (True, "All tests passed")
            
            # Collect all events
            async for event in stream_create_validator(
                user_code=sample_user_code,
                requirements=sample_requirements,
                anthropic_client=mock_anthropic_client
            ):
                events.append(event)
            
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
        
        with patch('determystic.agents.create_validator.IsolatedEnv') as mock_env:
            mock_env_instance = mock_env.return_value.__enter__.return_value
            mock_env_instance.run_tests.return_value = (True, "Tests passed successfully")
            
            # Run the agent and verify dependencies are updated correctly
            result, validation_contents, test_contents = await create_ast_validator(
                user_code=sample_user_code,
                requirements=sample_requirements,
                anthropic_client=mock_anthropic_client
            )
            
            # Verify that the agent executed successfully
            assert result is not None
            assert isinstance(result, str)
            assert len(result) > 0
            
            # Verify basic types - TestModel doesn't actually execute tools
            assert isinstance(validation_contents, str)
            assert isinstance(test_contents, str)
            
            # TestModel doesn't call tools, so no environment interaction expected
            # Real tool integration is tested in test_real_tool_integration_end_to_end

    @pytest.mark.asyncio
    async def test_real_tool_integration_end_to_end(self):
        """Test that our tools work end-to-end with realistic agent behavior."""
        from determystic.agents.create_validator import (
            AgentDependencies, 
            write_file, read_file, edit_file, run_tests, finalize
        )
        
        # Create dependencies manually
        deps = AgentDependencies()
        
        # Mock context for tool calls
        class MockRunContext:
            def __init__(self, deps):
                self.deps = deps
        
        ctx = MockRunContext(deps)
        
        # Test 1: Write validator file
        validator_code = '''"""AST validator for detecting exceptions in test functions."""

import ast
from determystic.external import DeterministicTraverser


class TestExceptionTraverser(DeterministicTraverser):
    """Traverser to detect exception handling in test functions."""
    
    def visit_FunctionDef(self, node):
        """Check if test functions contain exception handling."""
        if node.name.startswith('test_'):
            # Look for try/except blocks in test functions
            for child in ast.walk(node):
                if isinstance(child, ast.Try):
                    self.add_error(
                        child,
                        "Test functions should not contain exception handling blocks"
                    )
        self.generic_visit(node)
'''
        
        write_result = await write_file(ctx, type('WriteFileInput', (), {
            'filename': 'validator.py',
            'content': validator_code
        })())
        
        assert "✅ File 'validator.py' written" in write_result
        assert len(deps.files) == 1
        assert 'validator.py' in deps.files
        assert len(deps.files['validator.py']) > 0
        
        # Test 2: Write test file
        test_code = '''"""Tests for test exception validator."""

import ast
import pytest
from validator import TestExceptionTraverser


def test_detects_exception_in_test_function():
    """Test that exceptions in test functions are flagged."""
    code = """
def test_something():
    try:
        result = 1 / 0
    except ZeroDivisionError:
        pass  # This should be flagged
"""
    tree = ast.parse(code)
    traverser = TestExceptionTraverser()
    traverser.visit(tree)
    
    assert len(traverser.errors) == 1
    assert "exception handling" in traverser.errors[0].message.lower()


def test_allows_exceptions_in_regular_functions():
    """Test that exceptions in regular functions are allowed."""
    code = """
def regular_function():
    try:
        result = 1 / 0
    except ZeroDivisionError:
        return None
"""
    tree = ast.parse(code)
    traverser = TestExceptionTraverser()
    traverser.visit(tree)
    
    assert len(traverser.errors) == 0


def test_allows_test_functions_without_exceptions():
    """Test that test functions without exceptions are allowed."""
    code = """
def test_clean_function():
    result = 2 + 2
    assert result == 4
"""
    tree = ast.parse(code)
    traverser = TestExceptionTraverser()
    traverser.visit(tree)
    
    assert len(traverser.errors) == 0
'''
        
        test_result = await write_file(ctx, type('WriteFileInput', (), {
            'filename': 'test_validator.py', 
            'content': test_code
        })())
        
        assert "✅ File 'test_validator.py' written" in test_result
        assert len(deps.files) == 2
        assert 'test_validator.py' in deps.files
        
        # Test 3: Read files back
        read_result = await read_file(ctx, type('ReadFileInput', (), {
            'filename': 'validator.py'
        })())
        
        assert "📄 Contents of 'validator.py'" in read_result
        assert "TestExceptionTraverser" in read_result
        
        # Test 4: Edit a file (use a more specific string to avoid multiple matches)
        edit_result = await edit_file(ctx, type('EditFileInput', (), {
            'filename': 'validator.py',
            'old_str': 'class TestExceptionTraverser(DeterministicTraverser):',
            'new_str': 'class TestExceptionTraverser(DeterministicTraverser):',
            'target_all': False
        })())
        
        assert "✅ Replaced 1 occurrence(s)" in edit_result
        
        # Test 5: Test the isolated environment integration (mocked)
        with patch('determystic.agents.create_validator.IsolatedEnv') as mock_env:
            mock_env_instance = mock_env.return_value.__enter__.return_value
            mock_env_instance.run_tests.return_value = (True, "All tests passed")
            
            test_run_result = await run_tests(ctx, type('RunTestsInput', (), {
                'message': 'Testing our validator'
            })())
            
            assert "✅ Tests passed!" in test_run_result
            mock_env_instance.run_tests.assert_called_once_with(
                validator_code=validator_code,
                test_code=test_code
            )
        
        # Test 6: Finalize
        final_result = await finalize(ctx, type('FinalizeInput', (), {
            'message': 'Successfully created test exception validator'
        })())
        
        assert "🎉 Implementation complete!" in final_result
        assert "Successfully created test exception validator" in final_result
        assert "validator.py:" in final_result
        assert "test_validator.py:" in final_result
        
        # Verify final state
        assert len(deps.files) == 2
        assert 'validator.py' in deps.files
        assert 'test_validator.py' in deps.files
        assert len(deps.validation_contents) > 0  # Legacy property
        assert len(deps.test_contents) > 0  # Legacy property
        
        print("✅ End-to-end test completed successfully!")
        print(f"📊 Created {len(deps.files)} files:")
        for filename, content in deps.files.items():
            print(f"  📄 {filename}: {len(content)} characters")


if __name__ == "__main__":
    # Run the test
    pytest.main([__file__, "-v"])