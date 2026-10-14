import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src" / "pricor"


def imported_modules(path: Path) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.add(node.module)
    return modules


@pytest.mark.parametrize(
    ("layer", "forbidden"),
    [
        ("domain", ("pricor.application", "pricor.ports", "pricor.adapters", "pricor.entrypoints")),
        ("ports", ("pricor.application", "pricor.adapters", "pricor.entrypoints")),
        ("application", ("pricor.adapters", "pricor.entrypoints")),
        ("adapters", ("pricor.application", "pricor.entrypoints")),
    ],
)
def test_layers_depend_only_inward(layer, forbidden):
    offenders = [
        f"{path.relative_to(SRC)} imports {module}"
        for path in sorted((SRC / layer).glob("*.py"))
        for module in sorted(imported_modules(path))
        if module.startswith(forbidden)
    ]

    assert offenders == []
