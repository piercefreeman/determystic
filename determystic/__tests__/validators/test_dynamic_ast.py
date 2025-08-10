"""Tests for dynamic AST validator functionality."""

import ast
import tempfile
from pathlib import Path

import pytest

from determystic.external import DeterministicTraverser
from determystic.validators.dynamic_ast import DynamicASTValidator
from determystic.configs.project import ProjectConfigManager


class MockTraverserSingleArg(DeterministicTraverser):
    """Mock traverser that only accepts code argument (like OptionalTypeHintTraverser)."""
    
    def __init__(self, code: str) -> None:
        super().__init__(code)
    
    def visit_Name(self, node: ast.Name) -> None:
        if node.id == "bad_pattern":
            self.add_error(node, "Found bad pattern")
        self.generic_visit(node)


class MockTraverserTwoArgs(DeterministicTraverser):
    """Mock traverser that accepts both code and filename arguments."""
    
    def __init__(self, code: str, filename: str = "<string>") -> None:
        super().__init__(code, filename)
    
    def visit_Name(self, node: ast.Name) -> None:
        if node.id == "another_bad_pattern":
            self.add_error(node, f"Found bad pattern in {self.filename}")
        self.generic_visit(node)


class TestDynamicASTValidator:
    """Test suite for DynamicASTValidator."""

    @pytest.fixture
    def temp_project_dir(self):
        """Create a temporary project directory with .determystic structure."""
        with tempfile.TemporaryDirectory() as temp_dir:
            project_path = Path(temp_dir)
            
            # Create .determystic directory
            determystic_dir = project_path / ".determystic"
            determystic_dir.mkdir()
            
            # Create validations directory
            validations_dir = determystic_dir / "validations"
            validations_dir.mkdir()
            
            # Create tests directory
            tests_dir = determystic_dir / "tests"
            tests_dir.mkdir()
            
            yield project_path

    @pytest.fixture
    def sample_validator_content_single_arg(self) -> str:
        """Sample validator content that uses single argument constructor."""
        return '''
import ast
from determystic.external import DeterministicTraverser

class TestValidator(DeterministicTraverser):
    def __init__(self, code):
        super().__init__(code)
    
    def visit_Name(self, node):
        if node.id == "bad_pattern":
            self.add_error(node, "Found bad pattern")
        self.generic_visit(node)
'''

    @pytest.fixture
    def sample_validator_content_two_args(self) -> str:
        """Sample validator content that uses two argument constructor."""
        return '''
import ast
from determystic.external import DeterministicTraverser

class TestValidator(DeterministicTraverser):
    def __init__(self, code, filename="<string>"):
        super().__init__(code, filename)
    
    def visit_Name(self, node):
        if node.id == "another_bad_pattern":
            self.add_error(node, f"Found bad pattern in {self.filename}")
        self.generic_visit(node)
'''

    @pytest.fixture
    def sample_python_code_with_issues(self) -> str:
        """Sample Python code that contains validation issues."""
        return '''
def test_function():
    bad_pattern = "this should be flagged"
    another_bad_pattern = "this should also be flagged"
    good_code = "this is fine"
    return bad_pattern
'''

    @pytest.fixture
    def sample_python_code_clean(self) -> str:
        """Sample Python code without validation issues."""
        return '''
def test_function():
    good_code = "this is fine"
    return good_code
'''

    def test_create_validators_empty_config(self, temp_project_dir: Path) -> None:
        """Test create_validators with empty configuration."""
        # Create empty config
        config_path = temp_project_dir / ".determystic" / "config.toml"
        config_path.write_text('''
version = "1.0"
[validators]
[settings]
''')
        
        # Reset and set runtime path and load config manager
        ProjectConfigManager.runtime_custom_path = None
        ProjectConfigManager._found_path = None
        ProjectConfigManager.set_runtime_custom_path(temp_project_dir)
        mock_config_manager = ProjectConfigManager.load_from_disk()
        
        validators = DynamicASTValidator.create_validators(mock_config_manager)
        assert len(validators) == 0

    def test_create_validators_with_single_arg_validator(
        self,
        temp_project_dir: Path,
        sample_validator_content_single_arg: str
    ) -> None:
        """Test create_validators with a validator that uses single argument constructor."""
        # Create validator file
        validator_file = temp_project_dir / ".determystic" / "validations" / "test_validator.determystic"
        validator_file.write_text(sample_validator_content_single_arg)

        # Create config
        config_path = temp_project_dir / ".determystic" / "config.toml"
        config_path.write_text('''
version = "1.0"
[validators.test_validator]
name = "test_validator"
validator_path = "validations/test_validator.determystic"
[settings]
''')

        # Reset and set runtime path and load config manager
        ProjectConfigManager.runtime_custom_path = None
        ProjectConfigManager._found_path = None
        ProjectConfigManager.set_runtime_custom_path(temp_project_dir)
        mock_config_manager = ProjectConfigManager.load_from_disk()
        
        validators = DynamicASTValidator.create_validators(mock_config_manager)
        
        assert len(validators) == 1
        assert validators[0].name == "test_validator"
        assert validators[0].traverser_class is not None  # type: ignore

    def test_create_validators_with_two_arg_validator(
        self, 
        temp_project_dir: Path, 
        sample_validator_content_two_args: str
    ) -> None:
        """Test create_validators with a validator that uses two argument constructor."""
        # Create validator file
        validator_file = temp_project_dir / ".determystic" / "validations" / "test_validator.determystic"
        validator_file.write_text(sample_validator_content_two_args)
        
        # Create config
        config_path = temp_project_dir / ".determystic" / "config.toml"
        config_path.write_text('''
version = "1.0"
[validators.test_validator]
name = "test_validator"
validator_path = "validations/test_validator.determystic"
[settings]
''')
        
        # Reset and set runtime path and load config manager
        ProjectConfigManager.runtime_custom_path = None
        ProjectConfigManager._found_path = None
        ProjectConfigManager.set_runtime_custom_path(temp_project_dir)
        mock_config_manager = ProjectConfigManager.load_from_disk()
        
        validators = DynamicASTValidator.create_validators(mock_config_manager)
        
        assert len(validators) == 1
        assert validators[0].name == "test_validator"
        assert validators[0].traverser_class is not None  # type: ignore

    def test_create_validators_nonexistent_file(self, temp_project_dir: Path) -> None:
        """Test create_validators with a validator file that doesn't exist."""
        # Create config pointing to non-existent file
        config_path = temp_project_dir / ".determystic" / "config.toml"
        config_path.write_text('''
version = "1.0"
[validators.missing_validator]
name = "missing_validator"
validator_path = "validations/missing.determystic"
[settings]
''')
        
        # Reset and set runtime path and load config manager
        ProjectConfigManager.runtime_custom_path = None
        ProjectConfigManager._found_path = None
        ProjectConfigManager.set_runtime_custom_path(temp_project_dir)
        mock_config_manager = ProjectConfigManager.load_from_disk()
        
        validators = DynamicASTValidator.create_validators(mock_config_manager)
        
        # Should return empty list since file doesn't exist
        assert len(validators) == 0

    def test_load_validator_module_invalid_syntax(self, temp_project_dir: Path) -> None:
        """Test loading a validator module with invalid Python syntax."""
        # Create validator file with invalid syntax
        validator_file = temp_project_dir / ".determystic" / "validations" / "invalid.determystic"
        validator_file.write_text("this is not valid python syntax !!!")
        
        validator = DynamicASTValidator(
            name="invalid",
            validator_path=validator_file,
            path=temp_project_dir
        )
        
        # Should fail to load
        assert validator.traverser_class is None

    def test_load_validator_module_no_traverser_class(self, temp_project_dir: Path) -> None:
        """Test loading a validator module that doesn't contain a DeterministicTraverser subclass."""
        # Create validator file without DeterministicTraverser subclass
        validator_file = temp_project_dir / ".determystic" / "validations" / "no_traverser.determystic"
        validator_file.write_text('''
def some_function():
    return "no traverser here"

class NotATraverser:
    pass
''')
        
        validator = DynamicASTValidator(
            name="no_traverser",
            validator_path=validator_file,
            path=temp_project_dir
        )
        
        # Should fail to load
        assert validator.traverser_class is None

    @pytest.mark.asyncio
    async def test_validate_with_single_arg_constructor(
        self, 
        temp_project_dir: Path,
        sample_python_code_with_issues: str
    ) -> None:
        """Test validation with a traverser that uses single argument constructor."""
        # Create Python file to validate
        python_file = temp_project_dir / "test_code.py"
        python_file.write_text(sample_python_code_with_issues)
        
        # Create validator instance with mock traverser class
        validator = DynamicASTValidator(
            name="test_validator",
            validator_path=Path("dummy"),  # Not used since we're mocking
            path=temp_project_dir
        )
        validator.traverser_class = MockTraverserSingleArg
        
        result = await validator.validate()
        
        # Should find the "bad_pattern" issue
        assert not result.success
        assert "bad_pattern" in result.output
        assert "test_code.py:3:" in result.output

    @pytest.mark.asyncio
    async def test_validate_with_two_arg_constructor(
        self, 
        temp_project_dir: Path,
        sample_python_code_with_issues: str
    ) -> None:
        """Test validation with a traverser that uses two argument constructor."""
        # Create Python file to validate
        python_file = temp_project_dir / "test_code.py"
        python_file.write_text(sample_python_code_with_issues)
        
        # Create validator instance with mock traverser class
        validator = DynamicASTValidator(
            name="test_validator",
            validator_path=Path("dummy"),  # Not used since we're mocking
            path=temp_project_dir
        )
        validator.traverser_class = MockTraverserTwoArgs
        
        result = await validator.validate()
        
        # Should find the "another_bad_pattern" issue
        assert not result.success
        assert "another_bad_pattern" in result.output
        assert "test_code.py" in result.output

    @pytest.mark.asyncio
    async def test_validate_clean_code(
        self, 
        temp_project_dir: Path,
        sample_python_code_clean: str
    ) -> None:
        """Test validation with clean code that has no issues."""
        # Create Python file to validate
        python_file = temp_project_dir / "test_code.py"
        python_file.write_text(sample_python_code_clean)
        
        # Create validator instance with mock traverser class
        validator = DynamicASTValidator(
            name="test_validator",
            validator_path=Path("dummy"),  # Not used since we're mocking
            path=temp_project_dir
        )
        validator.traverser_class = MockTraverserSingleArg
        
        result = await validator.validate()
        
        # Should pass validation
        assert result.success
        assert "No issues found" in result.output

    @pytest.mark.asyncio
    async def test_validate_no_python_files(self, temp_project_dir: Path) -> None:
        """Test validation when there are no Python files."""
        # Create validator instance
        validator = DynamicASTValidator(
            name="test_validator",
            validator_path=Path("dummy"),
            path=temp_project_dir
        )
        validator.traverser_class = MockTraverserSingleArg
        
        result = await validator.validate()
        
        # Should pass with no files message
        assert result.success
        assert "No Python files found" in result.output

    @pytest.mark.asyncio
    async def test_validate_failed_traverser_load(self, temp_project_dir: Path) -> None:
        """Test validation when traverser class failed to load."""
        # Create Python file to validate
        python_file = temp_project_dir / "test_code.py"
        python_file.write_text("print('hello')")
        
        # Create validator instance with no traverser class
        validator = DynamicASTValidator(
            name="test_validator",
            validator_path=Path("dummy"),
            path=temp_project_dir
        )
        validator.traverser_class = None
        
        result = await validator.validate()
        
        # Should fail validation
        assert not result.success
        assert "Failed to load validator" in result.output

    @pytest.mark.asyncio
    async def test_validate_ignores_hidden_directories(
        self, 
        temp_project_dir: Path,
        sample_python_code_with_issues: str
    ) -> None:
        """Test that validation ignores Python files in hidden directories."""
        # Create Python file in hidden directory
        hidden_dir = temp_project_dir / ".hidden"
        hidden_dir.mkdir()
        hidden_file = hidden_dir / "hidden_code.py"
        hidden_file.write_text(sample_python_code_with_issues)
        
        # Create Python file in regular directory
        regular_file = temp_project_dir / "regular_code.py"
        regular_file.write_text(sample_python_code_with_issues)
        
        # Create validator instance
        validator = DynamicASTValidator(
            name="test_validator",
            validator_path=Path("dummy"),
            path=temp_project_dir
        )
        validator.traverser_class = MockTraverserSingleArg
        
        result = await validator.validate()
        
        # Should only process the regular file, not the hidden one
        assert not result.success
        assert "regular_code.py" in result.output
        assert "hidden_code.py" not in result.output

    def test_display_name_property(self, temp_project_dir: Path) -> None:
        """Test that display_name property formats the name correctly."""
        validator = DynamicASTValidator(
            name="test_validator",
            validator_path=Path("dummy"),
            path=temp_project_dir
        )
        
        # Should format underscores as title case
        assert validator.display_name == "Test Validator"
        
        # Test with different name format
        validator2 = DynamicASTValidator(
            name="custom_ast_checker",
            validator_path=Path("dummy"),
            path=temp_project_dir
        )
        
        assert validator2.display_name == "Custom Ast Checker"