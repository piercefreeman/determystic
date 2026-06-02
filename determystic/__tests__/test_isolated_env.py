"""Tests for isolated agent test execution."""

import os
import subprocess
from importlib import metadata
from unittest.mock import patch

from determystic.isolated_env import IsolatedEnv, _installed_determystic_runtime_dependencies


# determystic: tested-exceptions[determystic.isolated_env.IsolatedEnv.run_tests: TimeoutExpired]
def test_run_tests_reports_timeouts(tmp_path) -> None:
    """Timeouts from pytest execution are returned as failed test runs."""
    env = IsolatedEnv()

    with (
        patch.object(env, "_create_test_package", return_value=tmp_path),
        patch(
            "determystic.isolated_env.subprocess.run",
            side_effect=subprocess.TimeoutExpired(["pytest"], 30),
        ),
    ):
        success, output = env.run_tests("validator", "tests")

    assert success is False
    assert output == "Test execution timed out"


# determystic: tested-exceptions[determystic.isolated_env.IsolatedEnv.run_tests: Exception]
def test_run_tests_reports_unexpected_errors() -> None:
    """Unexpected setup errors are returned as failed test runs."""
    env = IsolatedEnv()

    with patch.object(
        env,
        "_create_test_package",
        side_effect=RuntimeError("package setup failed"),
    ):
        success, output = env.run_tests("validator", "tests")

    assert success is False
    assert "Unexpected error running tests: package setup failed" in output


def test_create_test_package_uses_source_dependency_when_project_root_exists(tmp_path) -> None:
    """Source checkouts should install determystic from the local project root."""
    source_root = tmp_path / "source"
    source_root.mkdir()
    (source_root / "pyproject.toml").write_text("[project]\nname = \"determystic\"\n")

    env = IsolatedEnv()
    env.temp_dir = tmp_path
    env.determystic_package_path = source_root

    package_dir = env._create_test_package("validator", "tests")
    pyproject = (package_dir / "pyproject.toml").read_text()

    assert f"determystic @ file://{source_root.absolute()}" in pyproject
    assert not (package_dir / "determystic").exists()


def test_create_test_package_uses_import_path_when_no_project_root(tmp_path) -> None:
    """Installed uvx-style packages should not be treated as installable source roots."""
    site_packages = tmp_path / "site-packages"
    package_source = site_packages / "determystic"
    package_source.mkdir(parents=True)
    (package_source / "__init__.py").write_text("")
    (package_source / "external.py").write_text("class DeterministicTraverser: pass\n")

    env = IsolatedEnv()
    env.temp_dir = tmp_path
    env.determystic_package_path = site_packages

    with patch(
        "determystic.isolated_env._installed_determystic_runtime_dependencies",
        return_value=["pydantic>=2.0.0"],
    ):
        package_dir = env._create_test_package("validator", "tests")

    pyproject = (package_dir / "pyproject.toml").read_text()

    assert "determystic @ file://" not in pyproject
    assert '"pydantic>=2.0.0"' in pyproject
    assert not (package_dir / "determystic").exists()


def test_run_tests_adds_installed_package_parent_to_pythonpath(tmp_path) -> None:
    """uvx-style runs should import determystic from the currently running package path."""
    site_packages = tmp_path / "site-packages"
    env = IsolatedEnv()
    env.temp_dir = tmp_path
    env.determystic_package_path = site_packages

    completed = subprocess.CompletedProcess(
        args=["uv", "run", "pytest"],
        returncode=0,
        stdout="tests passed",
        stderr="",
    )

    with (
        patch(
            "determystic.isolated_env._installed_determystic_runtime_dependencies",
            return_value=["pydantic>=2.0.0"],
        ),
        patch("determystic.isolated_env.subprocess.run", return_value=completed) as mock_run,
    ):
        success, output = env.run_tests("validator", "tests")

    run_env = mock_run.call_args.kwargs["env"]
    pythonpath_entries = run_env["PYTHONPATH"].split(os.pathsep)

    assert success is True
    assert output == "tests passed"
    assert pythonpath_entries[0] == str(site_packages.absolute())


# determystic: tested-exceptions[determystic.isolated_env._installed_determystic_runtime_dependencies: metadata.PackageNotFoundError]
def test_installed_determystic_runtime_dependencies_falls_back_when_metadata_is_missing() -> None:
    """Missing installed metadata should still provide the minimal runtime dependency."""
    with patch(
        "determystic.isolated_env.metadata.distribution",
        side_effect=metadata.PackageNotFoundError,
    ):
        assert _installed_determystic_runtime_dependencies() == ["pydantic>=2.0.0"]
