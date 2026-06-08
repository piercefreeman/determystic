"""Shared project path filtering for validators."""

from fnmatch import fnmatchcase
from pathlib import Path


TEST_PATH_PARTS = {"tests", "__tests__"}
GLOB_CHARS = {"*", "?", "["}


def iter_python_files(
    project_root: Path,
    ignore_paths: list[str] | tuple[str, ...] | None = None,
    *,
    include_tests: bool = True,
    include_ignored: bool = False,
    isolation_paths: list[str] | tuple[str, ...] | None = None,
) -> list[Path]:
    """Return Python files that are visible to validators."""
    return [
        py_file
        for py_file in project_root.rglob("*.py")
        if _is_relevant_python_file(py_file)
        and not is_ignored_path(py_file, project_root, isolation_paths)
        and (
            include_ignored
            or not is_ignored_path(py_file, project_root, ignore_paths)
        )
        and (include_tests or not is_test_file(py_file))
    ]


def is_ignored_path(
    path: Path,
    project_root: Path,
    ignore_paths: list[str] | tuple[str, ...] | None,
) -> bool:
    """Return whether a project-relative path matches an ignore entry."""
    return _is_ignored_path(path, project_root, ignore_paths)


def is_test_file(path: Path) -> bool:
    """Return whether a path is a Python test file or under a test directory."""
    return (
        path.name.startswith("test_")
        or path.name.endswith("_test.py")
        or any(part in TEST_PATH_PARTS for part in path.parts)
    )


def _is_relevant_python_file(path: Path) -> bool:
    """Return whether a Python file should be considered before config ignores."""
    return (
        not any(part.startswith(".") for part in path.parts)
        and "__pycache__" not in path.parts
    )


def _is_ignored_path(
    path: Path,
    project_root: Path,
    ignore_paths: list[str] | tuple[str, ...] | None,
) -> bool:
    """Return whether a project-relative path matches an ignore entry."""
    if not ignore_paths:
        return False

    try:
        relative_path = path.resolve().relative_to(project_root.resolve())
    except ValueError:
        return False

    relative = relative_path.as_posix()
    return any(
        _matches_ignore_pattern(relative, ignore_path)
        for ignore_path in ignore_paths
        if ignore_path.strip()
    )


def _matches_ignore_pattern(relative_path: str, ignore_path: str) -> bool:
    pattern = _normalize_ignore_pattern(ignore_path)
    if not pattern:
        return False

    if any(char in pattern for char in GLOB_CHARS):
        return fnmatchcase(relative_path, pattern)

    return relative_path == pattern or relative_path.startswith(f"{pattern}/")


def _normalize_ignore_pattern(ignore_path: str) -> str:
    pattern = ignore_path.strip().replace("\\", "/")
    while pattern.startswith("./"):
        pattern = pattern[2:]
    if pattern.startswith("/"):
        pattern = pattern[1:]
    return pattern.rstrip("/")
