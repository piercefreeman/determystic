"""Tests for shared path filtering."""

from determystic.path_filters import (
    _matches_any_pattern,
    is_ignored_path,
    iter_python_files,
)


def test_matches_any_pattern_matches_project_relative_files_and_directories(tmp_path) -> None:
    """Project-relative file and directory ignore entries match expected paths."""
    generated_file = tmp_path / "generated" / "client.py"
    generated_file.parent.mkdir()
    generated_file.write_text("value = 1")
    target_file = tmp_path / "service.py"
    target_file.write_text("value = 1")

    assert _matches_any_pattern(generated_file, tmp_path, ["generated/"])
    assert _matches_any_pattern(target_file, tmp_path, ["service.py"])
    assert not _matches_any_pattern(target_file, tmp_path, ["generated/"])


# determystic: tested-exceptions[determystic.path_filters._matches_any_pattern: ValueError]
def test_matches_any_pattern_returns_false_for_paths_outside_project(tmp_path) -> None:
    """Paths outside the project are not considered ignored."""
    outside_path = tmp_path.parent / "outside.py"

    assert not _matches_any_pattern(outside_path, tmp_path, ["outside.py"])


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


def test_iter_python_files_can_include_ignored_reference_sources(tmp_path) -> None:
    """Validators can include ignored files when they only need references."""
    (tmp_path / "service.py").write_text("value = 1")
    generated_dir = tmp_path / "generated"
    generated_dir.mkdir()
    (generated_dir / "client.py").write_text("value = 1")

    files = {
        file.relative_to(tmp_path).as_posix()
        for file in iter_python_files(
            tmp_path,
            ["generated/"],
            include_ignored=True,
        )
    }

    assert files == {"generated/client.py", "service.py"}


def test_iter_python_files_include_paths_allowlist(tmp_path) -> None:
    """Only files under include entries are visible, and excludes win on overlap."""
    api_dir = tmp_path / "api"
    api_dir.mkdir()
    (api_dir / "service.py").write_text("value = 1")
    (api_dir / "generated.py").write_text("value = 1")
    worker_dir = tmp_path / "worker"
    worker_dir.mkdir()
    (worker_dir / "job.py").write_text("value = 1")

    files = {
        file.relative_to(tmp_path).as_posix()
        for file in iter_python_files(
            tmp_path,
            ["api/generated.py"],
            include_paths=["api/"],
        )
    }

    assert files == {"api/service.py"}


def test_is_ignored_path_treats_non_included_paths_as_ignored(tmp_path) -> None:
    """When an include list is set, files outside it count as ignored."""
    api_file = tmp_path / "api" / "service.py"
    api_file.parent.mkdir()
    api_file.write_text("value = 1")
    worker_file = tmp_path / "worker" / "job.py"
    worker_file.parent.mkdir()
    worker_file.write_text("value = 1")

    assert not is_ignored_path(api_file, tmp_path, [], include_paths=["api/"])
    assert is_ignored_path(worker_file, tmp_path, [], include_paths=["api/"])
    assert is_ignored_path(api_file, tmp_path, ["api/"], include_paths=["api/"])


def test_iter_python_files_always_excludes_isolated_project_paths(tmp_path) -> None:
    """Nested validation scopes are excluded even when ignored files are included."""
    (tmp_path / "service.py").write_text("value = 1")
    generated_dir = tmp_path / "generated"
    generated_dir.mkdir()
    (generated_dir / "client.py").write_text("value = 1")
    nested_project_dir = tmp_path / "packages" / "worker"
    nested_project_dir.mkdir(parents=True)
    (nested_project_dir / "worker.py").write_text("value = 1")

    files = {
        file.relative_to(tmp_path).as_posix()
        for file in iter_python_files(
            tmp_path,
            ["generated/"],
            include_ignored=True,
            isolation_paths=["packages/worker"],
        )
    }

    assert files == {"generated/client.py", "service.py"}
