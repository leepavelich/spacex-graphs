"""Enforce the package's dependency direction and purity without importing it."""

import ast
import io
import re
import tokenize
import unittest
from collections.abc import Iterator
from pathlib import Path

PACKAGE = "spacex_graphs"
PACKAGE_DIR = Path(__file__).resolve().parents[1] / PACKAGE
LAYERS = (
    ("config", "errors"),
    ("cache",),
    ("parsing",),
    ("validation",),
    ("transform",),
    ("plotting",),
    ("output",),
    ("cli",),
    ("__main__",),
    ("__init__",),
)
LAYER_BY_MODULE = {name: layer for layer, names in enumerate(LAYERS) for name in names}
PURE_MODULES = {"config", "errors", "parsing", "validation", "transform", "plotting"}
IO_MODULES = {
    "os",
    "pathlib",
    "requests",
    "urllib",
    "http",
    "socket",
    "subprocess",
    "tempfile",
    "shutil",
    "glob",
}
SUPPRESSION = re.compile(r"#\s*(?:type\s*:\s*ignore|noqa)\b", re.IGNORECASE)


def _imports(tree: ast.Module) -> Iterator[tuple[int, str]]:
    """Yield fully qualified import targets, including function-local imports."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name
        elif isinstance(node, ast.ImportFrom):
            # The inventory test limits the DAG to a single package level.
            origin: str | None
            if node.level:
                origin = f"{PACKAGE}.{node.module}" if node.module else PACKAGE
            else:
                origin = node.module
            if origin == PACKAGE:
                for alias in node.names:
                    yield node.lineno, f"{PACKAGE}.{alias.name}"
            elif origin is not None:
                yield node.lineno, origin


class TestArchitecture(unittest.TestCase):
    def test_dependency_dag_and_io_isolation(self):
        modules = {
            ".".join(path.relative_to(PACKAGE_DIR).with_suffix("").parts): path
            for path in PACKAGE_DIR.rglob("*.py")
        }
        imports: list[tuple[str, int, str]] = []
        for module, path in sorted(modules.items()):
            with tokenize.open(path) as source:
                tree = ast.parse(source.read(), filename=str(path))
            imports.extend((module, line, target) for line, target in _imports(tree))
        self.assertEqual(
            set(modules), set(LAYER_BY_MODULE), "update the layer inventory"
        )

        violations = []
        for module, line, target in imports:
            root, _, suffix = target.partition(".")
            if root == PACKAGE:
                # A bare or wildcard import hides the actual dependencies.
                dependency = suffix.partition(".")[0] or "__init__"
                if (
                    dependency not in LAYER_BY_MODULE
                    or LAYER_BY_MODULE[dependency] >= LAYER_BY_MODULE[module]
                ):
                    violations.append(f"{module}.py:{line} forbidden import {target}")
            elif module in PURE_MODULES and root in IO_MODULES:
                violations.append(f"{module}.py:{line} pure module imports {target}")
        self.assertEqual(violations, [])

    def test_production_code_has_no_suppressions(self):
        violations = []
        for path in sorted(PACKAGE_DIR.rglob("*.py")):
            with tokenize.open(path) as source:
                tokens = tokenize.generate_tokens(io.StringIO(source.read()).readline)
            for token in tokens:
                if token.type == tokenize.COMMENT and SUPPRESSION.search(token.string):
                    violations.append(
                        f"{path.relative_to(PACKAGE_DIR)}:{token.start[0]} {token.string}"
                    )
        self.assertEqual(violations, [])
