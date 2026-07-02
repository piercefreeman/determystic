"""Shared visual language and interactive primitives for the determystic CLI.

Every command renders through this module so the CLI feels like one coherent
tool: a single accent color, consistent glyphs, prompt_toolkit-backed inputs
with real line editing (word jumps, kill-word, paste), and questionary-backed
arrow-key menus.
"""

import sys
from typing import AsyncGenerator, NoReturn

import questionary
from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.lexers import PygmentsLexer
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.styles import Style as PtStyle
from pygments.lexers import PythonLexer # type: ignore
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text
from rich.theme import Theme

from determystic.agents.create_validator import StreamEvent

ACCENT = "#a78bfa"
SUCCESS = "#34d399"
ERROR = "#f87171"
WARNING = "#fbbf24"
MUTED = "#8b8fa3"

# Rich resolves theme names only as exact matches, so compound styles
# ("accent" + bold) need their own entries.
THEME = Theme({
    "accent": ACCENT,
    "accent.bold": f"bold {ACCENT}",
    "success": SUCCESS,
    "success.bold": f"bold {SUCCESS}",
    "error": ERROR,
    "error.bold": f"bold {ERROR}",
    "warning": WARNING,
    "warning.bold": f"bold {WARNING}",
    "muted": MUTED,
    "muted.bold": f"bold {MUTED}",
    "muted.italic": f"italic {MUTED}",
})

console = Console(theme=THEME)

PROMPT_STYLE = PtStyle.from_dict({
    "prompt": f"{ACCENT} bold",
    "placeholder": f"{MUTED} italic",
    "bottom-toolbar": f"noreverse {MUTED}",
})

QUESTIONARY_STYLE = questionary.Style([
    ("qmark", f"fg:{ACCENT} bold"),
    ("question", "bold"),
    ("answer", f"fg:{ACCENT}"),
    ("pointer", f"fg:{ACCENT} bold"),
    ("highlighted", f"fg:{ACCENT} bold"),
    ("selected", f"fg:{ACCENT}"),
    ("instruction", f"fg:{MUTED}"),
    ("desc", f"fg:{MUTED} italic"),
])


def banner(command: str, subtitle: str | None = None) -> None:
    """Print the one-line app header every command starts with."""
    header = Text()
    header.append("◆ ", style="accent")
    header.append("determystic", style="bold")
    header.append(f" {command}", style="muted")
    console.print(header)
    if subtitle:
        console.print(Text(f"  {subtitle}", style="muted"))
    console.print()


def section(title: str, step: str | None = None) -> None:
    """Print a step heading, e.g. `1/3 Paste the problematic code`."""
    heading = Text()
    if step:
        heading.append(f"{step} ", style="accent.bold")
    heading.append(title, style="bold")
    console.print()
    console.print(heading)


def success(message: str) -> None:
    console.print(Text.assemble(("✓ ", "success.bold"), (message, "bold")))


def error(message: str) -> None:
    console.print(Text.assemble(("✗ ", "error.bold"), (message, "error")))


def warning(message: str) -> None:
    console.print(Text.assemble(("! ", "warning.bold"), (message, "warning")))


def hint(message: str) -> None:
    console.print(Text(f"  {message}", style="muted"))


def detail(label: str, value: str) -> None:
    """Print an aligned key/value summary line."""
    console.print(Text.assemble(("  ", ""), (f"{label:<12}", "muted"), (value, "")))


def code_block(code: str, title: str | None = None, line_numbers: bool = False) -> None:
    """Render Python code in a subtle rounded frame on the terminal background."""
    syntax = Syntax(
        code,
        "python",
        theme="ansi_dark",
        background_color="default",
        line_numbers=line_numbers,
    )
    console.print(Panel(
        syntax,
        box=box.ROUNDED,
        border_style="grey35",
        title=title,
        title_align="left",
        padding=(0, 1),
    ))


async def text_input(
    label: str,
    *,
    description: str | None = None,
    placeholder: str | None = None,
    default: str = "",
    password: bool = False,
) -> str:
    """Single-line input with full line editing (option+arrows, kill-word, paste).

    An empty submission falls back to `default`, which is shown as the
    placeholder when no explicit placeholder is given.
    """
    _print_input_label(label, description)

    shown_placeholder = placeholder or default or None
    session: PromptSession[str] = PromptSession(
        message=[("class:prompt", "❯ ")],
        style=PROMPT_STYLE,
        key_bindings=_editing_key_bindings(),
        placeholder=(
            FormattedText([("class:placeholder", shown_placeholder)])
            if shown_placeholder
            else None
        ),
        is_password=password,
    )

    try:
        with patch_stdout():
            result = await session.prompt_async()
    except (EOFError, KeyboardInterrupt):
        _exit_cancelled()

    return result.strip() or default


async def multiline_input(label: str, *, description: str | None = None) -> str:
    """Multiline input with bracketed paste support.

    Submits on a double Enter (an empty line following an empty line); returns
    an empty string if the user interrupts the prompt.
    """
    _print_input_label(label, description)

    session: PromptSession[str] = PromptSession(
        message=[("class:prompt", "❯ ")],
        style=PROMPT_STYLE,
        multiline=True,
        key_bindings=_multiline_key_bindings(),
        prompt_continuation=[("class:placeholder", "· ")],
        enable_history_search=False,
        mouse_support=True,
        lexer=PygmentsLexer(PythonLexer),  # Python syntax highlighting
        bottom_toolbar=FormattedText([
            ("class:bottom-toolbar", " enter twice to submit · paste is supported"),
        ]),
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


async def select_option(
    label: str,
    choices: list[tuple[str, str | None]],
) -> str:
    """Arrow-key selection menu; each choice is a (value, description) pair."""
    q_choices = []
    for value, description in choices:
        title: list[tuple[str, str]] = [("class:text", value)]
        if description:
            title.append(("class:desc", f"  {description}"))
        q_choices.append(questionary.Choice(title=title, value=value))

    try:
        answer = await questionary.select(
            label,
            choices=q_choices,
            style=QUESTIONARY_STYLE,
            qmark="◆",
            pointer="❯",
            instruction=" ",
        ).unsafe_ask_async()
    except (EOFError, KeyboardInterrupt):
        _exit_cancelled()

    return answer


async def confirm(label: str, *, default: bool = True) -> bool:
    """y/n confirmation styled to match the rest of the CLI."""
    try:
        answer = await questionary.confirm(
            label,
            default=default,
            style=QUESTIONARY_STYLE,
            qmark="◆",
        ).unsafe_ask_async()
    except (EOFError, KeyboardInterrupt):
        _exit_cancelled()

    return bool(answer)


async def render_agent_stream(
    events: AsyncGenerator[StreamEvent, None],
) -> StreamEvent | None:
    """Render agent stream events to the console and return the final event."""
    final_event: StreamEvent | None = None
    async for event in events:
        if event.event_type == 'user_prompt':
            console.print(Text.assemble(("● ", "accent"), (event.content, "")))
        elif event.event_type == 'model_request_start':
            console.print(Text(event.content, style="muted.italic"))
        elif event.event_type == 'text_chunk':
            # Print text chunks as they arrive
            console.print(event.content, end="")
        elif event.event_type == 'tool_processing_start':
            console.print(Text(event.content, style="muted"))
        elif event.event_type == 'tool_call_start':
            console.print(Text(f"  → {event.content}", style="muted"))
        elif event.event_type == 'tool_call_end':
            console.print(Text.assemble(("  ✓ ", "success"), (event.content, "muted")))
        elif event.event_type == 'final_result':
            console.print()
            success(event.content)
            final_event = event
    return final_event


def _exit_cancelled() -> NoReturn:
    """Leave quietly when the user interrupts an interactive prompt."""
    console.print(Text("cancelled", style="muted"))
    sys.exit(130)


def _print_input_label(label: str, description: str | None) -> None:
    console.print()
    console.print(Text(label, style="bold"))
    if description:
        console.print(Text(description, style="muted"))


def _editing_key_bindings() -> KeyBindings:
    """Word-navigation bindings so option/ctrl + arrows behave like a modern editor."""
    bindings = KeyBindings()

    @bindings.add("escape", "left")
    @bindings.add("c-left")
    def _(event):
        """Jump to the beginning of the previous word."""
        buffer = event.current_buffer
        position = buffer.document.find_previous_word_beginning(count=event.arg)
        if position:
            buffer.cursor_position += position

    @bindings.add("escape", "right")
    @bindings.add("c-right")
    def _(event):
        """Jump to the end of the next word."""
        buffer = event.current_buffer
        position = buffer.document.find_next_word_ending(count=event.arg)
        if position:
            buffer.cursor_position += position

    return bindings


def _multiline_key_bindings() -> KeyBindings:
    """Multiline editing: word navigation plus double-Enter submission."""
    bindings = _editing_key_bindings()

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

    return bindings
