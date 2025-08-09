"""Pydantic AI agent for creating and testing AST validators."""

import os
import tempfile
import asyncio
from pathlib import Path
from typing import Literal, Optional
from dataclasses import dataclass

from pydantic import BaseModel, Field, field_validator
from pydantic_ai import Agent, ModelRetry, RunContext
from pydantic_ai.models.anthropic import AnthropicModel

# Agent Configuration
ALLOWED_FILES = {"ast_validator.py", "ast_test.py"}

# System Prompt for Anthropic API
SYSTEM_PROMPT = """You are an expert Python engineering agent specialized in creating and testing Abstract Syntax Tree (AST) validators.

## Your Core Mission

**Your primary job is to create an AST validator that identifies when given code MATCHES the problematic situation described by the user.**

The validator should:
- Return is_valid=False when the code exhibits the described issue (problematic pattern found)
- Return is_valid=True when the code does NOT exhibit the issue (code is acceptable)
- Detect the specific pattern or problem the user is concerned about

## Examples of Pattern Detection

### Example 1: No exceptions in test functions
**User Description:** "Exceptions shouldn't ever be allowed in a code block that starts with function name 'test'"

**Code that SHOULD be flagged (is_valid=False):**
```python
def test_calculation():
    try:
        result = calculate(5, 0)
    except ZeroDivisionError:
        pass  # BAD: Test is hiding errors
```

**Code that should NOT be flagged (is_valid=True):**
```python
def test_calculation():
    result = calculate(5, 2)
    assert result == 2.5  # GOOD: No exception handling

def process_data():
    try:
        data = fetch_data()
    except Exception:
        return None  # OK: Not a test function
```

### Example 2: Undefined variables
**User Description:** "Code uses variables that haven't been defined"

**Code that SHOULD be flagged (is_valid=False):**
```python
def calculate_sum(a, b):
    return a + b + c  # BAD: 'c' is undefined
```

**Code that should NOT be flagged (is_valid=True):**
```python
def calculate_sum(a, b, c):
    return a + b + c  # OK: All variables defined
```

## Implementation Requirements

Your ast_validator.py should return ValidationResult with:
- is_valid=False when the problematic pattern IS found
- is_valid=True when the problematic pattern is NOT found

Your ast_test.py should:
1. Test the user-provided code (should be flagged as problematic)
2. Test additional problematic examples
3. Test valid code that should NOT be flagged
4. Include edge cases

## Workflow

1. Understand the problematic pattern described
2. Implement ast_validator.py to detect that pattern
3. Create comprehensive tests in ast_test.py
4. Run tests to ensure everything works
5. Finalize once all tests pass

Remember: NEVER skip tests or use try/except to bypass test logic."""


# Tool Models
class FileWriteInput(BaseModel):
    """Input for writing a file."""
    filename: Literal["ast_validator.py", "ast_test.py"]
    content: str = Field(description="The complete content to write to the file")
    
    @field_validator("filename")
    @classmethod
    def validate_filename(cls, v: str) -> str:
        if v not in ALLOWED_FILES:
            raise ValueError(f"Can only write to {ALLOWED_FILES}, got {v}")
        return v


class FileEditInput(BaseModel):
    """Input for editing a file."""
    filename: Literal["ast_validator.py", "ast_test.py"]
    prev_str: str = Field(description="The exact string to replace")
    new_str: str = Field(description="The new string to insert")
    
    @field_validator("filename")
    @classmethod
    def validate_filename(cls, v: str) -> str:
        if v not in ALLOWED_FILES:
            raise ValueError(f"Can only edit {ALLOWED_FILES}, got {v}")
        return v


class TestRunInput(BaseModel):
    """Input for running tests."""
    test_file: str = Field(default="ast_test.py", description="Test file to run")


class FinalizeInput(BaseModel):
    """Input for finalizing the test suite."""
    message: str = Field(description="Summary of what was accomplished")


# Agent Dependencies
@dataclass
class AgentDependencies:
    """Dependencies and state for the agent."""
    dirty_files: set[str]
    temp_dir: Optional[Path]
    files: dict[str, str]
    
    def __init__(self):
        self.dirty_files = set()
        self.temp_dir = None
        self.files = {}
    
    def mark_dirty(self, filename: str) -> None:
        """Mark a file as modified."""
        self.dirty_files.add(filename)
    
    def get_temp_dir(self) -> Path:
        """Get or create a temporary directory for testing."""
        if self.temp_dir is None:
            self.temp_dir = Path(tempfile.mkdtemp(prefix="ast_validator_"))
        return self.temp_dir
    
    def cleanup(self) -> None:
        """Clean up temporary resources."""
        if self.temp_dir and self.temp_dir.exists():
            import shutil
            shutil.rmtree(self.temp_dir)


# Create the agent at module level (idiomatic pydantic-ai pattern)
ast_validator_agent = Agent(
    model=AnthropicModel("claude-3-5-sonnet-20241022"),
    system_prompt=SYSTEM_PROMPT,
    deps_type=AgentDependencies,
    result_type=str,
)


# Register tools using the @agent.tool decorator pattern
@ast_validator_agent.tool
async def write_file(ctx: RunContext[AgentDependencies], input: FileWriteInput) -> str:
    """Write content to a file (ast_validator.py or ast_test.py)."""
    try:
        # Store content in memory
        ctx.deps.files[input.filename] = input.content
        ctx.deps.mark_dirty(input.filename)
        
        # Also write to temp directory for testing
        temp_dir = ctx.deps.get_temp_dir()
        file_path = temp_dir / input.filename
        file_path.write_text(input.content)
        
        return f"Successfully wrote {len(input.content)} characters to {input.filename}"
    except Exception as e:
        raise ModelRetry(f"Failed to write file: {e}")


@ast_validator_agent.tool
async def edit_file(ctx: RunContext[AgentDependencies], input: FileEditInput) -> str:
    """Edit a file by replacing a string with a new string."""
    try:
        # Get current content
        if input.filename not in ctx.deps.files:
            raise ValueError(f"File {input.filename} has not been created yet. Use write_file first.")
        
        current_content = ctx.deps.files[input.filename]
        
        # Check if the string to replace exists
        if input.prev_str not in current_content:
            raise ValueError(f"String to replace not found in {input.filename}")
        
        # Replace the string
        new_content = current_content.replace(input.prev_str, input.new_str, 1)
        
        # Store updated content
        ctx.deps.files[input.filename] = new_content
        ctx.deps.mark_dirty(input.filename)
        
        # Update file in temp directory
        temp_dir = ctx.deps.get_temp_dir()
        file_path = temp_dir / input.filename
        file_path.write_text(new_content)
        
        return f"Successfully edited {input.filename}, replaced {len(input.prev_str)} characters with {len(input.new_str)} characters"
    except Exception as e:
        raise ModelRetry(f"Failed to edit file: {e}")


@ast_validator_agent.tool
async def run_test(ctx: RunContext[AgentDependencies], input: TestRunInput) -> str:
    """Run pytest on the test file using uv."""
    try:
        temp_dir = ctx.deps.get_temp_dir()
        
        # Ensure test file exists
        test_path = temp_dir / input.test_file
        if not test_path.exists():
            raise ValueError(f"Test file {input.test_file} not found. Please write it first.")
        
        # Run pytest using uv
        process = await asyncio.create_subprocess_exec(
            "uv", "run", "pytest", str(test_path), "-v", "--tb=short",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=temp_dir
        )
        
        stdout, stderr = await process.communicate()
        
        output = stdout.decode() if stdout else ""
        errors = stderr.decode() if stderr else ""
        
        result = f"Test Output:\n{output}\n"
        if errors:
            result += f"\nErrors:\n{errors}"
        
        if process.returncode == 0:
            result = f"✅ All tests passed!\n\n{result}"
        else:
            result = f"❌ Tests failed (exit code: {process.returncode})\n\n{result}"
        
        return result
    except Exception as e:
        raise ModelRetry(f"Failed to run tests: {e}")


@ast_validator_agent.tool
async def finalize_test(ctx: RunContext[AgentDependencies], input: FinalizeInput) -> str:
    """Finalize the test suite and save files."""
    try:
        # Create output directory
        output_dir = Path("output")
        output_dir.mkdir(exist_ok=True)
        
        # Save all dirty files to output directory
        saved_files = []
        for filename in ctx.deps.dirty_files:
            if filename in ctx.deps.files:
                output_path = output_dir / filename
                output_path.write_text(ctx.deps.files[filename])
                saved_files.append(str(output_path))
        
        # Clean up temp directory
        ctx.deps.cleanup()
        
        result = f"""
✅ Test Suite Finalized!

Summary: {input.message}

Files saved to output directory:
{chr(10).join(f"  - {f}" for f in saved_files)}

The AST validator and comprehensive test suite are ready for use.
"""
        return result
    except Exception as e:
        raise ModelRetry(f"Failed to finalize: {e}")


# Main execution function
async def create_ast_validator(
    user_code: str,
    requirements: Optional[str] = None
) -> str:
    """Create an AST validator with comprehensive tests.
    
    Args:
        user_code: The code provided by the user to test
        requirements: Additional requirements for the validator
        
    Returns:
        Summary of the created validator and tests
    """
    deps = AgentDependencies()
    
    prompt = f"""
Create a comprehensive AST validator and test suite.

User-provided code that SHOULD BE DETECTED as problematic:
```python
{user_code}
```

Issue Description: {requirements if requirements else "Detect issues in the provided code"}

IMPORTANT: The validator should return is_valid=False (flag as problematic) when it finds code matching the described issue.

Please:
1. Implement ast_validator.py that detects when code matches the problematic pattern described
2. Create ast_test.py with comprehensive pytest tests including:
   - A test with the exact user-provided code (should be flagged as problematic)
   - Additional examples of the problematic pattern (should be flagged)
   - Examples of valid code that should NOT be flagged
   - Edge cases and boundary conditions
3. Run the tests to ensure everything works correctly
4. The validator should identify the SPECIFIC issue described, not general code quality
5. Finalize the implementation once all tests pass
"""
    
    result = await ast_validator_agent.run(prompt, deps=deps)
    return result.data


# Example usage
if __name__ == "__main__":
    # Example user code with potential issues
    example_code = '''
def test_divide():
    try:
        result = 10 / 0
    except ZeroDivisionError:
        pass  # Test is hiding an error!
        
def test_multiply():
    try:
        return 5 * 2
    except Exception:
        return None  # Another hidden error in test
'''
    
    # Run the agent
    result = asyncio.run(create_ast_validator(
        user_code=example_code,
        requirements="Exceptions should never be allowed in functions that start with 'test'"
    ))
    
    print(result)
    