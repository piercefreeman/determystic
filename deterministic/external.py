"""External validation interface for agent-generated validators.

This module provides the standard interface that all agent-generated 
validators should use for consistent error reporting and validation results.
"""

import ast
from dataclasses import dataclass


@dataclass
class ValidationIssue:
    """Represents a single validation issue found in code."""
    
    line_number: int
    column_number: int | None = None
    message: str = ""
    code_snippet: str | None = None
    severity: str = "error"  # error, warning, info
    
    def __str__(self) -> str:
        """Format the issue for display."""
        parts = [f"Line {self.line_number}"]
        if self.column_number is not None:
            parts.append(f"Col {self.column_number}")
        parts.append(f": {self.message}")
        return " ".join(parts)


@dataclass 
class ValidationResult:
    """Result from running a validation check."""
    
    is_valid: bool
    issues: list[ValidationIssue] = None
    message: str | None = None
    
    def __post_init__(self):
        if self.issues is None:
            self.issues = []
    
    @property
    def formatted_message(self) -> str:
        """Get a formatted message with all issues."""
        if not self.issues:
            return self.message or ("✓ No issues found" if self.is_valid else "✗ Validation failed")
        
        parts = []
        for issue in self.issues:
            parts.append(str(issue))
            if issue.code_snippet:
                # Add indented code snippet
                snippet_lines = issue.code_snippet.strip().split('\n')
                for i, line in enumerate(snippet_lines):
                    parts.append(f"    {line}")
                    # Add pointer for the specific line if it's the first line
                    if i == 0 and issue.column_number is not None:
                        pointer = " " * (4 + issue.column_number) + "^"
                        parts.append(pointer)
        
        return "\n".join(parts)


def find_pattern_in_code(code: str, pattern: str, filename: str = "<string>") -> list[ValidationIssue]:
    """
    Find all occurrences of a pattern in code and return ValidationIssues with line context.
    
    Args:
        code: The source code to search
        pattern: The pattern to find (e.g., "Optional[")
        filename: Name of the file being checked
        
    Returns:
        List of ValidationIssue objects with line numbers and context
    """
    issues = []
    lines = code.split('\n')
    
    for line_num, line in enumerate(lines, 1):
        if pattern in line:
            # Find the column position
            col_pos = line.find(pattern)
            
            # Get surrounding context (current line + 1 before/after if available)
            context_lines = []
            start_line = max(0, line_num - 2)
            end_line = min(len(lines), line_num + 1)
            
            for ctx_line_num in range(start_line, end_line):
                prefix = ">>> " if ctx_line_num + 1 == line_num else "    "
                context_lines.append(f"{prefix}{lines[ctx_line_num]}")
            
            code_snippet = "\n".join(context_lines)
            
            issue = ValidationIssue(
                line_number=line_num,
                column_number=col_pos,
                message=f"Found '{pattern}' in {filename}",
                code_snippet=code_snippet
            )
            issues.append(issue)
    
    return issues


def create_issue_with_context(
    code: str, 
    line_number: int, 
    message: str, 
    column_number: int | None = None,
    context_lines: int = 2
) -> ValidationIssue:
    """
    Create a ValidationIssue with code context around the specified line.
    
    Args:
        code: The source code
        line_number: Line number where the issue occurs (1-indexed)
        message: Description of the issue
        column_number: Optional column position
        context_lines: Number of lines of context to include before/after
        
    Returns:
        ValidationIssue with formatted code context
    """
    lines = code.split('\n')
    
    # Calculate context range
    start_line = max(0, line_number - context_lines - 1)
    end_line = min(len(lines), line_number + context_lines)
    
    # Build context with line numbers
    context_parts = []
    for i in range(start_line, end_line):
        line_content = lines[i]
        line_num = i + 1
        
        if line_num == line_number:
            # Highlight the problem line
            context_parts.append(f">>> {line_num:3d} | {line_content}")
        else:
            context_parts.append(f"    {line_num:3d} | {line_content}")
    
    code_snippet = "\n".join(context_parts)
    
    return ValidationIssue(
        line_number=line_number,
        column_number=column_number, 
        message=message,
        code_snippet=code_snippet
    )


class DeterministicTraverser(ast.NodeVisitor):
    """Base class for all deterministic AST validators.
    
    This class provides a structured way to traverse the AST and collect
    validation errors with proper line numbers and code context.
    """
    
    def __init__(self, code: str, filename: str = "<string>"):
        """Initialize the traverser.
        
        Args:
            code: The source code being validated
            filename: Name of the file being validated
        """
        self.code = code
        self.filename = filename
        self.errors: list[ValidationIssue] = []
        self._lines = code.split('\n')
    
    def add_error(
        self, 
        node: ast.AST, 
        message: str, 
        column_offset: int | None = None,
        context_lines: int = 2
    ) -> None:
        """Add a validation error for the given AST node.
        
        Args:
            node: The AST node where the error occurs
            message: Description of the error
            column_offset: Optional column offset override
            context_lines: Number of context lines to include
        """
        line_number = getattr(node, 'lineno', 1)
        col_number = column_offset or getattr(node, 'col_offset', None)
        
        issue = create_issue_with_context(
            code=self.code,
            line_number=line_number,
            message=message,
            column_number=col_number,
            context_lines=context_lines
        )
        
        self.errors.append(issue)
    
    def add_error_at_line(
        self, 
        line_number: int, 
        message: str, 
        column_number: int | None = None,
        context_lines: int = 2
    ) -> None:
        """Add a validation error at a specific line number.
        
        Args:
            line_number: Line number where the error occurs
            message: Description of the error
            column_number: Optional column position
            context_lines: Number of context lines to include
        """
        issue = create_issue_with_context(
            code=self.code,
            line_number=line_number,
            message=message,
            column_number=column_number,
            context_lines=context_lines
        )
        
        self.errors.append(issue)
    
    def validate(self) -> ValidationResult:
        """Run the validation by parsing and traversing the AST.
        
        Returns:
            ValidationResult with all collected errors
        """
        try:
            tree = ast.parse(self.code, filename=self.filename)
            self.visit(tree)
        except SyntaxError as e:
            # Add syntax error as a validation issue
            self.add_error_at_line(
                line_number=e.lineno or 1,
                message=f"Syntax error: {e.msg}",
                column_number=e.offset
            )
        
        return ValidationResult(
            is_valid=len(self.errors) == 0,
            issues=self.errors,
            message=None if len(self.errors) == 0 else f"Found {len(self.errors)} issue(s)"
        )
    