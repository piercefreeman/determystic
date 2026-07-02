"""Shared, lazily-parsed view of a project's source files.

Validators that scan the same project scope repeat the same expensive work per
file: walking the tree, reading contents, parsing the AST, and extracting
suppression comments. A ``SourceFileCache`` shared between validators performs
each of those steps at most once per file per run.
"""

import ast
from dataclasses import dataclass, field
from pathlib import Path

from determystic.path_filters import iter_python_files
from determystic.suppressions import SuppressionComments


@dataclass
class SourceFile:
    """One project file with lazily computed parse artifacts."""

    path: Path
    relative_path: str
    content: str | None = None
    read_error: str | None = None
    _tree: ast.AST | None = field(default=None, repr=False)
    _tree_loaded: bool = field(default=False, repr=False)
    _suppressions: SuppressionComments | None = field(default=None, repr=False)

    @property
    def tree(self) -> ast.AST | None:
        """The parsed AST, or ``None`` if the file has a syntax error."""
        if not self._tree_loaded:
            self._tree_loaded = True
            if self.content is not None:
                try:
                    self._tree = ast.parse(self.content, filename=self.relative_path)
                except SyntaxError:
                    self._tree = None
        return self._tree

    @property
    def suppressions(self) -> SuppressionComments:
        if self._suppressions is None:
            if self.content is None:
                self._suppressions = SuppressionComments.empty()
            else:
                self._suppressions = SuppressionComments.from_source(
                    self.content,
                    tree=self.tree,
                )
        return self._suppressions


class SourceFileCache:
    """Caches walked files and their parse artifacts for one validation run."""

    def __init__(self) -> None:
        self._file_lists: dict[tuple, list[SourceFile]] = {}

    def get_files(
        self,
        project_root: Path,
        ignore_paths: list[str] | tuple[str, ...] | None = None,
        *,
        include_paths: list[str] | tuple[str, ...] | None = None,
        isolation_paths: list[str] | tuple[str, ...] | None = None,
    ) -> list[SourceFile]:
        """Return the visible project files, reading each from disk once."""
        key = (
            project_root,
            tuple(ignore_paths or ()),
            tuple(include_paths or ()),
            tuple(isolation_paths or ()),
        )
        if key not in self._file_lists:
            self._file_lists[key] = self._load_files(
                project_root,
                ignore_paths,
                include_paths=include_paths,
                isolation_paths=isolation_paths,
            )
        return self._file_lists[key]

    @staticmethod
    def _load_files(
        project_root: Path,
        ignore_paths: list[str] | tuple[str, ...] | None,
        *,
        include_paths: list[str] | tuple[str, ...] | None,
        isolation_paths: list[str] | tuple[str, ...] | None,
    ) -> list[SourceFile]:
        source_files: list[SourceFile] = []
        for path in iter_python_files(
            project_root,
            ignore_paths,
            include_paths=include_paths,
            isolation_paths=isolation_paths,
        ):
            relative_path = str(path.relative_to(project_root))
            try:
                content = path.read_text()
            except Exception as error:
                source_files.append(
                    SourceFile(
                        path=path,
                        relative_path=relative_path,
                        read_error=str(error),
                    )
                )
                continue
            source_files.append(
                SourceFile(path=path, relative_path=relative_path, content=content)
            )
        return source_files
