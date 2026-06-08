"""Tests for project and workspace discovery."""

from pathlib import Path

from determystic.project_discovery import (
    _is_relative_to,
    _load_pyproject,
    discover_validation_targets,
)


def test_discovers_uv_workspace_members_with_inherited_root_config(tmp_path) -> None:
    """uv workspace members inherit root determystic config unless they define one."""
    (tmp_path / "pyproject.toml").write_text(
        """
[project]
name = "root"

[tool.determystic]
enabled = ["all"]

[tool.uv.workspace]
members = ["packages/*"]
exclude = ["packages/skipped"]
"""
    )
    _write_pyproject(tmp_path / "packages" / "api", "api")
    (tmp_path / "packages" / "raw").mkdir(parents=True)
    _write_pyproject(tmp_path / "packages" / "worker", "worker")
    _write_pyproject(tmp_path / "packages" / "skipped", "skipped")

    targets = discover_validation_targets(tmp_path)

    target_map = {
        target.project_root.relative_to(tmp_path).as_posix(): target
        for target in targets
    }
    assert set(target_map) == {
        ".",
        "packages/api",
        "packages/raw",
        "packages/worker",
    }
    assert target_map["packages/api"].config_path == tmp_path / "pyproject.toml"
    assert target_map["packages/raw"].config_path == tmp_path / "pyproject.toml"
    assert target_map["packages/worker"].config_path == tmp_path / "pyproject.toml"
    assert target_map["."].extra_ignore_paths == (
        "packages/api",
        "packages/raw",
        "packages/worker",
    )


def test_uv_workspace_member_config_overrides_inherited_root_config(tmp_path) -> None:
    """Workspace members with determystic config use their local pyproject."""
    (tmp_path / "pyproject.toml").write_text(
        """
[project]
name = "root"

[tool.determystic]
enabled = ["all"]

[tool.uv.workspace]
members = ["packages/*"]
exclude = ["standalone-tool"]
"""
    )
    member_root = tmp_path / "packages" / "api"
    member_root.mkdir(parents=True)
    (member_root / "pyproject.toml").write_text(
        """
[project]
name = "api"

[tool.determystic]
enabled = ["hanging_functions"]
"""
    )

    targets = discover_validation_targets(tmp_path)

    api_target = next(target for target in targets if target.project_root == member_root)
    assert api_target.config_path == member_root / "pyproject.toml"


def test_uv_workspace_root_also_discovers_nested_project_markers(tmp_path) -> None:
    """uv metadata is merged with other nested Python project markers."""
    (tmp_path / "pyproject.toml").write_text(
        """
[project]
name = "root"

[tool.determystic]
enabled = ["all"]

[tool.uv.workspace]
members = ["packages/*"]
exclude = ["standalone-tool"]
"""
    )
    (tmp_path / "packages" / "worker").mkdir(parents=True)
    _write_pyproject(tmp_path / "standalone-tool", "standalone-tool")
    _write_setup_py(tmp_path / "services" / "worker-service")

    targets = discover_validation_targets(tmp_path)

    target_map = {
        target.project_root.relative_to(tmp_path).as_posix(): target
        for target in targets
    }
    assert set(target_map) == {
        ".",
        "standalone-tool",
        "packages/worker",
        "services/worker-service",
    }
    assert all(target.config_path == tmp_path / "pyproject.toml" for target in target_map.values())
    assert target_map["."].extra_ignore_paths == (
        "packages/worker",
        "services/worker-service",
        "standalone-tool",
    )


def test_uv_workspace_member_path_inherits_root_config(tmp_path) -> None:
    """Validating a member directly can still use workspace root determystic config."""
    (tmp_path / "pyproject.toml").write_text(
        """
[project]
name = "root"

[tool.determystic]
enabled = ["all"]

[tool.uv.workspace]
members = ["packages/*"]
"""
    )
    member_root = tmp_path / "packages" / "api"
    package_dir = member_root / "src" / "api"
    package_dir.mkdir(parents=True)
    (member_root / "pyproject.toml").write_text("[project]\nname = \"api\"\n")

    member_targets = discover_validation_targets(member_root)
    package_targets = discover_validation_targets(package_dir)

    for targets in (member_targets, package_targets):
        assert len(targets) == 1
        assert targets[0].project_root == member_root
        assert targets[0].config_path == tmp_path / "pyproject.toml"


def test_discovers_non_uv_nested_pyprojects_as_isolated_targets(tmp_path) -> None:
    """Nested pyprojects are validated independently outside uv workspaces too."""
    (tmp_path / "pyproject.toml").write_text(
        """
[project]
name = "root"

[tool.determystic]
enabled = ["all"]
"""
    )
    _write_pyproject(tmp_path / "services" / "api", "api")
    _write_pyproject(tmp_path / "libs" / "shared", "shared")
    _write_setup_py(tmp_path / "services" / "worker")

    targets = discover_validation_targets(tmp_path)

    target_map = {
        target.project_root.relative_to(tmp_path).as_posix(): target
        for target in targets
    }
    assert set(target_map) == {
        ".",
        "libs/shared",
        "services/api",
        "services/worker",
    }
    assert target_map["services/api"].config_path == tmp_path / "pyproject.toml"
    assert target_map["libs/shared"].config_path == tmp_path / "pyproject.toml"
    assert target_map["services/worker"].config_path == tmp_path / "pyproject.toml"
    assert target_map["."].extra_ignore_paths == (
        "libs/shared",
        "services/api",
        "services/worker",
    )


def test_discovers_child_projects_when_requested_path_has_no_pyproject(tmp_path) -> None:
    """A repository root without pyproject can still contain isolated projects."""
    _write_pyproject(tmp_path / "apps" / "web", "web")
    _write_pyproject(tmp_path / "apps" / "worker", "worker")

    targets = discover_validation_targets(tmp_path)

    assert [
        target.project_root.relative_to(tmp_path).as_posix()
        for target in targets
    ] == ["apps/web", "apps/worker"]
    assert all(
        target.config_path == target.project_root / "pyproject.toml"
        for target in targets
    )


def test_discovers_nearest_project_for_path_inside_project(tmp_path) -> None:
    """A normal nested path still resolves to its containing project."""
    project_root = tmp_path / "project"
    package_dir = project_root / "src" / "example"
    package_dir.mkdir(parents=True)
    (project_root / "pyproject.toml").write_text("[project]\nname = \"example\"\n")

    targets = discover_validation_targets(package_dir)

    assert len(targets) == 1
    assert targets[0].project_root == project_root
    assert targets[0].config_path == project_root / "pyproject.toml"


# determystic: tested-exceptions[determystic.project_discovery._load_pyproject: FileNotFoundError, tomllib.TOMLDecodeError]
def test_load_pyproject_returns_empty_data_for_missing_or_invalid_toml(tmp_path) -> None:
    """Pyproject loading failures are treated as absent config."""
    assert _load_pyproject(tmp_path / "missing" / "pyproject.toml") == {}

    invalid_pyproject = tmp_path / "pyproject.toml"
    invalid_pyproject.write_text("[project\n")

    assert _load_pyproject(invalid_pyproject) == {}


# determystic: tested-exceptions[determystic.project_discovery._is_relative_to: ValueError]
def test_is_relative_to_returns_false_for_unrelated_paths(tmp_path) -> None:
    """Path containment checks return false for unrelated paths."""
    assert not _is_relative_to(tmp_path / "first", tmp_path / "second")


def _write_pyproject(project_root: Path, name: str) -> None:
    project_root.mkdir(parents=True)
    (project_root / "pyproject.toml").write_text(f"[project]\nname = \"{name}\"\n")


def _write_setup_py(project_root: Path) -> None:
    project_root.mkdir(parents=True)
    (project_root / "setup.py").write_text("from setuptools import setup\nsetup()\n")
