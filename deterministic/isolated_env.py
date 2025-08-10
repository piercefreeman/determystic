"""Isolated environment runner for agent test execution."""

import tempfile
import subprocess
from pathlib import Path
from typing import Optional
import shutil


class IsolatedEnv:
    """Runner for executing agent-generated tests in an isolated temporary environment."""
    
    def __init__(self, project_root: Path):
        """Initialize the isolated environment.
        
        Args:
            project_root: Root path of the deterministic project
        """
        self.project_root = project_root
        self.temp_dir: Optional[Path] = None
        
    def __enter__(self):
        """Context manager entry - create temp directory."""
        self.temp_dir = Path(tempfile.mkdtemp(prefix="deterministic_isolated_"))
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - cleanup temp directory."""
        if self.temp_dir and self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)
    
    def create_test_package(self, validator_code: str, test_code: str) -> Path:
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
        
        # Create pyproject.toml with local deterministic dependency
        pyproject_content = f'''[build-system]
requires = ["setuptools>=61.0"]
build-backend = "setuptools.build_meta"

[project]
name = "temp-validator"
version = "0.1.0"
dependencies = [
    "deterministic @ file://{self.project_root.absolute()}",
    "pytest>=6.0"
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
            package_dir = self.create_test_package(validator_code, test_code)
            
            result = subprocess.run(
                ["uv run", "pytest", "test_validator.py", "-v"],
                cwd=package_dir,
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