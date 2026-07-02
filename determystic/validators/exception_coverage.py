"""Validator that requires except handlers to be marked as tested."""

import ast
import io
import tokenize
from dataclasses import dataclass
from pathlib import Path

from determystic.configs.project import ProjectConfigManager
from determystic.path_filters import is_ignored_path, is_test_file, iter_python_files
from determystic.validators.base import BaseValidator, ValidationResult

DefinitionNode = ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef


MARKER_NAMES = {
    "tested-exception",
    "tested-exceptions",
    "test-exception",
    "test-exceptions",
}


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
    node: ast.FunctionDef | ast.AsyncFunctionDef


@dataclass(frozen=True)
class TestModuleContext:
    """Static import and helper definitions available to a test module."""

    module_name: str
    imports: dict[str, str]
    definitions: dict[str, DefinitionNode]


@dataclass(frozen=True)
class TestCoverageFacts:
    """Static evidence collected from one test function."""

    called_targets: frozenset[str]
    exception_aliases: frozenset[str]


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
                node=node,
            )
        )


class ExceptionCoverageValidator(BaseValidator):
    """Validator that ensures production except handlers are covered by test markers."""

    def __init__(
        self,
        *,
        name: str = "exception_coverage",
        path: Path | None = None,
        ignore_paths: list[str] | None = None,
        include_paths: list[str] | None = None,
        isolation_paths: list[str] | None = None,
    ) -> None:
        super().__init__(name=name, path=path)
        self.ignore_paths = ignore_paths or []
        self.include_paths = include_paths or []
        self.isolation_paths = isolation_paths or []

    @classmethod
    def create_validators(
        cls, config_manager: ProjectConfigManager
    ) -> list["BaseValidator"]:
        """Factory function that creates a single exception coverage validator."""
        return [
            cls(
                path=config_manager.project_root,
                ignore_paths=config_manager.paths_exclude,
                include_paths=config_manager.paths_include,
                isolation_paths=config_manager.isolation_paths,
            )
        ]

    async def validate(self) -> ValidationResult:
        """Validate exception handler coverage markers across the project."""
        production_files = self._get_production_python_files(self.path)
        test_files = self._get_test_python_files(self.path)

        requirements = self._collect_requirements(production_files)
        coverage_entries, marker_issues = self._collect_test_coverage(
            test_files,
            requirements,
        )
        coverage_issues = self._find_coverage_issues(requirements, coverage_entries)

        issues = [*marker_issues, *coverage_issues]
        if not issues:
            return ValidationResult(
                success=True, output="All except handlers are marked as tested"
            )

        return ValidationResult(success=False, output="\n".join(issues))

    def _get_production_python_files(self, path: Path) -> list[Path]:
        return iter_python_files(
            path,
            self.ignore_paths,
            include_paths=self.include_paths,
            include_tests=False,
            isolation_paths=self.isolation_paths,
        )

    def _get_test_python_files(self, path: Path) -> list[Path]:
        return [
            py_file
            for py_file in iter_python_files(
                path,
                self.ignore_paths,
                include_ignored=True,
                isolation_paths=self.isolation_paths,
            )
            if is_test_file(py_file)
        ]

    def _collect_requirements(
        self, python_files: list[Path]
    ) -> list[ExceptionRequirement]:
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
        requirements: list[ExceptionRequirement],
    ) -> tuple[list[CoverageEntry], list[str]]:
        entries: list[CoverageEntry] = []
        issues: list[str] = []

        for py_file in test_files:
            parsed = self._parse_python_file(py_file)
            if parsed is None:
                continue

            source, tree = parsed
            relative_path = str(py_file.relative_to(self.path))
            is_ignored = is_ignored_path(
                py_file,
                self.path,
                self.ignore_paths,
                include_paths=self.include_paths,
            )
            markers = _parse_test_markers(source)
            functions = _test_functions(tree)
            module_context = _test_module_context(
                tree,
                module_name=_module_name_for_file(py_file, self.path),
            )
            attached_marker_lines: set[int] = set()

            for marker in markers:
                if marker.error and not is_ignored:
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

            entries.extend(
                _infer_coverage_entries(
                    module_path=relative_path,
                    functions=functions,
                    requirements=requirements,
                    module_context=module_context,
                )
            )

            for marker in markers:
                if (
                    is_ignored
                    or marker.error
                    or marker.line_number in attached_marker_lines
                ):
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

        for requirement in requirements:
            requirements_by_target.setdefault(requirement.target, []).append(
                requirement
            )

        for requirement in requirements:
            if any(
                _coverage_entry_matches_requirement(entry, requirement)
                for entry in coverage_entries
            ):
                continue

            issues.append(
                f"{requirement.module_path}:{requirement.line_number}: "
                f"Except handler for '{requirement.exception_name}' in "
                f"{requirement.target} is not covered by a test marker or "
                "inferred test evidence. Add a tested-exceptions marker above "
                "the test function, or exercise the target with a recognizable "
                f"'{requirement.exception_name}' exception."
            )

        for entry in coverage_entries:
            target_requirements = [
                requirement
                for target, target_requirements in requirements_by_target.items()
                if _targets_match(entry.target, target)
                for requirement in target_requirements
            ]
            if not target_requirements:
                issues.append(
                    f"{entry.module_path}:{entry.line_number}: "
                    f"tested-exceptions marker in '{entry.test_function}' targets "
                    f"'{entry.target}', but no production function with except handlers "
                    "matches that name"
                )
                continue

            if any(
                _exception_aliases_cover(
                    requirement.exception_aliases,
                    entry.exception_aliases,
                )
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

    directive = comment[marker_index + len(marker) :].strip()
    bracket_start = directive.find("[")
    marker_name = directive[: bracket_start if bracket_start != -1 else None]
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

    body = directive[bracket_start + 1 : bracket_end].strip()
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


def _test_module_context(tree: ast.AST, *, module_name: str) -> TestModuleContext:
    imports: dict[str, str] = {}
    definitions: dict[str, DefinitionNode] = {}

    if not isinstance(tree, ast.Module):
        return TestModuleContext(
            module_name=module_name,
            imports=imports,
            definitions=definitions,
        )

    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                local_name = alias.asname or alias.name.split(".", 1)[0]
                imports[local_name] = alias.name
            continue

        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:
                module = f"{'.' * node.level}{module}"
            for alias in node.names:
                if alias.name == "*":
                    continue
                local_name = alias.asname or alias.name
                imports[local_name] = f"{module}.{alias.name}" if module else alias.name
            continue

        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            definitions[node.name] = node

    return TestModuleContext(
        module_name=module_name,
        imports=imports,
        definitions=definitions,
    )


def _infer_coverage_entries(
    *,
    module_path: str,
    functions: list[TestFunction],
    requirements: list[ExceptionRequirement],
    module_context: TestModuleContext,
) -> list[CoverageEntry]:
    entries: list[CoverageEntry] = []

    for test_function in functions:
        facts = _coverage_facts_for_test(test_function.node, module_context)
        if not facts.called_targets or not facts.exception_aliases:
            continue

        for requirement in requirements:
            if not any(
                _targets_match(candidate, requirement.target)
                for candidate in facts.called_targets
            ):
                continue
            if not _exception_aliases_cover(
                requirement.exception_aliases,
                facts.exception_aliases,
            ):
                continue

            entries.append(
                CoverageEntry(
                    module_path=module_path,
                    line_number=test_function.line_number,
                    test_function=test_function.name,
                    target=requirement.target,
                    exception_name=requirement.exception_name,
                    exception_aliases=requirement.exception_aliases,
                )
            )

    return entries


def _coverage_facts_for_test(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    module_context: TestModuleContext,
) -> TestCoverageFacts:
    collector = TestCoverageFactCollector(module_context)
    return collector.collect(node)


class TestCoverageFactCollector(ast.NodeVisitor):
    """Collect target calls and exception evidence from one test function."""

    def __init__(self, module_context: TestModuleContext) -> None:
        self.module_context = module_context
        self.local_definitions: dict[str, DefinitionNode] = {}
        self.value_bindings: dict[str, str] = {}
        self.called_targets: set[str] = set()
        self.exception_aliases: set[str] = set()
        self._collected_definition_ids: set[int] = set()

    def collect(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> TestCoverageFacts:
        for statement in node.body:
            self.visit(statement)
        return TestCoverageFacts(
            called_targets=frozenset(self.called_targets),
            exception_aliases=frozenset(self.exception_aliases),
        )

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._collect_local_definition(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._collect_local_definition(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._collect_local_definition(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        self.visit(node.value)
        for target in node.targets:
            self._bind_assignment_target(target, node.value)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None:
            self.visit(node.value)
            self._bind_assignment_target(node.target, node.value)

    def visit_Raise(self, node: ast.Raise) -> None:
        self.exception_aliases.update(_exception_aliases_from_expr(node.exc))
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        targets = self._call_targets(node.func)
        self.called_targets.update(targets)
        self._collect_called_definition_exception_aliases(node.func)

        if any(_is_exception_target(target) for target in targets):
            self.exception_aliases.update(_exception_aliases_from_expr(node.func))

        if any(_is_pytest_raises_target(target) for target in targets) and node.args:
            self.exception_aliases.update(_exception_aliases_from_expr(node.args[0]))

        for argument in node.args:
            self._collect_referenced_definition_exception_aliases(argument)

        for keyword in node.keywords:
            if keyword.arg == "side_effect":
                self.exception_aliases.update(
                    _exception_aliases_from_expr(keyword.value)
                )
            self._collect_referenced_definition_exception_aliases(keyword.value)

        self.generic_visit(node)

    def _collect_local_definition(self, node: DefinitionNode) -> None:
        self.local_definitions[node.name] = node
        self._collect_definition_exception_aliases(node)

    def _bind_assignment_target(self, target: ast.AST, value: ast.AST) -> None:
        if not isinstance(target, ast.Name) or not isinstance(value, ast.Call):
            return
        call_target = self._primary_call_target(value.func)
        if call_target is not None:
            self.value_bindings[target.id] = call_target

    def _primary_call_target(self, node: ast.AST) -> str | None:
        targets = self._call_targets(node)
        if not targets:
            return None
        return max(targets, key=lambda target: (target.count("."), len(target)))

    def _call_targets(self, node: ast.AST) -> set[str]:
        if isinstance(node, ast.Name):
            return {self._target_for_name(node.id)}

        if isinstance(node, ast.Attribute):
            targets = {_attribute_name(node), node.attr}
            value_target = self._attribute_value_target(node.value)
            if value_target is not None:
                targets.add(f"{value_target}.{node.attr}")
            return targets

        return set()

    def _target_for_name(self, name: str) -> str:
        if name in self.value_bindings:
            return self.value_bindings[name]
        if name in self.module_context.imports:
            return self.module_context.imports[name]
        if name in self.local_definitions or name in self.module_context.definitions:
            return f"{self.module_context.module_name}.{name}"
        return name

    def _attribute_value_target(self, node: ast.AST) -> str | None:
        if isinstance(node, ast.Name):
            if node.id in self.value_bindings:
                return self.value_bindings[node.id]
            if node.id in self.module_context.imports:
                return self.module_context.imports[node.id]
            if (
                node.id in self.local_definitions
                or node.id in self.module_context.definitions
            ):
                return f"{self.module_context.module_name}.{node.id}"
            return None

        if isinstance(node, ast.Attribute):
            value_target = self._attribute_value_target(node.value)
            if value_target is None:
                return None
            return f"{value_target}.{node.attr}"

        return None

    def _collect_called_definition_exception_aliases(self, node: ast.AST) -> None:
        if isinstance(node, ast.Name):
            self._collect_definition_exception_aliases_for_name(node.id)

    def _collect_referenced_definition_exception_aliases(self, node: ast.AST) -> None:
        if isinstance(node, ast.Name):
            self._collect_definition_exception_aliases_for_name(node.id)

    def _collect_definition_exception_aliases_for_name(self, name: str) -> None:
        definition = self.local_definitions.get(
            name
        ) or self.module_context.definitions.get(name)
        if definition is None:
            return
        self._collect_definition_exception_aliases(definition)

    def _collect_definition_exception_aliases(self, node: DefinitionNode) -> None:
        node_id = id(node)
        if node_id in self._collected_definition_ids:
            return
        self._collected_definition_ids.add(node_id)

        collector = ExceptionEvidenceCollector()
        collector.visit(node)
        self.exception_aliases.update(collector.exception_aliases)


class ExceptionEvidenceCollector(ast.NodeVisitor):
    """Collect exception names mentioned inside helper definitions."""

    def __init__(self) -> None:
        self.exception_aliases: set[str] = set()

    def visit_Raise(self, node: ast.Raise) -> None:
        self.exception_aliases.update(_exception_aliases_from_expr(node.exc))
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        targets = _raw_call_targets(node.func)
        if any(_is_exception_target(target) for target in targets):
            self.exception_aliases.update(_exception_aliases_from_expr(node.func))

        if any(_is_pytest_raises_target(target) for target in targets) and node.args:
            self.exception_aliases.update(_exception_aliases_from_expr(node.args[0]))

        for keyword in node.keywords:
            if keyword.arg == "side_effect":
                self.exception_aliases.update(
                    _exception_aliases_from_expr(keyword.value)
                )

        self.generic_visit(node)


def _raw_call_targets(node: ast.AST) -> set[str]:
    if isinstance(node, ast.Name):
        return {node.id}
    if isinstance(node, ast.Attribute):
        return {_attribute_name(node), node.attr}
    return set()


def _is_pytest_raises_target(target: str) -> bool:
    return (
        target == "raises"
        or target == "pytest.raises"
        or target.endswith(".pytest.raises")
    )


def _is_exception_target(target: str) -> bool:
    exception_name = target.rsplit(".", 1)[-1]
    return exception_name.endswith(("Error", "Exception"))


def _exception_aliases_from_expr(node: ast.AST | None) -> set[str]:
    if node is None:
        return set()

    if isinstance(node, ast.Call):
        return _exception_aliases_from_expr(node.func)

    if isinstance(node, ast.Name):
        return set(_exception_aliases(node.id))

    if isinstance(node, ast.Attribute):
        return set(_exception_aliases(_attribute_name(node)))

    if isinstance(node, ast.Tuple | ast.List | ast.Set):
        aliases: set[str] = set()
        for element in node.elts:
            aliases.update(_exception_aliases_from_expr(element))
        return aliases

    return set()


def _coverage_entry_matches_requirement(
    entry: CoverageEntry,
    requirement: ExceptionRequirement,
) -> bool:
    return _targets_match(
        entry.target, requirement.target
    ) and _exception_aliases_cover(
        requirement.exception_aliases,
        entry.exception_aliases,
    )


def _targets_match(candidate: str, target: str) -> bool:
    candidate = candidate.strip(".")
    target = target.strip(".")
    if not candidate or not target:
        return False
    if candidate == target:
        return True
    if target.endswith(f".{candidate}") or candidate.endswith(f".{target}"):
        return True
    return "." not in candidate and target.rsplit(".", 1)[-1] == candidate


def _exception_aliases_cover(
    requirement_aliases: frozenset[str],
    covered_aliases: frozenset[str],
) -> bool:
    if requirement_aliases & covered_aliases:
        return True

    broad_handlers = {"exception", "baseexception", "bare"}
    return bool(requirement_aliases & broad_handlers and covered_aliases)


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
