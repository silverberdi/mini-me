"""Deterministic bounded context packager for LocalWorker tasks.

Extracts symbol-aware context from authorized allowed_files inside the execution worktree,
enforcing hard character budgets, preventing symbol truncation, and handling task-class scoping.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

from minime.local_worker.models import DEFAULT_CONTEXT_BUDGET_CHARS, LocalTaskClass

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


@dataclass(frozen=True)
class ContextPackagingResult:
    """Structured result of local worker context packaging."""

    success: bool
    context: str = ""
    status: str = "OK"  # "OK", "TARGET_SYMBOL_EXCEEDS_BUDGET", "NO_SYMBOL_FOUND", "FALLBACK_EXCERPT", "NO_AUTHORIZED_FILES", "FALLBACK_EXCEEDS_BUDGET"


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
    max_budget_chars: int = DEFAULT_CONTEXT_BUDGET_CHARS,
) -> ContextPackagingResult:
    """Deterministically package symbol-aware context from authorized allowed_files inside worktree_path.

    Contracts:
    1. Only authorized allowed_files inside worktree_path are read.
    2. Symbol-aware Python function extraction applies specifically to TEST_AUTHORING tasks.
    3. Complete target function definitions are retained; indivisible symbols exceeding hard budget fail closed.
    4. len(result.context) <= max_budget_chars is strictly guaranteed whenever success is True.
    """
    if not worktree_path:
        return ContextPackagingResult(success=False, context="", status="WORKTREE_MISSING")

    wt_root = Path(worktree_path).resolve()
    if not wt_root.is_dir():
        return ContextPackagingResult(success=False, context="", status="WORKTREE_INVALID")

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
        return ContextPackagingResult(success=False, context="", status="NO_AUTHORIZED_FILES")

    sorted_allowed = sorted(normalized_allowed)
    task_cls_str = task_class.value if hasattr(task_class, "value") else str(task_class)

    # Strategy 1: Symbol-aware packaging for TEST_AUTHORING
    if task_cls_str == LocalTaskClass.TEST_AUTHORING.value:
        candidate_symbols = extract_candidate_symbols(instruction)
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
                        meta_header = f"FILE: {rel_file}\nSYMBOL: {symbol}"
                        symbol_lines = lines[start_line - 1 : end_line]
                        symbol_block = "\n".join(symbol_lines)
                        symbol_section = f"--- TARGET SYMBOL ({symbol}) ---\n{symbol_block}"

                        mandatory_minimal = f"{meta_header}\n\n{symbol_section}".strip()

                        # FAIL CLOSED if the complete target symbol + meta header exceeds max_budget_chars
                        if len(mandatory_minimal) > max_budget_chars:
                            return ContextPackagingResult(
                                success=False,
                                context="",
                                status="TARGET_SYMBOL_EXCEEDS_BUDGET",
                            )

                        header_lines = _extract_file_header(lines)
                        header_block = "\n".join(header_lines)
                        header_section = f"--- FILE HEADER & IMPORTS ---\n{header_block}" if header_block.strip() else ""

                        base_context = f"{meta_header}\n\n{header_section}\n\n{symbol_section}".strip() if header_section else mandatory_minimal

                        if len(base_context) > max_budget_chars:
                            base_context = mandatory_minimal

                        remaining_budget = max_budget_chars - len(base_context)
                        adjacent_block = ""
                        if remaining_budget > 200:
                            adjacent_lines = lines[end_line : end_line + 60]
                            trimmed_adj = []
                            cur_len = 0
                            for line in adjacent_lines:
                                line_cost = len(line) + 1
                                if cur_len + line_cost > remaining_budget:
                                    break
                                trimmed_adj.append(line)
                                cur_len += line_cost
                            if trimmed_adj:
                                adj_text = "\n".join(trimmed_adj)
                                if adj_text.strip():
                                    adjacent_block = f"\n\n--- ADJACENT CONTEXT ---\n{adj_text}"

                        final_package = f"{base_context}{adjacent_block}".strip()
                        if len(final_package) > max_budget_chars:
                            final_package = base_context

                        if len(final_package) > max_budget_chars:
                            return ContextPackagingResult(
                                success=False,
                                context="",
                                status="TARGET_SYMBOL_EXCEEDS_BUDGET",
                            )

                        return ContextPackagingResult(
                            success=True,
                            context=final_package,
                            status="OK",
                        )

    # Strategy 2: Bounded file excerpt fallback (for non-TEST_AUTHORING or when no symbol was found)
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

        # Accurately account for inter-part separator ("\n\n") cost
        sep_cost = 2 if fallback_parts else 0
        if current_chars + sep_cost > max_budget_chars:
            break

        file_hdr = f"FILE: {rel_file}\n"
        if current_chars + sep_cost + len(file_hdr) > max_budget_chars:
            break

        current_chars += (sep_cost + len(file_hdr))
        excerpt_lines.append(file_hdr)

        for line in lines:
            line_cost = len(line) + 1
            if current_chars + line_cost > max_budget_chars:
                break
            excerpt_lines.append(line)
            current_chars += line_cost

        if len(excerpt_lines) > 1:
            fallback_parts.append("\n".join(excerpt_lines))
        else:
            # Revert if no content lines could fit
            current_chars -= (sep_cost + len(file_hdr))

    if not fallback_parts:
        return ContextPackagingResult(success=False, context="", status="NO_AUTHORIZED_FILES")

    final_fallback = "\n\n".join(fallback_parts).strip()

    if len(final_fallback) > max_budget_chars:
        return ContextPackagingResult(
            success=False,
            context="",
            status="FALLBACK_EXCEEDS_BUDGET",
        )

    return ContextPackagingResult(
        success=True,
        context=final_fallback,
        status="FALLBACK_EXCERPT",
    )
