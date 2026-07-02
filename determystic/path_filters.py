"""Shared project path filtering for validators."""

import os
from fnmatch import fnmatchcase
from pathlib import Path


TEST_PATH_PARTS = {"tests", "__tests__"}
GLOB_CHARS = {"*", "?", "["}


def iter_python_files(
    project_root: Path,
    ignore_paths: list[str] | tuple[str, ...] | None = None,
    *,
    include_paths: list[str] | tuple[str, ...] | None = None,
    include_tests: bool = True,
    include_ignored: bool = False,
    isolation_paths: list[str] | tuple[str, ...] | None = None,
) -> list[Path]:
    """Return Python files that are visible to validators."""
    root = project_root
    if any(part.startswith(".") for part in root.parts) or "__pycache__" in root.parts:
        return []

    ignore = _clean_patterns(ignore_paths)
    include = _clean_patterns(include_paths)
    isolation = _clean_patterns(isolation_paths)

    # Non-glob patterns match a path and everything beneath it, so directories
    # they match can be skipped without descending into them. Glob patterns are
    # still evaluated per file below.
    prune_prefixes = set(_non_glob_patterns(isolation))
    if not include_ignored:
        prune_prefixes.update(_non_glob_patterns(ignore))

    python_files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        relative_dir = os.path.relpath(dirpath, root).replace(os.sep, "/")
        if relative_dir == ".":
            relative_dir = ""

        dirnames[:] = [
            dirname
            for dirname in dirnames
            if not dirname.startswith(".")
            and dirname != "__pycache__"
            and not _is_pruned_dir(
                f"{relative_dir}/{dirname}" if relative_dir else dirname,
                prune_prefixes,
            )
        ]

        for filename in filenames:
            if not filename.endswith(".py") or filename.startswith("."):
                continue
            relative = f"{relative_dir}/{filename}" if relative_dir else filename
            if _matches_patterns(relative, isolation):
                continue
            if not include_ignored:
                if _matches_patterns(relative, ignore):
                    continue
                if include and not _matches_patterns(relative, include):
                    continue
            path = Path(dirpath) / filename
            if not include_tests and is_test_file(path):
                continue
            python_files.append(path)

    python_files.sort()
    return python_files


def is_ignored_path(
    path: Path,
    project_root: Path,
    ignore_paths: list[str] | tuple[str, ...] | None,
    *,
    include_paths: list[str] | tuple[str, ...] | None = None,
) -> bool:
    """Return whether a path is excluded, or outside the include list when one is set."""
    if _matches_any_pattern(path, project_root, ignore_paths):
        return True
    if include_paths:
        return not _matches_any_pattern(path, project_root, include_paths)
    return False


def matches_path_pattern(relative_path: str, pattern: str) -> bool:
    """Return whether a project-relative posix path matches a config path entry."""
    return _matches_ignore_pattern(relative_path, pattern)


def is_test_file(path: Path) -> bool:
    """Return whether a path is a Python test file or under a test directory."""
    return (
        path.name.startswith("test_")
        or path.name.endswith("_test.py")
        or any(part in TEST_PATH_PARTS for part in path.parts)
    )


def _clean_patterns(
    patterns: list[str] | tuple[str, ...] | None,
) -> tuple[str, ...]:
    if not patterns:
        return ()
    return tuple(pattern for pattern in patterns if pattern.strip())


def _non_glob_patterns(patterns: tuple[str, ...]) -> list[str]:
    normalized = (_normalize_ignore_pattern(pattern) for pattern in patterns)
    return [
        pattern
        for pattern in normalized
        if pattern and not any(char in pattern for char in GLOB_CHARS)
    ]


def _is_pruned_dir(relative_dir: str, prune_prefixes: set[str]) -> bool:
    return any(
        relative_dir == prefix or relative_dir.startswith(f"{prefix}/")
        for prefix in prune_prefixes
    )


def _matches_patterns(relative_path: str, patterns: tuple[str, ...]) -> bool:
    return any(_matches_ignore_pattern(relative_path, pattern) for pattern in patterns)


def _matches_any_pattern(
    path: Path,
    project_root: Path,
    patterns: list[str] | tuple[str, ...] | None,
) -> bool:
    """Return whether a project-relative path matches any config path entry."""
    if not patterns:
        return False

    try:
        relative_path = path.resolve().relative_to(project_root.resolve())
    except ValueError:
        return False

    relative = relative_path.as_posix()
    return any(
        _matches_ignore_pattern(relative, pattern)
        for pattern in patterns
        if pattern.strip()
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
