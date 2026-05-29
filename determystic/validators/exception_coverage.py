"""Validator that requires except handlers to be marked as tested."""

import ast
import io
import tokenize
from dataclasses import dataclass
from pathlib import Path

from determystic.configs.project import ProjectConfigManager
from determystic.validators.base import BaseValidator, ValidationResult


MARKER_NAMES = {
    "tested-exception",
    "tested-exceptions",
    "test-exception",
    "test-exceptions",
}
TEST_PATH_PARTS = {"tests", "__tests__"}


@dataclass(frozen=True)
class ExceptionRequirement:
    """One exception type handled by an except clause in production code."""

    module_path: str
    line_number: int
    target: str
    exception_name: str
    exception_aliases: frozenset[str]


@dataclass(frozen=True)
class CoverageEntry:
    """One test marker entry claiming coverage for a production except handler."""

    module_path: str
    line_number: int
    test_function: str
    target: str
    exception_name: str
    exception_aliases: frozenset[str]


@dataclass(frozen=True)
class ParsedMarker:
    """A parsed determystic tested-exceptions comment."""

    line_number: int
    entries: tuple[tuple[str, str], ...]
    error: str | None = None


@dataclass(frozen=True)
class TestFunction:
    """A test function and the source line where its leading comments attach."""

    name: str
    line_number: int
    comment_anchor_line: int


class ExceptionHandlerCollector(ast.NodeVisitor):
    """Collect except handlers and map them to their enclosing function."""

    def __init__(self, module_path: str, module_name: str) -> None:
        self.module_path = module_path
        self.module_name = module_name
        self.scope_stack: list[str] = []
        self.requirements: list[ExceptionRequirement] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.scope_stack.append(node.name)
        self.generic_visit(node)
        self.scope_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def visit_Try(self, node: ast.Try) -> None:
        target = self._current_target()
        for handler in node.handlers:
            for exception_name, exception_aliases in _handler_exception_names(handler):
                self.requirements.append(
                    ExceptionRequirement(
                        module_path=self.module_path,
                        line_number=handler.lineno,
                        target=target,
                        exception_name=exception_name,
                        exception_aliases=frozenset(
                            _normalize_exception_name(alias)
                            for alias in exception_aliases
                        ),
                    )
                )
        self.generic_visit(node)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.scope_stack.append(node.name)
        self.generic_visit(node)
        self.scope_stack.pop()

    def _current_target(self) -> str:
        if not self.scope_stack:
            return f"{self.module_name}.<module>"
        return ".".join([self.module_name, *self.scope_stack])


class TestFunctionCollector(ast.NodeVisitor):
    """Collect pytest-style test functions from a parsed test module."""

    def __init__(self) -> None:
        self.class_stack: list[str] = []
        self.functions: list[TestFunction] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.class_stack.append(node.name)
        self.generic_visit(node)
        self.class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._collect_function(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._collect_function(node)
        self.generic_visit(node)

    def _collect_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        if not node.name.startswith("test_"):
            return

        decorator_lines = [decorator.lineno for decorator in node.decorator_list]
        anchor_line = min([node.lineno, *decorator_lines])
        qualified_name = ".".join([*self.class_stack, node.name])
        self.functions.append(
            TestFunction(
                name=qualified_name,
                line_number=node.lineno,
                comment_anchor_line=anchor_line,
            )
        )


class ExceptionCoverageValidator(BaseValidator):
    """Validator that ensures production except handlers are covered by test markers."""

    def __init__(self, *, name: str = "exception_coverage", path: Path | None = None) -> None:
        super().__init__(name=name, path=path)

    @classmethod
    def create_validators(cls, config_manager: ProjectConfigManager) -> list["BaseValidator"]:
        """Factory function that creates a single exception coverage validator."""
        return [cls(path=config_manager.project_root)]

    async def validate(self) -> ValidationResult:
        """Validate exception handler coverage markers across the project."""
        production_files = self._get_production_python_files(self.path)
        test_files = self._get_test_python_files(self.path)

        requirements = self._collect_requirements(production_files)
        coverage_entries, marker_issues = self._collect_test_coverage(test_files)
        coverage_issues = self._find_coverage_issues(requirements, coverage_entries)

        issues = [*marker_issues, *coverage_issues]
        if not issues:
            return ValidationResult(success=True, output="All except handlers are marked as tested")

        return ValidationResult(success=False, output="\n".join(issues))

    def _get_production_python_files(self, path: Path) -> list[Path]:
        return [
            py_file
            for py_file in path.rglob("*.py")
            if _is_relevant_python_file(py_file) and not _is_test_file(py_file)
        ]

    def _get_test_python_files(self, path: Path) -> list[Path]:
        return [
            py_file
            for py_file in path.rglob("*.py")
            if _is_relevant_python_file(py_file) and _is_test_file(py_file)
        ]

    def _collect_requirements(self, python_files: list[Path]) -> list[ExceptionRequirement]:
        requirements: list[ExceptionRequirement] = []

        for py_file in python_files:
            parsed = self._parse_python_file(py_file)
            if parsed is None:
                continue

            _, tree = parsed
            relative_path = str(py_file.relative_to(self.path))
            collector = ExceptionHandlerCollector(
                relative_path,
                _module_name_for_file(py_file, self.path),
            )
            collector.visit(tree)
            requirements.extend(collector.requirements)

        return requirements

    def _collect_test_coverage(
        self,
        test_files: list[Path],
    ) -> tuple[list[CoverageEntry], list[str]]:
        entries: list[CoverageEntry] = []
        issues: list[str] = []

        for py_file in test_files:
            parsed = self._parse_python_file(py_file)
            if parsed is None:
                continue

            source, tree = parsed
            relative_path = str(py_file.relative_to(self.path))
            markers = _parse_test_markers(source)
            functions = _test_functions(tree)
            attached_marker_lines: set[int] = set()

            for marker in markers:
                if marker.error:
                    issues.append(
                        f"{relative_path}:{marker.line_number}: {marker.error}"
                    )

            for test_function in functions:
                for comment_line in _leading_comment_block_lines(
                    source,
                    test_function.comment_anchor_line,
                ):
                    for marker in markers:
                        if marker.line_number != comment_line or marker.error:
                            continue
                        attached_marker_lines.add(marker.line_number)
                        entries.extend(
                            CoverageEntry(
                                module_path=relative_path,
                                line_number=marker.line_number,
                                test_function=test_function.name,
                                target=target,
                                exception_name=exception_name,
                                exception_aliases=_exception_aliases(exception_name),
                            )
                            for target, exception_name in marker.entries
                        )

            for marker in markers:
                if marker.error or marker.line_number in attached_marker_lines:
                    continue
                issues.append(
                    f"{relative_path}:{marker.line_number}: "
                    "tested-exceptions marker must be immediately above a test function"
                )

        return entries, issues

    def _find_coverage_issues(
        self,
        requirements: list[ExceptionRequirement],
        coverage_entries: list[CoverageEntry],
    ) -> list[str]:
        issues: list[str] = []
        requirements_by_target: dict[str, list[ExceptionRequirement]] = {}
        coverage_by_target: dict[str, set[str]] = {}

        for requirement in requirements:
            requirements_by_target.setdefault(requirement.target, []).append(requirement)

        for entry in coverage_entries:
            coverage_by_target.setdefault(entry.target, set()).update(entry.exception_aliases)

        for requirement in requirements:
            covered_exceptions = coverage_by_target.get(requirement.target, set())
            if requirement.exception_aliases & covered_exceptions:
                continue

            issues.append(
                f"{requirement.module_path}:{requirement.line_number}: "
                f"Except handler for '{requirement.exception_name}' in "
                f"{requirement.target} is not marked as tested. Add a "
                "tested-exceptions marker above the test function that covers "
                f"target '{requirement.target}' and exception "
                f"'{requirement.exception_name}'."
            )

        for entry in coverage_entries:
            target_requirements = requirements_by_target.get(entry.target)
            if target_requirements is None:
                issues.append(
                    f"{entry.module_path}:{entry.line_number}: "
                    f"tested-exceptions marker in '{entry.test_function}' targets "
                    f"'{entry.target}', but no production function with except handlers "
                    "matches that name"
                )
                continue

            if any(
                requirement.exception_aliases & entry.exception_aliases
                for requirement in target_requirements
            ):
                continue

            issues.append(
                f"{entry.module_path}:{entry.line_number}: "
                f"tested-exceptions marker in '{entry.test_function}' lists "
                f"'{entry.exception_name}' for '{entry.target}', but that function "
                "does not catch that exception"
            )

        return issues

    def _parse_python_file(self, py_file: Path) -> tuple[str, ast.AST] | None:
        try:
            source = py_file.read_text(encoding="utf-8")
            return source, ast.parse(source, filename=str(py_file))
        except (SyntaxError, UnicodeDecodeError):
            return None


def _parse_test_markers(source: str) -> list[ParsedMarker]:
    markers: list[ParsedMarker] = []

    try:
        tokens = tokenize.generate_tokens(io.StringIO(source).readline)
        for token in tokens:
            if token.type != tokenize.COMMENT:
                continue
            marker = _parse_marker_comment(token.start[0], token.string)
            if marker is not None:
                markers.append(marker)
    except tokenize.TokenError:
        return [
            ParsedMarker(
                line_number=1,
                entries=(),
                error="Could not parse tested-exceptions markers because tokenization failed",
            )
        ]

    return markers


def _parse_marker_comment(line_number: int, comment: str) -> ParsedMarker | None:
    marker = "determystic:"
    marker_index = comment.lower().find(marker)
    if marker_index == -1:
        return None

    directive = comment[marker_index + len(marker):].strip()
    bracket_start = directive.find("[")
    marker_name = directive[:bracket_start if bracket_start != -1 else None]
    normalized_marker_name = marker_name.strip().lower().replace("_", "-")
    if normalized_marker_name not in MARKER_NAMES:
        return None

    bracket_end = directive.find("]", bracket_start + 1)
    if bracket_start == -1 or bracket_end == -1:
        return ParsedMarker(
            line_number=line_number,
            entries=(),
            error=(
                "Invalid tested-exceptions marker. Expected "
                "'# determystic: tested-exceptions[module.function: ExceptionName]'"
            ),
        )

    body = directive[bracket_start + 1:bracket_end].strip()
    entries: list[tuple[str, str]] = []
    errors: list[str] = []

    for raw_entry in body.split(";"):
        raw_entry = raw_entry.strip()
        if not raw_entry:
            continue
        if ":" not in raw_entry:
            errors.append(f"'{raw_entry}' is missing ':'")
            continue

        target, exception_list = raw_entry.split(":", 1)
        target = target.strip()
        exception_names = [
            exception_name.strip()
            for exception_name in exception_list.split(",")
            if exception_name.strip()
        ]

        if not target:
            errors.append("target function is empty")
            continue
        if "." not in target:
            errors.append(f"'{target}' is not a module.function target")
            continue
        if not exception_names:
            errors.append(f"'{target}' does not list any exceptions")
            continue

        entries.extend((target, exception_name) for exception_name in exception_names)

    if errors or not entries:
        return ParsedMarker(
            line_number=line_number,
            entries=(),
            error=f"Invalid tested-exceptions marker: {', '.join(errors) or 'no entries found'}",
        )

    return ParsedMarker(line_number=line_number, entries=tuple(entries))


def _test_functions(tree: ast.AST) -> list[TestFunction]:
    collector = TestFunctionCollector()
    collector.visit(tree)
    return collector.functions


def _leading_comment_block_lines(source: str, anchor_line: int) -> list[int]:
    source_lines = source.splitlines()
    comment_lines: list[int] = []
    line_number = anchor_line - 1

    while line_number >= 1:
        line = source_lines[line_number - 1].strip()
        if not line:
            break
        if not line.startswith("#"):
            break
        comment_lines.append(line_number)
        line_number -= 1

    return comment_lines


def _handler_exception_names(handler: ast.ExceptHandler) -> list[tuple[str, set[str]]]:
    if handler.type is None:
        return [("BaseException", {"BaseException", "bare"})]

    if isinstance(handler.type, ast.Tuple):
        return [_exception_name(element) for element in handler.type.elts]

    return [_exception_name(handler.type)]


def _exception_name(node: ast.AST) -> tuple[str, set[str]]:
    if isinstance(node, ast.Name):
        return node.id, {node.id}

    if isinstance(node, ast.Attribute):
        dotted_name = _attribute_name(node)
        simple_name = node.attr
        return dotted_name, {dotted_name, simple_name}

    unparsed_name = ast.unparse(node)
    return unparsed_name, {unparsed_name, unparsed_name.rsplit(".", 1)[-1]}


def _attribute_name(node: ast.Attribute) -> str:
    parts = [node.attr]
    value = node.value

    while isinstance(value, ast.Attribute):
        parts.append(value.attr)
        value = value.value

    if isinstance(value, ast.Name):
        parts.append(value.id)
    else:
        parts.append(ast.unparse(value))

    return ".".join(reversed(parts))


def _exception_aliases(exception_name: str) -> frozenset[str]:
    return frozenset(
        _normalize_exception_name(alias)
        for alias in {exception_name, exception_name.rsplit(".", 1)[-1]}
    )


def _normalize_exception_name(exception_name: str) -> str:
    return exception_name.strip().lower()


def _module_name_for_file(py_file: Path, project_root: Path) -> str:
    relative_path = py_file.relative_to(project_root).with_suffix("")
    parts = list(relative_path.parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) if parts else py_file.stem


def _is_relevant_python_file(py_file: Path) -> bool:
    return (
        not any(part.startswith(".") for part in py_file.parts)
        and "__pycache__" not in py_file.parts
    )


def _is_test_file(py_file: Path) -> bool:
    return (
        py_file.name.startswith("test_")
        or py_file.name.endswith("_test.py")
        or any(part in TEST_PATH_PARTS for part in py_file.parts)
    )
