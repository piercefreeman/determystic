"""Tests for the interactive new-validator command."""

from types import SimpleNamespace
from typing import Awaitable, Callable, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from determystic.agents.create_validator import AgentDependencies, StreamEvent
from determystic.agents.local_agent import LocalAgentSelectionError
from determystic.cli.new_validator import _get_multiline_input, new_validator_command


async def _invoke_new_validator_command() -> None:
    callback = new_validator_command.callback
    assert callback is not None
    async_callback = cast(
        Callable[[object | None], Awaitable[None]],
        getattr(callback, "__wrapped__"),
    )
    await async_callback(None)


# determystic: tested-exceptions[determystic.cli.new_validator.new_validator_command: LocalAgentSelectionError]
@pytest.mark.asyncio
async def test_new_validator_command_exits_when_agent_selection_fails() -> None:
    """Local agent selection failures are shown before exiting."""
    config = SimpleNamespace(settings=SimpleNamespace(validator_agent="codex"))

    with (
        patch("determystic.cli.new_validator.ProjectConfigManager.load_from_disk", return_value=config),
        patch(
            "determystic.cli.new_validator.select_local_agent",
            side_effect=LocalAgentSelectionError("codex unavailable"),
        ),
        patch("determystic.cli.new_validator.sys.exit", side_effect=SystemExit(1)) as mock_exit,
        patch("determystic.cli.new_validator.console.print") as mock_print,
    ):
        with pytest.raises(SystemExit):
            await _invoke_new_validator_command()

    mock_exit.assert_called_once_with(1)
    assert "codex unavailable" in str(mock_print.call_args_list[0])


# determystic: tested-exceptions[determystic.cli.new_validator.new_validator_command: Exception]
@pytest.mark.asyncio
async def test_new_validator_command_reports_save_errors() -> None:
    """Generated validator save failures are reported without crashing."""
    config = SimpleNamespace(
        settings=SimpleNamespace(validator_agent="codex"),
        validators={},
        new_validation=MagicMock(side_effect=RuntimeError("disk full")),
        save_to_disk=MagicMock(),
    )
    deps = AgentDependencies()
    deps.validation_contents = "validator code"
    deps.test_contents = "test code"

    async def fake_stream_create_validator_with_local_agent(*args, **kwargs):
        yield StreamEvent(event_type="final_result", content="done", deps=deps)

    with (
        patch("determystic.cli.new_validator.ProjectConfigManager.load_from_disk", return_value=config),
        patch("determystic.cli.new_validator.select_local_agent", return_value="codex"),
        patch("determystic.cli.new_validator._get_multiline_input", new=AsyncMock(return_value="bad code")),
        patch(
            "determystic.cli.new_validator.Prompt.ask",
            side_effect=["detect bad code", "save-error-validator", "y"],
        ),
        patch(
            "determystic.cli.new_validator.stream_create_validator_with_local_agent",
            new=fake_stream_create_validator_with_local_agent,
        ),
        patch("determystic.cli.new_validator.console.print") as mock_print,
    ):
        await _invoke_new_validator_command()

    config.save_to_disk.assert_not_called()
    assert "Error saving validator files: disk full" in str(mock_print.call_args_list)


# determystic: tested-exceptions[determystic.cli.new_validator._get_multiline_input: EOFError, KeyboardInterrupt]
@pytest.mark.asyncio
async def test_get_multiline_input_handles_terminal_interrupts() -> None:
    """Prompt interruption returns an empty string."""

    class FailingSession:
        def __init__(self, exception: BaseException) -> None:
            self.exception = exception

        async def prompt_async(self):
            raise self.exception

    for exception in (EOFError(), KeyboardInterrupt()):
        with patch(
            "determystic.cli.new_validator.PromptSession",
            return_value=FailingSession(exception),
        ):
            assert await _get_multiline_input("Paste code") == ""
