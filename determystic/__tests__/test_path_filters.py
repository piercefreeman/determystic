"""Tests for shared path filtering."""

from determystic.path_filters import is_ignored_path, iter_python_files


def test_is_ignored_path_matches_project_relative_files_and_directories(tmp_path) -> None:
    """Project-relative file and directory ignore entries match expected paths."""
    generated_file = tmp_path / "generated" / "client.py"
    generated_file.parent.mkdir()
    generated_file.write_text("value = 1")
    target_file = tmp_path / "service.py"
    target_file.write_text("value = 1")

    assert is_ignored_path(generated_file, tmp_path, ["generated/"])
    assert is_ignored_path(target_file, tmp_path, ["service.py"])
    assert not is_ignored_path(target_file, tmp_path, ["generated/"])


def test_iter_python_files_respects_ignore_paths_and_test_filter(tmp_path) -> None:
    """Python file discovery applies hidden, test, and configured path filters."""
    (tmp_path / "service.py").write_text("value = 1")
    (tmp_path / "test_service.py").write_text("value = 1")
    generated_dir = tmp_path / "generated"
    generated_dir.mkdir()
    (generated_dir / "client.py").write_text("value = 1")
    hidden_dir = tmp_path / ".cache"
    hidden_dir.mkdir()
    (hidden_dir / "hidden.py").write_text("value = 1")

    files = {
        file.relative_to(tmp_path).as_posix()
        for file in iter_python_files(
            tmp_path,
            ["generated/"],
            include_tests=False,
        )
    }

    assert files == {"service.py"}
