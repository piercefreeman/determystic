"""Tests for the external validator interface."""

from determystic.external import DeterministicTraverser


# determystic: tested-exceptions[determystic.external.DeterministicTraverser.validate: SyntaxError]
def test_deterministic_traverser_validate_reports_syntax_errors() -> None:
    """Syntax errors are converted into validation issues."""
    traverser = DeterministicTraverser("def broken(:\n")

    result = traverser.validate()

    assert not result.is_valid
    assert result.issues is not None
    assert len(result.issues) == 1
    assert "Syntax error" in result.issues[0].message
