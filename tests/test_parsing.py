"""Tests for the pure parsing helpers."""

import datetime
import unittest

from spacex_graphs.parsing import (
    LaunchRecord,
    drop_duplicate_launches,
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

    def test_to_range_returns_average(self):
        self.assertEqual(parse_payload_mass_text("5000 to 6000 kg"), 5500)

    def test_footnote_digits_are_not_mass(self):
        self.assertIsNone(parse_payload_mass_text("Classified[12]"))
        self.assertIsNone(parse_payload_mass_text("Unknown[232]"))
        self.assertEqual(parse_payload_mass_text("[12] 5,000 kg"), 5000)

    def test_unrelated_numbers_are_ignored_when_kg_present(self):
        self.assertEqual(parse_payload_mass_text("5,000 kg (2019-2020 est.)"), 5000)
        self.assertEqual(parse_payload_mass_text("2 × 1,200 kg"), 1200)

    def test_space_separated_thousands(self):
        self.assertEqual(parse_payload_mass_text("16 000 kg"), 16000)
        self.assertEqual(parse_payload_mass_text("16\u00a0000 kg"), 16000)

    def test_kg_figure_wins_over_leading_pounds(self):
        self.assertEqual(parse_payload_mass_text("75,200 lb (34,100 kg)"), 34100)

    def test_pounds_only_is_converted(self):
        self.assertEqual(parse_payload_mass_text("2,500 lb"), 1134)

    def test_decimal_kg(self):
        self.assertEqual(parse_payload_mass_text("0.5 kg"), 0)
        self.assertEqual(parse_payload_mass_text("12.6 kg"), 13)

    def test_no_mass_returns_none(self):
        self.assertIsNone(parse_payload_mass_text("—"))
        self.assertIsNone(parse_payload_mass_text(""))
        self.assertIsNone(parse_payload_mass_text(None))


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
        self.assertEqual(record.payload, "20 Starlink V3")
        self.assertEqual(record.payload_mass, 34100)
        self.assertEqual(record.orbit, "LEO")

    def test_failed_flight_keeps_reported_mass_and_outcome(self):
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
        self.assertEqual(record.payload_mass, 16000)
        self.assertEqual(record.outcome, "Failure")

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
        self.assertIsNone(record.payload_mass)

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
        self.assertIsNone(record.payload_mass)

    def test_failed_launch_keeps_reported_mass_and_outcome(self):
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
        self.assertEqual(record.payload_mass, 16000)
        self.assertEqual(record.outcome, "Failure")

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


class TestCellText(unittest.TestCase):
    """Cell text reaches records cleaned, through the Falcon row parser."""

    def _record(self, payload="Sat", mass="1 kg", orbit="LEO"):
        html = _starship_table(
            _falcon_row("3 January 2025", "F9", payload, mass, orbit, "Success")
        )
        (record,) = parse_launch_page(FALCON_URL, html)
        return record

    def test_line_breaks_separate_words(self):
        self.assertEqual(
            self._record(payload="SPHEREx<br>PUNCH").payload, "SPHEREx PUNCH"
        )

    def test_footnotes_and_hidden_sort_keys_are_removed(self):
        payload = '<span style="display:none">0042</span>SES-8<sup class="reference">[18]</sup>[31]'
        self.assertEqual(self._record(payload=payload).payload, "SES-8")
        self.assertEqual(self._record(orbit="GTO<sup>[324]</sup>").orbit, "GTO")

    def test_whitespace_collapses_to_single_spaces(self):
        payload = "Starlink:\u00a0Group  12-4\n(21\u00a0satellites)"
        self.assertEqual(
            self._record(payload=payload).payload,
            "Starlink: Group 12-4 (21 satellites)",
        )

    def test_mass_on_separate_lines_is_not_merged(self):
        self.assertEqual(self._record(mass="4,700<br/>172 kg").payload_mass, 172)


class TestDropDuplicateLaunches(unittest.TestCase):
    def test_same_time_and_vehicle_is_one_launch(self):
        when = datetime.datetime(2025, 1, 6, 20, 43)
        first = LaunchRecord(2025, "LEO", "Starlink 6-71[12]", 1, when, "Falcon 9")
        relisted = LaunchRecord(2025, "LEO", "Starlink 6-71[48]", 1, when, "Falcon 9")
        unique, dropped = drop_duplicate_launches([first, relisted])
        self.assertEqual((unique, dropped), ([first], 1))

    def test_different_vehicles_at_the_same_time_are_kept(self):
        when = datetime.datetime(2025, 1, 6, 20, 43)
        falcon = LaunchRecord(2025, "LEO", "A", 1, when, "Falcon 9")
        starship = LaunchRecord(2025, "LEO", "B", 1, when, "Block 2 Starship")
        self.assertEqual(drop_duplicate_launches([falcon, starship])[1], 0)


if __name__ == "__main__":
    unittest.main()
