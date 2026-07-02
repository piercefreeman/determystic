"""Shared interactive console helpers for agent-backed CLI commands."""

from typing import AsyncGenerator

from rich.console import Console
from prompt_toolkit import PromptSession
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.lexers import PygmentsLexer
from pygments.lexers import PythonLexer # type: ignore
from prompt_toolkit.patch_stdout import patch_stdout

from determystic.agents.create_validator import StreamEvent

console = Console()


async def get_multiline_input(prompt_text: str) -> str:
    """Get multiline input from the user with bracketed paste support.

    This function properly handles pasted content with multiple newlines
    by using prompt_toolkit's built-in bracketed paste support.

    Args:
        prompt_text: The prompt to display

    Returns:
        The user's multiline input
    """
    console.print(f"\n[bold cyan]{prompt_text}[/bold cyan]")
    console.print("[dim]You can paste code directly (even with multiple newlines).[/dim]")
    console.print("[dim]Press Enter twice (empty line) to finish input:[/dim]\n")

    # Create key bindings for double enter submission
    bindings = KeyBindings()

    @bindings.add('enter')
    def _(event):
        """Handle Enter key - submit if current line is empty and previous line was also empty."""
        buffer = event.current_buffer

        # Get current line content
        current_line = buffer.document.current_line

        # If current line is empty, check if we should submit
        if not current_line.strip():
            # Get all text and split into lines
            all_text = buffer.document.text
            lines = all_text.split('\n')

            # If we have at least one line and the last line is empty
            if len(lines) >= 2 and not lines[-1].strip():
                # Check if previous line was also empty (double enter condition)
                if not lines[-2].strip():
                    # Submit the input by accepting the buffer
                    buffer.validate_and_handle()
                    return

        # Otherwise, just insert a newline
        buffer.insert_text('\n')

    # Create a prompt session
    session = PromptSession(
        message="> ",
        multiline=True,
        key_bindings=bindings,
        enable_history_search=False,
        mouse_support=True,
        lexer=PygmentsLexer(PythonLexer),  # Python syntax highlighting
        # Bracketed paste is enabled by default in prompt_toolkit
        # It automatically handles pasted content properly
    )

    try:
        # Use async prompt session to avoid event loop conflicts
        with patch_stdout():
            result = await session.prompt_async()
        # Handle case where result is None (when user exits via our custom key binding)
        if result is None:
            return ""
        return result.strip()
    except (EOFError, KeyboardInterrupt):
        # Handle Ctrl+D, Ctrl+C gracefully
        return ""


async def render_agent_stream(
    events: AsyncGenerator[StreamEvent, None],
) -> StreamEvent | None:
    """Render agent stream events to the console and return the final event."""
    final_event: StreamEvent | None = None
    async for event in events:
        if event.event_type == 'user_prompt':
            console.print(f"[bold blue]📝 {event.content}[/bold blue]")
        elif event.event_type == 'model_request_start':
            console.print(f"[bold yellow]{event.content}[/bold yellow]")
        elif event.event_type == 'text_chunk':
            # Print text chunks as they arrive
            console.print(event.content, end="", style="white")
        elif event.event_type == 'tool_processing_start':
            console.print(f"\n[bold cyan]{event.content}[/bold cyan]")
        elif event.event_type == 'tool_call_start':
            console.print(f"[cyan]🔧 Calling {event.content}[/cyan]")
        elif event.event_type == 'tool_call_end':
            console.print(f"[green]{event.content}[/green]")
        elif event.event_type == 'final_result':
            console.print(f"\n[bold green]{event.content}[/bold green]")
            final_event = event
    return final_event
