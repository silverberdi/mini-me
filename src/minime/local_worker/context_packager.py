"""Deterministic bounded context packager for LocalWorker tasks.

Extracts symbol-aware context from authorized allowed_files inside the execution worktree,
preventing arbitrary tail truncation of target functions and enforcing security boundaries.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from minime.local_worker.models import LocalTaskClass

_TEST_SYMBOL_RE = re.compile(r"\b(test_[a-zA-Z0-9_]+)\b")
_PY_IDENTIFIER_RE = re.compile(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\b")

_COMMON_KEYWORDS = {
    "def", "async", "class", "return", "import", "from", "assert", "self", "none",
    "true", "false", "in", "is", "not", "and", "or", "if", "else", "elif", "try",
    "except", "finally", "with", "as", "for", "while", "pass", "raise", "yield",
    "the", "file", "test", "tests", "fixture", "fixtures", "stale", "contract",
    "only", "current", "matches", "behavior", "modify", "preserve", "source",
    "files", "forbidden", "repair", "update", "change", "task", "instruction",
}


def extract_candidate_symbols(instruction: str) -> list[str]:
    """Extract candidate function/test symbol names from instruction deterministically."""
    symbols: list[str] = []

    # Priority 1: Explicit test_ function names
    test_matches = _TEST_SYMBOL_RE.findall(instruction)
    for m in test_matches:
        if m not in symbols:
            symbols.append(m)

    # Priority 2: Other function/identifier-like tokens
    all_tokens = _PY_IDENTIFIER_RE.findall(instruction)
    for tok in all_tokens:
        tok_lower = tok.lower()
        if tok_lower in _COMMON_KEYWORDS or len(tok) < 3:
            continue
        if tok not in symbols:
            symbols.append(tok)

    return symbols


def _find_symbol_in_ast(code: str, symbol_name: str) -> tuple[int, int] | None:
    """Find start and end 1-based line numbers of a symbol in Python source code."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == symbol_name:
                start = node.lineno
                end = getattr(node, "end_lineno", start)
                # Include decorators if present
                if node.decorator_list:
                    dec_starts = [d.lineno for d in node.decorator_list if hasattr(d, "lineno")]
                    if dec_starts:
                        start = min(start, min(dec_starts))
                return (start, end)

    return None


def _extract_file_header(lines: list[str], max_lines: int = 50) -> list[str]:
    """Extract file header (module docstrings and top-level import statements)."""
    header: list[str] = []
    in_docstring = False
    docstring_char = None

    for line in lines[:max_lines]:
        stripped = line.strip()
        if not stripped:
            if header:
                header.append(line)
            continue

        if stripped.startswith(('"""', "'''")):
            if not in_docstring:
                in_docstring = True
                docstring_char = stripped[:3]
                header.append(line)
                if stripped.endswith(docstring_char) and len(stripped) > 3:
                    in_docstring = False
                continue
            else:
                if stripped.endswith(docstring_char):
                    in_docstring = False
                header.append(line)
                continue

        if in_docstring:
            header.append(line)
            continue

        if (
            stripped.startswith("import ")
            or stripped.startswith("from ")
            or stripped.startswith("#")
            or stripped.startswith("__")
        ):
            header.append(line)
            continue

        if stripped.startswith("def ") or stripped.startswith("class ") or stripped.startswith("@"):
            break

        header.append(line)

    return header


def package_task_context(
    *,
    instruction: str,
    task_class: LocalTaskClass | str,
    allowed_files: list[str] | tuple[str, ...],
    worktree_path: str | Path | None,
    max_budget_chars: int = 12000,
) -> str:
    """Deterministically package symbol-aware context from authorized allowed_files inside worktree_path.

    Guarantees:
    1. Only authorized allowed_files are read.
    2. Candidate symbols are located via AST/line parsing.
    3. Target function definitions are complete and never cut midway.
    4. Deterministic output given identical inputs and repository state.
    5. Safe fallback to bounded excerpt when no symbol is found.
    """
    if not worktree_path:
        return ""

    wt_root = Path(worktree_path).resolve()
    if not wt_root.is_dir():
        return ""

    normalized_allowed: list[str] = []
    for f in allowed_files:
        if not f or not f.strip():
            continue
        clean_f = f.strip()
        if clean_f.startswith("/") or ".." in clean_f.split("/"):
            continue
        if clean_f not in normalized_allowed:
            normalized_allowed.append(clean_f)

    if not normalized_allowed:
        return ""

    # Sort allowed files for strict determinism
    sorted_allowed = sorted(normalized_allowed)
    candidate_symbols = extract_candidate_symbols(instruction)

    # Strategy 1: Symbol-aware packaging for TEST_AUTHORING / code tasks
    if candidate_symbols:
        for rel_file in sorted_allowed:
            target_path = (wt_root / rel_file).resolve()
            try:
                target_path.relative_to(wt_root)
            except ValueError:
                continue

            if not target_path.is_file():
                continue

            try:
                content = target_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue

            lines = content.splitlines()

            for symbol in candidate_symbols:
                loc = _find_symbol_in_ast(content, symbol)
                if loc is not None:
                    start_line, end_line = loc
                    header_lines = _extract_file_header(lines)

                    header_block = "\n".join(header_lines)
                    symbol_lines = lines[start_line - 1 : end_line]
                    symbol_block = "\n".join(symbol_lines)

                    header_section = f"--- FILE HEADER & IMPORTS ---\n{header_block}" if header_block.strip() else ""
                    symbol_section = f"--- TARGET SYMBOL ({symbol}) ---\n{symbol_block}"

                    meta_header = f"FILE: {rel_file}\nSYMBOL: {symbol}"

                    # Calculate remaining budget for adjacent context
                    base_context = f"{meta_header}\n\n{header_section}\n\n{symbol_section}".strip()
                    remaining_budget = max_budget_chars - len(base_context)

                    adjacent_block = ""
                    if remaining_budget > 200:
                        # Append adjacent context after function up to budget
                        adjacent_lines = lines[end_line : end_line + 60]
                        adj_text = "\n".join(adjacent_lines)
                        if len(adj_text) > remaining_budget:
                            # Line-bounded trimming of adjacent context
                            trimmed_adj = []
                            cur_len = 0
                            for line in adjacent_lines:
                                if cur_len + len(line) + 1 > remaining_budget:
                                    break
                                trimmed_adj.append(line)
                                cur_len += len(line) + 1
                            adj_text = "\n".join(trimmed_adj)
                        if adj_text.strip():
                            adjacent_block = f"\n\n--- ADJACENT CONTEXT ---\n{adj_text}"

                    final_package = f"{base_context}{adjacent_block}"

                    # Guarantee complete function body is retained even if budget is tight
                    if len(final_package) > max_budget_chars:
                        final_package = f"{meta_header}\n\n{symbol_section}"

                    return final_package

    # Strategy 2: Bounded file excerpt fallback (no symbol found or non-AST file)
    fallback_parts: list[str] = []
    current_chars = 0

    for rel_file in sorted_allowed:
        target_path = (wt_root / rel_file).resolve()
        try:
            target_path.relative_to(wt_root)
        except ValueError:
            continue

        if not target_path.is_file():
            continue

        try:
            content = target_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        lines = content.splitlines()
        excerpt_lines: list[str] = []

        file_hdr = f"FILE: {rel_file}\n"
        if current_chars + len(file_hdr) > max_budget_chars:
            break

        excerpt_lines.append(file_hdr)
        current_chars += len(file_hdr)

        for line in lines:
            line_cost = len(line) + 1
            if current_chars + line_cost > max_budget_chars:
                break
            excerpt_lines.append(line)
            current_chars += line_cost

        fallback_parts.append("\n".join(excerpt_lines))

    return "\n\n".join(fallback_parts).strip()
