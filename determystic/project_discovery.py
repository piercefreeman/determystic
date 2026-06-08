"""Project and workspace discovery for validation scopes."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any

from determystic.io import detect_pyproject_path


SKIPPED_PROJECT_DIR_NAMES = {
    ".git",
    ".hg",
    ".mypy_cache",
    ".nox",
    ".pytest_cache",
    ".ruff_cache",
    ".svn",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "env",
    "node_modules",
    "venv",
}


@dataclass(frozen=True)
class ValidationTarget:
    """One isolated project scope to validate."""

    project_root: Path
    config_path: Path
    extra_ignore_paths: tuple[str, ...] = ()

    @property
    def label(self) -> str:
        return self.project_root.name or str(self.project_root)


def discover_validation_targets(start_path: Path) -> list[ValidationTarget]:
    """Discover isolated project scopes for a path."""
    start = start_path.resolve()
    if start.is_file():
        start = start.parent

    if not start.exists():
        return []

    root_pyproject = start / "pyproject.toml"
    if root_pyproject.exists():
        workspace_targets = _discover_uv_workspace_targets(start, root_pyproject)
        if workspace_targets:
            return workspace_targets

        pyproject_paths = _find_pyproject_paths(start)
        if len(pyproject_paths) > 1:
            inherited_config_path = (
                root_pyproject if _has_determystic_config(root_pyproject) else None
            )
            return _targets_from_pyprojects(
                pyproject_paths,
                inherited_config_path=inherited_config_path,
            )

        return [
            ValidationTarget(
                project_root=start,
                config_path=_config_path_for_single_project(root_pyproject),
            )
        ]

    child_pyproject_paths = _find_pyproject_paths(start)
    if child_pyproject_paths:
        return _targets_from_pyprojects(child_pyproject_paths)

    detected_root = detect_pyproject_path(start)
    if detected_root is None:
        return []

    return [
        ValidationTarget(
            project_root=detected_root,
            config_path=_config_path_for_single_project(
                detected_root / "pyproject.toml"
            ),
        )
    ]


def _discover_uv_workspace_targets(
    workspace_root: Path,
    pyproject_path: Path,
) -> list[ValidationTarget]:
    data = _load_pyproject(pyproject_path)
    workspace = data.get("tool", {}).get("uv", {}).get("workspace")
    if not isinstance(workspace, dict):
        return []

    members = _string_list(workspace.get("members"))
    if not members:
        return []

    exclude = _string_list(workspace.get("exclude"))
    member_roots = [
        path
        for member_pattern in members
        for path in _glob_project_dirs(workspace_root, member_pattern)
        if not _is_excluded_workspace_member(path, workspace_root, exclude)
    ]
    return _targets_from_project_roots(
        [workspace_root, *member_roots],
        inherited_config_path=(
            pyproject_path if _has_determystic_config(pyproject_path) else None
        ),
    )


def _targets_from_pyprojects(
    pyproject_paths: list[Path],
    *,
    inherited_config_path: Path | None = None,
) -> list[ValidationTarget]:
    return _targets_from_project_roots(
        [pyproject_path.parent for pyproject_path in pyproject_paths],
        inherited_config_path=inherited_config_path,
    )


def _targets_from_project_roots(
    project_roots: list[Path],
    *,
    inherited_config_path: Path | None = None,
) -> list[ValidationTarget]:
    unique_roots = sorted({root.resolve() for root in project_roots})
    targets: list[ValidationTarget] = []

    for project_root in unique_roots:
        pyproject_path = project_root / "pyproject.toml"
        nested_roots = [
            other_root
            for other_root in unique_roots
            if other_root != project_root and _is_relative_to(other_root, project_root)
        ]
        extra_ignore_paths = tuple(
            _relative_posix_path(nested_root, project_root)
            for nested_root in nested_roots
        )
        config_path = _config_path_for_project(
            pyproject_path,
            inherited_config_path,
        )
        targets.append(
            ValidationTarget(
                project_root=project_root,
                config_path=config_path,
                extra_ignore_paths=extra_ignore_paths,
            )
        )

    return targets


def _config_path_for_project(
    pyproject_path: Path,
    inherited_config_path: Path | None,
) -> Path:
    if inherited_config_path is None:
        return pyproject_path
    if pyproject_path.resolve() == inherited_config_path.resolve():
        return pyproject_path
    if _has_determystic_config(pyproject_path):
        return pyproject_path
    return inherited_config_path


def _config_path_for_single_project(pyproject_path: Path) -> Path:
    if _has_determystic_config(pyproject_path):
        return pyproject_path

    containing_workspace_config_path = _find_containing_uv_workspace_config(
        pyproject_path.parent
    )
    if containing_workspace_config_path is None:
        return pyproject_path
    if not _has_determystic_config(containing_workspace_config_path):
        return pyproject_path
    return containing_workspace_config_path


def _find_containing_uv_workspace_config(project_root: Path) -> Path | None:
    current = project_root.parent
    while current != current.parent:
        pyproject_path = current / "pyproject.toml"
        if pyproject_path.exists() and _uv_workspace_includes_project(
            current,
            pyproject_path,
            project_root,
        ):
            return pyproject_path
        current = current.parent
    return None


def _uv_workspace_includes_project(
    workspace_root: Path,
    pyproject_path: Path,
    project_root: Path,
) -> bool:
    data = _load_pyproject(pyproject_path)
    workspace = data.get("tool", {}).get("uv", {}).get("workspace")
    if not isinstance(workspace, dict):
        return False

    members = _string_list(workspace.get("members"))
    if not members:
        return False

    excluded = _is_excluded_workspace_member(
        project_root,
        workspace_root,
        _string_list(workspace.get("exclude")),
    )
    if excluded:
        return False

    resolved_project_root = project_root.resolve()
    return any(
        member_root == resolved_project_root
        for member_pattern in members
        for member_root in _glob_project_dirs(workspace_root, member_pattern)
    )


def _find_pyproject_paths(root: Path) -> list[Path]:
    pyproject_paths: list[Path] = []
    for path in root.rglob("pyproject.toml"):
        if _has_skipped_part(path.relative_to(root)):
            continue
        pyproject_paths.append(path.resolve())
    return sorted(pyproject_paths)


def _glob_project_dirs(root: Path, pattern: str) -> list[Path]:
    return sorted(
        path.resolve()
        for path in root.glob(pattern)
        if path.is_dir()
        and not _has_skipped_part(path.relative_to(root))
        and (path / "pyproject.toml").exists()
    )


def _is_excluded_workspace_member(
    path: Path,
    workspace_root: Path,
    exclude_patterns: list[str],
) -> bool:
    if not exclude_patterns:
        return False

    relative_path = _relative_posix_path(path, workspace_root)
    return any(
        _matches_workspace_glob(relative_path, pattern)
        for pattern in exclude_patterns
    )


def _matches_workspace_glob(relative_path: str, pattern: str) -> bool:
    normalized_pattern = _normalize_workspace_pattern(pattern)
    if not normalized_pattern:
        return False
    return (
        fnmatchcase(relative_path, normalized_pattern)
        or fnmatchcase(f"{relative_path}/", f"{normalized_pattern}/")
    )


def _normalize_workspace_pattern(pattern: str) -> str:
    normalized = pattern.strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    if normalized.startswith("/"):
        normalized = normalized[1:]
    return normalized.rstrip("/")


def _has_determystic_config(pyproject_path: Path) -> bool:
    data = _load_pyproject(pyproject_path)
    return isinstance(data.get("tool", {}).get("determystic"), dict)


def _load_pyproject(pyproject_path: Path) -> dict[str, Any]:
    try:
        with pyproject_path.open("rb") as file:
            return tomllib.load(file)
    except (FileNotFoundError, tomllib.TOMLDecodeError):
        return {}


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item.strip()]


def _has_skipped_part(path: Path) -> bool:
    return any(part in SKIPPED_PROJECT_DIR_NAMES for part in path.parts)


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _relative_posix_path(path: Path, parent: Path) -> str:
    return path.relative_to(parent).as_posix()
