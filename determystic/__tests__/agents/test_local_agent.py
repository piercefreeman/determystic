"""Tests for local CLI agent selection and execution."""

from pathlib import Path
from unittest.mock import patch

import pytest

from determystic.agents.local_agent import (
    LocalAgentSelectionError,
    create_validator_with_local_agent,
    get_local_agent_preference,
    normalize_local_agent_preference,
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


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [
        (None, "auto"),
        ("", "auto"),
        ("auto", "auto"),
        ("Codex", "codex"),
        (" claude ", "claude"),
    ],
)
def test_normalize_local_agent_preference(raw_value: object, expected: str) -> None:
    """Project settings should accept simple string preferences."""
    assert normalize_local_agent_preference(raw_value) == expected


def test_get_local_agent_preference_uses_validator_agent_key() -> None:
    """The documented validator_agent key should take precedence."""
    assert get_local_agent_preference({"validator_agent": "codex", "agent": "claude"}) == "codex"
    assert get_local_agent_preference({"agent": "claude"}) == "claude"


def test_read_generated_files_from_workspace(tmp_path: Path) -> None:
    """Generated files should be read directly from the temporary workspace."""
    (tmp_path / "validator.py").write_text("from determystic.external import DeterministicTraverser\n")
    (tmp_path / "test_validator.py").write_text("def test_validator():\n    assert True\n")

    validator, tests = _read_generated_files(tmp_path, "")

    assert "DeterministicTraverser" in validator
    assert "def test_validator" in tests


def test_read_generated_files_from_fenced_fallback(tmp_path: Path) -> None:
    """Fallback fenced blocks should be accepted when file writes are unavailable."""
    output = """
```validator.py
from determystic.external import DeterministicTraverser
```
```test_validator.py
def test_validator():
    assert True
```
"""

    validator, tests = _read_generated_files(tmp_path, output)

    assert "DeterministicTraverser" in validator
    assert "def test_validator" in tests


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

            result = create_validator_with_local_agent(
                user_code="x = 1",
                requirements="detect x",
                agent_name="codex",
            )

    assert result.summary == "fixed summary"
    assert result.validation_contents == "good validator"
    assert result.test_contents == "good tests"
    assert result.tests_passed is True
    assert mock_run_agent.call_count == 2
