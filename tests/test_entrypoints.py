"""Smoke tests for both supported command-line entry points."""

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class EntrypointTests(unittest.TestCase):
    def assert_help(self, *args: str) -> None:
        # The interpreter and arguments are fixed by these tests, not user input.
        result = subprocess.run(  # noqa: S603
            [sys.executable, *args, "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("usage:", result.stdout)
        self.assertIn("--output", result.stdout)
        self.assertIn("--quiet", result.stdout)

    def test_module_help(self) -> None:
        self.assert_help("-m", "spacex_graphs")

    def test_script_help(self) -> None:
        self.assert_help("graphs.py")
