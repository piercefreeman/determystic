"""Tests for shared CLI validator selection helpers."""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from determystic.cli.common import get_active_validators
from determystic.configs.project import ProjectConfigManager


@pytest.fixture(autouse=True)
def reset_project_config_state():
    """Reset project config path state before each selection test."""
    ProjectConfigManager._found_path = None
    ProjectConfigManager.runtime_custom_path = None
    yield
    ProjectConfigManager._found_path = None
    ProjectConfigManager.runtime_custom_path = None


def _with_project_config(config: ProjectConfigManager) -> list[str]:
    with tempfile.TemporaryDirectory() as temp_dir:
        config_file = Path(temp_dir) / "pyproject.toml"
        config_file.write_text("")
        with patch.object(ProjectConfigManager, "get_possible_config_paths", return_value=[config_file]):
            return [validator.name for validator in get_active_validators(config)]


def test_bundled_validators_are_disabled_by_default() -> None:
    """Bundled validators should not run unless explicitly enabled."""
    active_names = _with_project_config(ProjectConfigManager())

    assert active_names == []


def test_enabled_bundled_validators_are_active() -> None:
    """A bundled validator can be enabled by its config name."""
    active_names = _with_project_config(ProjectConfigManager(enabled=["static_analysis"]))

    assert active_names == ["static_analysis", "static_analysis"]


def test_enabled_accepts_display_names_and_wildcard() -> None:
    """Bundled validators can be selected by display names or an explicit wildcard."""
    display_name_active = _with_project_config(ProjectConfigManager(enabled=["Function Visibility"]))
    wildcard_active = _with_project_config(ProjectConfigManager(enabled=["all"]))

    assert display_name_active == ["function_visibility"]
    assert wildcard_active == [
        "static_analysis",
        "static_analysis",
        "hanging_functions",
        "function_visibility",
        "exception_coverage",
    ]


def test_exclude_overrides_enabled_bundled_validators() -> None:
    """The legacy exclude list still suppresses enabled bundled validators."""
    active_names = _with_project_config(
        ProjectConfigManager(
            enabled=["static_analysis", "function_visibility"],
            exclude=["Static Analysis"],
        )
    )

    assert active_names == ["function_visibility"]


def test_custom_validators_are_active_by_default() -> None:
    """Project-authored validators should run without being listed in enabled."""
    with tempfile.TemporaryDirectory() as temp_dir:
        project_root = Path(temp_dir)
        config_file = project_root / "pyproject.toml"
        config_file.write_text("")
        validator_path = project_root / ".determystic" / "validations" / "custom.determystic"
        validator_path.parent.mkdir(parents=True)
        validator_path.write_text(
            "\n".join(
                [
                    "from determystic.external import DeterministicTraverser",
                    "",
                    "class CustomTraverser(DeterministicTraverser):",
                    "    pass",
                ]
            )
        )
        config = ProjectConfigManager()

        with patch.object(ProjectConfigManager, "get_possible_config_paths", return_value=[config_file]):
            active_names = [validator.name for validator in get_active_validators(config)]

    assert active_names == ["custom"]
