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

    def test_suborbital_is_transatmospheric(self):
        self.assertEqual(clean_orbit_category("Suborbital[19]"), "Transatmospheric")
        self.assertEqual(clean_orbit_category("Sub-orbital[8]"), "Transatmospheric")

    def test_starlink_on_suborbital_trajectory_is_transatmospheric(self):
        self.assertEqual(
            clean_orbit_category("Transatmospheric (Starlink)"), "Transatmospheric"
        )
        self.assertEqual(clean_orbit_category("Suborbital (Starlink)"), "Transatmospheric")

    def test_unmapped_leo_variants_fall_back_to_leo(self):
        self.assertEqual(clean_orbit_category("Elliptical LEO"), "LEO (Other)")
        self.assertEqual(clean_orbit_category("Low Earth orbit"), "LEO (Other)")
        self.assertEqual(clean_orbit_category("Elliptical LEO (Starlink)"), "LEO (Starlink)")

    def test_en_dash_and_footnote_variants(self):
        self.assertEqual(clean_orbit_category("Sun–Earth L1 insertion"), "Other")
        self.assertEqual(
            clean_orbit_category(
                "Heliocentric0.99–1.67 AU[248](close to Mars transfer orbit)"
            ),
            "Heliocentric",
        )


class TestCategorizeStarlink(unittest.TestCase):
    def test_starlink_payload_tagged(self):
        self.assertEqual(categorize_starlink("Starlink 6-1", "LEO"), "LEO (Starlink)")

    def test_other_payload_unchanged(self):
        self.assertEqual(categorize_starlink("Crew Dragon", "LEO"), "LEO")

    def test_starlink_tag_not_doubled(self):
        self.assertEqual(
            categorize_starlink("20 Starlink V3", "LEO (Starlink)"), "LEO (Starlink)"
        )

    def test_starship_starlink_flights(self):
        """Starlink mass counts as Starlink only once it actually reaches orbit."""
        suborbital = categorize_starlink("20 Starlink V3", "Transatmospheric")
        self.assertEqual(clean_orbit_category(suborbital), "Transatmospheric")
        orbital = categorize_starlink("20 Starlink V3", "LEO")
        self.assertEqual(clean_orbit_category(orbital), "LEO (Starlink)")


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
