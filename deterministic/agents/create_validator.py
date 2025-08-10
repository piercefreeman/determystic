"""Pydantic AI agent for creating and testing AST validators."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, AsyncGenerator, Callable
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

- Use `write_validator` to create the AST validator code
- Use `write_tests` to create comprehensive test cases
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


# Models
class StreamEvent(BaseModel):
    """Event emitted during streaming execution."""
    event_type: str = Field(description="Type of event (user_prompt, model_request_start, text_chunk, tool_call_start, tool_call_end, final_result)")
    content: str = Field(description="Content of the event")
    metadata: dict = Field(default_factory=dict, description="Additional metadata")


class WriteValidatorInput(BaseModel):
    """Input for writing validator code."""
    content: str = Field(description="The validator Python code content")


class WriteTestsInput(BaseModel):
    """Input for writing test code."""
    content: str = Field(description="The test Python code content")


class RunTestsInput(BaseModel):
    """Input for running tests."""
    message: str = Field(default="Running tests", description="Optional message about test execution")


class FinalizeInput(BaseModel):
    """Input for finalizing the implementation."""
    message: str = Field(description="Summary of what was accomplished")


# Dependencies
@dataclass
class AgentDependencies:
    """Dependencies and state for the agent."""
    project_root: Path
    test_contents: str = field(default="")
    validation_contents: str = field(default="")


# Agent
agent = Agent(
    deps_type=AgentDependencies,
)


# Tools
@agent.tool
async def write_validator(
    ctx: RunContext[AgentDependencies], 
    input: WriteValidatorInput
) -> str:
    """Write the AST validator code content."""
    ctx.deps.validation_contents = input.content
    return f"✅ Validator code written ({len(input.content)} characters)"


@agent.tool
async def write_tests(
    ctx: RunContext[AgentDependencies], 
    input: WriteTestsInput
) -> str:
    """Write the test code content."""
    ctx.deps.test_contents = input.content
    return f"✅ Test code written ({len(input.content)} characters)"


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
    with IsolatedEnv(ctx.deps.project_root) as env:
        success, output = env.run_tests(
            validator_code=ctx.deps.validation_contents,
            test_code=ctx.deps.test_contents
        )
        
        if success:
            return f"✅ Tests passed!\n\n{output}"
        else:
            return f"❌ Tests failed:\n\n{output}"


@agent.tool
async def finalize(
    ctx: RunContext[AgentDependencies], 
    input: FinalizeInput
) -> str:
    """Finalize the implementation."""
    validator_size = len(ctx.deps.validation_contents)
    test_size = len(ctx.deps.test_contents)
    
    return f"🎉 Implementation complete! {input.message}\n\nFiles created:\n- Validator: {validator_size} characters\n- Tests: {test_size} characters"


# Streaming function
async def stream_create_validator(
    user_code: str,
    requirements: Optional[str],
    anthropic_client,
    project_root: Path,
    callback: Optional[Callable[[StreamEvent], None]] = None
) -> AsyncGenerator[StreamEvent, None]:
    """Stream the validator creation process."""
    
    # Create dependencies
    deps = AgentDependencies(project_root=project_root)
    
    # Create agent with provided client
    stream_agent = Agent(
        model=anthropic_client,
        system_prompt=SYSTEM_PROMPT,
        deps_type=AgentDependencies,
    )
    
    # Register tools
    stream_agent.tool(write_validator)
    stream_agent.tool(write_tests)
    stream_agent.tool(run_tests)
    stream_agent.tool(finalize)
    
    # Format the prompt
    prompt = TASK_PROMPT_TEMPLATE.format(
        user_code=user_code,
        requirements=requirements or "Detect issues in the provided code"
    )
    
    # Use agent.iter() for streaming with graph introspection
    async with stream_agent.iter(prompt, deps=deps) as agent_run:
        async for node in agent_run:
            if stream_agent.is_user_prompt_node(node):
                # User prompt started
                event = StreamEvent(
                    event_type='user_prompt',
                    content=f"Processing user request: {node.user_prompt}",
                    metadata={'step': 'user_prompt'}
                )
                if callback:
                    await callback(event)
                yield event
                
            elif stream_agent.is_model_request_node(node):
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
                                
            elif stream_agent.is_call_tools_node(node):
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
                            
            elif stream_agent.is_end_node(node):
                # Final result - include file contents
                event = StreamEvent(
                    event_type='final_result',
                    content=f"✅ Complete! {node.data.output}",
                    metadata={
                        'step': 'final_result', 
                        'output': node.data.output,
                        'validation_contents': deps.validation_contents,
                        'test_contents': deps.test_contents
                    }
                )
                if callback:
                    await callback(event)
                yield event


# Non-streaming function
async def create_ast_validator(
    user_code: str,
    requirements: Optional[str],
    anthropic_client,
    project_root: Path
) -> tuple[str, str, str]:
    """Create an AST validator with comprehensive tests.
    
    Args:
        user_code: The code provided by the user to test
        requirements: Additional requirements for the validator
        anthropic_client: Configured Anthropic client instance
        project_root: Root path of the deterministic project
        
    Returns:
        Tuple of (summary, validation_contents, test_contents)
    """
    deps = AgentDependencies(project_root=project_root)
    
    # Create agent with provided client
    run_agent = Agent(
        model=anthropic_client,
        system_prompt=SYSTEM_PROMPT,
        deps_type=AgentDependencies,
    )
    
    # Register tools
    run_agent.tool(write_validator)
    run_agent.tool(write_tests)
    run_agent.tool(run_tests)
    run_agent.tool(finalize)
    
    # Format the prompt
    prompt = TASK_PROMPT_TEMPLATE.format(
        user_code=user_code,
        requirements=requirements or "Detect issues in the provided code"
    )
    
    result = await run_agent.run(prompt, deps=deps)
    return result.output, deps.validation_contents, deps.test_contents
