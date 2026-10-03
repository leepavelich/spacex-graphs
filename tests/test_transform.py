"""Tests for orbit categorization and DataFrame transforms."""

import datetime
import unittest

from spacex_graphs.parsing import LaunchRecord
from spacex_graphs.transform import (
    build_cumulative_frame,
    build_dataframe,
    categorize_starlink,
    chart_caption,
    clean_orbit_category,
    launch_succeeded,
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
        self.assertEqual(
            clean_orbit_category("Suborbital (Starlink)"), "Transatmospheric"
        )

    def test_unmapped_leo_variants_fall_back_to_leo(self):
        self.assertEqual(clean_orbit_category("Elliptical LEO"), "LEO (Other)")
        self.assertEqual(clean_orbit_category("Low Earth orbit"), "LEO (Other)")
        self.assertEqual(
            clean_orbit_category("Elliptical LEO (Starlink)"), "LEO (Starlink)"
        )

    def test_en_dash_and_footnote_variants(self):
        self.assertEqual(clean_orbit_category("Sun–Earth L1 insertion"), "Other")
        self.assertEqual(
            clean_orbit_category(
                "Heliocentric 0.99–1.67 AU[248] (close to Mars transfer orbit)"
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


class TestOrbitCategories(unittest.TestCase):
    def test_every_mapping_value_is_a_known_category(self):
        from spacex_graphs.config import ORBIT_CATEGORIES, ORBIT_MAPPING

        unknown = sorted(set(ORBIT_MAPPING.values()) - set(ORBIT_CATEGORIES))
        self.assertEqual(unknown, [])

    def test_fallbacks_are_known_categories(self):
        from spacex_graphs.config import ORBIT_CATEGORIES

        for orbit in ("Elliptical LEO", "Elliptical LEO (Starlink)", "Molniya", ""):
            with self.subTest(orbit=orbit):
                self.assertIn(clean_orbit_category(orbit), ORBIT_CATEGORIES)

    def test_every_category_has_a_color_in_legend_order(self):
        from spacex_graphs.config import ORBIT_CATEGORIES
        from spacex_graphs.plotting import ORBIT_COLORS

        self.assertEqual(tuple(ORBIT_COLORS), ORBIT_CATEGORIES)


EXPECTED_ORBIT_MAPPING = {
    "Ballistic lunar transfer (BLT)": "BLT",
    "BLT": "BLT",
    "GEO": "GTO/GEO",
    "GTO": "GTO/GEO",
    "HEO for P/2 orbit": "Other",
    "Heliocentric": "Heliocentric",
    "Heliocentric 0.99–1.67 AU (close to Mars transfer orbit)": "Heliocentric",
    "LEO": "LEO (Other)",
    "LEO (ISS)": "LEO (Other)",
    "LEO (Starlink)": "LEO (Starlink)",
    "LEO / MEO": "Other",
    "MEO": "MEO",
    "Polar LEO": "LEO (Other)",
    "Polar orbit LEO": "LEO (Other)",
    "Polar (Retrograde)": "LEO (Other)",
    "Retrograde LEO": "LEO (Other)",
    "SSO": "SSO (Other)",
    "SSO (Starlink)": "SSO (Starlink)",
    "Sub-orbital": "Transatmospheric",
    "Suborbital": "Transatmospheric",
    "Sun–Earth L1 insertion": "Other",
    "Sun–Earth L2 injection": "Other",
    "Transatmospheric": "Transatmospheric",
    "—": "Transatmospheric",
    "Suborbital (Starlink)": "Transatmospheric",
    "Sub-orbital (Starlink)": "Transatmospheric",
    "Transatmospheric (Starlink)": "Transatmospheric",
}


class TestOrbitMappingTable(unittest.TestCase):
    """Pins every mapping entry, so recategorizing an orbit is a visible change."""

    def test_mapping_matches_table(self):
        from spacex_graphs.config import ORBIT_MAPPING

        self.assertEqual(ORBIT_MAPPING, EXPECTED_ORBIT_MAPPING)

    def test_starlink_payloads_take_the_starlink_category(self):
        for orbit, expected in [
            ("LEO", "LEO (Starlink)"),
            ("SSO", "SSO (Starlink)"),
            ("Suborbital", "Transatmospheric"),
        ]:
            with self.subTest(orbit=orbit):
                orbit_with_tag = categorize_starlink("Starlink Group 1", orbit)
                self.assertEqual(clean_orbit_category(orbit_with_tag), expected)


class TestOrbitMapping(unittest.TestCase):
    def test_every_mapping_key_is_reachable(self):
        # clean_orbit_category strips "[...]" footnotes before the lookup, so a
        # key containing brackets could never match
        from spacex_graphs.config import ORBIT_MAPPING

        unreachable = [key for key in ORBIT_MAPPING if "[" in key]
        self.assertEqual(unreachable, [])

    def test_both_blt_spellings_map_to_blt(self):
        self.assertEqual(clean_orbit_category("BLT"), "BLT")
        self.assertEqual(clean_orbit_category("Ballistic lunar transfer (BLT)"), "BLT")


def _launch(when, mass, orbit="LEO", payload="Sat"):
    return LaunchRecord(when.year, orbit, payload, mass, when, "Falcon 9")


class TestBuildDataFrame(unittest.TestCase):
    def test_keeps_raw_orbit_alongside_category(self):
        df = build_dataframe([_launch(datetime.datetime(2024, 1, 5), 1, "GTO[12]")])
        self.assertEqual(df.loc[0, "RawOrbit"], "GTO[12]")
        self.assertEqual(df.loc[0, "Orbit"], "GTO/GEO")

    def test_grouping_sums_mass_per_year_and_category(self):
        df = build_dataframe(
            [
                _launch(datetime.datetime(2024, 1, 5), 100, payload="A"),
                _launch(datetime.datetime(2024, 2, 5), 200, payload="B"),
                _launch(datetime.datetime(2024, 3, 5), 50, orbit="GTO", payload="C"),
            ]
        )
        grouped = payload_mass_by_year_orbit(df)
        self.assertEqual(list(grouped.columns), ["Year", "Orbit", "PayloadMass"])
        self.assertEqual(
            sorted(zip(grouped["Orbit"], grouped["PayloadMass"], strict=True)),
            [("GTO/GEO", 50), ("LEO (Other)", 300)],
        )

    def test_only_successful_launches_with_known_mass_count(self):
        when = datetime.datetime(2024, 1, 5)
        df = build_dataframe(
            [
                LaunchRecord(2024, "LEO", "A", 100, when, "Falcon 9", "Success"),
                LaunchRecord(2024, "LEO", "B", 200, when, "Falcon 9", "Failure"),
                LaunchRecord(2024, "LEO", "C", None, when, "Falcon 9", "Success"),
            ]
        )
        self.assertEqual(list(df["PayloadMass"]), [100, 0, 0])
        self.assertEqual(df["ReportedMass"].tolist()[:2], [100, 200])
        self.assertTrue(df["ReportedMass"].isna().iloc[2])

    def test_outcome_classification(self):
        for outcome, counts in [
            ("Success", True),
            ("Successful simulated failure", True),
            ("Failure", False),
            ("Precluded (pre-flight failure)", False),
            ("Unsuccessful", False),
            ("Partial success", False),
            ("success", True),
        ]:
            with self.subTest(outcome=outcome):
                self.assertEqual(launch_succeeded(outcome), counts)


class TestChartCaption(unittest.TestCase):
    def test_names_the_source_latest_launch_and_unknown_masses(self):
        df = build_dataframe(
            [
                LaunchRecord(
                    2026, "LEO", "A", 100, datetime.datetime(2026, 9, 2), "F9"
                ),
                LaunchRecord(
                    2026, "LEO", "NROL", None, datetime.datetime(2026, 8, 1), "F9"
                ),
                # Failed launches already count 0, so they aren't "unknown"
                LaunchRecord(
                    2026,
                    "LEO",
                    "B",
                    None,
                    datetime.datetime(2026, 7, 1),
                    "F9",
                    "Failure",
                ),
            ]
        )
        caption = chart_caption(df)
        self.assertIn("Wikipedia", caption)
        self.assertIn("CC BY-SA 4.0", caption)
        self.assertIn("through 2 September 2026", caption)
        self.assertIn("1 successful launch with unknown", caption)


class TestBuildCumulativeFrame(unittest.TestCase):
    TODAY = datetime.date(2026, 10, 3)

    def _series(self, records, year):
        frame = build_cumulative_frame(build_dataframe(records), self.TODAY)
        points = frame[frame["Year"] == year]
        return list(
            zip(points["DayOfYear"], points["CumulativePayloadMass"], strict=True)
        )

    def test_past_year_runs_from_jan_1_to_dec_31(self):
        records = [
            _launch(datetime.datetime(2025, 3, 1, 12), 100),
            _launch(datetime.datetime(2025, 2, 1, 12), 50),
        ]
        self.assertEqual(
            self._series(records, 2025), [(1, 0), (32, 50), (60, 150), (365, 150)]
        )

    def test_current_year_ends_today(self):
        records = [_launch(datetime.datetime(2026, 5, 1), 10)]
        self.assertEqual(self._series(records, 2026)[-1], (276, 10))

    def test_midnight_launch_on_jan_1_never_steps_backwards(self):
        records = [_launch(datetime.datetime(2025, 1, 1), 70)]
        series = self._series(records, 2025)
        self.assertEqual(series[0], (1, 0))  # the line starts at the origin
        masses = [mass for _, mass in series]
        self.assertEqual(masses, sorted(masses))
        self.assertEqual(masses[-1], 70)

    def test_years_before_minimum_are_dropped(self):
        records = [
            _launch(datetime.datetime(2015, 6, 1), 1),
            _launch(datetime.datetime(2025, 6, 1), 1),
        ]
        frame = build_cumulative_frame(build_dataframe(records), self.TODAY)
        self.assertEqual(sorted(frame["Year"].unique()), [2025])

    def test_input_frame_is_not_modified(self):
        df = build_dataframe([_launch(datetime.datetime(2025, 6, 1), 1)])
        before = df.copy()
        build_cumulative_frame(df, self.TODAY)
        self.assertTrue(df.equals(before))


if __name__ == "__main__":
    unittest.main()
