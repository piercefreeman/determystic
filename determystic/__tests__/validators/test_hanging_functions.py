"""Tests for hanging functions validator functionality."""

import tempfile
from pathlib import Path

import pytest

from determystic.validators.hanging_functions import HangingFunctionsValidator


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

    def test_create_validators(self, temp_project_dir: Path) -> None:
        """Test create_validators factory method."""
        validators = HangingFunctionsValidator.create_validators(temp_project_dir)
        
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
        
        validator = HangingFunctionsValidator()
        result = await validator.validate(temp_project_dir)
        
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
        
        validator = HangingFunctionsValidator()
        result = await validator.validate(temp_project_dir)
        
        # Should pass validation
        assert result.success
        assert "No hanging functions found" in result.output

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
        
        validator = HangingFunctionsValidator()
        result = await validator.validate(temp_project_dir)
        
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
        
        validator = HangingFunctionsValidator()
        result = await validator.validate(temp_project_dir)
        
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
        
        validator = HangingFunctionsValidator()
        result = await validator.validate(temp_project_dir)
        
        # Should only process the regular file
        assert not result.success
        assert "main.py" in result.output
        # Count occurrences - should only be from regular file
        assert result.output.count("hanging_function") == 1

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
        
        validator = HangingFunctionsValidator()
        result = await validator.validate(temp_project_dir)
        
        # Should only find hanging_function, not the script entrypoints
        assert not result.success
        assert "hanging_function" in result.output
        assert "cli" not in result.output
        assert "entry_point" not in result.output

    @pytest.mark.asyncio
    async def test_validate_no_python_files(self, temp_project_dir: Path) -> None:
        """Test validation when there are no Python files."""
        validator = HangingFunctionsValidator()
        result = await validator.validate(temp_project_dir)
        
        # Should pass with no files message
        assert result.success
        assert "No Python files found" in result.output

    @pytest.mark.asyncio
    async def test_validate_syntax_error_in_file(
        self, 
        temp_project_dir: Path
    ) -> None:
        """Test that files with syntax errors are skipped gracefully."""
        # Create file with syntax error
        bad_file = temp_project_dir / "bad_syntax.py"
        bad_file.write_text("def broken_function(\n    # Missing closing parenthesis")
        
        # Create valid file with hanging function
        good_file = temp_project_dir / "good_file.py"
        good_file.write_text('''
def hanging_function():
    return "hanging"
''')
        
        validator = HangingFunctionsValidator()
        result = await validator.validate(temp_project_dir)
        
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
        
        validator = HangingFunctionsValidator()
        result = await validator.validate(temp_project_dir)
        
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
        
        validator = HangingFunctionsValidator()
        result = await validator.validate(temp_project_dir)
        
        # Should only find hanging_method
        assert not result.success
        assert "hanging_method" in result.output
        assert "called_method" not in result.output
        assert "__init__" not in result.output  # Dunder methods ignored

    def test_display_name_property(self, temp_project_dir: Path) -> None:
        """Test that display_name property formats the name correctly."""
        validator = HangingFunctionsValidator()
        
        # Should format underscores as title case
        assert validator.display_name == "Hanging Functions"