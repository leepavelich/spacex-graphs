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
    "urllib3",
    "http",
    "socket",
    "subprocess",
    "tempfile",
    "shutil",
    "glob",
    # The clock: cli.run passes today's date down instead
    "time",
}
# pyplot keeps global figure state and may start a GUI backend; only cli's
# on-screen display path may import it
PYPLOT_ALLOWED = {"cli"}
# Calls that read the clock or open files, which pure modules must not make
CLOCK_METHODS = {"now", "utcnow", "today", "fromtimestamp", "utcfromtimestamp"}
OPEN_CALLS = {("open",), ("builtins", "open"), ("io", "open"), ("io", "open_code")}
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


def _dotted(node: ast.expr) -> tuple[str, ...]:
    """The dotted name a call targets, such as ("datetime", "date", "today")."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return tuple(reversed(parts))


def _imports_pyplot_name(tree: ast.Module) -> bool:
    """Whether the module does "from matplotlib import pyplot"."""
    return any(
        isinstance(node, ast.ImportFrom)
        and node.module == "matplotlib"
        and any(alias.name == "pyplot" for alias in node.names)
        for node in ast.walk(tree)
    )


def _parse_modules() -> dict[str, ast.Module]:
    trees = {}
    for path in sorted(PACKAGE_DIR.rglob("*.py")):
        module = ".".join(path.relative_to(PACKAGE_DIR).with_suffix("").parts)
        with tokenize.open(path) as source:
            trees[module] = ast.parse(source.read(), filename=str(path))
    return trees


def _impure_calls(tree: ast.Module) -> Iterator[tuple[int, str]]:
    """Calls that read the clock or open a file."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _dotted(node.func)
        if name in OPEN_CALLS or (len(name) > 1 and name[-1] in CLOCK_METHODS):
            yield node.lineno, ".".join(name)


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

    def test_only_cli_imports_pyplot(self):
        violations = [
            f"{module}.py:{line} imports {target}"
            for module, tree in _parse_modules().items()
            if module not in PYPLOT_ALLOWED
            for line, target in _imports(tree)
            if target == "matplotlib.pyplot"
            or (target == "matplotlib" and _imports_pyplot_name(tree))
        ]
        self.assertEqual(violations, [])

    def test_pure_modules_neither_read_the_clock_nor_open_files(self):
        violations = [
            f"{module}.py:{line} calls {name}"
            for module, tree in _parse_modules().items()
            if module in PURE_MODULES
            for line, name in _impure_calls(tree)
        ]
        self.assertEqual(violations, [])

    def test_the_checks_catch_what_they_look_for(self):
        # Guards the guards: each forbidden form is reported
        tree = ast.parse(
            "import urllib3\n"
            "import time\n"
            "from matplotlib import pyplot\n"
            "import matplotlib.pyplot as plt\n"
            "datetime.datetime.now()\n"
            "date.today()\n"
            "datetime.fromtimestamp(0)\n"
            "open('x')\n"
            "builtins.open('x')\n"
            "io.open('x')\n"
            "time.time()\n"
            "today.year\n"
        )
        self.assertEqual(
            [name for _, name in _impure_calls(tree)],
            [
                "datetime.datetime.now",
                "date.today",
                "datetime.fromtimestamp",
                "open",
                "builtins.open",
                "io.open",
            ],
        )
        targets = [target for _, target in _imports(tree)]
        self.assertIn("matplotlib.pyplot", targets)
        self.assertTrue(_imports_pyplot_name(tree))
        self.assertTrue({"urllib3", "time"} <= {t.partition(".")[0] for t in targets})
        self.assertTrue({"urllib3", "time"} <= IO_MODULES)

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
