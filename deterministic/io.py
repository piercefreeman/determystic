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


def detect_project_path(explicit_path: Optional[str | Path] = None) -> Path:
    """
    Detect the project path using the following priority:
    1. If explicit_path is provided, use it as-is
    2. Try to find pyproject.toml root
    3. Fallback to git repository root
    4. Fallback to current working directory
    
    Args:
        explicit_path: Explicitly specified path (highest priority)
        
    Returns:
        Resolved project path
    """
    # If explicit path is provided, use it as-is
    if explicit_path is not None:
        return Path(explicit_path).resolve()
    
    # Start from current working directory
    cwd = Path.cwd()
    
    # Try to find pyproject.toml root
    pyproject_root = detect_pyproject_path(cwd)
    if pyproject_root is not None:
        return pyproject_root
    
    # Fallback to git repository root
    git_root = detect_git_root(cwd)
    if git_root is not None:
        return git_root
    
    # Final fallback to current working directory
    return cwd