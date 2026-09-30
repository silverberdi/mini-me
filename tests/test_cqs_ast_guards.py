"""AST static guard suite checking designated query modules for forbidden mutating symbols."""

from __future__ import annotations

import ast
from pathlib import Path


def check_ast_for_forbidden_calls(file_path: Path, forbidden_names: set[str]) -> list[str]:
    """Parse AST of python file and find calls to forbidden function names."""
    if not file_path.exists():
        return []

    code = file_path.read_text()
    tree = ast.parse(code, filename=str(file_path))
    violations: list[str] = []

    class ForbiddenCallVisitor(ast.NodeVisitor):
        def visit_Attribute(self, node: ast.Attribute):
            if node.attr in forbidden_names:
                violations.append(f"Line {node.lineno}: forbidden attribute access '{node.attr}'")
            self.generic_visit(node)

    visitor = ForbiddenCallVisitor()
    visitor.visit(tree)
    return violations


def test_status_and_dashboard_services_ast_guards():
    src_root = Path("/Users/silveriobernal/Documents/Code/Development/mini-me/src/minime/services")
    dashboard_file = src_root / "dashboard_service.py"
    status_file = src_root / "status_service.py"

    forbidden = {"get_for_update", "with_for_update"}

    dash_violations = check_ast_for_forbidden_calls(dashboard_file, forbidden)
    assert len(dash_violations) == 0, f"Dashboard service AST violations: {dash_violations}"

    status_violations = check_ast_for_forbidden_calls(status_file, forbidden)
    assert len(status_violations) == 0, f"Status service AST violations: {status_violations}"
