"""Tests for local CLI agent selection and execution."""

from pathlib import Path
from unittest.mock import patch

import pytest

from determystic.agents.local_agent import (
    LocalAgentExecutionError,
    LocalAgentSelectionError,
    _external_interface,
    _build_edit_prompt,
    _build_prompt,
    _create_validator_with_local_agent,
    _edit_validator_with_local_agent,
    select_local_agent,
    _read_generated_files,
)


def test_auto_selects_codex_when_available() -> None:
    """Auto mode should prefer Codex when both CLIs are installed."""

    def fake_which(command: str) -> str | None:
        return f"/usr/local/bin/{command}" if command in {"codex", "claude"} else None

    assert select_local_agent("auto", which=fake_which) == "codex"


def test_auto_falls_back_to_claude() -> None:
    """Auto mode should use Claude when Codex is unavailable."""

    def fake_which(command: str) -> str | None:
        return "/usr/local/bin/claude" if command == "claude" else None

    assert select_local_agent("auto", which=fake_which) == "claude"


def test_explicit_preference_requires_installed_agent() -> None:
    """A configured preference should not silently fall back to another agent."""

    def fake_which(command: str) -> str | None:
        return "/usr/local/bin/claude" if command == "claude" else None

    assert select_local_agent("claude", which=fake_which) == "claude"
    with pytest.raises(LocalAgentSelectionError, match="codex"):
        select_local_agent("codex", which=fake_which)


def test_read_generated_files_from_workspace(tmp_path: Path) -> None:
    """Generated files should be read directly from the temporary workspace."""
    (tmp_path / "validator.py").write_text("from determystic.external import DeterministicTraverser\n")
    (tmp_path / "test_validator.py").write_text("def test_validator():\n    assert True\n")

    validator, tests = _read_generated_files(tmp_path)

    assert "DeterministicTraverser" in validator
    assert "def test_validator" in tests


def test_read_generated_files_requires_workspace_files(tmp_path: Path) -> None:
    """Local agents must write both generated files to the temporary workspace."""
    (tmp_path / "validator.py").write_text("from determystic.external import DeterministicTraverser\n")

    with pytest.raises(LocalAgentExecutionError, match="test_validator.py"):
        _read_generated_files(tmp_path)


def test_build_prompt_uses_local_cli_instructions() -> None:
    """The local prompt should not depend on Pydantic-agent tool instructions."""
    with patch("determystic.agents.local_agent._external_interface", return_value="class X: pass"):
        prompt = _build_prompt(
            user_code="value = None",
            requirements="detect None assignment",
            previous_failure="tests failed",
        )

    assert "Create exactly these two files" in prompt
    assert "Ensure the tests are executable by pytest" in prompt
    assert "fallback fenced blocks" not in prompt
    assert "read_external_file" not in prompt
    assert "Run the tests to ensure everything works correctly" not in prompt
    assert "tests failed" in prompt


# determystic: tested-exceptions[determystic.agents.local_agent._external_interface: OSError]
def test_external_interface_handles_read_errors() -> None:
    """The prompt builder can tolerate a missing external interface file."""
    with patch("pathlib.Path.read_text", side_effect=OSError("missing")):
        assert _external_interface() == ""


def test_create_validator_with_local_agent_retries_failed_tests() -> None:
    """The local runner should give the CLI one repair attempt when tests fail."""
    with patch("determystic.agents.local_agent._run_agent_once") as mock_run_agent:
        mock_run_agent.side_effect = [
            ("summary", "bad validator", "bad tests"),
            ("fixed summary", "good validator", "good tests"),
        ]

        with patch("determystic.agents.local_agent.IsolatedEnv") as mock_env:
            env = mock_env.return_value.__enter__.return_value
            env.run_tests.side_effect = [
                (False, "tests failed"),
                (True, "tests passed"),
            ]

            result = _create_validator_with_local_agent(
                user_code="x = 1",
                requirements="detect x",
                agent_name="codex",
            )

    assert result.summary == "fixed summary"
    assert result.validation_contents == "good validator"
    assert result.test_contents == "good tests"
    assert result.tests_passed is True
    assert mock_run_agent.call_count == 2


def test_build_edit_prompt_describes_existing_workspace() -> None:
    """The edit prompt should describe in-place edits to the seeded files."""
    with patch("determystic.agents.local_agent._external_interface", return_value="class X: pass"):
        prompt = _build_edit_prompt(
            validator_name="no-optional",
            change_request="also flag typing.Union[X, None]",
            description="Disallow Optional type hints",
            previous_failure="tests failed",
        )

    assert "Edit the existing AST validator 'no-optional'" in prompt
    assert "already contains an existing validator" in prompt
    assert "also flag typing.Union[X, None]" in prompt
    assert "Disallow Optional type hints" in prompt
    assert "Create exactly these two files" not in prompt
    assert "tests failed" in prompt


def test_edit_validator_with_local_agent_seeds_existing_files() -> None:
    """The edit runner should write the current files into the agent workspace."""
    seeded_files: dict[str, str] = {}

    def fake_run_agent_once(agent_name, workdir, prompt, timeout_seconds):
        seeded_files["validator.py"] = (workdir / "validator.py").read_text()
        seeded_files["test_validator.py"] = (workdir / "test_validator.py").read_text()
        return "edit summary", "updated validator", "updated tests"

    with patch("determystic.agents.local_agent._run_agent_once", side_effect=fake_run_agent_once):
        with patch("determystic.agents.local_agent.IsolatedEnv") as mock_env:
            env = mock_env.return_value.__enter__.return_value
            env.run_tests.return_value = (True, "tests passed")

            result = _edit_validator_with_local_agent(
                validator_name="no-optional",
                change_request="also flag Union",
                validation_contents="original validator",
                test_contents="original tests",
                agent_name="codex",
            )

    assert seeded_files["validator.py"] == "original validator"
    assert seeded_files["test_validator.py"] == "original tests"
    assert result.summary == "edit summary"
    assert result.validation_contents == "updated validator"
    assert result.test_contents == "updated tests"
    assert result.tests_passed is True


def test_edit_validator_with_local_agent_retries_failed_tests() -> None:
    """The edit runner should give the CLI one repair attempt when tests fail."""
    with patch("determystic.agents.local_agent._run_agent_once") as mock_run_agent:
        mock_run_agent.side_effect = [
            ("summary", "bad validator", "bad tests"),
            ("fixed summary", "good validator", "good tests"),
        ]

        with patch("determystic.agents.local_agent.IsolatedEnv") as mock_env:
            env = mock_env.return_value.__enter__.return_value
            env.run_tests.side_effect = [
                (False, "tests failed"),
                (True, "tests passed"),
            ]

            result = _edit_validator_with_local_agent(
                validator_name="no-optional",
                change_request="also flag Union",
                validation_contents="original validator",
                test_contents="original tests",
                agent_name="codex",
            )

    assert result.summary == "fixed summary"
    assert result.validation_contents == "good validator"
    assert result.tests_passed is True
    assert mock_run_agent.call_count == 2
    retry_prompt = mock_run_agent.call_args_list[1].kwargs["prompt"]
    assert "tests failed" in retry_prompt


def test_edit_validator_with_local_agent_raises_after_exhausted_attempts() -> None:
    """The edit runner should surface the last failure once attempts run out."""
    with patch("determystic.agents.local_agent._run_agent_once") as mock_run_agent:
        mock_run_agent.return_value = ("summary", "bad validator", "bad tests")

        with patch("determystic.agents.local_agent.IsolatedEnv") as mock_env:
            env = mock_env.return_value.__enter__.return_value
            env.run_tests.return_value = (False, "tests failed")

            with pytest.raises(LocalAgentExecutionError, match="tests failed"):
                _edit_validator_with_local_agent(
                    validator_name="no-optional",
                    change_request="also flag Union",
                    validation_contents="original validator",
                    test_contents="original tests",
                    agent_name="codex",
                )
