"""Tests for the shared CLI UI primitives."""

from unittest.mock import patch

import pytest
from prompt_toolkit.keys import Keys

from determystic.agents.create_validator import AgentDependencies, StreamEvent
from determystic.cli.ui import (
    _editing_key_bindings,
    confirm,
    multiline_input,
    render_agent_stream,
    select_option,
    text_input,
)


class _FailingQuestion:
    def __init__(self, exception: BaseException) -> None:
        self.exception = exception

    async def unsafe_ask_async(self):
        raise self.exception


# determystic: tested-exceptions[determystic.cli.ui.multiline_input: EOFError, KeyboardInterrupt]
@pytest.mark.asyncio
async def test_multiline_input_handles_terminal_interrupts() -> None:
    """Prompt interruption returns an empty string."""

    class FailingSession:
        def __init__(self, exception: BaseException) -> None:
            self.exception = exception

        async def prompt_async(self):
            raise self.exception

    for exception in (EOFError(), KeyboardInterrupt()):
        with (
            patch("determystic.cli.ui.PromptSession", return_value=FailingSession(exception)),
            patch("determystic.cli.ui.console.print"),
        ):
            assert await multiline_input("Paste code") == ""


# determystic: tested-exceptions[determystic.cli.ui.text_input: EOFError, KeyboardInterrupt]
@pytest.mark.asyncio
async def test_text_input_exits_quietly_on_interrupt() -> None:
    """Interrupting a single-line prompt exits with the conventional code 130."""

    class FailingSession:
        async def prompt_async(self):
            raise KeyboardInterrupt()

    with (
        patch("determystic.cli.ui.PromptSession", return_value=FailingSession()),
        patch("determystic.cli.ui.console.print"),
    ):
        with pytest.raises(SystemExit) as exc_info:
            await text_input("Name")

    assert exc_info.value.code == 130


@pytest.mark.asyncio
async def test_text_input_falls_back_to_default_on_empty_submission() -> None:
    """An empty submission returns the default value."""

    class EmptySession:
        async def prompt_async(self):
            return "   "

    with (
        patch("determystic.cli.ui.PromptSession", return_value=EmptySession()),
        patch("determystic.cli.ui.console.print"),
    ):
        assert await text_input("Name", default="custom_validator") == "custom_validator"


# determystic: tested-exceptions[determystic.cli.ui.select_option: EOFError, KeyboardInterrupt]
@pytest.mark.asyncio
async def test_select_option_exits_quietly_on_interrupt() -> None:
    """Interrupting the selection menu exits with the conventional code 130."""
    for exception in (EOFError(), KeyboardInterrupt()):
        with (
            patch("determystic.cli.ui.questionary.select", return_value=_FailingQuestion(exception)),
            patch("determystic.cli.ui.console.print"),
        ):
            with pytest.raises(SystemExit) as exc_info:
                await select_option("Pick one", [("a", None)])

        assert exc_info.value.code == 130


# determystic: tested-exceptions[determystic.cli.ui.confirm: EOFError, KeyboardInterrupt]
@pytest.mark.asyncio
async def test_confirm_exits_quietly_on_interrupt() -> None:
    """Interrupting a confirmation exits with the conventional code 130."""
    for exception in (EOFError(), KeyboardInterrupt()):
        with (
            patch("determystic.cli.ui.questionary.confirm", return_value=_FailingQuestion(exception)),
            patch("determystic.cli.ui.console.print"),
        ):
            with pytest.raises(SystemExit) as exc_info:
                await confirm("Proceed?")

        assert exc_info.value.code == 130


def test_editing_key_bindings_support_word_navigation() -> None:
    """Option/ctrl + arrow keys are bound to word jumps."""
    bindings = _editing_key_bindings()

    assert bindings.get_bindings_for_keys((Keys.Escape, Keys.Left))
    assert bindings.get_bindings_for_keys((Keys.Escape, Keys.Right))
    assert bindings.get_bindings_for_keys((Keys.ControlLeft,))
    assert bindings.get_bindings_for_keys((Keys.ControlRight,))


@pytest.mark.asyncio
async def test_render_agent_stream_returns_final_event() -> None:
    """The renderer prints all events and returns the final_result event."""
    deps = AgentDependencies()

    async def fake_events():
        yield StreamEvent(event_type="user_prompt", content="starting", deps=deps)
        yield StreamEvent(event_type="tool_call_end", content="tests passed", deps=deps)
        yield StreamEvent(event_type="final_result", content="done", deps=deps)

    with patch("determystic.cli.ui.console.print") as mock_print:
        final_event = await render_agent_stream(fake_events())

    assert final_event is not None
    assert final_event.content == "done"
    printed = str(mock_print.call_args_list)
    assert "starting" in printed
    assert "tests passed" in printed


@pytest.mark.asyncio
async def test_render_agent_stream_without_final_event() -> None:
    """Streams that never produce a final_result return None."""
    deps = AgentDependencies()

    async def fake_events():
        yield StreamEvent(event_type="user_prompt", content="starting", deps=deps)

    with patch("determystic.cli.ui.console.print"):
        assert await render_agent_stream(fake_events()) is None
