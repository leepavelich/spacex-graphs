"""Tests for the pure parsing helpers."""

import datetime
import unittest

from spacex_graphs.parsing import (
    parse_launch_datetime,
    parse_launch_page,
    parse_payload_mass_text,
)

STARSHIP_URL = "https://en.wikipedia.org/wiki/List_of_Starship_launches"
FALCON_URL = "https://en.wikipedia.org/wiki/List_of_Falcon_9_and_Falcon_Heavy_launches"


def _falcon_row(date, booster, payload, mass, orbit, outcome):
    """Builds a Falcon 9/Heavy table row with the live 9-column layout."""
    cells = [
        date,
        booster,
        "CCSFS, SLC-40",
        payload,
        mass,
        orbit,
        "SpaceX",
        outcome,
        "Success (ASOG)",
    ]
    return "<tr>" + "".join(f"<td>{cell}</td>" for cell in cells) + "</tr>"


def _starship_row(date, ship, payload, mass, orbit, outcome):
    """Builds a Starship table row with the live Wikipedia column layout."""
    cells = [
        date,
        "Block 3 B21",
        ship,
        "Starbase, OLP-2",
        payload,
        mass,
        orbit,
        "SpaceX",
        outcome,
        "Success (OLP-2)",
        "Controlled (ocean)",
    ]
    return "<tr>" + "".join(f"<td>{cell}</td>" for cell in cells) + "</tr>"


def _starship_table(*rows):
    return f'<table class="wikitable">{"".join(rows)}</table>'


class TestParseLaunchDatetime(unittest.TestCase):
    def test_day_first_format(self):
        self.assertEqual(
            parse_launch_datetime("4 June 2010 18:45"),
            datetime.datetime(2010, 6, 4, 18, 45),
        )

    def test_month_first_format(self):
        self.assertEqual(
            parse_launch_datetime("August 26, 2025"),
            datetime.datetime(2025, 8, 26, 0, 0),
        )

    def test_missing_time_defaults_to_midnight(self):
        self.assertEqual(
            parse_launch_datetime("15 January 2023"),
            datetime.datetime(2023, 1, 15, 0, 0),
        )

    def test_footnotes_and_extra_text_ignored(self):
        self.assertEqual(
            parse_launch_datetime("1 May 2024 03:30 [12] (planned)"),
            datetime.datetime(2024, 5, 1, 3, 30),
        )

    def test_unparseable_returns_none(self):
        self.assertIsNone(parse_launch_datetime("TBD"))

    def test_date_shaped_but_invalid_returns_none(self):
        # Each matches the date regex but used to raise ValueError and abort the run
        for text in (
            "31 February 2026",
            "Mid 2026 to 2027",
            "TBD 12 2026",
            "4 juin 2010",
            "1 May 2024 24:00",
        ):
            with self.subTest(text=text):
                self.assertIsNone(parse_launch_datetime(text))


class TestParsePayloadMassText(unittest.TestCase):
    def test_simple_mass(self):
        self.assertEqual(parse_payload_mass_text("5,000 kg"), 5000)

    def test_range_returns_average(self):
        self.assertEqual(parse_payload_mass_text("5,000–6,000 kg"), 5500)
        self.assertEqual(parse_payload_mass_text("5000-6000 kg"), 5500)

    def test_approximate_mass(self):
        self.assertEqual(parse_payload_mass_text("~16,000 kg (35,000 lb)[54]"), 16000)

    def test_unparseable_returns_zero(self):
        self.assertEqual(parse_payload_mass_text("—"), 0)
        self.assertEqual(parse_payload_mass_text(""), 0)
        self.assertEqual(parse_payload_mass_text(None), 0)


class TestParseStarshipRow(unittest.TestCase):
    def test_orbital_starlink_flight(self):
        html = _starship_table(
            _starship_row(
                "September 20, 2026 23:00:00<sup>[81]</sup>",
                "Block 3 S41",
                "20 Starlink V3<sup>[81]</sup>",
                "~ 34,100 kg (75,200 lb)<sup>[81]</sup>",
                "LEO",
                "Success",
            )
        )
        (record,) = parse_launch_page(STARSHIP_URL, html)
        self.assertEqual(record.launch_datetime, datetime.datetime(2026, 9, 20, 23, 0))
        self.assertEqual(record.vehicle, "Block 3 Starship")
        self.assertEqual(record.payload, "20 Starlink V3[81]")
        self.assertEqual(record.payload_mass, 34100)
        self.assertEqual(record.orbit, "LEO")

    def test_failed_flight_has_zero_mass(self):
        html = _starship_table(
            _starship_row(
                "May 27, 2025 23:36:28",
                "Block 2 S35",
                "8 Starlink simulator satellites",
                "~ 16,000 kg (35,000 lb)",
                "Transatmospheric",
                "Failure",
            )
        )
        (record,) = parse_launch_page(STARSHIP_URL, html)
        self.assertEqual(record.vehicle, "Block 2 Starship")
        self.assertEqual(record.payload_mass, 0)

    def test_empty_payload_with_hidden_sort_key(self):
        html = _starship_table(
            _starship_row(
                "March 14, 2024 13:25:00",
                "Block 1 S28",
                '—<span style="display:none">N/a</span>',
                '—<span style="display:none">N/a</span>',
                "Suborbital<sup>[19]</sup>",
                "Success",
            )
        )
        (record,) = parse_launch_page(STARSHIP_URL, html)
        self.assertEqual(record.payload, "Starship Test")
        self.assertEqual(record.payload_mass, 0)

    def test_unexpected_column_count_is_skipped(self):
        html = _starship_table("<tr><td>September 2026</td><td>Block 3</td></tr>")
        self.assertEqual(parse_launch_page(STARSHIP_URL, html), [])


class TestParseFalconPage(unittest.TestCase):
    def _parse(self, *rows):
        return parse_launch_page(FALCON_URL, _starship_table(*rows))

    def test_successful_falcon_9_launch(self):
        (record,) = self._parse(
            _falcon_row(
                "3 January 2025 01:27",
                "F9 B5 B1086.2",
                "Starlink Group 6-71",
                "17,400 kg (38,400 lb)",
                "LEO",
                "Success",
            )
        )
        self.assertEqual(record.vehicle, "Falcon 9")
        self.assertEqual(record.payload, "Starlink Group 6-71")
        self.assertEqual(record.payload_mass, 17400)
        self.assertEqual(record.orbit, "LEO")
        self.assertEqual(record.launch_datetime, datetime.datetime(2025, 1, 3, 1, 27))

    def test_falcon_heavy_detected_from_booster(self):
        (record,) = self._parse(
            _falcon_row(
                "29 December 2023 01:07",
                "Falcon Heavy B5 B1084",
                "USSF-52",
                "Classified",
                "HEO",
                "Success",
            )
        )
        self.assertEqual(record.vehicle, "Falcon Heavy")
        self.assertEqual(record.payload_mass, 0)

    def test_failed_launch_counts_no_mass(self):
        (record,) = self._parse(
            _falcon_row(
                "12 July 2024 02:35",
                "F9 B5 B1069.17",
                "Starlink Group 9-3",
                "~16,000 kg",
                "LEO",
                "Failure",
            )
        )
        self.assertEqual(record.payload_mass, 0)

    def test_payload_continuation_and_planned_rows_skipped(self):
        records = self._parse(
            _falcon_row("3 January 2025", "F9", "Starlink", "1 kg", "LEO", "Success"),
            "<tr><td>Description of the payload above.</td></tr>",
            # Future launches live in a 6-column table and must not be counted
            "<tr>" + "<td>x</td>" * 6 + "</tr>",
        )
        self.assertEqual(len(records), 1)

    def test_invalid_date_row_is_skipped_not_fatal(self):
        records = self._parse(
            _falcon_row("31 February 2026", "F9", "Bad", "1 kg", "LEO", "Success"),
            _falcon_row("1 March 2026", "F9", "Good", "2 kg", "LEO", "Success"),
        )
        self.assertEqual([r.payload for r in records], ["Good"])


if __name__ == "__main__":
    unittest.main()
