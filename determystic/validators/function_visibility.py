"""Function visibility validator for public/private ordering and naming.

This validator builds a project-level import graph for Python modules, then uses
that graph to distinguish definitions used by other files/classes from helpers
used only inside their defining file or class.
"""

import ast
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from determystic.configs.project import ProjectConfigManager
from determystic.suppressions import SuppressionComments
from determystic.validators.base import BaseValidator, ValidationResult


ParentKey = tuple[str, str, str | None]


@dataclass(frozen=True)
class DefinitionKey:
    """Unique key for a module function or class method."""

    module_path: str
    class_name: str | None
    name: str


@dataclass(frozen=True)
class ClassRef:
    """Reference to a known project class."""

    module_path: str
    class_name: str


@dataclass(frozen=True)
class ImportedSymbol:
    """Imported symbol binding from a project module."""

    module_name: str
    symbol_name: str


@dataclass
class FunctionDefinition:
    """A function or method definition that can be checked for visibility."""

    key: DefinitionKey
    line_number: int
    has_decorators: bool
    parent_key: ParentKey

    @property
    def name(self) -> str:
        return self.key.name

    @property
    def is_method(self) -> bool:
        return self.key.class_name is not None

    @property
    def is_private(self) -> bool:
        return self.name.startswith("_") and not self.name.startswith("__")

    @property
    def is_dunder(self) -> bool:
        return self.name.startswith("__") and self.name.endswith("__")

    @property
    def qualified_name(self) -> str:
        if self.key.class_name:
            return f"{self.key.class_name}.{self.name}"
        return self.name


@dataclass
class ModuleInfo:
    """Parsed project module and its import/definition metadata."""

    path: Path
    relative_path: str
    module_names: list[str]
    tree: ast.Module
    functions: dict[str, FunctionDefinition] = field(default_factory=dict)
    classes: dict[str, dict[str, FunctionDefinition]] = field(default_factory=dict)
    definitions_by_parent: dict[ParentKey, list[FunctionDefinition]] = field(default_factory=dict)
    module_bindings: dict[str, str] = field(default_factory=dict)
    symbol_bindings: dict[str, ImportedSymbol] = field(default_factory=dict)
    explicit_exports: set[str] = field(default_factory=set)
    suppressions: SuppressionComments = field(default_factory=SuppressionComments.empty)

    @property
    def canonical_module(self) -> str:
        return self.module_names[0]


@dataclass
class ProjectIndex:
    """Project-wide lookup tables used for reference resolution."""

    modules_by_path: dict[str, ModuleInfo]
    modules_by_name: dict[str, ModuleInfo]


@dataclass
class ReferenceIndex:
    """Internal and external references to project definitions."""

    internal: set[DefinitionKey] = field(default_factory=set)
    external: set[DefinitionKey] = field(default_factory=set)


class DefinitionCollector:
    """Collect module-level functions and direct class methods."""

    def __init__(self, module: ModuleInfo) -> None:
        self.module = module

    def collect(self) -> None:
        self._collect_module_body(self.module.tree.body)
        self.module.explicit_exports = self._collect_explicit_exports(self.module.tree.body)

    def _collect_module_body(self, body: list[ast.stmt]) -> None:
        parent_key = self._module_parent_key()
        self.module.definitions_by_parent.setdefault(parent_key, [])

        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                definition = self._create_definition(node, None, parent_key)
                self.module.functions[definition.name] = definition
                self.module.definitions_by_parent[parent_key].append(definition)
            elif isinstance(node, ast.ClassDef):
                self._collect_class_body(node, [])

    def _collect_class_body(self, node: ast.ClassDef, class_stack: list[str]) -> None:
        class_name = ".".join([*class_stack, node.name])
        parent_key = self._class_parent_key(class_name)
        self.module.classes.setdefault(class_name, {})
        self.module.definitions_by_parent.setdefault(parent_key, [])

        for child in node.body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                definition = self._create_definition(child, class_name, parent_key)
                self.module.classes[class_name][definition.name] = definition
                self.module.definitions_by_parent[parent_key].append(definition)
            elif isinstance(child, ast.ClassDef):
                self._collect_class_body(child, [*class_stack, node.name])

    def _create_definition(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        class_name: str | None,
        parent_key: ParentKey,
    ) -> FunctionDefinition:
        return FunctionDefinition(
            key=DefinitionKey(
                module_path=self.module.relative_path,
                class_name=class_name,
                name=node.name,
            ),
            line_number=node.lineno,
            has_decorators=bool(node.decorator_list),
            parent_key=parent_key,
        )

    def _module_parent_key(self) -> ParentKey:
        return ("module", self.module.relative_path, None)

    def _class_parent_key(self, class_name: str) -> ParentKey:
        return ("class", self.module.relative_path, class_name)

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


class ReferenceCollector(ast.NodeVisitor):
    """Collect references to project functions and methods."""

    def __init__(self, module: ModuleInfo, project: ProjectIndex, references: ReferenceIndex) -> None:
        self.module = module
        self.project = project
        self.references = references
        self.class_stack: list[str] = []
        self.scope_stack: list[dict[str, ClassRef]] = [{}]

    def visit_Import(self, node: ast.Import) -> None:
        return

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        return

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.class_stack.append(node.name)
        self.scope_stack.append({})
        for child in node.body:
            self.visit(child)
        self.scope_stack.pop()
        self.class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function_body(node.body)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function_body(node.body)

    def visit_Assign(self, node: ast.Assign) -> None:
        class_ref = self._infer_expr_class(node.value)
        if class_ref:
            for target in node.targets:
                self._bind_assignment_target(target, class_ref)
        self.visit(node.value)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None:
            class_ref = self._infer_expr_class(node.value)
            if class_ref:
                self._bind_assignment_target(node.target, class_ref)
            self.visit(node.value)

    def visit_Call(self, node: ast.Call) -> None:
        self._record_callable_reference(node.func)
        for arg in node.args:
            self.visit(arg)
        for keyword in node.keywords:
            self.visit(keyword.value)

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load):
            function_key = self._resolve_function_name(node.id)
            if function_key:
                self._record_definition_reference(function_key)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if isinstance(node.ctx, ast.Load):
            self._record_callable_reference(node)
        self.generic_visit(node)

    def _visit_function_body(self, body: list[ast.stmt]) -> None:
        self.scope_stack.append({})
        for child in body:
            self.visit(child)
        self.scope_stack.pop()

    def _bind_assignment_target(self, target: ast.expr, class_ref: ClassRef) -> None:
        if isinstance(target, ast.Name):
            self.scope_stack[-1][target.id] = class_ref
        elif isinstance(target, (ast.Tuple, ast.List)):
            for element in target.elts:
                self._bind_assignment_target(element, class_ref)

    def _record_callable_reference(self, node: ast.expr) -> None:
        if isinstance(node, ast.Name):
            function_key = self._resolve_function_name(node.id)
            if function_key:
                self._record_definition_reference(function_key)
            return

        if not isinstance(node, ast.Attribute):
            return

        method_key = self._resolve_method_attribute(node)
        if method_key:
            self._record_definition_reference(method_key)
            return

        function_key = self._resolve_function_attribute(node)
        if function_key:
            self._record_definition_reference(function_key)

    def _record_definition_reference(self, key: DefinitionKey) -> None:
        if key.class_name is None:
            if key.module_path == self.module.relative_path:
                self.references.internal.add(key)
            else:
                self.references.external.add(key)
            return

        if key.module_path == self.module.relative_path and key.class_name == self._current_class_name():
            self.references.internal.add(key)
        else:
            self.references.external.add(key)

    def _resolve_function_name(self, name: str) -> DefinitionKey | None:
        symbol = self.module.symbol_bindings.get(name)
        if symbol:
            target_module = self.project.modules_by_name.get(symbol.module_name)
            if target_module and symbol.symbol_name in target_module.functions:
                return target_module.functions[symbol.symbol_name].key

        if name in self.module.functions:
            return self.module.functions[name].key

        return None

    def _resolve_function_attribute(self, node: ast.Attribute) -> DefinitionKey | None:
        parts = self._dotted_parts(node)
        if not parts:
            return None

        for prefix_length in range(len(parts) - 1, 0, -1):
            prefix = ".".join(parts[:prefix_length])
            target_module_name = self.module.module_bindings.get(prefix)
            if not target_module_name:
                continue

            target_module = self.project.modules_by_name.get(target_module_name)
            symbol_name = parts[prefix_length]
            if (
                target_module
                and prefix_length == len(parts) - 1
                and symbol_name in target_module.functions
            ):
                return target_module.functions[symbol_name].key

        return None

    def _resolve_method_attribute(self, node: ast.Attribute) -> DefinitionKey | None:
        receiver_class = self._infer_expr_class(node.value)
        if not receiver_class:
            return None

        target_module = self.project.modules_by_path.get(receiver_class.module_path)
        if not target_module:
            return None

        methods = target_module.classes.get(receiver_class.class_name, {})
        definition = methods.get(node.attr)
        if definition:
            return definition.key
        return None

    def _infer_expr_class(self, node: ast.expr) -> ClassRef | None:
        if isinstance(node, ast.Call):
            return self._resolve_class_expr(node.func)

        if isinstance(node, ast.Name):
            if node.id in {"self", "cls"} and self._current_class_name():
                return ClassRef(
                    module_path=self.module.relative_path,
                    class_name=self._current_class_name() or "",
                )

            bound_class = self._lookup_bound_class(node.id)
            if bound_class:
                return bound_class

        return self._resolve_class_expr(node)

    def _resolve_class_expr(self, node: ast.expr) -> ClassRef | None:
        if isinstance(node, ast.Name):
            symbol = self.module.symbol_bindings.get(node.id)
            if symbol:
                target_module = self.project.modules_by_name.get(symbol.module_name)
                if target_module and symbol.symbol_name in target_module.classes:
                    return ClassRef(target_module.relative_path, symbol.symbol_name)

            if node.id in self.module.classes:
                return ClassRef(self.module.relative_path, node.id)

            return self._lookup_bound_class(node.id)

        if not isinstance(node, ast.Attribute):
            return None

        parts = self._dotted_parts(node)
        if not parts:
            return None

        for prefix_length in range(len(parts), 0, -1):
            prefix = ".".join(parts[:prefix_length])
            target_module_name = self.module.module_bindings.get(prefix)
            if not target_module_name:
                continue

            target_module = self.project.modules_by_name.get(target_module_name)
            if not target_module:
                continue

            remaining_parts = parts[prefix_length:]
            if len(remaining_parts) == 1 and remaining_parts[0] in target_module.classes:
                return ClassRef(target_module.relative_path, remaining_parts[0])

        return None

    def _lookup_bound_class(self, name: str) -> ClassRef | None:
        for scope in reversed(self.scope_stack):
            bound_class = scope.get(name)
            if bound_class:
                return bound_class
        return None

    def _current_class_name(self) -> str | None:
        if not self.class_stack:
            return None
        return ".".join(self.class_stack)

    def _dotted_parts(self, node: ast.expr) -> list[str] | None:
        if isinstance(node, ast.Name):
            return [node.id]
        if isinstance(node, ast.Attribute):
            value_parts = self._dotted_parts(node.value)
            if value_parts is None:
                return None
            return [*value_parts, node.attr]
        return None


class FunctionVisibilityValidator(BaseValidator):
    """Validate function visibility naming and ordering."""

    def __init__(self, *, name: str = "function_visibility", path: Path | None = None) -> None:
        super().__init__(name=name, path=path)

    @classmethod
    def create_validators(cls, config_manager: ProjectConfigManager) -> list["BaseValidator"]:
        """Create the built-in function visibility validator."""
        return [cls(path=config_manager.project_root)]

    async def validate(self) -> ValidationResult:
        """Validate function visibility across the project."""
        if self.path is None:
            return ValidationResult(success=True, output="No project path configured")

        python_files = self._get_python_files(self.path)
        if not python_files:
            return ValidationResult(success=True, output="No Python files found")

        project = self._build_project_index(python_files)
        references = self._collect_references(project)
        script_entrypoints = self._get_script_entrypoints(self.path)
        issues = self._find_issues(project, references, script_entrypoints)

        if not issues:
            return ValidationResult(success=True, output="No function visibility issues found")

        return ValidationResult(success=False, output="\n".join(issues))

    def _get_python_files(self, path: Path) -> list[Path]:
        """Get Python files that should be included in project analysis."""
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

    def _build_project_index(self, python_files: list[Path]) -> ProjectIndex:
        modules_by_path: dict[str, ModuleInfo] = {}
        modules_by_name: dict[str, ModuleInfo] = {}

        for py_file in python_files:
            try:
                content = py_file.read_text(encoding="utf-8")
                tree = ast.parse(content, filename=str(py_file))
            except (SyntaxError, UnicodeDecodeError):
                continue

            relative_path = str(py_file.relative_to(self.path))
            module_names = self._module_names_for_file(py_file)
            if not module_names:
                continue

            module = ModuleInfo(
                path=py_file,
                relative_path=relative_path,
                module_names=module_names,
                tree=tree,
                suppressions=SuppressionComments.from_source(content, tree),
            )
            modules_by_path[relative_path] = module

            for module_name in module_names:
                modules_by_name.setdefault(module_name, module)

        project = ProjectIndex(modules_by_path=modules_by_path, modules_by_name=modules_by_name)

        for module in modules_by_path.values():
            DefinitionCollector(module).collect()

        for module in modules_by_path.values():
            self._collect_import_bindings(module, project)

        return project

    def _module_names_for_file(self, py_file: Path) -> list[str]:
        if self.path is None:
            return []

        relative_path = py_file.relative_to(self.path)
        path_parts = list(relative_path.parts)
        module_names = []

        if path_parts and path_parts[0] == "src" and len(path_parts) > 1:
            src_name = self._module_name_from_parts(path_parts[1:])
            if src_name:
                module_names.append(src_name)

        full_name = self._module_name_from_parts(path_parts)
        if full_name and full_name not in module_names:
            module_names.append(full_name)

        return module_names

    def _module_name_from_parts(self, path_parts: list[str]) -> str | None:
        if not path_parts:
            return None

        module_parts = list(path_parts)
        if module_parts[-1] == "__init__.py":
            module_parts = module_parts[:-1]
        else:
            module_parts[-1] = Path(module_parts[-1]).stem

        if not module_parts:
            return None

        return ".".join(module_parts)

    def _collect_import_bindings(self, module: ModuleInfo, project: ProjectIndex) -> None:
        for node in module.tree.body:
            if isinstance(node, ast.Import):
                self._collect_import(node, module, project)
            elif isinstance(node, ast.ImportFrom):
                self._collect_import_from(node, module, project)

    def _collect_import(self, node: ast.Import, module: ModuleInfo, project: ProjectIndex) -> None:
        for alias in node.names:
            target_module = project.modules_by_name.get(alias.name)
            if not target_module:
                continue

            binding_name = alias.asname or alias.name
            module.module_bindings[binding_name] = target_module.canonical_module

    def _collect_import_from(
        self,
        node: ast.ImportFrom,
        module: ModuleInfo,
        project: ProjectIndex,
    ) -> None:
        target_module_name = self._resolve_import_from_module(node, module, project)
        if not target_module_name:
            return

        target_module = project.modules_by_name.get(target_module_name)
        if not target_module:
            return

        for alias in node.names:
            if alias.name == "*":
                self._collect_star_import(module, target_module)
                continue

            binding_name = alias.asname or alias.name
            possible_module_name = f"{target_module.canonical_module}.{alias.name}"
            if possible_module_name in project.modules_by_name:
                module.module_bindings[binding_name] = possible_module_name
                continue

            module.symbol_bindings[binding_name] = ImportedSymbol(
                module_name=target_module.canonical_module,
                symbol_name=alias.name,
            )

    def _collect_star_import(self, module: ModuleInfo, target_module: ModuleInfo) -> None:
        exported_names = target_module.explicit_exports
        if not exported_names:
            exported_names = set(target_module.functions) | set(target_module.classes)

        for name in exported_names:
            module.symbol_bindings[name] = ImportedSymbol(
                module_name=target_module.canonical_module,
                symbol_name=name,
            )

    def _resolve_import_from_module(
        self,
        node: ast.ImportFrom,
        module: ModuleInfo,
        project: ProjectIndex,
    ) -> str | None:
        if node.level == 0:
            module_name = node.module or ""
            if module_name in project.modules_by_name:
                return project.modules_by_name[module_name].canonical_module
            return None

        current_parts = module.canonical_module.split(".")
        if module.path.name != "__init__.py":
            current_parts = current_parts[:-1]

        base_length = len(current_parts) - node.level + 1
        if base_length < 0:
            return None

        target_parts = current_parts[:base_length]
        if node.module:
            target_parts.extend(node.module.split("."))

        module_name = ".".join(target_parts)
        if module_name in project.modules_by_name:
            return project.modules_by_name[module_name].canonical_module
        return None

    def _collect_references(self, project: ProjectIndex) -> ReferenceIndex:
        references = ReferenceIndex()
        for module in project.modules_by_path.values():
            ReferenceCollector(module, project, references).visit(module.tree)
        return references

    def _find_issues(
        self,
        project: ProjectIndex,
        references: ReferenceIndex,
        script_entrypoints: set[str],
    ) -> list[str]:
        issues: list[str] = []

        for module in project.modules_by_path.values():
            for definition in self._all_definitions(module):
                if (
                    self._requires_private_prefix(definition, module, references, script_entrypoints)
                    and not module.suppressions.suppresses(definition.line_number, "private-prefix")
                ):
                    issues.append(self._format_naming_issue(definition))

            for definitions in module.definitions_by_parent.values():
                issues.extend(
                    self._find_ordering_issues(module, definitions, references, script_entrypoints)
                )

        return issues

    def _all_definitions(self, module: ModuleInfo) -> list[FunctionDefinition]:
        definitions = list(module.functions.values())
        for methods in module.classes.values():
            definitions.extend(methods.values())
        return definitions

    def _requires_private_prefix(
        self,
        definition: FunctionDefinition,
        module: ModuleInfo,
        references: ReferenceIndex,
        script_entrypoints: set[str],
    ) -> bool:
        if definition.is_private or self._is_special_public(definition, module, script_entrypoints):
            return False

        return definition.key in references.internal and definition.key not in references.external

    def _find_ordering_issues(
        self,
        module: ModuleInfo,
        definitions: list[FunctionDefinition],
        references: ReferenceIndex,
        script_entrypoints: set[str],
    ) -> list[str]:
        issues = []
        first_private_definition: FunctionDefinition | None = None

        for definition in definitions:
            if self._is_private_for_ordering(definition, module, references, script_entrypoints):
                first_private_definition = first_private_definition or definition
                continue

            if first_private_definition is not None:
                if module.suppressions.suppresses(
                    definition.line_number,
                    "function-order",
                    fallback_line=first_private_definition.line_number,
                ):
                    continue
                issues.append(self._format_ordering_issue(definition, first_private_definition))

        return issues

    def _is_private_for_ordering(
        self,
        definition: FunctionDefinition,
        module: ModuleInfo,
        references: ReferenceIndex,
        script_entrypoints: set[str],
    ) -> bool:
        if self._is_special_public(definition, module, script_entrypoints):
            return False

        if definition.is_private:
            return True

        return definition.key in references.internal and definition.key not in references.external

    def _is_special_public(
        self,
        definition: FunctionDefinition,
        module: ModuleInfo,
        script_entrypoints: set[str],
    ) -> bool:
        if definition.is_dunder or definition.has_decorators:
            return True

        if definition.is_method:
            return False

        return definition.name in module.explicit_exports or definition.name in script_entrypoints

    def _format_naming_issue(self, definition: FunctionDefinition) -> str:
        if definition.is_method:
            return (
                f"{definition.key.module_path}:{definition.line_number}: "
                f"Method '{definition.qualified_name}' is only used within its class; "
                "prefix it with '_'"
            )

        return (
            f"{definition.key.module_path}:{definition.line_number}: "
            f"Function '{definition.name}' is only used within this file; prefix it with '_'"
        )

    def _format_ordering_issue(
        self,
        public_definition: FunctionDefinition,
        private_definition: FunctionDefinition,
    ) -> str:
        if public_definition.is_method:
            return (
                f"{public_definition.key.module_path}:{public_definition.line_number}: "
                f"Public method '{public_definition.qualified_name}' should be defined before "
                f"private/internal method '{private_definition.qualified_name}'"
            )

        return (
            f"{public_definition.key.module_path}:{public_definition.line_number}: "
            f"Public function '{public_definition.name}' should be defined before "
            f"private/internal function '{private_definition.name}'"
        )

    def _get_script_entrypoints(self, path: Path) -> set[str]:
        """Extract script entrypoint function names from pyproject.toml."""
        pyproject_path = path / "pyproject.toml"
        entrypoints = set()

        if not pyproject_path.exists():
            return entrypoints

        try:
            with open(pyproject_path, "rb") as f:
                data = tomllib.load(f)

            scripts = data.get("project", {}).get("scripts", {})
            for script_path in scripts.values():
                if ":" in script_path:
                    _, func_name = script_path.split(":", 1)
                    entrypoints.add(func_name)
        except (tomllib.TOMLDecodeError, KeyError, ValueError):
            pass

        return entrypoints
