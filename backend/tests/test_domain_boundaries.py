"""Enforce the standard-library-only boundary for domain modules."""

import ast
import sys
from pathlib import Path


def test_AC_VP_14_domain_imports_are_pure_standard_library() -> None:
    domain_dir = Path(__file__).parents[1] / "src" / "app" / "domain"
    python_files = sorted(domain_dir.glob("*.py"))

    for path in python_files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_roots = [alias.name.split(".", maxsplit=1)[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                module = str(node.module)
                if module == "app.domain" or module.startswith("app.domain."):
                    continue
                imported_roots = [module.split(".", maxsplit=1)[0]]
            else:
                continue

            assert all(root in sys.stdlib_module_names for root in imported_roots), (
                f"{path.name} imports outside the standard library: {imported_roots}"
            )
