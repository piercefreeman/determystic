# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "packaging",
#     "toml",
# ]
# ///

import sys
from pathlib import Path
from sys import stdout

import toml # type: ignore
from packaging.version import parse


def update_version_python(new_version: str) -> None:
    """Update the version in pyproject.toml"""
    pyproject_path = Path("pyproject.toml")
    if not pyproject_path.exists():
        stdout.write("pyproject.toml not found, skipping version update\n")
        return

    filedata = toml.loads(pyproject_path.read_text())

    # Parse the new version to ensure it's valid and potentially reformat
    python_version = format_python_version(new_version)

    updated = False

    # Update project.version if it exists
    if "project" in filedata and "version" in filedata["project"]:
        filedata["project"]["version"] = python_version
        updated = True

    if not updated:
        stdout.write("Warning: [project] section not found in pyproject.toml\n")
        return

    pyproject_path.write_text(toml.dumps(filedata))
    stdout.write(f"Updated pyproject.toml version to: {python_version}\n")


def format_python_version(new_version: str) -> str:
    """Format version string for Python packaging standards"""
    parsed_version = parse(new_version)
    
    # Base version
    python_version = f"{parsed_version.major}.{parsed_version.minor}.{parsed_version.micro}"
    
    # Add pre-release info
    if parsed_version.is_prerelease and parsed_version.pre is not None:
        pre_type, pre_num = parsed_version.pre
        if pre_type == "a":
            python_version += f"a{pre_num}"
        elif pre_type == "b":
            python_version += f"b{pre_num}"
        elif pre_type == "rc":
            python_version += f"rc{pre_num}"
    
    # Add post-release info
    if parsed_version.is_postrelease and parsed_version.post is not None:
        python_version += f".post{parsed_version.post}"
    
    # Add dev release info
    if parsed_version.is_devrelease and parsed_version.dev is not None:
        python_version += f".dev{parsed_version.dev}"
    
    return python_version


if __name__ == "__main__":
    if len(sys.argv) != 2:
        stdout.write("Usage: python update_version.py <new_version>\n")
        sys.exit(1)
    
    new_version = sys.argv[1].lstrip("v")
    update_version_python(new_version)
    stdout.write(f"Version update completed: {new_version}\n")