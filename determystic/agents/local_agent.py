"""Local CLI agent support for creating AST validators."""

from __future__ import annotations

import asyncio
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import AsyncGenerator, Callable, Literal

from pydantic import BaseModel, Field

from determystic.agents.create_validator import (
    AgentDependencies,
    StreamEvent,
    SYSTEM_PROMPT,
)
from determystic.configs.project import ValidatorAgentPreference
from determystic.isolated_env import IsolatedEnv

LocalAgentName = Literal["codex", "claude"]

LOCAL_AGENT_ORDER: tuple[LocalAgentName, ...] = ("codex", "claude")
LOCAL_AGENT_SETTINGS_KEY = "validator_agent"

LOCAL_AGENT_SYSTEM_PROMPT = SYSTEM_PROMPT.split("## Tool Usage Instructions", maxsplit=1)[0].strip()

LOCAL_AGENT_INSTRUCTIONS_TEMPLATE = """## Local CLI Instructions

You are running inside a temporary workspace for determystic.

Create exactly these two files in the current directory:
- validator.py
- test_validator.py

Do not modify any other files. The caller will read these files and run them in an isolated
determystic test environment after your command exits.

If file editing is unavailable, include fallback fenced blocks in your final answer:
```validator.py
<validator contents>
```
```test_validator.py
<test contents>
```

The current `determystic.external` interface is:
```python
{external_interface}
```

Key reminders:
- The validator should flag problematic code with `is_valid=False`.
- Focus on the specific issue described by the user.
- Keep examples minimal and directly related to the AST pattern.
- The caller will run the generated tests after your command exits.
"""

LOCAL_AGENT_TASK_PROMPT_TEMPLATE = """Create a comprehensive AST validator and test suite.

User-provided code that SHOULD BE DETECTED as problematic:
```python
{user_code}
```

Issue Description: {requirements}

**CRITICAL: If the provided code is large or complex, extract ONLY the minimal portions that demonstrate the problematic pattern. Focus on creating the smallest possible reproduction case that still exhibits the issue.**

IMPORTANT: The validator should return is_valid=False (flag as problematic) when it finds code matching the described issue.

Please:
1. **Extract minimal examples**: If the user-provided code is lengthy, identify and extract only the core patterns that need to be detected
2. Implement the validator that detects when code matches the problematic pattern described
3. Create comprehensive pytest tests including:
   - A test with the essential parts of the user-provided code (should be flagged as problematic)
   - Additional minimal examples of the problematic pattern (should be flagged)
   - Simple examples of valid code that should NOT be flagged
   - Edge cases and boundary conditions (keep these concise)
4. Ensure the tests are executable by pytest; the caller will run them after this command exits
5. The validator should identify the SPECIFIC issue described, not general code quality

Remember: Focus on minimal viable reproduction cases for both good and bad behavior within the AST parsing and testing framework.
"""

LOCAL_AGENT_RETRY_PROMPT_TEMPLATE = """The previous attempt failed validation or tests. Fix the files using this feedback:

{previous_failure}
"""


class LocalAgentSelectionError(RuntimeError):
    """Raised when no configured local agent can be selected."""


class LocalAgentExecutionError(RuntimeError):
    """Raised when a selected local agent fails to generate a validator."""


class LocalAgentResult(BaseModel):
    """Result produced by a local CLI agent."""

    summary: str = Field(description="Summary of the generated validator")
    validation_contents: str = Field(description="Generated validator code")
    test_contents: str = Field(description="Generated pytest code")
    tests_passed: bool = Field(default=False, description="Whether generated tests passed")
    test_output: str = Field(default="", description="Output from generated tests")


def _external_interface() -> str:
    """Read the external validator interface for local CLI agents."""
    external_path = Path(__file__).resolve().parents[1] / "external.py"
    try:
        return external_path.read_text()
    except OSError:
        return ""


def select_local_agent(
    preference: ValidatorAgentPreference,
    which: Callable[[str], str | None] = shutil.which,
) -> LocalAgentName:
    """Choose an installed local agent, preferring Codex in auto mode."""
    if preference != "auto":
        if which(preference):
            return preference
        raise LocalAgentSelectionError(
            f"Configured local agent '{preference}' is not installed or is not on PATH."
        )

    for agent_name in LOCAL_AGENT_ORDER:
        if which(agent_name):
            return agent_name

    raise LocalAgentSelectionError(
        "No supported local coding agent was found on PATH. Install Codex or Claude Code, "
        f"or set [tool.determystic.settings].{LOCAL_AGENT_SETTINGS_KEY} to an installed agent."
    )


def _build_prompt(user_code: str, requirements: str | None, previous_failure: str | None = None) -> str:
    task_prompt = LOCAL_AGENT_TASK_PROMPT_TEMPLATE.format(
        user_code=user_code,
        requirements=requirements or "Detect issues in the provided code",
    )
    local_instructions = LOCAL_AGENT_INSTRUCTIONS_TEMPLATE.format(
        external_interface=_external_interface(),
    )
    prompt_sections = [LOCAL_AGENT_SYSTEM_PROMPT, local_instructions, task_prompt]
    if previous_failure:
        prompt_sections.append(
            LOCAL_AGENT_RETRY_PROMPT_TEMPLATE.format(previous_failure=previous_failure)
        )
    return "\n\n".join(prompt_sections)


def _build_agent_command(agent_name: LocalAgentName, workdir: Path, output_path: Path) -> list[str]:
    if agent_name == "codex":
        return [
            "codex",
            "exec",
            "--skip-git-repo-check",
            "--ephemeral",
            "--sandbox",
            "workspace-write",
            "-C",
            str(workdir),
            "-o",
            str(output_path),
            "-",
        ]

    return [
        "claude",
        "--print",
        "--no-session-persistence",
        "--permission-mode",
        "acceptEdits",
        "--allowedTools",
        "Read,Write,Edit,Bash",
    ]


def _extract_fenced_file(output: str, filename: str) -> str | None:
    exact_pattern = rf"```{re.escape(filename)}\s*\n(.*?)```"
    exact_matches = re.findall(exact_pattern, output, flags=re.DOTALL | re.IGNORECASE)
    if exact_matches:
        return exact_matches[0].strip()

    generic_pattern = r"```python\s*\n(.*?)```"
    matches = re.findall(generic_pattern, output, flags=re.DOTALL | re.IGNORECASE)
    if not matches:
        return None

    if len(matches) == 1:
        return matches[0].strip()

    lowered = filename.lower()
    for match in matches:
        if lowered == "validator.py" and "DeterministicTraverser" in match:
            return match.strip()
        if lowered == "test_validator.py" and "def test_" in match:
            return match.strip()

    return matches[0].strip()


def _read_generated_files(workdir: Path, agent_output: str) -> tuple[str, str]:
    validator_path = workdir / "validator.py"
    tests_path = workdir / "test_validator.py"

    validation_contents = validator_path.read_text() if validator_path.exists() else ""
    test_contents = tests_path.read_text() if tests_path.exists() else ""

    if not validation_contents:
        validation_contents = _extract_fenced_file(agent_output, "validator.py") or ""
    if not test_contents:
        test_contents = _extract_fenced_file(agent_output, "test_validator.py") or ""

    if not validation_contents or not test_contents:
        missing = []
        if not validation_contents:
            missing.append("validator.py")
        if not test_contents:
            missing.append("test_validator.py")
        raise LocalAgentExecutionError(f"Local agent did not generate {', '.join(missing)}.")

    return validation_contents, test_contents


def _run_agent_once(
    agent_name: LocalAgentName,
    workdir: Path,
    prompt: str,
    timeout_seconds: int,
) -> tuple[str, str, str]:
    output_path = workdir / "agent-summary.txt"
    command = _build_agent_command(agent_name, workdir, output_path)

    completed = subprocess.run(
        command,
        cwd=workdir,
        input=prompt,
        text=True,
        capture_output=True,
        timeout=timeout_seconds,
        check=False,
    )

    output = "\n".join(part for part in [completed.stdout, completed.stderr] if part)
    if output_path.exists():
        output = "\n".join(part for part in [output_path.read_text(), output] if part)

    if completed.returncode != 0:
        raise LocalAgentExecutionError(
            f"{agent_name} exited with code {completed.returncode}.\n\n{output.strip()}"
        )

    validation_contents, test_contents = _read_generated_files(workdir, output)
    return output.strip(), validation_contents, test_contents


def create_validator_with_local_agent(
    user_code: str,
    requirements: str | None,
    agent_name: LocalAgentName,
    *,
    max_attempts: int = 2,
    timeout_seconds: int = 600,
) -> LocalAgentResult:
    """Create an AST validator by running an installed local CLI agent."""
    previous_failure: str | None = None

    with tempfile.TemporaryDirectory(prefix="determystic_agent_") as temp_dir:
        workdir = Path(temp_dir)

        for attempt in range(1, max_attempts + 1):
            prompt = _build_prompt(user_code, requirements, previous_failure)
            summary, validation_contents, test_contents = _run_agent_once(
                agent_name=agent_name,
                workdir=workdir,
                prompt=prompt,
                timeout_seconds=timeout_seconds,
            )

            with IsolatedEnv() as env:
                tests_passed, test_output = env.run_tests(
                    validator_code=validation_contents,
                    test_code=test_contents,
                )

            if tests_passed:
                return LocalAgentResult(
                    summary=summary or f"{agent_name} generated a validator.",
                    validation_contents=validation_contents,
                    test_contents=test_contents,
                    tests_passed=True,
                    test_output=test_output,
                )

            previous_failure = (
                f"Attempt {attempt} generated files, but their tests failed:\n\n{test_output}"
            )

        raise LocalAgentExecutionError(previous_failure or "Local agent failed to generate a validator.")


async def stream_create_validator_with_local_agent(
    user_code: str,
    requirements: str | None,
    agent_name: LocalAgentName,
) -> AsyncGenerator[StreamEvent, None]:
    """Stream coarse progress events while a local CLI agent creates a validator."""
    deps = AgentDependencies()

    yield StreamEvent(
        event_type="user_prompt",
        content=f"Creating validator with local {agent_name} agent",
        deps=deps,
    )
    yield StreamEvent(
        event_type="model_request_start",
        content=f"{agent_name} is generating validator files...",
        deps=deps,
    )

    result = await asyncio.to_thread(
        create_validator_with_local_agent,
        user_code,
        requirements,
        agent_name,
    )

    deps.validation_contents = result.validation_contents
    deps.test_contents = result.test_contents

    yield StreamEvent(
        event_type="tool_call_end",
        content="Generated validator tests passed in the isolated environment.",
        deps=deps,
    )
    yield StreamEvent(
        event_type="final_result",
        content=result.summary,
        deps=deps,
    )
