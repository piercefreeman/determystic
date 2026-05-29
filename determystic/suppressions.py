"""Shared suppression comment handling for determystic validators."""

import ast
import io
import tokenize
from dataclasses import dataclass


GLOBAL_SUPPRESSION_CODES = {"all", "lint", "determystic"}
GROUP_SUPPRESSION_CODES = {
    "dead-code": {
        "unused-function",
        "unused-method",
        "unused-class",
        "unused-argument",
        "unreachable-code",
    },
    "unused": {
        "unused-function",
        "unused-method",
        "unused-class",
        "unused-argument",
    },
    "used": {
        "unused-function",
        "unused-method",
        "unused-class",
        "unused-argument",
    },
    "function-visibility": {
        "private-prefix",
        "function-order",
    },
}


@dataclass(frozen=True)
class SuppressionRange:
    """A source line range where suppression codes apply."""

    start_line: int
    end_line: int
    codes: frozenset[str]

    def contains(self, line_number: int) -> bool:
        return self.start_line <= line_number <= self.end_line


@dataclass(frozen=True)
class ParsedSuppression:
    """One parsed determystic suppression comment."""

    line_number: int
    codes: frozenset[str]
    starts_block: bool = False
    ends_block: bool = False


class SuppressionComments:
    """Lookup table for determystic suppression comments.

    Supported forms:
    - ``# determystic: used``
    - ``# determystic: ignore``
    - ``# determystic: ignore[unused-function, function-order]``
    - ``# determystic: ignore-start[dead-code]`` / ``ignore-end[dead-code]``

    Line comments apply to the same line and the immediately following line.
    Comments on or immediately above a function/class definition apply to that
    definition's source range.
    """

    def __init__(
        self,
        line_codes: dict[int, set[str]],
        ranges: list[SuppressionRange] | None = None,
    ) -> None:
        self.line_codes = line_codes
        self.ranges = ranges or []

    @classmethod
    def empty(cls) -> "SuppressionComments":
        return cls({})

    @classmethod
    def from_source(
        cls,
        source: str,
        tree: ast.AST | None = None,
    ) -> "SuppressionComments":
        parsed_comments = cls._parse_source_comments(source)
        line_codes: dict[int, set[str]] = {}
        block_ranges = cls._block_ranges(parsed_comments, source)

        for parsed_comment in parsed_comments:
            if parsed_comment.starts_block or parsed_comment.ends_block:
                continue
            line_codes.setdefault(parsed_comment.line_number, set()).update(parsed_comment.codes)

        if tree is None:
            try:
                tree = ast.parse(source)
            except SyntaxError:
                tree = None

        definition_ranges = cls._definition_ranges(tree, line_codes) if tree is not None else []
        return cls(line_codes, [*block_ranges, *definition_ranges])

    def suppresses(
        self,
        line_number: int,
        code: str,
        *,
        fallback_line: int | None = None,
    ) -> bool:
        """Return whether the given issue code is suppressed for a line."""
        normalized_code = _normalize_code(code)
        candidate_lines = [line_number, line_number - 1]
        if fallback_line is not None:
            candidate_lines.extend([fallback_line, fallback_line - 1])

        for candidate_line in candidate_lines:
            if candidate_line < 1:
                continue
            if self._codes_suppress(self.line_codes.get(candidate_line, set()), normalized_code):
                return True

        for suppression_range in self.ranges:
            if not suppression_range.contains(line_number):
                continue
            if self._codes_suppress(suppression_range.codes, normalized_code):
                return True

        if fallback_line is not None:
            for suppression_range in self.ranges:
                if not suppression_range.contains(fallback_line):
                    continue
                if self._codes_suppress(suppression_range.codes, normalized_code):
                    return True

        return False

    @classmethod
    def _parse_source_comments(cls, source: str) -> list[ParsedSuppression]:
        parsed_comments: list[ParsedSuppression] = []

        try:
            tokens = tokenize.generate_tokens(io.StringIO(source).readline)
            for token in tokens:
                if token.type != tokenize.COMMENT:
                    continue
                parsed_comment = cls._parse_comment(token.start[0], token.string)
                if parsed_comment:
                    parsed_comments.append(parsed_comment)
        except tokenize.TokenError:
            return []

        return parsed_comments

    @staticmethod
    def _parse_comment(line_number: int, comment: str) -> ParsedSuppression | None:
        marker = "determystic:"
        marker_index = comment.lower().find(marker)
        if marker_index == -1:
            return None

        directive = comment[marker_index + len(marker):].strip()
        lowered_directive = directive.lower()
        if lowered_directive.startswith("used"):
            return ParsedSuppression(line_number, frozenset({"used"}))
        if lowered_directive.startswith(("ignore-start", "ignore-begin")):
            return ParsedSuppression(
                line_number,
                frozenset(_parse_codes(directive)),
                starts_block=True,
            )
        if lowered_directive.startswith("ignore-end"):
            return ParsedSuppression(
                line_number,
                frozenset(_parse_codes(directive)),
                ends_block=True,
            )
        if lowered_directive.startswith("ignore"):
            return ParsedSuppression(line_number, frozenset(_parse_codes(directive)))
        return None

    @classmethod
    def _block_ranges(
        cls,
        parsed_comments: list[ParsedSuppression],
        source: str,
    ) -> list[SuppressionRange]:
        ranges: list[SuppressionRange] = []
        open_blocks: list[ParsedSuppression] = []
        last_line = max(1, len(source.splitlines()))

        for parsed_comment in parsed_comments:
            if parsed_comment.starts_block:
                open_blocks.append(parsed_comment)
                continue

            if not parsed_comment.ends_block:
                continue

            matching_index = cls._matching_block_index(open_blocks, parsed_comment.codes)
            if matching_index is None:
                continue

            start_comment = open_blocks.pop(matching_index)
            ranges.append(
                SuppressionRange(
                    start_line=start_comment.line_number,
                    end_line=parsed_comment.line_number,
                    codes=start_comment.codes,
                )
            )

        for start_comment in open_blocks:
            ranges.append(
                SuppressionRange(
                    start_line=start_comment.line_number,
                    end_line=last_line,
                    codes=start_comment.codes,
                )
            )

        return ranges

    @staticmethod
    def _matching_block_index(
        open_blocks: list[ParsedSuppression],
        end_codes: frozenset[str],
    ) -> int | None:
        if not open_blocks:
            return None

        for index in range(len(open_blocks) - 1, -1, -1):
            if _codes_overlap(open_blocks[index].codes, end_codes):
                return index
        return len(open_blocks) - 1

    @classmethod
    def _definition_ranges(
        cls,
        tree: ast.AST,
        line_codes: dict[int, set[str]],
    ) -> list[SuppressionRange]:
        ranges: list[SuppressionRange] = []

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue

            start_line = node.lineno
            end_line = getattr(node, "end_lineno", start_line)
            codes = {
                *line_codes.get(start_line, set()),
                *line_codes.get(start_line - 1, set()),
            }
            if not codes:
                continue

            ranges.append(
                SuppressionRange(
                    start_line=start_line,
                    end_line=end_line,
                    codes=frozenset(codes),
                )
            )

        return ranges

    @staticmethod
    def _codes_suppress(codes: set[str] | frozenset[str], issue_code: str) -> bool:
        if not codes:
            return False
        if codes & GLOBAL_SUPPRESSION_CODES:
            return True
        if issue_code in codes:
            return True

        for code in codes:
            if issue_code in GROUP_SUPPRESSION_CODES.get(code, set()):
                return True
        return False


def _normalize_code(value: str) -> str:
    return value.strip().lower().replace("_", "-")


def _parse_codes(directive: str) -> set[str]:
    start = directive.find("[")
    end = directive.find("]", start + 1)
    if start == -1 or end == -1:
        return {"all"}

    codes = {
        _normalize_code(part)
        for part in directive[start + 1:end].split(",")
        if part.strip()
    }
    return codes or {"all"}


def _codes_overlap(left: frozenset[str], right: frozenset[str]) -> bool:
    if left & GLOBAL_SUPPRESSION_CODES or right & GLOBAL_SUPPRESSION_CODES:
        return True
    if left & right:
        return True
    for left_code in left:
        left_group = GROUP_SUPPRESSION_CODES.get(left_code, set())
        if left_group & right:
            return True
    for right_code in right:
        right_group = GROUP_SUPPRESSION_CODES.get(right_code, set())
        if right_group & left:
            return True
    return False
