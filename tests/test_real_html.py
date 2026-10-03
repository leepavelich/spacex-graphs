"""Parses trimmed real Wikipedia pages (see tests/fixtures/README.md)."""

import datetime
import pathlib
import unittest

from spacex_graphs.parsing import parse_launch_page

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
FALCON_URL = "https://en.wikipedia.org/wiki/List_of_Falcon_9_and_Falcon_Heavy_launches"
STARSHIP_URL = "https://en.wikipedia.org/wiki/List_of_Starship_launches"


def _parse(filename, url):
    records = parse_launch_page(url, (FIXTURES / filename).read_bytes())
    return [
        (r.launch_datetime, r.payload, r.payload_mass, r.orbit, r.vehicle)
        for r in records
    ]


class TestRealFalconPage(unittest.TestCase):
    def test_launches_match_snapshot(self):
        nbsp = " "
        self.assertEqual(
            _parse("falcon_launches.html", FALCON_URL),
            [
                (datetime.datetime(2025, 1, 4, 1, 27), "Thuraya 4-NGS", 5000, "GTO", "Falcon 9"),
                (datetime.datetime(2025, 1, 6, 20, 43), f"Starlink: Group{nbsp}6‑71", 17500, "LEO", "Falcon 9"),
                (datetime.datetime(2025, 1, 8, 15, 27), f"Starlink: Group{nbsp}12-11 (21{nbsp}satellites)", 16500, "LEO", "Falcon 9"),
                (datetime.datetime(2025, 1, 10, 3, 53), f"NROL-153 (22{nbsp}Starshield satellites)[35]", 0, "LEO", "Falcon 9"),
                (datetime.datetime(2025, 1, 10, 19, 11), f"Starlink: Group{nbsp}12-12 (21{nbsp}satellites)", 16500, "LEO", "Falcon 9"),
                (datetime.datetime(2025, 1, 13, 16, 47), f"Starlink: Group{nbsp}12-4 (21{nbsp}satellites)", 16500, "LEO", "Falcon 9"),
            ],
        )

    def test_planned_launches_are_excluded(self):
        # The fixture includes rows from the 6-column planned-launch table
        html = (FIXTURES / "falcon_launches.html").read_text(encoding="utf-8")
        self.assertGreater(html.count('<table class="wikitable">'), 1)
        self.assertEqual(len(_parse("falcon_launches.html", FALCON_URL)), 6)


class TestRealStarshipPage(unittest.TestCase):
    def test_launches_match_snapshot(self):
        self.assertEqual(
            _parse("starship_launches.html", STARSHIP_URL),
            [
                (datetime.datetime(2024, 3, 14, 13, 25), "Starship Test", 0, "Suborbital[19]", "Block 1 Starship"),
                (datetime.datetime(2024, 6, 6, 12, 50), "Starship Test", 0, "Suborbital[23]", "Block 1 Starship"),
                (datetime.datetime(2024, 10, 13, 12, 25), "Starship Test", 0, "Suborbital[29]", "Block 1 Starship"),
                (datetime.datetime(2024, 11, 19, 22, 0), "Plush banana", 0, "Transatmospheric[31]", "Block 1 Starship"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
