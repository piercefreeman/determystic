"""Isolated environment runner for agent test execution."""

import json
import os
import shutil
import subprocess
import tempfile
from importlib import metadata
from pathlib import Path
from typing import Optional

from determystic.io import get_determystic_package_path


class IsolatedEnv:
    """Runner for executing agent-generated tests in an isolated temporary environment."""
    
    def __init__(self):
        """Initialize the isolated environment.
        
        Args:
            project_root: Root path of the determystic project
        """
        self.determystic_package_path = get_determystic_package_path()
        self.temp_dir: Optional[Path] = None
        
    def __enter__(self):
        """Context manager entry - create temp directory."""
        self.temp_dir = Path(tempfile.mkdtemp(prefix="determystic_isolated_"))
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - cleanup temp directory."""
        if self.temp_dir and self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)
    
    def run_tests(self, validator_code: str, test_code: str) -> tuple[bool, str]:
        """Run the agent-generated tests in an isolated environment.
        
        Args:
            validator_code: The validator Python code
            test_code: The test code to run
            
        Returns:
            Tuple of (success, output) where success indicates if tests passed
        """
        try:
            # Create the temporary package
            package_dir = self._create_test_package(validator_code, test_code)
            env = self._subprocess_env()
            
            result = subprocess.run(
                ["uv", "run", "pytest", "test_validator.py", "-v"],
                cwd=package_dir,
                env=env,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            # Return success status and combined output
            success = result.returncode == 0
            output = result.stdout + "\n" + result.stderr if result.stderr else result.stdout
            
            return success, output.strip()
            
        except subprocess.TimeoutExpired:
            return False, "Test execution timed out"
        except Exception as e:
            return False, f"Unexpected error running tests: {e}"

    def _create_test_package(self, validator_code: str, test_code: str) -> Path:
        """Create a temporary package for running agent-generated tests.

        Args:
            validator_code: The validator code to test
            test_code: The test code to run

        Returns:
            Path to the temporary package directory
        """
        if not self.temp_dir:
            raise RuntimeError("IsolatedEnv must be used as a context manager")

        # Create package structure
        package_dir = self.temp_dir / "temp_validator"
        package_dir.mkdir(parents=True)

        dependency_specs = self._dependency_specs()
        dependency_lines = ",\n".join(f"    {json.dumps(spec)}" for spec in dependency_specs)

        # Create pyproject.toml with the dependencies needed by generated tests.
        pyproject_content = f'''[build-system]
requires = ["setuptools>=61.0"]
build-backend = "setuptools.build_meta"

[project]
name = "temp-validator"
version = "0.1.0"
dependencies = [
{dependency_lines}
]

[tool.setuptools.packages.find]
where = ["."]
'''

        (package_dir / "pyproject.toml").write_text(pyproject_content)

        # Create the validator module
        (package_dir / "validator.py").write_text(validator_code)

        # Create test module
        (package_dir / "test_validator.py").write_text(test_code)

        return package_dir

    def _has_installable_determystic_source(self) -> bool:
        """Return whether the resolved path can be installed as a Python project."""
        root = self.determystic_package_path
        return (root / "pyproject.toml").exists() or (root / "setup.py").exists()

    def _dependency_specs(self) -> list[str]:
        """Build dependency specs for the temporary pytest project."""
        specs = ["pytest>=6.0"]

        if self._has_installable_determystic_source():
            specs.insert(
                0,
                f"determystic @ file://{self.determystic_package_path.absolute()}",
            )
            return specs

        specs.extend(_installed_determystic_runtime_dependencies())
        return _dedupe_dependency_specs(specs)

    def _subprocess_env(self) -> dict[str, str]:
        """Build the subprocess environment for the isolated pytest run."""
        env = os.environ.copy()
        if self._has_installable_determystic_source():
            return env

        package_parent = str(self.determystic_package_path.absolute())
        existing_pythonpath = env.get("PYTHONPATH")
        env["PYTHONPATH"] = (
            f"{package_parent}{os.pathsep}{existing_pythonpath}"
            if existing_pythonpath
            else package_parent
        )
        return env


def _installed_determystic_runtime_dependencies() -> list[str]:
    """Return runtime dependency specs from installed package metadata."""
    try:
        dist = metadata.distribution("determystic")
    except metadata.PackageNotFoundError:
        return ["pydantic>=2.0.0"]

    return list(dist.requires or []) or ["pydantic>=2.0.0"]


def _dedupe_dependency_specs(specs: list[str]) -> list[str]:
    """Deduplicate dependency specs while preserving order."""
    seen: set[str] = set()
    deduped: list[str] = []
    for spec in specs:
        if spec in seen:
            continue
        seen.add(spec)
        deduped.append(spec)
    return deduped
