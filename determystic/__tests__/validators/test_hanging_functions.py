"""Tests for hanging functions validator functionality."""

import tempfile
import tomllib
from pathlib import Path
from unittest.mock import patch

import pytest

from determystic.validators.hanging_functions import HangingFunctionsValidator
from determystic.configs.project import ProjectConfigManager


class TestHangingFunctionsValidator:
    """Test suite for HangingFunctionsValidator."""

    @pytest.fixture
    def temp_project_dir(self):
        """Create a temporary project directory."""
        with tempfile.TemporaryDirectory() as temp_dir:
            project_path = Path(temp_dir)
            yield project_path

    @pytest.fixture
    def sample_code_with_hanging_function(self) -> str:
        """Sample Python code with a hanging function."""
        return '''
def used_function():
    """This function is called."""
    return "I am used"

def hanging_function():
    """This function is never called."""
    return "I am hanging"

def main():
    result = used_function()
    print(result)

if __name__ == "__main__":
    main()
'''

    @pytest.fixture
    def sample_code_no_hanging_functions(self) -> str:
        """Sample Python code with no hanging functions."""
        return '''
def helper_function():
    """This function is called."""
    return "I help"

def main_function():
    """This function calls helper."""
    result = helper_function()
    return result

# Call main function
result = main_function()
print(result)
'''

    @pytest.fixture
    def sample_code_with_class_methods(self) -> str:
        """Sample Python code with class methods."""
        return '''
class Calculator:
    def __init__(self):
        self.result = 0
    
    def add(self, x, y):
        """Used method."""
        return x + y
    
    def unused_method(self):
        """This method is never called."""
        return "unused"
    
    def _private_method(self):
        """Private method - should be flagged."""
        return "private"
    
    def __str__(self):
        """Dunder method - should be ignored."""
        return str(self.result)

calc = Calculator()
result = calc.add(1, 2)
'''

    @pytest.fixture
    def sample_pyproject_toml(self) -> str:
        """Sample pyproject.toml with script entrypoints."""
        return '''
[project]
name = "test-project"
version = "0.1.0"

[project.scripts]
my-script = "main:cli"
another-script = "module.submodule:entry_point"
'''

    @pytest.fixture
    def sample_code_with_decorated_functions(self) -> str:
        """Sample Python code with decorated functions."""
        return '''
import functools
from flask import Flask

app = Flask(__name__)

@app.route('/')
def home():
    """This function has a decorator - should be ignored."""
    return "Home page"

@app.route('/api/data')
@functools.cache
def get_data():
    """This function has multiple decorators - should be ignored."""
    return {"data": "value"}

@property
def my_property():
    """Property decorator - should be ignored."""
    return "property value"

@staticmethod
def static_method():
    """Static method decorator - should be ignored."""
    return "static"

@classmethod
def class_method(cls):
    """Class method decorator - should be ignored."""
    return "class method"

def hanging_function():
    """This function has no decorator and is never called - should be flagged."""
    return "hanging"

def used_function():
    """This function has no decorator but is called."""
    return "used"

# Call the used function
result = used_function()
'''

    def test_create_validators(self, temp_project_dir: Path) -> None:
        """Test create_validators factory method."""
        # Create basic pyproject config structure
        config_path = temp_project_dir / "pyproject.toml"
        config_path.write_text('''
[tool.determystic]
version = "1.0"
[tool.determystic.validators]
[tool.determystic.settings]
''')

        # Reset and set runtime path and load config manager
        ProjectConfigManager.runtime_custom_path = None
        ProjectConfigManager._found_path = None
        ProjectConfigManager.set_runtime_custom_path(temp_project_dir)
        mock_config_manager = ProjectConfigManager.load_from_disk()
        
        validators = HangingFunctionsValidator.create_validators(mock_config_manager)
        
        assert len(validators) == 1
        assert isinstance(validators[0], HangingFunctionsValidator)
        assert validators[0].name == "hanging_functions"

    @pytest.mark.asyncio
    async def test_validate_with_hanging_function(
        self, 
        temp_project_dir: Path,
        sample_code_with_hanging_function: str
    ) -> None:
        """Test validation that finds hanging functions."""
        # Create Python file with hanging function
        python_file = temp_project_dir / "main.py"
        python_file.write_text(sample_code_with_hanging_function)
        
        validator = HangingFunctionsValidator(path=temp_project_dir)
        result = await validator.validate()
        
        # Should find the hanging function
        assert not result.success
        assert "hanging_function" in result.output
        assert "main.py:6:" in result.output
        assert "never referenced" in result.output

    @pytest.mark.asyncio
    async def test_validate_no_hanging_functions(
        self, 
        temp_project_dir: Path,
        sample_code_no_hanging_functions: str
    ) -> None:
        """Test validation with no hanging functions."""
        # Create Python file without hanging functions
        python_file = temp_project_dir / "main.py"
        python_file.write_text(sample_code_no_hanging_functions)
        
        validator = HangingFunctionsValidator(path=temp_project_dir)
        result = await validator.validate()
        
        # Should pass validation
        assert result.success
        assert "No dead code found" in result.output

    @pytest.mark.asyncio
    async def test_validate_with_class_methods(
        self, 
        temp_project_dir: Path,
        sample_code_with_class_methods: str
    ) -> None:
        """Test validation with class methods."""
        # Create Python file with class methods
        python_file = temp_project_dir / "calculator.py"
        python_file.write_text(sample_code_with_class_methods)
        
        validator = HangingFunctionsValidator(path=temp_project_dir)
        result = await validator.validate()
        
        # Should find unused_method and _private_method but not __str__
        assert not result.success
        assert "unused_method" in result.output
        assert "_private_method" in result.output
        assert "__str__" not in result.output  # Dunder methods should be ignored
        assert "__init__" not in result.output  # Dunder methods should be ignored

    @pytest.mark.asyncio
    async def test_validate_ignores_test_files(
        self, 
        temp_project_dir: Path,
        sample_code_with_hanging_function: str
    ) -> None:
        """Test that validation ignores test files."""
        # Create test files with hanging functions
        test_file1 = temp_project_dir / "test_something.py"
        test_file1.write_text(sample_code_with_hanging_function)
        
        test_file2 = temp_project_dir / "something_test.py"
        test_file2.write_text(sample_code_with_hanging_function)
        
        test_dir = temp_project_dir / "__tests__"
        test_dir.mkdir()
        test_file3 = test_dir / "test_file.py"
        test_file3.write_text(sample_code_with_hanging_function)
        
        tests_dir = temp_project_dir / "tests"
        tests_dir.mkdir()
        test_file4 = tests_dir / "test_file.py"
        test_file4.write_text(sample_code_with_hanging_function)
        
        # Create a regular file with hanging function
        regular_file = temp_project_dir / "main.py"
        regular_file.write_text(sample_code_with_hanging_function)
        
        validator = HangingFunctionsValidator(path=temp_project_dir)
        result = await validator.validate()
        
        # Should only find hanging functions in the regular file
        assert not result.success
        assert "main.py" in result.output
        assert "test_something.py" not in result.output
        assert "something_test.py" not in result.output
        assert "__tests__" not in result.output
        assert "tests" not in result.output

    @pytest.mark.asyncio
    async def test_validate_ignores_hidden_directories(
        self, 
        temp_project_dir: Path,
        sample_code_with_hanging_function: str
    ) -> None:
        """Test that validation ignores hidden directories."""
        # Create file in hidden directory
        hidden_dir = temp_project_dir / ".hidden"
        hidden_dir.mkdir()
        hidden_file = hidden_dir / "main.py"
        hidden_file.write_text(sample_code_with_hanging_function)
        
        # Create file in __pycache__ directory
        pycache_dir = temp_project_dir / "__pycache__"
        pycache_dir.mkdir()
        pycache_file = pycache_dir / "main.py"
        pycache_file.write_text(sample_code_with_hanging_function)
        
        # Create regular file
        regular_file = temp_project_dir / "main.py"
        regular_file.write_text(sample_code_with_hanging_function)
        
        validator = HangingFunctionsValidator(path=temp_project_dir)
        result = await validator.validate()
        
        # Should only process the regular file
        assert not result.success
        assert "main.py" in result.output
        # Count occurrences - should only be from regular file
        assert result.output.count("hanging_function") == 1

    @pytest.mark.asyncio
    async def test_validate_respects_configured_ignore_paths(
        self,
        temp_project_dir: Path,
        sample_code_with_hanging_function: str,
    ) -> None:
        """Configured ignore paths exclude Python files from dead-code analysis."""
        generated_dir = temp_project_dir / "generated"
        generated_dir.mkdir()
        ignored_file = generated_dir / "client.py"
        ignored_file.write_text(sample_code_with_hanging_function)

        validator = HangingFunctionsValidator(
            path=temp_project_dir,
            ignore_paths=["generated/"],
        )
        result = await validator.validate()

        assert result.success
        assert "No Python files found" in result.output

    @pytest.mark.asyncio
    async def test_validate_with_script_entrypoints(
        self, 
        temp_project_dir: Path,
        sample_pyproject_toml: str
    ) -> None:
        """Test that script entrypoints are ignored."""
        # Create pyproject.toml with script entrypoints
        pyproject_file = temp_project_dir / "pyproject.toml"
        pyproject_file.write_text(sample_pyproject_toml)
        
        # Create Python file with functions matching script entrypoints
        python_code = '''
def cli():
    """This is a script entrypoint - should be ignored."""
    print("CLI running")

def entry_point():
    """This is also a script entrypoint - should be ignored."""
    print("Entry point running")

def hanging_function():
    """This function is not an entrypoint and is never called."""
    return "hanging"
'''
        python_file = temp_project_dir / "main.py"
        python_file.write_text(python_code)
        
        validator = HangingFunctionsValidator(path=temp_project_dir)
        result = await validator.validate()
        
        # Should only find hanging_function, not the script entrypoints
        assert not result.success
        assert "hanging_function" in result.output
        assert "cli" not in result.output
        assert "entry_point" not in result.output

    # determystic: tested-exceptions[determystic.validators.hanging_functions.HangingFunctionsValidator._get_script_entrypoints: TOMLDecodeError, KeyError, ValueError]
    def test_get_script_entrypoints_handles_pyproject_parse_errors(
        self,
        temp_project_dir: Path,
    ) -> None:
        """Malformed entrypoint configuration is treated as no entrypoints."""
        pyproject_file = temp_project_dir / "pyproject.toml"
        pyproject_file.write_text("[project]\n")
        validator = HangingFunctionsValidator(path=temp_project_dir)

        parse_errors = [
            tomllib.TOMLDecodeError("bad toml", "bad", 0),
            KeyError("scripts"),
            ValueError("bad script"),
        ]
        for parse_error in parse_errors:
            with patch(
                "determystic.validators.hanging_functions.tomllib.load",
                side_effect=parse_error,
            ):
                assert validator._get_script_entrypoints(temp_project_dir) == set()

    @pytest.mark.asyncio
    async def test_validate_no_python_files(self, temp_project_dir: Path) -> None:
        """Test validation when there are no Python files."""
        validator = HangingFunctionsValidator(path=temp_project_dir)
        result = await validator.validate()
        
        # Should pass with no files message
        assert result.success
        assert "No Python files found" in result.output

    # determystic: tested-exceptions[determystic.validators.hanging_functions.HangingFunctionsValidator.validate: SyntaxError, UnicodeDecodeError]
    @pytest.mark.asyncio
    async def test_validate_syntax_error_in_file(
        self, 
        temp_project_dir: Path
    ) -> None:
        """Test that files with syntax errors are skipped gracefully."""
        # Create file with syntax error
        bad_file = temp_project_dir / "bad_syntax.py"
        bad_file.write_text("def broken_function(\n    # Missing closing parenthesis")

        bad_unicode_file = temp_project_dir / "bad_unicode.py"
        bad_unicode_file.write_bytes(b"\xff")
        
        # Create valid file with hanging function
        good_file = temp_project_dir / "good_file.py"
        good_file.write_text('''
def hanging_function():
    return "hanging"
''')
        
        validator = HangingFunctionsValidator(path=temp_project_dir)
        result = await validator.validate()
        
        # Should find hanging function in good file, skip bad file
        assert not result.success
        assert "hanging_function" in result.output
        assert "good_file.py" in result.output

    @pytest.mark.asyncio
    async def test_validate_function_references_without_calls(
        self, 
        temp_project_dir: Path
    ) -> None:
        """Test that function references (not just calls) are detected."""
        python_code = '''
def referenced_function():
    """This function is referenced but not called."""
    return "referenced"

def calling_function():
    """This function references the other."""
    func_ref = referenced_function  # Reference without call
    return func_ref

def hanging_function():
    """This function is truly hanging."""
    return "hanging"

result = calling_function()
'''
        python_file = temp_project_dir / "main.py"
        python_file.write_text(python_code)
        
        validator = HangingFunctionsValidator(path=temp_project_dir)
        result = await validator.validate()
        
        # Should only find hanging_function
        assert not result.success
        assert "hanging_function" in result.output
        assert "referenced_function" not in result.output
        assert "calling_function" not in result.output

    @pytest.mark.asyncio
    async def test_validate_method_calls(
        self, 
        temp_project_dir: Path
    ) -> None:
        """Test that method calls are properly detected."""
        python_code = '''
class MyClass:
    def called_method(self):
        """This method is called."""
        return "called"
    
    def hanging_method(self):
        """This method is never called."""
        return "hanging"

obj = MyClass()
result = obj.called_method()
'''
        python_file = temp_project_dir / "main.py"
        python_file.write_text(python_code)
        
        validator = HangingFunctionsValidator(path=temp_project_dir)
        result = await validator.validate()
        
        # Should only find hanging_method
        assert not result.success
        assert "hanging_method" in result.output
        assert "called_method" not in result.output
        assert "__init__" not in result.output  # Dunder methods ignored

    @pytest.mark.asyncio
    async def test_validate_ignores_decorated_functions(
        self, 
        temp_project_dir: Path,
        sample_code_with_decorated_functions: str
    ) -> None:
        """Test that decorated functions are ignored even if they're not referenced."""
        # Create Python file with decorated functions
        python_file = temp_project_dir / "main.py"
        python_file.write_text(sample_code_with_decorated_functions)
        
        validator = HangingFunctionsValidator(path=temp_project_dir)
        result = await validator.validate()
        
        # Should only find hanging_function (the one without decorators)
        # All decorated functions should be ignored
        assert not result.success
        assert "hanging_function" in result.output
        assert "home" not in result.output
        assert "get_data" not in result.output
        assert "my_property" not in result.output
        assert "static_method" not in result.output
        assert "class_method" not in result.output
        assert "used_function" not in result.output  # This is called, so not hanging
        # Verify only one function is reported
        assert result.output.count("never referenced") == 1

    @pytest.mark.asyncio
    async def test_validate_ignores_ast_visitor_hooks(
        self,
        temp_project_dir: Path,
    ) -> None:
        """Test that NodeVisitor-style visit hooks are not treated as hanging methods."""
        python_code = '''
import ast


class MyVisitor(ast.NodeVisitor):
    def visit_Call(self, node):
        self.generic_visit(node)

visitor = MyVisitor()
'''
        python_file = temp_project_dir / "visitor.py"
        python_file.write_text(python_code)

        validator = HangingFunctionsValidator(path=temp_project_dir)
        result = await validator.validate()

        assert result.success
        assert "No dead code found" in result.output

    @pytest.mark.asyncio
    async def test_validate_detects_unused_classes_arguments_and_unreachable_code(
        self,
        temp_project_dir: Path,
    ) -> None:
        """Test the broader dead-code checks beyond unused functions."""
        python_code = '''
class UsedClass:
    def method(self, value, unused_value):
        return value

class UnusedClass:
    pass

def function_with_unused_arg(used_value, unused_value):
    print(used_value)
    return used_value
    print("unreachable")

instance = UsedClass()
result = instance.method("used", "unused")
'''
        python_file = temp_project_dir / "main.py"
        python_file.write_text(python_code)

        validator = HangingFunctionsValidator(path=temp_project_dir)
        result = await validator.validate()

        assert not result.success
        assert "Class 'UnusedClass' is defined but never referenced" in result.output
        assert "Argument 'unused_value' in 'UsedClass.method' is never used" in result.output
        assert "Argument 'unused_value' in 'function_with_unused_arg' is never used" in result.output
        assert "Unreachable code after terminal statement" in result.output

    @pytest.mark.asyncio
    async def test_validate_treats_imported_superclass_only_classes_as_referenced(
        self,
        temp_project_dir: Path,
    ) -> None:
        """Imported classes used only for inheritance should not look unused."""
        base_file = temp_project_dir / "base.py"
        base_file.write_text(
            '''
class BasePlugin:
    pass
'''
        )

        plugin_file = temp_project_dir / "plugin.py"
        plugin_file.write_text(
            '''
from base import BasePlugin as PluginBase

class ConcretePlugin(PluginBase):
    pass
'''
        )

        registry_file = temp_project_dir / "registry.py"
        registry_file.write_text(
            '''
from plugin import ConcretePlugin
'''
        )

        validator = HangingFunctionsValidator(path=temp_project_dir)
        result = await validator.validate()

        assert result.success, result.output
        assert "No dead code found" in result.output

    @pytest.mark.asyncio
    async def test_validate_respects_determystic_suppression_comments(
        self,
        temp_project_dir: Path,
    ) -> None:
        """Test inline comments for externally used symbols and specific ignores."""
        python_code = '''
class ExternalPlugin:  # determystic: used
    def callback(self, event, context):  # determystic: used
        return event

def public_api(value):  # determystic: used
    return "called externally"

# determystic: used
def function_with_intentional_dead_code(arg):  # determystic: ignore[unused-argument]
    return 1
    print("unreachable")  # determystic: ignore[unreachable-code]

def hanging_function():
    return "still flagged"
'''
        python_file = temp_project_dir / "main.py"
        python_file.write_text(python_code)

        validator = HangingFunctionsValidator(path=temp_project_dir)
        result = await validator.validate()

        assert not result.success
        assert "hanging_function" in result.output
        assert "ExternalPlugin" not in result.output
        assert "callback" not in result.output
        assert "public_api" not in result.output
        assert "function_with_intentional_dead_code" not in result.output
        assert "Argument 'arg'" not in result.output
        assert "unreachable" not in result.output.lower()

    @pytest.mark.asyncio
    async def test_validate_respects_function_and_block_suppression_comments(
        self,
        temp_project_dir: Path,
    ) -> None:
        """Test definition-level and block-level dead-code suppressions."""
        python_code = '''
# determystic: ignore[dead-code]
def generated_callback(event, context):
    return event
    print("unreachable")

# determystic: ignore-start[dead-code]
class ExternalClass:
    pass

def external_function(unused_value):
    return "external"
# determystic: ignore-end[dead-code]

def hanging_function():
    return "still flagged"
'''
        python_file = temp_project_dir / "main.py"
        python_file.write_text(python_code)

        validator = HangingFunctionsValidator(path=temp_project_dir)
        result = await validator.validate()

        assert not result.success
        assert "hanging_function" in result.output
        assert "generated_callback" not in result.output
        assert "ExternalClass" not in result.output
        assert "external_function" not in result.output
        assert "unused_value" not in result.output
        assert "unreachable" not in result.output.lower()

    @pytest.mark.asyncio
    async def test_validate_respects_explicit_exports(
        self,
        temp_project_dir: Path,
    ) -> None:
        """Test that __all__ exports count as intentional public API."""
        python_code = '''
__all__ = ["ExportedClass", "exported_function"]

class ExportedClass:
    pass

def exported_function():
    return "exported"
'''
        python_file = temp_project_dir / "main.py"
        python_file.write_text(python_code)

        validator = HangingFunctionsValidator(path=temp_project_dir)
        result = await validator.validate()

        assert result.success
        assert "No dead code found" in result.output

    def test_display_name_property(self, temp_project_dir: Path) -> None:
        """Test that display_name property formats the name correctly."""
        validator = HangingFunctionsValidator(path=temp_project_dir)
        
        # Should format underscores as title case
        assert validator.display_name == "Hanging Functions"
