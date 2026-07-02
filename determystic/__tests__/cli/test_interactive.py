"""Tests for shared interactive console helpers."""

from unittest.mock import patch

import pytest

from determystic.agents.create_validator import AgentDependencies, StreamEvent
from determystic.cli.interactive import get_multiline_input, render_agent_stream


# determystic: tested-exceptions[determystic.cli.interactive.get_multiline_input: EOFError, KeyboardInterrupt]
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
            "determystic.cli.interactive.PromptSession",
            return_value=FailingSession(exception),
        ):
            assert await get_multiline_input("Paste code") == ""


@pytest.mark.asyncio
async def test_render_agent_stream_returns_final_event() -> None:
    """The renderer prints all events and returns the final_result event."""
    deps = AgentDependencies()

    async def fake_events():
        yield StreamEvent(event_type="user_prompt", content="starting", deps=deps)
        yield StreamEvent(event_type="tool_call_end", content="tests passed", deps=deps)
        yield StreamEvent(event_type="final_result", content="done", deps=deps)

    with patch("determystic.cli.interactive.console.print") as mock_print:
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

    with patch("determystic.cli.interactive.console.print"):
        assert await render_agent_stream(fake_events()) is None
