"""Parses trimmed real Wikipedia pages (see tests/fixtures/README.md)."""

import datetime
import pathlib
import unittest

from spacex_graphs.parsing import parse_launch_page

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def _parse(filename, layout):
    records = parse_launch_page(layout, (FIXTURES / filename).read_bytes())
    return [
        (r.launch_datetime, r.payload, r.payload_mass, r.orbit, r.vehicle, r.outcome)
        for r in records
    ]


def _launch(when, payload, mass, orbit, vehicle, outcome="Success"):
    return (datetime.datetime(*when), payload, mass, orbit, vehicle, outcome)


class TestRealFalconPage(unittest.TestCase):
    def test_launches_match_snapshot(self):
        self.assertEqual(
            _parse("falcon_launches.html", "falcon"),
            [
                _launch((2025, 1, 4, 1, 27), "Thuraya 4-NGS", 5000, "GTO", "Falcon 9"),
                _launch(
                    (2025, 1, 6, 20, 43),
                    "Starlink: Group 6‑71",
                    17500,
                    "LEO",
                    "Falcon 9",
                ),
                _launch(
                    (2025, 1, 8, 15, 27),
                    "Starlink: Group 12-11 (21 satellites)",
                    16500,
                    "LEO",
                    "Falcon 9",
                ),
                _launch(
                    (2025, 1, 10, 3, 53),
                    "NROL-153 (22 Starshield satellites)",
                    None,
                    "LEO",
                    "Falcon 9",
                ),
                _launch(
                    (2025, 1, 10, 19, 11),
                    "Starlink: Group 12-12 (21 satellites)",
                    16500,
                    "LEO",
                    "Falcon 9",
                ),
                _launch(
                    (2025, 1, 13, 16, 47),
                    "Starlink: Group 12-4 (21 satellites)",
                    16500,
                    "LEO",
                    "Falcon 9",
                ),
                # A secondary payload with its own outcome cell: both masses
                # are reported, and both outcomes kept
                _launch(
                    (2012, 10, 8, 0, 35),
                    "SpaceX CRS-1 (Dragon C103) + Orbcomm-OG2",
                    4700 + 172,
                    "LEO (ISS)",
                    "Falcon 9",
                    "Success; Partial failure",
                ),
                _launch(
                    (2015, 6, 28, 14, 21),
                    "SpaceX CRS-7 (Dragon C109)",
                    1952,
                    "LEO (ISS)",
                    "Falcon 9",
                    "Failure",
                ),
                _launch(
                    (2016, 9, 3, 7, 0),
                    "AMOS-6",
                    5500,
                    "GTO",
                    "Falcon 9",
                    "Precluded (pre-flight failure)",
                ),
                # Three payloads sharing the date, site, orbit, and outcome
                # cells through rowspan, under a "Falcon Heavy" booster cell
                _launch(
                    (2023, 5, 1, 0, 26),
                    "ViaSat-3 Americas + Aurora 4A (Arcturus) + GS-1",
                    6400 + 300 + 22,
                    "GEO",
                    "Falcon Heavy",
                ),
                _launch(
                    (2026, 7, 5, 10, 50),
                    "Starlink: Group 10-50 + "
                    "Fabships Flight 1 (semiconductor test pods x 2)",
                    16675 + 28,
                    "LEO",
                    "Falcon 9",
                ),
            ],
        )

    def test_planned_launches_are_excluded(self):
        # The fixture includes rows from the 6-column planned-launch table
        html = (FIXTURES / "falcon_launches.html").read_text(encoding="utf-8")
        self.assertGreater(html.count('<table class="wikitable">'), 1)
        self.assertEqual(len(_parse("falcon_launches.html", "falcon")), 11)


class TestRealStarshipPage(unittest.TestCase):
    def test_launches_match_snapshot(self):
        self.assertEqual(
            _parse("starship_launches.html", "starship"),
            [
                _launch(
                    (2024, 3, 14, 13, 25),
                    "Starship Test",
                    None,
                    "Suborbital",
                    "Block 1 Starship",
                ),
                _launch(
                    (2024, 6, 6, 12, 50),
                    "Starship Test",
                    None,
                    "Suborbital",
                    "Block 1 Starship",
                ),
                _launch(
                    (2024, 10, 13, 12, 25),
                    "Starship Test",
                    None,
                    "Suborbital",
                    "Block 1 Starship",
                ),
                _launch(
                    (2024, 11, 19, 22, 0),
                    "Plush banana",
                    None,
                    "Transatmospheric",
                    "Block 1 Starship",
                ),
                _launch(
                    (2025, 1, 16, 22, 37),
                    "10 Starlink simulator satellites",
                    20000,
                    "Transatmospheric",
                    "Block 2 Starship",
                    "Failure",
                ),
                _launch(
                    (2025, 8, 26, 23, 30),
                    "8 Starlink simulator satellites",
                    16000,
                    "Transatmospheric",
                    "Block 2 Starship",
                ),
                _launch(
                    (2026, 5, 22, 22, 30),
                    "20 Starlink simulator satellites and 2 modified Starlink V3",
                    37500,
                    "Transatmospheric",
                    "Block 3 Starship",
                ),
            ],
        )


if __name__ == "__main__":
    unittest.main()
