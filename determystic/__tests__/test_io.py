"""Tests for IO utilities."""

import subprocess
import sys
import types
from unittest.mock import patch

import pytest

from determystic.io import detect_git_root, get_determystic_package_path


# determystic: tested-exceptions[determystic.io.detect_git_root: CalledProcessError, FileNotFoundError]
def test_detect_git_root_handles_git_lookup_failures(tmp_path) -> None:
    """Git discovery returns None when git fails or is unavailable."""
    with patch(
        "determystic.io.subprocess.run",
        side_effect=subprocess.CalledProcessError(1, ["git"]),
    ):
        assert detect_git_root(tmp_path) is None

    with patch(
        "determystic.io.subprocess.run",
        side_effect=FileNotFoundError("git"),
    ):
        assert detect_git_root(tmp_path) is None


# determystic: tested-exceptions[determystic.io.get_determystic_package_path: ImportError, AttributeError]
def test_get_determystic_package_path_reports_resolution_errors() -> None:
    """Package path resolution wraps import and module shape failures."""
    with patch.dict(sys.modules, {"determystic": None}):
        with pytest.raises(RuntimeError, match="Unable to resolve"):
            get_determystic_package_path()

    fake_module = types.ModuleType("determystic")
    with patch.dict(sys.modules, {"determystic": fake_module}):
        with pytest.raises(RuntimeError, match="Unable to resolve"):
            get_determystic_package_path()
