"""Compatibility imports for older supported Python versions."""

import sys

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # ty: ignore[unresolved-import]

__all__ = ["tomllib"]
