"""Tests for orbit categorization and DataFrame transforms."""

import datetime
import unittest

from spacex_graphs.parsing import LaunchRecord
from spacex_graphs.transform import (
    build_dataframe,
    categorize_starlink,
    clean_orbit_category,
    payload_mass_by_year_orbit,
)


class TestCleanOrbitCategory(unittest.TestCase):
    def test_known_orbits_map_to_categories(self):
        self.assertEqual(clean_orbit_category("GTO"), "GTO/GEO")
        self.assertEqual(clean_orbit_category("LEO (ISS)"), "LEO (Other)")
        self.assertEqual(clean_orbit_category("LEO (Starlink)"), "LEO (Starlink)")

    def test_footnote_brackets_removed(self):
        self.assertEqual(clean_orbit_category("GTO[338]"), "GTO/GEO")

    def test_unknown_orbit_falls_back_to_other(self):
        self.assertEqual(clean_orbit_category("Cislunar"), "Other")

    def test_starship_test_flight_dash(self):
        self.assertEqual(clean_orbit_category("—"), "Transatmospheric")


class TestCategorizeStarlink(unittest.TestCase):
    def test_starlink_payload_tagged(self):
        self.assertEqual(categorize_starlink("Starlink 6-1", "LEO"), "LEO (Starlink)")

    def test_other_payload_unchanged(self):
        self.assertEqual(categorize_starlink("Crew Dragon", "LEO"), "LEO")


class TestDataFrames(unittest.TestCase):
    def _record(self, year, orbit, payload, mass):
        return LaunchRecord(
            year, orbit, payload, mass, datetime.datetime(year, 6, 1), "Falcon 9"
        )

    def test_build_dataframe_categorizes_orbits(self):
        df = build_dataframe(
            [
                self._record(2023, "LEO", "Starlink 6-1", 17000),
                self._record(2023, "GTO", "SES-18", 3500),
            ]
        )
        self.assertEqual(list(df["Orbit"]), ["LEO (Starlink)", "GTO/GEO"])

    def test_payload_mass_by_year_orbit_sums_masses(self):
        df = build_dataframe(
            [
                self._record(2023, "LEO", "Starlink 6-1", 17000),
                self._record(2023, "LEO", "Starlink 6-2", 16000),
            ]
        )
        grouped = payload_mass_by_year_orbit(df)
        self.assertEqual(len(grouped), 1)
        self.assertEqual(grouped.iloc[0]["PayloadMass"], 33000)


if __name__ == "__main__":
    unittest.main()
