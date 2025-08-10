"""Pydantic AI agent for creating and testing AST validators."""

from typing import Optional, AsyncGenerator
from pydantic_ai.messages import PartDeltaEvent, TextPartDelta
from pydantic_ai.messages import FunctionToolCallEvent, FunctionToolResultEvent

from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext

from deterministic.isolated_env import IsolatedEnv


# Prompts
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
   - Implement appropriate `visit_*` methods for AST nodes you need to check
   - Use `self.add_error(node, message)` to report issues
   - Call `self.generic_visit(node)` to continue traversing child nodes

3. **Return format:**
   - is_valid=False: Code contains the problematic pattern
   - is_valid=True: Code is acceptable
   - Include error messages with line numbers and context

4. **Test thoroughly:**
   - The exact user-provided code should be detected as problematic
   - Create additional test cases that should be flagged
   - Create valid examples that should NOT be flagged
   - Test edge cases

## Tool Usage Instructions

**CRITICAL: Always start by reading the current external.py file to understand the latest available classes and functions.**

- Use `read_external_file` FIRST to get the current external.py interface before implementation
- Use `write_file` to write files with specific filenames:
 - Use filename "validator.py" for the AST validator implementation
 - Use filename "test_validator.py" for the test cases
- Use `read_file` to read the contents of any file
- Use `edit_file` to edit specific parts of a file
- Use `run_tests` to execute tests and verify they work correctly
- Use `finalize` when the implementation is complete and all tests pass

## Key Reminders

- The validator should flag problematic code (return is_valid=False)
- Focus on the SPECIFIC issue described by the user, not general code quality
- Always test your implementation thoroughly before finalizing
- Make the error messages clear and actionable
"""

TASK_PROMPT_TEMPLATE = """Create a comprehensive AST validator and test suite.

User-provided code that SHOULD BE DETECTED as problematic:
```python
{user_code}
```

Issue Description: {requirements}

IMPORTANT: The validator should return is_valid=False (flag as problematic) when it finds code matching the described issue.

Please:
1. Implement the validator that detects when code matches the problematic pattern described
2. Create comprehensive pytest tests including:
   - A test with the exact user-provided code (should be flagged as problematic)
   - Additional examples of the problematic pattern (should be flagged)
   - Examples of valid code that should NOT be flagged
   - Edge cases and boundary conditions
3. Run the tests to ensure everything works correctly
4. The validator should identify the SPECIFIC issue described, not general code quality
5. Finalize the implementation once all tests pass
"""

# Dependencies
class AgentDependencies(BaseModel):
    """Dependencies and state for the agent."""
    files: dict[str, str] = Field(default_factory=dict, description="Map of filenames to their contents")
    
    # Legacy support - these now proxy to the files dict
    @property
    def test_contents(self) -> str:
        """Legacy property for test contents."""
        return self.files.get("test_validator.py", "")
    
    @test_contents.setter
    def test_contents(self, value: str) -> None:
        """Legacy setter for test contents."""
        self.files["test_validator.py"] = value
    
    @property
    def validation_contents(self) -> str:
        """Legacy property for validation contents."""
        return self.files.get("validator.py", "")
    
    @validation_contents.setter
    def validation_contents(self, value: str) -> None:
        """Legacy setter for validation contents."""
        self.files["validator.py"] = value


# Models
class StreamEvent(BaseModel):
    """Event emitted during streaming execution."""
    event_type: str = Field(description="Type of event (user_prompt, model_request_start, text_chunk, tool_call_start, tool_call_end, final_result)")
    content: str = Field(description="Content of the event")
    deps: AgentDependencies


class WriteValidatorInput(BaseModel):
    """Input for writing validator code."""
    content: str = Field(description="The validator Python code content")


class WriteTestsInput(BaseModel):
    """Input for writing test code."""
    content: str = Field(description="The test Python code content")


class WriteFileInput(BaseModel):
    """Input for writing a generic file."""
    filename: str = Field(description="The name of the file to write")
    content: str = Field(description="The file content")


class ReadFileInput(BaseModel):
    """Input for reading a file."""
    filename: str = Field(description="The name of the file to read")


class EditFileInput(BaseModel):
    """Input for editing a file."""
    filename: str = Field(description="The name of the file to edit")
    old_str: str = Field(description="The old string to replace")
    new_str: str = Field(description="The new string to replace with")
    target_all: bool = Field(default=False, description="If True, replace all occurrences. If False, will error if multiple or zero matches")


class RunTestsInput(BaseModel):
    """Input for running tests."""
    message: str = Field(default="Running tests", description="Optional message about test execution")


class FinalizeInput(BaseModel):
    """Input for finalizing the implementation."""
    message: str = Field(description="Summary of what was accomplished")


class ReadExternalFileInput(BaseModel):
    """Input for reading the external.py file."""
    pass  # No parameters needed




# Agent
agent = Agent(
    deps_type=AgentDependencies,
    system_prompt=SYSTEM_PROMPT,
)



@agent.tool
async def run_tests(
    ctx: RunContext[AgentDependencies], 
    input: RunTestsInput
) -> str:
    """Run the tests using isolated environment."""
    if not ctx.deps.validation_contents:
        return "❌ No validator code available. Please write validator first."
    
    if not ctx.deps.test_contents:
        return "❌ No test code available. Please write tests first."
    
    # Use isolated environment to run tests
    with IsolatedEnv() as env:
        success, output = env.run_tests(
            validator_code=ctx.deps.validation_contents,
            test_code=ctx.deps.test_contents
        )
        
        if success:
            return f"✅ Tests passed!\n\n{output}"
        else:
            return f"❌ Tests failed:\n\n{output}"


@agent.tool
async def write_file(
    ctx: RunContext[AgentDependencies], 
    input: WriteFileInput
) -> str:
    """Write content to a file with the specified filename."""
    # Validate filename and set appropriate content
    if input.filename in ["validator.py", "test_validator.py"]:
        ctx.deps.files[input.filename] = input.content
        return f"✅ File '{input.filename}' written ({len(input.content)} characters)"
    else:
        return f"❌ Invalid filename '{input.filename}'. Expected 'validator.py' or 'test_validator.py'"


@agent.tool
async def read_file(
    ctx: RunContext[AgentDependencies], 
    input: ReadFileInput
) -> str:
    """Read the contents of a file."""
    if input.filename not in ctx.deps.files:
        return f"❌ File '{input.filename}' not found. Available files: {list(ctx.deps.files.keys())}"
    
    content = ctx.deps.files[input.filename]
    return f"📄 Contents of '{input.filename}' ({len(content)} characters):\n\n{content}"


@agent.tool
async def edit_file(
    ctx: RunContext[AgentDependencies], 
    input: EditFileInput
) -> str:
    """Edit a file by replacing old_str with new_str."""
    if input.filename not in ctx.deps.files:
        return f"❌ File '{input.filename}' not found. Available files: {list(ctx.deps.files.keys())}"
    
    content = ctx.deps.files[input.filename]
    
    # Count occurrences of old_str
    count = content.count(input.old_str)
    
    if count == 0:
        return f"❌ String not found in '{input.filename}': '{input.old_str[:50]}...'"
    elif count > 1 and not input.target_all:
        return f"❌ Multiple occurrences ({count}) found in '{input.filename}'. Use target_all=True to replace all, or provide a more specific old_str."
    
    # Perform replacement
    if input.target_all:
        new_content = content.replace(input.old_str, input.new_str)
        replacements = count
    else:
        new_content = content.replace(input.old_str, input.new_str, 1)
        replacements = 1
    
    ctx.deps.files[input.filename] = new_content
    
    return f"✅ Replaced {replacements} occurrence(s) in '{input.filename}'"


@agent.tool
async def read_external_file(
    ctx: RunContext[AgentDependencies], 
    input: ReadExternalFileInput
) -> str:
    """Read the current external.py file to understand available classes and functions."""
    try:
        # Read the external.py file from the deterministic package
        import deterministic.external
        import inspect
        
        # Get the path to the external.py file
        external_file_path = inspect.getfile(deterministic.external)
        
        # Read the file content
        with open(external_file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        return f"📄 Current external.py interface ({len(content)} characters):\n\n{content}"
    
    except Exception as e:
        return f"❌ Error reading external.py: {str(e)}"


@agent.tool
async def finalize(
    ctx: RunContext[AgentDependencies], 
    input: FinalizeInput
) -> str:
    """Finalize the implementation."""
    validator_size = len(ctx.deps.validation_contents)
    test_size = len(ctx.deps.test_contents)
    
    files_summary = "\n".join([f"- {filename}: {len(content)} characters" for filename, content in ctx.deps.files.items()])
    
    return f"🎉 Implementation complete! {input.message}\n\nFiles created:\n{files_summary}\n\nLegacy compatibility:\n- Validator: {validator_size} characters\n- Tests: {test_size} characters"


# Streaming function
async def stream_create_validator(
    user_code: str,
    requirements: Optional[str],
    anthropic_client,
) -> AsyncGenerator[StreamEvent, None]:
    """Stream the validator creation process."""
    
    # Create dependencies
    deps = AgentDependencies()
    
    # Format the prompt
    prompt = TASK_PROMPT_TEMPLATE.format(
        user_code=user_code,
        requirements=requirements or "Detect issues in the provided code"
    )
    
    # Use agent.iter() for streaming with graph introspection
    async with agent.iter(prompt, model=anthropic_client, deps=deps) as agent_run:
        async for node in agent_run:
            if agent.is_user_prompt_node(node):
                # User prompt started
                event = StreamEvent(
                    event_type='user_prompt',
                    content=f"Processing user request: {node.user_prompt}",
                    deps=deps
                )
                yield event
                
            elif agent.is_model_request_node(node):
                # Model request - stream the text response
                event = StreamEvent(
                    event_type='model_request_start',
                    content="🤖 Agent is thinking...",
                    deps=deps
                )
                yield event
                
                # Stream the model response text
                async with node.stream(agent_run.ctx) as request_stream:
                    async for stream_event in request_stream:
                        if isinstance(stream_event, PartDeltaEvent):
                            if isinstance(stream_event.delta, TextPartDelta):
                                if stream_event.delta.content_delta:
                                    event = StreamEvent(
                                        event_type='text_chunk',
                                        content=stream_event.delta.content_delta,
                                        deps=deps
                                    )
                                    yield event
                                
            elif agent.is_call_tools_node(node):
                # Tool calls - show what tools are being called
                event = StreamEvent(
                    event_type='tool_processing_start',
                    content="🔧 Using tools to create and test files...",
                    deps=deps
                )
                yield event
                
                # Stream tool calls and results
                async with node.stream(agent_run.ctx) as tool_stream:
                    async for stream_event in tool_stream:
                        if isinstance(stream_event, FunctionToolCallEvent):
                            # Tool call started
                            tool_name = stream_event.part.tool_name
                            tool_args = getattr(stream_event.part, 'args', {})
                            
                            event = StreamEvent(
                                event_type='tool_call_start',
                                content=f"🔧 Starting {tool_name}",
                                deps=deps
                            )
                            yield event
                            
                        elif isinstance(stream_event, FunctionToolResultEvent):
                            # Tool call completed
                            event = StreamEvent(
                                event_type='tool_call_end',
                                content=f"✅ Tool completed: {stream_event.result.content[:100]}...",
                                deps=deps
                            )
                            yield event
                            
            elif agent.is_end_node(node):
                # Final result - include file contents
                event = StreamEvent(
                    event_type='final_result',
                    content=f"✅ Complete! {node.data.output}",
                    deps=deps
                )
                yield event
                break


# Non-streaming function
async def create_ast_validator(
    user_code: str,
    requirements: Optional[str],
    anthropic_client,
) -> tuple[str, str, str]:
    """Create an AST validator with comprehensive tests.
    
    Args:
        user_code: The code provided by the user to test
        requirements: Additional requirements for the validator
        anthropic_client: Configured Anthropic client instance
        
    Returns:
        Tuple of (summary, validation_contents, test_contents)
    """
    deps = AgentDependencies()
    
    # Format the prompt
    prompt = TASK_PROMPT_TEMPLATE.format(
        user_code=user_code,
        requirements=requirements or "Detect issues in the provided code"
    )
    
    result = await agent.run(prompt, model=anthropic_client, deps=deps)
    return result.output, deps.validation_contents, deps.test_contents
