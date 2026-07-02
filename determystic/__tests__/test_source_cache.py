"""Tests for the shared source file cache."""

from pathlib import Path

from determystic.source_cache import SourceFile, SourceFileCache


def test_get_files_reads_and_parses_project_files(tmp_path: Path) -> None:
    """Files are walked, read, and parsed with project-relative paths."""
    (tmp_path / "module.py").write_text("value = 1\n")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "other.py").write_text("def helper():\n    return 2\n")

    cache = SourceFileCache()
    source_files = cache.get_files(tmp_path)

    assert [source_file.relative_path for source_file in source_files] == [
        "module.py",
        "nested/other.py",
    ]
    assert all(source_file.content is not None for source_file in source_files)
    assert all(source_file.tree is not None for source_file in source_files)
    assert all(source_file.read_error is None for source_file in source_files)


def test_get_files_returns_same_objects_for_repeat_lookups(tmp_path: Path) -> None:
    """Repeated lookups with the same filters share one walked file list."""
    (tmp_path / "module.py").write_text("value = 1\n")

    cache = SourceFileCache()
    first = cache.get_files(tmp_path, ["ignored_dir"])
    second = cache.get_files(tmp_path, ["ignored_dir"])

    assert first is second


def test_get_files_distinguishes_filter_combinations(tmp_path: Path) -> None:
    """Different path filters produce independently cached file lists."""
    (tmp_path / "module.py").write_text("value = 1\n")
    (tmp_path / "extra").mkdir()
    (tmp_path / "extra" / "other.py").write_text("value = 2\n")

    cache = SourceFileCache()
    unfiltered = cache.get_files(tmp_path)
    filtered = cache.get_files(tmp_path, ["extra"])

    assert len(unfiltered) == 2
    assert len(filtered) == 1


# determystic: tested-exceptions[determystic.source_cache.SourceFile.tree: SyntaxError]
def test_tree_is_none_for_syntax_errors(tmp_path: Path) -> None:
    """A file that fails to parse exposes a None tree but keeps its content."""
    (tmp_path / "broken.py").write_text("def broken(:\n")

    cache = SourceFileCache()
    source_files = cache.get_files(tmp_path)

    assert len(source_files) == 1
    broken = source_files[0]
    assert broken.content is not None
    assert broken.tree is None
    # Suppressions still resolve (to an empty-range table) without raising.
    assert not broken.suppressions.suppresses(1, "anything")


def test_tree_is_parsed_once_and_shared(tmp_path: Path) -> None:
    """The parsed tree is computed lazily and reused on later accesses."""
    (tmp_path / "module.py").write_text("value = 1\n")

    cache = SourceFileCache()
    source_file = cache.get_files(tmp_path)[0]

    assert source_file.tree is source_file.tree


# determystic: tested-exceptions[determystic.source_cache.SourceFileCache._load_files: Exception]
def test_unreadable_files_surface_read_errors(tmp_path: Path) -> None:
    """Files that cannot be decoded report a read error instead of raising."""
    (tmp_path / "binary.py").write_bytes(b"\xff\xfe\x00bad utf8\x00")

    cache = SourceFileCache()
    source_files = cache.get_files(tmp_path)

    assert len(source_files) == 1
    unreadable = source_files[0]
    assert unreadable.content is None
    assert unreadable.read_error is not None
    assert unreadable.suppressions.suppresses(1, "anything") is False


def test_suppressions_are_available_for_parsed_files(tmp_path: Path) -> None:
    """Suppression comments are honored through the cached view."""
    (tmp_path / "module.py").write_text(
        "def helper():  # determystic: ignore\n    return 1\n"
    )

    cache = SourceFileCache()
    source_file = cache.get_files(tmp_path)[0]

    assert source_file.suppressions.suppresses(1, "custom_validator")


def test_source_file_without_content_has_empty_suppressions() -> None:
    """A read-error file exposes empty suppressions rather than raising."""
    source_file = SourceFile(
        path=Path("missing.py"),
        relative_path="missing.py",
        read_error="boom",
    )

    assert source_file.tree is None
    assert source_file.suppressions.suppresses(1, "all") is False
