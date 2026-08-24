from __future__ import annotations

import ast
from pathlib import Path

DOMAIN_ROOT = Path(__file__).resolve().parents[1] / "src" / "promotion_control_plane" / "domain"
FORBIDDEN_EXTERNAL_ROOTS = {
    "apscheduler",
    "celery",
    "fastapi",
    "openai",
    "sqlalchemy",
}
FORBIDDEN_LOCAL_LAYERS = {
    "adapters",
    "api",
    "cli",
    "infrastructure",
    "worker",
}
FORBIDDEN_FILESYSTEM_ROOTS = {"os", "pathlib", "shutil"}


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_domain_has_no_framework_or_outer_layer_dependencies() -> None:
    violations: list[str] = []
    for source in sorted(DOMAIN_ROOT.rglob("*.py")):
        for module in sorted(imported_modules(source)):
            root = module.split(".", 1)[0]
            if root in FORBIDDEN_EXTERNAL_ROOTS | FORBIDDEN_FILESYSTEM_ROOTS:
                violations.append(f"{source.name}: {module}")
                continue
            prefix = "promotion_control_plane."
            if module.startswith(prefix):
                local_layer = module[len(prefix) :].split(".", 1)[0]
                if local_layer in FORBIDDEN_LOCAL_LAYERS:
                    violations.append(f"{source.name}: {module}")

    assert violations == [], "Forbidden domain imports:\n" + "\n".join(violations)
