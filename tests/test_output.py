"""Tests for writing the SVG and CSV artifacts."""

import os
import tempfile
import unittest
from unittest import mock

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402

from spacex_graphs import output  # noqa: E402


def _figure():
    # Text, bars and a clipped line exercise every source of random SVG IDs
    fig, ax = plt.subplots()
    ax.bar(["2024", "2025"], [17000, 4000], label="mass")
    ax.plot([0, 1], [0, 20000])
    ax.set_title("Payload Mass")
    ax.legend()
    return fig


def _render_svgs(directory):
    figs = (_figure(), _figure())
    with mock.patch.object(output, "OUTPUT_DIR", directory), mock.patch.object(
        output.cache, "write_last_run_date"
    ):
        output.save_plots(*figs)
    plt.close("all")
    contents = {}
    for name in sorted(os.listdir(directory)):
        with open(os.path.join(directory, name), "rb") as f:
            contents[name] = f.read()
    return contents


class TestSavePlots(unittest.TestCase):
    def test_identical_data_produces_identical_svgs(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            first, second = _render_svgs(a), _render_svgs(b)
        self.assertEqual(len(first), 2)
        self.assertEqual(first, second)

    def test_svgs_have_no_embedded_timestamp(self):
        with tempfile.TemporaryDirectory() as directory:
            for content in _render_svgs(directory).values():
                self.assertNotIn(b"<dc:date>", content)


if __name__ == "__main__":
    unittest.main()
