"""Tests for shared determystic suppression comments."""

import ast

from determystic.suppressions import SuppressionComments


def test_line_suppression_applies_to_same_and_next_line() -> None:
    """A line suppression supports same-line and preceding-line comments."""
    suppressions = SuppressionComments.from_source(
        "\n".join(
            [
                "value = 1  # determystic: ignore[unreachable-code]",
                "next_value = 2",
            ]
        )
    )

    assert suppressions.suppresses(1, "unreachable-code")
    assert suppressions.suppresses(2, "unreachable-code")
    assert not suppressions.suppresses(2, "unused-function")


def test_definition_suppression_applies_to_function_body() -> None:
    """A suppression on or above a definition applies to its whole source range."""
    source = "\n".join(
        [
            "# determystic: ignore[dead-code]",
            "def generated(value):",
            "    return 1",
            "    print(value)",
        ]
    )
    suppressions = SuppressionComments.from_source(source, ast.parse(source))

    assert suppressions.suppresses(2, "unused-function")
    assert suppressions.suppresses(4, "unreachable-code")
    assert not suppressions.suppresses(4, "function-order")


def test_block_suppression_applies_until_matching_end() -> None:
    """Block comments suppress matching issue groups across a source range."""
    source = "\n".join(
        [
            "# determystic: ignore-start[function-visibility]",
            "def helper():",
            "    return 1",
            "def public_api():",
            "    return helper()",
            "# determystic: ignore-end[function-visibility]",
            "def later():",
            "    return 2",
        ]
    )
    suppressions = SuppressionComments.from_source(source)

    assert suppressions.suppresses(2, "private-prefix")
    assert suppressions.suppresses(4, "function-order")
    assert not suppressions.suppresses(7, "private-prefix")


def test_used_suppression_is_limited_to_unused_findings() -> None:
    """The convenience `used` marker should not hide unrelated lint rules."""
    suppressions = SuppressionComments.from_source("def public_api():  # determystic: used\n    pass")

    assert suppressions.suppresses(1, "unused-function")
    assert not suppressions.suppresses(1, "function-order")
