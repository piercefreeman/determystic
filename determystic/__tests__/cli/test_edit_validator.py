"""Tests for the interactive edit-validator command."""

from pathlib import Path
from types import SimpleNamespace
from typing import Awaitable, Callable, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from determystic.agents.create_validator import AgentDependencies, StreamEvent
from determystic.agents.local_agent import LocalAgentSelectionError
from determystic.cli.edit_validator import edit_validator_command
from determystic.configs.project import ValidatorFile


async def _invoke_edit_validator_command(name: str | None = None) -> None:
    callback = edit_validator_command.callback
    assert callback is not None
    async_callback = cast(
        Callable[[str | None, object | None], Awaitable[None]],
        getattr(callback, "__wrapped__"),
    )
    await async_callback(name, None)


def _make_config(tmp_path: Path, **overrides) -> SimpleNamespace:
    validator_path = tmp_path / "validator.determystic"
    validator_path.write_text("# existing validator")
    test_path = tmp_path / "test.determystic"
    test_path.write_text("# existing tests")

    validator_file = ValidatorFile(
        name="custom",
        validator_path=str(validator_path),
        test_path=str(test_path),
        description="Existing description",
    )

    config = SimpleNamespace(
        settings=SimpleNamespace(validator_agent="codex"),
        get_custom_validators=MagicMock(return_value={"custom": validator_file}),
        resolve_project_path=lambda path: Path(path),
        update_validation=MagicMock(return_value=validator_file),
        save_to_disk=MagicMock(),
    )
    for key, value in overrides.items():
        setattr(config, key, value)
    return config


# determystic: tested-exceptions[determystic.cli.edit_validator.edit_validator_command: LocalAgentSelectionError]
@pytest.mark.asyncio
async def test_edit_validator_command_exits_when_agent_selection_fails(tmp_path: Path) -> None:
    """Local agent selection failures are shown before exiting."""
    config = _make_config(tmp_path)

    with (
        patch("determystic.cli.edit_validator.ProjectConfigManager.load_from_disk", return_value=config),
        patch(
            "determystic.cli.edit_validator.select_local_agent",
            side_effect=LocalAgentSelectionError("codex unavailable"),
        ),
        patch("determystic.cli.edit_validator.sys.exit", side_effect=SystemExit(1)) as mock_exit,
        patch("determystic.cli.edit_validator.console.print") as mock_print,
    ):
        with pytest.raises(SystemExit):
            await _invoke_edit_validator_command()

    mock_exit.assert_called_once_with(1)
    assert "codex unavailable" in str(mock_print.call_args_list)


@pytest.mark.asyncio
async def test_edit_validator_command_exits_without_custom_validators() -> None:
    """Projects without custom validators cannot enter the edit workflow."""
    config = SimpleNamespace(
        settings=SimpleNamespace(validator_agent="codex"),
        get_custom_validators=MagicMock(return_value={}),
    )

    with (
        patch("determystic.cli.edit_validator.ProjectConfigManager.load_from_disk", return_value=config),
        patch("determystic.cli.edit_validator.sys.exit", side_effect=SystemExit(1)) as mock_exit,
        patch("determystic.cli.edit_validator.console.print") as mock_print,
    ):
        with pytest.raises(SystemExit):
            await _invoke_edit_validator_command()

    mock_exit.assert_called_once_with(1)
    panel = mock_print.call_args_list[0].args[0]
    assert "No custom validators found" in str(panel.renderable)


@pytest.mark.asyncio
async def test_edit_validator_command_rejects_unknown_validator(tmp_path: Path) -> None:
    """An unknown validator name lists the available validators before exiting."""
    config = _make_config(tmp_path)

    with (
        patch("determystic.cli.edit_validator.ProjectConfigManager.load_from_disk", return_value=config),
        patch("determystic.cli.edit_validator.select_local_agent", return_value="codex"),
        patch("determystic.cli.edit_validator.sys.exit", side_effect=SystemExit(1)) as mock_exit,
        patch("determystic.cli.edit_validator.console.print") as mock_print,
    ):
        with pytest.raises(SystemExit):
            await _invoke_edit_validator_command("unknown")

    mock_exit.assert_called_once_with(1)
    printed = str(mock_print.call_args_list)
    assert "not found" in printed
    assert "custom" in printed


@pytest.mark.asyncio
async def test_edit_validator_command_saves_updated_files(tmp_path: Path) -> None:
    """A successful agent run updates the validator files and saves the config."""
    config = _make_config(tmp_path)
    deps = AgentDependencies()
    deps.validation_contents = "updated validator"
    deps.test_contents = "updated tests"

    captured_kwargs: dict = {}

    def fake_stream_edit_validator_with_local_agent(**kwargs):
        captured_kwargs.update(kwargs)

        async def events():
            yield StreamEvent(event_type="final_result", content="done", deps=deps)

        return events()

    with (
        patch("determystic.cli.edit_validator.ProjectConfigManager.load_from_disk", return_value=config),
        patch("determystic.cli.edit_validator.select_local_agent", return_value="codex"),
        patch("determystic.cli.edit_validator.get_multiline_input", new=AsyncMock(return_value="also flag Union")),
        patch("determystic.cli.edit_validator.Prompt.ask", return_value="y"),
        patch(
            "determystic.cli.edit_validator.stream_edit_validator_with_local_agent",
            new=fake_stream_edit_validator_with_local_agent,
        ),
        patch("determystic.cli.edit_validator.console.print"),
    ):
        await _invoke_edit_validator_command("custom")

    assert captured_kwargs["validator_name"] == "custom"
    assert captured_kwargs["change_request"] == "also flag Union"
    assert captured_kwargs["validation_contents"] == "# existing validator"
    assert captured_kwargs["test_contents"] == "# existing tests"
    assert captured_kwargs["description"] == "Existing description"

    config.update_validation.assert_called_once_with(
        name="custom",
        validator_script="updated validator",
        test_script="updated tests",
    )
    config.save_to_disk.assert_called_once()


# determystic: tested-exceptions[determystic.cli.edit_validator.edit_validator_command: Exception]
@pytest.mark.asyncio
async def test_edit_validator_command_reports_save_errors(tmp_path: Path) -> None:
    """Update failures are reported without crashing."""
    config = _make_config(
        tmp_path,
        update_validation=MagicMock(side_effect=RuntimeError("disk full")),
    )
    deps = AgentDependencies()
    deps.validation_contents = "updated validator"
    deps.test_contents = "updated tests"

    async def fake_stream_edit_validator_with_local_agent(*args, **kwargs):
        yield StreamEvent(event_type="final_result", content="done", deps=deps)

    with (
        patch("determystic.cli.edit_validator.ProjectConfigManager.load_from_disk", return_value=config),
        patch("determystic.cli.edit_validator.select_local_agent", return_value="codex"),
        patch("determystic.cli.edit_validator.get_multiline_input", new=AsyncMock(return_value="also flag Union")),
        patch("determystic.cli.edit_validator.Prompt.ask", return_value="y"),
        patch(
            "determystic.cli.edit_validator.stream_edit_validator_with_local_agent",
            new=fake_stream_edit_validator_with_local_agent,
        ),
        patch("determystic.cli.edit_validator.console.print") as mock_print,
    ):
        await _invoke_edit_validator_command("custom")

    config.save_to_disk.assert_not_called()
    assert "Error saving validator files: disk full" in str(mock_print.call_args_list)
