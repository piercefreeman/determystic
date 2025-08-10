"""IO utilities for path detection and project root discovery."""

import subprocess
from pathlib import Path
from typing import Optional


def detect_pyproject_path(start_path: Path) -> Optional[Path]:
    """
    Detect the root directory containing pyproject.toml.
    
    Args:
        start_path: Path to start searching from
        
    Returns:
        Path to directory containing pyproject.toml, or None if not found
    """
    current = start_path.resolve()
    
    # If start_path is a file, start from its parent directory
    if current.is_file():
        current = current.parent
    
    # Walk up the directory tree looking for pyproject.toml
    while current != current.parent:  # Stop at filesystem root
        pyproject_file = current / "pyproject.toml"
        if pyproject_file.exists():
            return current
        current = current.parent
    
    return None


def detect_git_root(start_path: Path) -> Optional[Path]:
    """
    Detect the git repository root directory.
    
    Args:
        start_path: Path to start searching from
        
    Returns:
        Path to git repository root, or None if not in a git repository
    """
    current = start_path.resolve()
    
    # If start_path is a file, start from its parent directory
    if current.is_file():
        current = current.parent
    
    try:
        # Use git to find the repository root
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=current,
            capture_output=True,
            text=True,
            check=True
        )
        return Path(result.stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError):
        # Not in a git repository or git not available
        return None
