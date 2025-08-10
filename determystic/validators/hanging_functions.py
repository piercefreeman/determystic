"""Hanging functions validator that detects unreferenced functions in the codebase.

This validator identifies functions that are defined but never called from anywhere
in the codebase. This is particularly useful for "vibe coded" applications that are
self-contained and not intended to be imported as libraries.

Many "vibe coded" apps are often self-contained (i.e., we're not building libraries
or needing to export an API). In such cases, if there's a hanging function, it's
likely just code slop that should be cleaned up. However, if you are building a
library intended for use in external codebases, this validator should be disabled
since exported functions may legitimately appear "hanging" from the perspective of
the library's internal code.
"""

import ast
import tomllib
from pathlib import Path
from typing import Set, List
from dataclasses import dataclass

from determystic.validators.base import BaseValidator, ValidationResult


@dataclass
class FunctionDef:
    """Represents a function definition in the codebase."""
    name: str
    module_path: str
    line_number: int
    is_method: bool = False
    is_private: bool = False
    is_dunder: bool = False


class FunctionCallCollector(ast.NodeVisitor):
    """AST visitor that collects all function calls and references."""
    
    def __init__(self, module_path: str) -> None:
        self.module_path = module_path
        self.function_calls: Set[str] = set()
        self.attribute_calls: Set[str] = set()
        
    def visit_Call(self, node: ast.Call) -> None:
        """Visit function calls."""
        if isinstance(node.func, ast.Name):
            self.function_calls.add(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            self.attribute_calls.add(node.func.attr)
        self.generic_visit(node)
    
    def visit_Name(self, node: ast.Name) -> None:
        """Visit name references (for function references without calls)."""
        if isinstance(node.ctx, (ast.Load,)):
            self.function_calls.add(node.id)
        self.generic_visit(node)
    
    def visit_Attribute(self, node: ast.Attribute) -> None:
        """Visit attribute references."""
        self.attribute_calls.add(node.attr)
        self.generic_visit(node)


class FunctionDefinitionCollector(ast.NodeVisitor):
    """AST visitor that collects all function definitions."""
    
    def __init__(self, module_path: str) -> None:
        self.module_path = module_path
        self.functions: List[FunctionDef] = []
        self.class_stack: List[str] = []
    
    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """Track when we're inside a class."""
        self.class_stack.append(node.name)
        self.generic_visit(node)
        self.class_stack.pop()
    
    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Visit function definitions."""
        self._process_function(node)
        self.generic_visit(node)
    
    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Visit async function definitions."""
        self._process_function(node)
        self.generic_visit(node)
    
    def _process_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        """Process a function definition node."""
        is_method = len(self.class_stack) > 0
        is_private = node.name.startswith('_') and not node.name.startswith('__')
        is_dunder = node.name.startswith('__') and node.name.endswith('__')
        
        func_def = FunctionDef(
            name=node.name,
            module_path=self.module_path,
            line_number=node.lineno,
            is_method=is_method,
            is_private=is_private,
            is_dunder=is_dunder
        )
        self.functions.append(func_def)


class HangingFunctionsValidator(BaseValidator):
    """Validator that detects functions defined but never referenced in the codebase."""
    
    def __init__(self, *, name: str = "hanging_functions", path: Path | None = None) -> None:
        super().__init__(name=name, path=path)
    
    @classmethod
    def create_validators(cls, path: Path) -> list["BaseValidator"]:
        """Factory function that creates a single HangingFunctionsValidator instance."""
        return [cls(path=path)]
    
    async def validate(self, path: Path) -> ValidationResult:
        """Validate the codebase for hanging functions."""
        # Find all Python files, excluding test files and hidden directories
        python_files = self._get_python_files(path)
        
        if not python_files:
            return ValidationResult(success=True, output="No Python files found")
        
        # Get script entrypoints from pyproject.toml
        script_entrypoints = self._get_script_entrypoints(path)
        
        # Collect all function definitions and calls
        all_functions: List[FunctionDef] = []
        all_calls: Set[str] = set()
        all_attribute_calls: Set[str] = set()
        
        for py_file in python_files:
            try:
                content = py_file.read_text(encoding='utf-8')
                tree = ast.parse(content, filename=str(py_file))
                relative_path = str(py_file.relative_to(path))
                
                # Collect function definitions
                def_collector = FunctionDefinitionCollector(relative_path)
                def_collector.visit(tree)
                all_functions.extend(def_collector.functions)
                
                # Collect function calls and references
                call_collector = FunctionCallCollector(relative_path)
                call_collector.visit(tree)
                all_calls.update(call_collector.function_calls)
                all_attribute_calls.update(call_collector.attribute_calls)
                
            except (SyntaxError, UnicodeDecodeError):
                # Skip files that can't be parsed
                continue
        
        # Find hanging functions
        hanging_functions = self._find_hanging_functions(
            all_functions, all_calls, all_attribute_calls, script_entrypoints
        )
        
        if not hanging_functions:
            return ValidationResult(success=True, output="No hanging functions found")
        
        # Format results
        issues = []
        for func in hanging_functions:
            issues.append(f"{func.module_path}:{func.line_number}: Function '{func.name}' is defined but never referenced")
        
        output = "\n".join(issues)
        return ValidationResult(success=False, output=output)
    
    def _get_python_files(self, path: Path) -> List[Path]:
        """Get all Python files, excluding test files and hidden directories."""
        python_files = list(path.rglob("*.py"))
        
        # Filter out hidden directories, test files, and __pycache__
        filtered_files = []
        for py_file in python_files:
            # Skip hidden directories
            if any(part.startswith('.') for part in py_file.parts):
                continue
                
            # Skip __pycache__ directories
            if '__pycache__' in py_file.parts:
                continue
            
            # Skip test files (test_*.py, *_test.py, or in __tests__ directories)
            file_name = py_file.name
            if (file_name.startswith('test_') or 
                file_name.endswith('_test.py') or 
                '__tests__' in py_file.parts or
                'tests' in py_file.parts):
                continue
            
            filtered_files.append(py_file)
        
        return filtered_files
    
    def _get_script_entrypoints(self, path: Path) -> Set[str]:
        """Extract script entrypoint function names from pyproject.toml."""
        pyproject_path = path / "pyproject.toml"
        entrypoints = set()
        
        if not pyproject_path.exists():
            return entrypoints
        
        try:
            with open(pyproject_path, 'rb') as f:
                data = tomllib.load(f)
            
            scripts = data.get('project', {}).get('scripts', {})
            for script_path in scripts.values():
                # Parse "module.path:function_name" format
                if ':' in script_path:
                    _, func_name = script_path.split(':', 1)
                    entrypoints.add(func_name)
                    
        except (tomllib.TOMLDecodeError, KeyError, ValueError):
            # If we can't parse the file, just continue without entrypoints
            pass
        
        return entrypoints
    
    def _find_hanging_functions(
        self, 
        all_functions: List[FunctionDef], 
        all_calls: Set[str], 
        all_attribute_calls: Set[str],
        script_entrypoints: Set[str]
    ) -> List[FunctionDef]:
        """Find functions that are defined but never referenced."""
        hanging_functions = []
        
        for func in all_functions:
            # Skip dunder methods (like __init__, __str__, etc.)
            if func.is_dunder:
                continue
            
            # Skip script entrypoints
            if func.name in script_entrypoints:
                continue
            
            # Check if function is referenced anywhere
            is_referenced = (
                func.name in all_calls or 
                func.name in all_attribute_calls
            )
            
            if not is_referenced:
                hanging_functions.append(func)
        
        return hanging_functions
