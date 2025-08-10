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
- Provide detailed error information with line numbers and code context

## Required AST Traverser Pattern

You MUST create a validator using the AST traverser pattern from `deterministic.external`:

```python
from deterministic.external import DeterministicTraverser

class YourValidatorTraverser(DeterministicTraverser):
    '''Custom AST traverser for your specific validation.'''
    
    def visit_SomeASTNode(self, node):
        '''Visit specific AST nodes and check for issues.'''
        
        # Check for your specific pattern
        if self.detect_problem(node):
            self.add_error(
                node, 
                "Clear description of what's wrong and how to fix it"
            )
        
        # Continue traversing
        self.generic_visit(node)
    
    def detect_problem(self, node):
        '''Your custom logic to detect the problematic pattern.'''
        # Example: check if node contains "Optional["
        try:
            node_source = ast.unparse(node)
            return "Optional[" in node_source
        except:
            return False
```

**The traverser will be automatically discovered and executed by the validation system.**

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

### Example 2: Optional type hints
**User Description:** "Don't use Optional[T], use T | None instead"

**Code that SHOULD be flagged (is_valid=False):**
```python
from typing import Optional

def process(value: Optional[str]) -> None:  # BAD: Use str | None
    pass
```

## Implementation Requirements

1. **Always create an AST traverser class:**
   ```python
   from deterministic.external import DeterministicTraverser
   
   class YourValidatorTraverser(DeterministicTraverser):
       # Your validation logic here
   ```

2. **Your traverser class should:**
   - Inherit from `DeterministicTraverser`
   - Override specific `visit_*` methods for the AST nodes you want to check
   - Use `self.add_error(node, message)` to report issues
   - Call `self.generic_visit(node)` to continue traversing child nodes

3. **Error reporting is automatic:**
   - Line numbers and column positions are extracted from AST nodes
   - Code context is automatically generated
   - All you need to do is call `self.add_error(node, "your message")`

4. **Your ast_test.py should:**
   - Import your traverser class
   - Test the user-provided code (should be flagged as problematic)
   - Test additional problematic examples
   - Test valid code that should NOT be flagged
   - Include edge cases
   - Create the traverser and call `.validate()` to get results

## Workflow

1. Import DeterministicTraverser from deterministic.external
2. Understand the problematic pattern described  
3. Create a traverser class that inherits from DeterministicTraverser
4. Override the appropriate visit_* methods to detect your pattern
5. Use self.add_error() to report issues with automatic line numbers
6. Create comprehensive tests in ast_test.py that instantiate your traverser
7. Run tests to ensure everything works and error messages are detailed
8. Finalize once all tests pass

Remember: ALWAYS use the DeterministicTraverser pattern - no validate_code functions!"""


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
    
    def get_file_contents(self) -> dict[str, str]:
        """Get the contents of all files that were created/modified."""
        return {filename: content for filename, content in self.files.items() if filename in self.dirty_files}


# Create the agent at module level (idiomatic pydantic-ai pattern)
# Note: We'll initialize with API key from environment/settings at runtime
def _create_agent():
    """Create the agent with proper API key configuration."""
    # Check if ANTHROPIC_API_KEY is available
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        try:
            from deterministic.settings import get_settings
            settings = get_settings()
            api_key = settings.anthropic_api_key
            if api_key:
                # Set environment variable so AnthropicModel can find it
                os.environ["ANTHROPIC_API_KEY"] = api_key
        except Exception:
            pass
    
    if not api_key and "ANTHROPIC_API_KEY" not in os.environ:
        raise ValueError("ANTHROPIC_API_KEY not found in environment or configuration")
    
    # Create model - it will use the environment variable automatically
    model = AnthropicModel("claude-sonnet-4-20250514")
    
    agent = Agent(
        model=model,
        system_prompt=SYSTEM_PROMPT,
        deps_type=AgentDependencies,
    )
    
    # Register tools
    agent.tool(write_file)
    agent.tool(edit_file)
    agent.tool(run_test)
    agent.tool(finalize_test)
    
    return agent

# Tool functions (will be registered with the agent)
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


async def finalize_test(ctx: RunContext[AgentDependencies], input: FinalizeInput) -> str:
    """Finalize the test suite and return file contents."""
    try:
        # Clean up temp directory
        ctx.deps.cleanup()
        
        result = f"""
✅ Test Suite Finalized!

Summary: {input.message}

Generated files:
{chr(10).join(f"  - {f}" for f in ctx.deps.dirty_files)}

The AST validator and comprehensive test suite are ready for use.
"""
        return result
    except Exception as e:
        raise ModelRetry(f"Failed to finalize: {e}")


# Streaming execution function
async def create_ast_validator_stream(
    user_code: str,
    requirements: Optional[str] = None,
    callback=None
):
    """Create an AST validator with comprehensive tests, streaming results.
    
    Args:
        user_code: The code provided by the user to test
        requirements: Additional requirements for the validator
        callback: Optional callback function to handle streaming events
        
    Yields:
        Streaming events as they occur
    """
    from dataclasses import dataclass
    
    @dataclass
    class StreamEvent:
        event_type: str  # 'text_chunk', 'tool_call_start', 'tool_call_end', 'final_result'
        content: str
        metadata: dict = None
    
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
    
    # Create the agent with proper configuration
    agent = _create_agent()
    
    # Use agent.iter() for graph introspection with streaming
    async with agent.iter(prompt, deps=deps) as agent_run:
        async for node in agent_run:
            if agent.is_user_prompt_node(node):
                # User prompt started
                event = StreamEvent(
                    event_type='user_prompt',
                    content=f"Processing user request: {node.user_prompt}",
                    metadata={'step': 'user_prompt'}
                )
                if callback:
                    await callback(event)
                yield event
                
            elif agent.is_model_request_node(node):
                # Model request - stream the text response
                event = StreamEvent(
                    event_type='model_request_start',
                    content="🤖 Agent is thinking...",
                    metadata={'step': 'model_request'}
                )
                if callback:
                    await callback(event)
                yield event
                
                # Stream the model response text
                async with node.stream(agent_run.ctx) as request_stream:
                    async for stream_event in request_stream:
                        from pydantic_ai.messages import PartDeltaEvent, TextPartDelta
                        if isinstance(stream_event, PartDeltaEvent):
                            if isinstance(stream_event.delta, TextPartDelta):
                                if stream_event.delta.content_delta:
                                    event = StreamEvent(
                                        event_type='text_chunk',
                                        content=stream_event.delta.content_delta,
                                        metadata={'step': 'streaming_text', 'part_index': stream_event.index}
                                    )
                                    if callback:
                                        await callback(event)
                                    yield event
                                
            elif agent.is_call_tools_node(node):
                # Tool calls - show what tools are being called
                event = StreamEvent(
                    event_type='tool_processing_start',
                    content="🔧 Using tools to create and test files...",
                    metadata={'step': 'tool_processing'}
                )
                if callback:
                    await callback(event)
                yield event
                
                # Stream tool calls and results
                async with node.stream(agent_run.ctx) as tool_stream:
                    async for stream_event in tool_stream:
                        from pydantic_ai.messages import FunctionToolCallEvent, FunctionToolResultEvent
                        if isinstance(stream_event, FunctionToolCallEvent):
                            # Tool call started
                            tool_name = stream_event.part.tool_name
                            tool_args = getattr(stream_event.part, 'args', {})
                            
                            event = StreamEvent(
                                event_type='tool_call_start',
                                content=f"🔧 Starting {tool_name}",
                                metadata={
                                    'step': 'tool_call_start',
                                    'tool_name': tool_name,
                                    'tool_args': tool_args
                                }
                            )
                            if callback:
                                await callback(event)
                            yield event
                            
                        elif isinstance(stream_event, FunctionToolResultEvent):
                            # Tool call completed
                            event = StreamEvent(
                                event_type='tool_call_end',
                                content=f"✅ Tool completed: {stream_event.result.content[:100]}...",
                                metadata={
                                    'step': 'tool_call_end',
                                    'tool_call_id': getattr(stream_event, 'tool_call_id', None),
                                    'result': stream_event.result.content
                                }
                            )
                            if callback:
                                await callback(event)
                            yield event
                            
            elif agent.is_end_node(node):
                # Final result - include file contents
                file_contents = deps.get_file_contents()
                event = StreamEvent(
                    event_type='final_result',
                    content=f"✅ Complete! {node.data.output}",
                    metadata={
                        'step': 'final_result', 
                        'output': node.data.output,
                        'file_contents': file_contents
                    }
                )
                if callback:
                    await callback(event)
                yield event


# Main execution function (non-streaming)
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
    
    # Create the agent with proper configuration
    agent = _create_agent()
    
    result = await agent.run(prompt, deps=deps)
    return result.output


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
    