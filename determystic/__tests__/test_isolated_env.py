"""Tests for isolated agent test execution."""

import subprocess
from unittest.mock import patch

from determystic.isolated_env import IsolatedEnv


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
