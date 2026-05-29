"""Dead-code validator for unused definitions, arguments, and unreachable code.

This validator intentionally targets the highest-signal checks from tools like
Vulture without trying to model every dynamic Python pattern. It is opt-in
because exported library APIs, framework callbacks, and plugin entrypoints can
legitimately look unused from inside a single codebase.
"""

import ast
import tomllib
from dataclasses import dataclass
from pathlib import Path

from determystic.configs.project import ProjectConfigManager
from determystic.suppressions import SuppressionComments
from determystic.validators.base import BaseValidator, ValidationResult

TERMINAL_STATEMENTS = (ast.Return, ast.Raise, ast.Break, ast.Continue)


@dataclass
class SymbolDef:
    """A function, method, or class definition that can be checked for usage."""

    name: str
    module_path: str
    line_number: int
    kind: str
    qualified_name: str
    has_decorators: bool = False
    is_dunder: bool = False
    is_exported: bool = False


@dataclass
class ArgumentDef:
    """A function or method argument that can be checked for usage."""

    name: str
    module_path: str
    line_number: int
    function_line_number: int
    function_name: str
    qualified_function_name: str
    is_method: bool


@dataclass
class UnreachableStatement:
    """A statement that cannot be reached during normal control flow."""

    module_path: str
    line_number: int


class ReferenceCollector(ast.NodeVisitor):
    """Collect name and attribute references across a parsed module."""

    def __init__(self) -> None:
        self.name_references: set[str] = set()
        self.attribute_references: set[str] = set()

    def visit_Call(self, node: ast.Call) -> None:
        """Visit function, class, and method calls."""
        if isinstance(node.func, ast.Name):
            self.name_references.add(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            self.attribute_references.add(node.func.attr)
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        """Visit name references, including function references without calls."""
        if isinstance(node.ctx, ast.Load):
            self.name_references.add(node.id)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        """Visit attribute references so method references can mark methods as used."""
        if isinstance(node.ctx, ast.Load):
            self.attribute_references.add(node.attr)
        self.generic_visit(node)


class ArgumentUsageCollector(ast.NodeVisitor):
    """Collect local argument references within one function body."""

    def __init__(self) -> None:
        self.name_references: set[str] = set()

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load):
            self.name_references.add(node.id)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.generic_visit(node)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self.generic_visit(node)


class DefinitionCollector(ast.NodeVisitor):
    """Collect functions, methods, classes, and unused arguments."""

    def __init__(self, module_path: str, exported_names: set[str]) -> None:
        self.module_path = module_path
        self.exported_names = exported_names
        self.symbols: list[SymbolDef] = []
        self.arguments: list[ArgumentDef] = []
        self.class_stack: list[str] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        class_name = ".".join([*self.class_stack, node.name])
        self.symbols.append(
            SymbolDef(
                name=node.name,
                module_path=self.module_path,
                line_number=node.lineno,
                kind="class",
                qualified_name=class_name,
                has_decorators=bool(node.decorator_list),
                is_exported=node.name in self.exported_names,
            )
        )

        self.class_stack.append(node.name)
        self.generic_visit(node)
        self.class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._process_function(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._process_function(node)
        self.generic_visit(node)

    def _process_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        is_method = bool(self.class_stack)
        is_dunder = node.name.startswith("__") and node.name.endswith("__")
        qualified_name = ".".join([*self.class_stack, node.name])
        self.symbols.append(
            SymbolDef(
                name=node.name,
                module_path=self.module_path,
                line_number=node.lineno,
                kind="method" if is_method else "function",
                qualified_name=qualified_name,
                has_decorators=bool(node.decorator_list),
                is_dunder=is_dunder,
                is_exported=node.name in self.exported_names,
            )
        )

        if is_dunder or node.decorator_list:
            return

        if is_method and node.name.startswith("visit_"):
            return

        usage_collector = ArgumentUsageCollector()
        for statement in node.body:
            usage_collector.visit(statement)

        for argument in _iter_arguments(node.args):
            if _should_skip_argument(argument.arg, is_method):
                continue
            if argument.arg in usage_collector.name_references:
                continue

            self.arguments.append(
                ArgumentDef(
                    name=argument.arg,
                    module_path=self.module_path,
                    line_number=getattr(argument, "lineno", node.lineno),
                    function_line_number=node.lineno,
                    function_name=node.name,
                    qualified_function_name=qualified_name,
                    is_method=is_method,
                )
            )


class UnreachableCodeCollector(ast.NodeVisitor):
    """Collect statements that appear after terminal control-flow statements."""

    def __init__(self, module_path: str) -> None:
        self.module_path = module_path
        self.statements: list[UnreachableStatement] = []

    def visit_Module(self, node: ast.Module) -> None:
        self._visit_body(node.body)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._visit_body(node.body)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_body(node.body)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_body(node.body)

    def visit_If(self, node: ast.If) -> None:
        self.visit(node.test)
        self._visit_body(node.body)
        self._visit_body(node.orelse)

    def visit_For(self, node: ast.For) -> None:
        self.visit(node.target)
        self.visit(node.iter)
        self._visit_body(node.body)
        self._visit_body(node.orelse)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self.visit(node.target)
        self.visit(node.iter)
        self._visit_body(node.body)
        self._visit_body(node.orelse)

    def visit_While(self, node: ast.While) -> None:
        self.visit(node.test)
        self._visit_body(node.body)
        self._visit_body(node.orelse)

    def visit_With(self, node: ast.With) -> None:
        for item in node.items:
            self.visit(item.context_expr)
            if item.optional_vars is not None:
                self.visit(item.optional_vars)
        self._visit_body(node.body)

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:
        for item in node.items:
            self.visit(item.context_expr)
            if item.optional_vars is not None:
                self.visit(item.optional_vars)
        self._visit_body(node.body)

    def visit_Try(self, node: ast.Try) -> None:
        self._visit_body(node.body)
        for handler in node.handlers:
            self._visit_body(handler.body)
        self._visit_body(node.orelse)
        self._visit_body(node.finalbody)

    def visit_Match(self, node: ast.Match) -> None:
        self.visit(node.subject)
        for case in node.cases:
            if case.guard is not None:
                self.visit(case.guard)
            self._visit_body(case.body)

    def _visit_body(self, body: list[ast.stmt]) -> None:
        is_unreachable = False

        for statement in body:
            if is_unreachable:
                self.statements.append(
                    UnreachableStatement(
                        module_path=self.module_path,
                        line_number=statement.lineno,
                    )
                )
            self.visit(statement)
            if _statement_terminates(statement):
                is_unreachable = True


class HangingFunctionsValidator(BaseValidator):
    """Validator that detects unused definitions, arguments, and unreachable code."""

    def __init__(self, *, name: str = "hanging_functions", path: Path | None = None) -> None:
        super().__init__(name=name, path=path)

    @classmethod
    def create_validators(cls, config_manager: ProjectConfigManager) -> list["BaseValidator"]:
        """Factory function that creates a single dead-code validator instance."""
        return [cls(path=config_manager.project_root)]

    async def validate(self) -> ValidationResult:
        """Validate the codebase for dead code."""
        python_files = self._get_python_files(self.path)

        if not python_files:
            return ValidationResult(success=True, output="No Python files found")

        script_entrypoints = self._get_script_entrypoints(self.path)
        all_symbols: list[SymbolDef] = []
        all_arguments: list[ArgumentDef] = []
        all_unreachable: list[UnreachableStatement] = []
        all_name_references: set[str] = set()
        all_attribute_references: set[str] = set()
        suppressions_by_module: dict[str, SuppressionComments] = {}

        for py_file in python_files:
            try:
                content = py_file.read_text(encoding="utf-8")
                tree = ast.parse(content, filename=str(py_file))
                relative_path = str(py_file.relative_to(self.path))
                suppressions = SuppressionComments.from_source(content, tree)
                suppressions_by_module[relative_path] = suppressions

                exported_names = self._collect_explicit_exports(tree.body)

                def_collector = DefinitionCollector(relative_path, exported_names)
                def_collector.visit(tree)
                all_symbols.extend(def_collector.symbols)
                all_arguments.extend(def_collector.arguments)

                reference_collector = ReferenceCollector()
                reference_collector.visit(tree)
                all_name_references.update(reference_collector.name_references)
                all_attribute_references.update(reference_collector.attribute_references)

                unreachable_collector = UnreachableCodeCollector(relative_path)
                unreachable_collector.visit(tree)
                all_unreachable.extend(unreachable_collector.statements)

            except (SyntaxError, UnicodeDecodeError):
                continue

        issues = [
            *self._find_unused_symbols(
                all_symbols,
                all_name_references,
                all_attribute_references,
                script_entrypoints,
                suppressions_by_module,
            ),
            *self._find_unused_arguments(all_arguments, suppressions_by_module),
            *self._find_unreachable_code(all_unreachable, suppressions_by_module),
        ]

        if not issues:
            return ValidationResult(success=True, output="No dead code found")

        return ValidationResult(success=False, output="\n".join(issues))

    def _get_python_files(self, path: Path) -> list[Path]:
        """Get all Python files, excluding test files and hidden directories."""
        python_files = list(path.rglob("*.py"))

        filtered_files = []
        for py_file in python_files:
            if any(part.startswith(".") for part in py_file.parts):
                continue
            if "__pycache__" in py_file.parts:
                continue

            file_name = py_file.name
            if (
                file_name.startswith("test_")
                or file_name.endswith("_test.py")
                or "__tests__" in py_file.parts
                or "tests" in py_file.parts
            ):
                continue

            filtered_files.append(py_file)

        return filtered_files

    def _get_script_entrypoints(self, path: Path) -> set[str]:
        """Extract script entrypoint function names from pyproject.toml."""
        pyproject_path = path / "pyproject.toml"
        entrypoints = set()

        if not pyproject_path.exists():
            return entrypoints

        try:
            with pyproject_path.open("rb") as file:
                data = tomllib.load(file)

            scripts = data.get("project", {}).get("scripts", {})
            for script_path in scripts.values():
                if ":" in script_path:
                    _, func_name = script_path.split(":", 1)
                    entrypoints.add(func_name)

        except (tomllib.TOMLDecodeError, KeyError, ValueError):
            pass

        return entrypoints

    def _collect_explicit_exports(self, body: list[ast.stmt]) -> set[str]:
        exports: set[str] = set()
        for node in body:
            if not isinstance(node, ast.Assign):
                continue

            assigns_all = any(
                isinstance(target, ast.Name) and target.id == "__all__"
                for target in node.targets
            )
            if not assigns_all or not isinstance(node.value, (ast.List, ast.Tuple)):
                continue

            for element in node.value.elts:
                if isinstance(element, ast.Constant) and isinstance(element.value, str):
                    exports.add(element.value)

        return exports

    def _find_unused_symbols(
        self,
        all_symbols: list[SymbolDef],
        all_name_references: set[str],
        all_attribute_references: set[str],
        script_entrypoints: set[str],
        suppressions_by_module: dict[str, SuppressionComments],
    ) -> list[str]:
        issues = []

        for symbol in all_symbols:
            code = f"unused-{symbol.kind}"
            suppressions = suppressions_by_module.get(symbol.module_path, SuppressionComments.empty())
            if suppressions.suppresses(symbol.line_number, code):
                continue
            if symbol.is_dunder or symbol.has_decorators or symbol.is_exported:
                continue
            if symbol.kind == "method" and symbol.name.startswith("visit_"):
                continue
            if symbol.kind == "function" and symbol.name in script_entrypoints:
                continue

            is_referenced = (
                symbol.name in all_name_references
                or symbol.name in all_attribute_references
            )
            if is_referenced:
                continue

            if symbol.kind == "class":
                issues.append(
                    f"{symbol.module_path}:{symbol.line_number}: "
                    f"Class '{symbol.qualified_name}' is defined but never referenced"
                )
            elif symbol.kind == "method":
                issues.append(
                    f"{symbol.module_path}:{symbol.line_number}: "
                    f"Method '{symbol.qualified_name}' is defined but never referenced"
                )
            else:
                issues.append(
                    f"{symbol.module_path}:{symbol.line_number}: "
                    f"Function '{symbol.name}' is defined but never referenced"
                )

        return issues

    def _find_unused_arguments(
        self,
        all_arguments: list[ArgumentDef],
        suppressions_by_module: dict[str, SuppressionComments],
    ) -> list[str]:
        issues = []

        for argument in all_arguments:
            suppressions = suppressions_by_module.get(argument.module_path, SuppressionComments.empty())
            if suppressions.suppresses(
                argument.line_number,
                "unused-argument",
                fallback_line=argument.function_line_number,
            ):
                continue
            issues.append(
                f"{argument.module_path}:{argument.line_number}: "
                f"Argument '{argument.name}' in '{argument.qualified_function_name}' is never used"
            )

        return issues

    def _find_unreachable_code(
        self,
        all_unreachable: list[UnreachableStatement],
        suppressions_by_module: dict[str, SuppressionComments],
    ) -> list[str]:
        issues = []

        for statement in all_unreachable:
            suppressions = suppressions_by_module.get(statement.module_path, SuppressionComments.empty())
            if suppressions.suppresses(statement.line_number, "unreachable-code"):
                continue
            issues.append(
                f"{statement.module_path}:{statement.line_number}: "
                "Unreachable code after terminal statement"
            )

        return issues


def _iter_arguments(arguments: ast.arguments) -> list[ast.arg]:
    result = [
        *arguments.posonlyargs,
        *arguments.args,
        *arguments.kwonlyargs,
    ]
    if arguments.vararg is not None:
        result.append(arguments.vararg)
    if arguments.kwarg is not None:
        result.append(arguments.kwarg)
    return result


def _should_skip_argument(argument_name: str, is_method: bool) -> bool:
    if argument_name.startswith("_"):
        return True
    if is_method and argument_name in {"self", "cls"}:
        return True
    return False


def _statement_terminates(statement: ast.stmt) -> bool:
    if isinstance(statement, TERMINAL_STATEMENTS):
        return True
    if isinstance(statement, ast.If):
        return bool(statement.body and statement.orelse) and (
            _body_terminates(statement.body)
            and _body_terminates(statement.orelse)
        )
    if isinstance(statement, ast.Match):
        return bool(statement.cases) and all(
            _body_terminates(case.body)
            for case in statement.cases
        )
    return False


def _body_terminates(body: list[ast.stmt]) -> bool:
    return bool(body) and _statement_terminates(body[-1])
