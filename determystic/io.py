"""IO utilities for path detection and project root discovery."""

import asyncio
import subprocess
from pathlib import Path
from typing import Optional, Callable, Coroutine, Any, TypeVar, ParamSpec
from functools import wraps


T = TypeVar("T")
P = ParamSpec("P")



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

def get_determystic_package_path() -> Optional[Path]:
    """
    Get the path to the determystic package.
    
    Returns:
        Path to the determystic package directory, or None if not found
    """
    try:
        import determystic
        # Get the package's __file__ attribute and traverse up to find the package root
        package_file = Path(determystic.__file__)
        # The package root is the parent directory of the __init__.py file
        package_root = package_file.parent.parent
        return package_root
    except (ImportError, AttributeError):
        raise RuntimeError("Unable to resolve the root of the determystic package.")

def async_to_sync(async_fn: Callable[P, Coroutine[Any, Any, T]]) -> Callable[P, T]:
    @wraps(async_fn)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
        loop = asyncio.get_event_loop()
        result = loop.run_until_complete(async_fn(*args, **kwargs))
        return result

    return wrapper
