"""Tests for the pure parsing helpers."""

import datetime
import locale
import random
import unittest
from typing import cast
from unittest import mock

from bs4 import BeautifulSoup

from spacex_graphs.config import TableLayout
from spacex_graphs.parsing import (
    _cell_text,
    _table_grid,
    parse_launch_datetime,
    parse_launch_page,
    parse_payload_mass_text,
)


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

    def test_space_separated_thousands(self):
        self.assertEqual(parse_payload_mass_text("16 000 kg"), 16000)
        self.assertEqual(parse_payload_mass_text("16\u00a0000 kg"), 16000)

    def test_kg_figure_wins_over_leading_pounds(self):
        self.assertEqual(parse_payload_mass_text("75,200 lb (34,100 kg)"), 34100)

    def test_tonnes_and_lbs(self):
        self.assertEqual(parse_payload_mass_text("1.5 t"), 1500)
        self.assertEqual(parse_payload_mass_text("~100 tonnes"), 100000)
        self.assertEqual(parse_payload_mass_text("2,500 lbs"), 1134)
        self.assertEqual(parse_payload_mass_text("16 t (35,000 lb)"), 16000)

    def test_units_must_be_whole_words(self):
        for text in ("12 transponders", "3 tugs", "4 lbsx", "7 kgs"):
            with self.subTest(text=text):
                self.assertIsNone(parse_payload_mass_text(text))

    def test_numbers_without_a_unit_are_not_masses(self):
        for text in ("Unknown (22 satellites)", "Group 6-12", "2025", "~16,000"):
            with self.subTest(text=text):
                self.assertIsNone(parse_payload_mass_text(text))

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
        (record,) = parse_launch_page("starship", html)
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
        (record,) = parse_launch_page("starship", html)
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
        (record,) = parse_launch_page("starship", html)
        self.assertEqual(record.payload, "Starship Test")
        self.assertIsNone(record.payload_mass)

    def test_unexpected_column_count_is_skipped(self):
        html = _starship_table("<tr><td>September 2026</td><td>Block 3</td></tr>")
        self.assertEqual(parse_launch_page("starship", html), [])

    def test_full_width_row_with_invalid_date_is_skipped(self):
        html = _starship_table(
            _starship_row(
                "February 29, 2025", "Block 2 S35", "Sat", "1 kg", "LEO", "Success"
            )
        )
        self.assertEqual(parse_launch_page("starship", html), [])


class TestParseFalconPage(unittest.TestCase):
    def _parse(self, *rows):
        return parse_launch_page("falcon", _starship_table(*rows))

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

    def test_falcon_heavy_detected_from_short_fh_label(self):
        # Two real 2019 launches label the booster only "FH B5 B1055 (core)"
        for booster in ("FH B5 B1055 (core)", "Falcon Heavy B5 B1084", "F9 B5 B1086"):
            with self.subTest(booster=booster):
                (record,) = self._parse(
                    _falcon_row("11 April 2019", booster, "X", "1 kg", "GTO", "Success")
                )
                expected = "Falcon 9" if booster.startswith("F9") else "Falcon Heavy"
                self.assertEqual(record.vehicle, expected)

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
        (record,) = parse_launch_page("falcon", html)
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

    def test_payload_masses_on_separate_lines_are_summed(self):
        self.assertEqual(self._record(mass="500 kg<br>300 kg").payload_mass, 800)
        self.assertEqual(
            self._record(mass="16,500 kg<br>(36,400 lb)").payload_mass, 16500
        )


_FALCON_LIST = (
    "https://en.wikipedia.org/wiki/List_of_Falcon_9_and_Falcon_Heavy_launches"
)

# Pins the page list, so a page dropped, retargeted, or given the wrong table
# layout shows up as a deliberate change in review
EXPECTED_PAGES = [
    ("Falcon 2010-2019", f"{_FALCON_LIST}_(2010%E2%80%932019)", "falcon"),
    ("Falcon 2020-2022", f"{_FALCON_LIST}_(2020%E2%80%932022)", "falcon"),
    ("Falcon 2023", f"{_FALCON_LIST}_(2023)", "falcon"),
    ("Falcon 2024", f"{_FALCON_LIST}_(2024)", "falcon"),
    ("Falcon current", _FALCON_LIST, "falcon"),
    (
        "Starship launches",
        "https://en.wikipedia.org/wiki/List_of_Starship_launches",
        "starship",
    ),
]


class TestPageLayouts(unittest.TestCase):
    def test_pages_match_the_pinned_list(self):
        from spacex_graphs.config import WIKIPEDIA_PAGES

        self.assertEqual([tuple(page) for page in WIKIPEDIA_PAGES], EXPECTED_PAGES)

    def test_every_page_has_a_parser_and_a_unique_name_and_url(self):
        from spacex_graphs.config import WIKIPEDIA_PAGES

        for page in WIKIPEDIA_PAGES:
            with self.subTest(page=page.name):
                self.assertEqual(parse_launch_page(page.layout, ""), [])
        self.assertEqual(len({p.name for p in WIKIPEDIA_PAGES}), len(WIKIPEDIA_PAGES))
        self.assertEqual(len({p.url for p in WIKIPEDIA_PAGES}), len(WIKIPEDIA_PAGES))

    def test_layout_picks_the_row_parser(self):
        html = _starship_table(
            _starship_row(
                "May 27, 2025 23:36", "Block 2 S35", "X", "1 kg", "LEO", "Success"
            )
        )
        self.assertEqual(len(parse_launch_page("starship", html)), 1)
        # The 11-cell Starship row read as a Falcon row lands in the wrong columns
        (falcon_reading,) = parse_launch_page("falcon", html)
        self.assertEqual(falcon_reading.vehicle, "Falcon 9")


class TestPageStructure(unittest.TestCase):
    def test_only_wikitable_tables_are_parsed(self):
        row = _falcon_row("3 January 2025", "F9", "Sat", "1 kg", "LEO", "Success")
        html = f"<table>{row}</table>" + _starship_table(row)
        self.assertEqual(len(parse_launch_page("falcon", html)), 1)

    def test_starship_without_a_block_number_is_plain_starship(self):
        html = _starship_table(
            _starship_row("May 27, 2025 23:36", "S35", "X", "1 kg", "LEO", "Success")
        )
        (record,) = parse_launch_page("starship", html)
        self.assertEqual(record.vehicle, "Starship")


class TestParseLaunchDatetimeEdgeCases(unittest.TestCase):
    def test_earliest_date_and_first_unmarked_time_win(self):
        for text in (
            "29 February 2024 23:59 (Mar 1, 2024 00:01)",
            "Feb 29, 2024 23:59 (1 March 2024 00:01)",
        ):
            with self.subTest(text=text):
                self.assertEqual(
                    parse_launch_datetime(text), datetime.datetime(2024, 2, 29, 23, 59)
                )

    def test_one_digit_hours_and_seconds(self):
        self.assertEqual(
            parse_launch_datetime("4 June 2010 8:45"),
            datetime.datetime(2010, 6, 4, 8, 45),
        )
        self.assertEqual(
            parse_launch_datetime("May 27, 2025 23:36:28"),
            datetime.datetime(2025, 5, 27, 23, 36),
        )

    def test_utc_time_wins_over_local_time(self):
        for text in (
            "1 May 2024 14:30 EST (19:30 UTC)",
            "1 May 2024 14:30 EST (19:30:05 utc)",
            "19:30 UTC 1 May 2024 (14:30 EST)",
        ):
            with self.subTest(text=text):
                self.assertEqual(
                    parse_launch_datetime(text), datetime.datetime(2024, 5, 1, 19, 30)
                )

    def test_abbreviated_and_any_case_english_months(self):
        expected = datetime.datetime(2025, 9, 1)
        for text in (
            "Sept 1, 2025",
            "Sep. 1, 2025",
            "1 Sep 2025",
            "1 sept 2025",
            "1 SEPTEMBER 2025",
        ):
            with self.subTest(text=text):
                self.assertEqual(parse_launch_datetime(text), expected)

    def test_words_that_merely_start_with_a_month_are_not_months(self):
        for text in (
            "Maybe 12, 2026",
            "12 Mayday 2026",
            "Marching 3, 2026",
            "3 Junk 2026",
            "Decade 1, 2026",
        ):
            with self.subTest(text=text):
                self.assertIsNone(parse_launch_datetime(text))

    def test_date_ranges_are_not_launch_dates(self):
        for text in (
            "1–3 May 2026",
            "1-3 May 2026",
            "May 31 – June 2, 2026",
            "1 May 2026 – 3 May 2026",
            "30 April to 2 May 2026",
            "1 May 2026 to June 2026",
        ):
            with self.subTest(text=text):
                self.assertIsNone(parse_launch_datetime(text))

    def test_dash_before_a_time_is_not_a_range(self):
        self.assertEqual(
            parse_launch_datetime("4 June 2010 – 18:45"),
            datetime.datetime(2010, 6, 4, 18, 45),
        )

    def test_an_invalid_time_does_not_discard_the_date(self):
        # A stray "24:00" is skipped for the next valid time, or midnight
        for text, expected in (
            ("1 May 2024 24:00", datetime.datetime(2024, 5, 1)),
            ("1 May 2024 12:60", datetime.datetime(2024, 5, 1)),
            ("1 May 2024 24:00 14:05", datetime.datetime(2024, 5, 1, 14, 5)),
            ("1 May 2024 24:00 UTC (10:15 UTC)", datetime.datetime(2024, 5, 1, 10, 15)),
            ("1 May 2024 99:99 UTC 08:30", datetime.datetime(2024, 5, 1, 8, 30)),
        ):
            with self.subTest(text=text):
                self.assertEqual(parse_launch_datetime(text), expected)

    def test_a_utc_launch_window_gives_its_start(self):
        for text in (
            "1 May 2024 14:30 – 15:00 UTC",
            "1 May 2024 14:30-15:00 UTC",
            "1 May 2024 14:30:00 — 15:00:00 utc",
            "1 May 2024 09:00 EST (14:30 – 15:00 UTC)",
        ):
            with self.subTest(text=text):
                self.assertEqual(
                    parse_launch_datetime(text), datetime.datetime(2024, 5, 1, 14, 30)
                )
        # An invalid window start falls back to the other times
        self.assertEqual(
            parse_launch_datetime("1 May 2024 25:00 – 15:00 UTC"),
            datetime.datetime(2024, 5, 1, 15, 0),
        )

    def test_year_must_be_exactly_four_digits(self):
        self.assertIsNone(parse_launch_datetime("1 May 20245"))
        self.assertIsNone(parse_launch_datetime("1 May 0000"))

    def test_month_names_do_not_depend_on_the_locale(self):
        def check_month_names():
            self.assertEqual(
                parse_launch_datetime("4 June 2010 18:45"),
                datetime.datetime(2010, 6, 4, 18, 45),
            )
            self.assertIsNone(parse_launch_datetime("4 juin 2010"))

        # Exercise the guarantee even in containers that only ship C locales.
        # CPython's date, time and datetime strptime methods use _strptime.
        forbidden = AssertionError("the parser must not consult the process locale")
        with (
            mock.patch("_strptime._strptime", side_effect=forbidden),
            mock.patch.object(locale, "setlocale", side_effect=forbidden),
        ):
            check_month_names()

        original = locale.setlocale(locale.LC_TIME)
        for name in ("fr_FR.UTF-8", "de_DE.UTF-8", "ru_RU.UTF-8", "tr_TR.UTF-8"):
            try:
                locale.setlocale(locale.LC_TIME, name)
            except locale.Error:
                continue
            try:
                check_month_names()
            finally:
                locale.setlocale(locale.LC_TIME, original)
            break


class TestParsePayloadMassEdgeCases(unittest.TestCase):
    def test_tonne_spellings(self):
        self.assertEqual(parse_payload_mass_text("16.5 t"), 16500)
        self.assertEqual(parse_payload_mass_text("16.5 metric tonnes"), 16500)
        self.assertEqual(parse_payload_mass_text("1 Tonne"), 1000)

    def test_kilogram_spellings(self):
        self.assertEqual(parse_payload_mass_text("12 kilograms"), 12)
        self.assertEqual(parse_payload_mass_text("1 kilogram"), 1)
        self.assertEqual(parse_payload_mass_text("12 KG"), 12)

    def test_capital_t_and_t_compounds_are_not_tonnes(self):
        for text in (
            "Unknown (20 T-class satellites)",
            "Classified (Intelsat 15T)",
            "16.5t",
            "3 t/s",
            "4 T",
        ):
            with self.subTest(text=text):
                self.assertIsNone(parse_payload_mass_text(text))

    def test_numbers_inside_words_or_numbers_are_not_masses(self):
        for text in ("Intelsat15 kg", "1.5e3 kg", "Group_7 kg"):
            with self.subTest(text=text):
                self.assertIsNone(parse_payload_mass_text(text))

    def test_hyphenated_label_is_not_merged_with_the_mass(self):
        self.assertEqual(parse_payload_mass_text("CAS500-2 500 kg"), 500)
        self.assertEqual(parse_payload_mass_text("CAS500-2 (500 kg)"), 500)

    def test_dashed_label_before_a_mass_is_not_a_range(self):
        self.assertEqual(parse_payload_mass_text("Flight 12 — 5,000 kg"), 5000)
        self.assertEqual(parse_payload_mass_text("Flight 12 – 5,000 kg"), 5000)

    def test_spaced_en_dash_range(self):
        self.assertEqual(parse_payload_mass_text("5,000 – 6,000 kg"), 5500)

    def test_range_cutoff_includes_exactly_ten_times_the_low_end(self):
        for text, mass in (
            ("500–5,000 kg", 2750),
            ("500–5,001 kg", 5001),
            ("5,000–500 kg", 500),
        ):
            with self.subTest(text=text):
                self.assertEqual(parse_payload_mass_text(text), mass)

    def test_unicode_hyphens(self):
        self.assertEqual(parse_payload_mass_text("5,000\u20116,000 kg"), 5500)

    def test_negative_masses_are_rejected(self):
        for text in ("-500 kg", "\u2212500 kg", "(-500 kg)"):
            with self.subTest(text=text):
                self.assertIsNone(parse_payload_mass_text(text))

    def test_summed_masses(self):
        self.assertEqual(parse_payload_mass_text("1,500 kg + 800 kg"), 2300)
        self.assertEqual(
            parse_payload_mass_text("1,500 kg (3,300 lb) + 800 kg (1,800 lb)"), 2300
        )

    def test_approximate_summed_masses(self):
        for text in (
            "~1,500 kg + ~800 kg",
            "~1,500 kg (3,300 lb) + ~800 kg (1,800 lb)",
            "≈1,500 kg + ≈800 kg",
            "c. 1,500 kg + c. 800 kg",
            "approx. 1,500 kg + approx. 800 kg",
            "1,500 kg + approximately 800 kg",
        ):
            with self.subTest(text=text):
                self.assertEqual(parse_payload_mass_text(text), 2300)

    def test_summed_terms_each_keep_their_own_unit(self):
        for text, expected in (
            ("1.5 t + 500 kg", 2000),
            ("1 t + 500 kg", 1500),
            ("500 kg + 1.5 t", 2000),
            ("1,000 lb + 500 kg", 954),
            ("~1.5 t (3,300 lb) + ~500 kg", 2000),
        ):
            with self.subTest(text=text):
                self.assertEqual(parse_payload_mass_text(text), expected)

    def test_each_line_is_a_payloads_mass(self):
        for text, expected in (
            ("500 kg\n300 kg", 800),
            ("1.5 t\n500 kg", 2000),
            ("~500 kg\n~300 kg (660 lb)", 800),
            ("1,100 lb\n660 lb", 798),
            ("500 kg\n+ 300 kg", 800),
            ("4,700\n172 kg", 172),
            ("Unknown\n300 kg", 300),
        ):
            with self.subTest(text=text):
                self.assertEqual(parse_payload_mass_text(text), expected)

    def test_a_conversion_on_its_own_line_is_not_another_payload(self):
        for text, expected in (
            ("16,500 kg\n(36,400 lb)", 16500),
            ("16,500 kg\n36,400 lb", 16500),
            ("36,400 lb\n16,500 kg", 16500),
            ("75,200 lb\n(34,100 kg)", 34100),
            ("~16,300 kg (35,900 lb)\n(Starlink)", 16300),
            ("6,350 kg (14,000 lb)\n+ OTV payload", 6350),
            ("800 kg (1,800 lb)\n(main satellite) + unknown additional", 800),
        ):
            with self.subTest(text=text):
                self.assertEqual(parse_payload_mass_text(text), expected)

    def test_multiplied_masses(self):
        for text, expected in (
            ("2 × 500 kg", 1000),
            ("2×500 kg", 1000),
            ("2 x 1,200 kg", 2400),
            ("3 X 1.5 t", 4500),
            ("2 × 500 kg + 100 kg", 1100),
        ):
            with self.subTest(text=text):
                self.assertEqual(parse_payload_mass_text(text), expected)

    def test_count_without_a_mass_is_not_a_mass(self):
        self.assertIsNone(parse_payload_mass_text("test pods x 2"))

    def test_overflowing_number_is_not_a_mass(self):
        self.assertIsNone(parse_payload_mass_text("9" * 400 + " t"))


class TestCellTextHiddenMarkup(unittest.TestCase):
    def _cell(self, html):
        soup = BeautifulSoup(f"<table><tr><td>{html}</td></tr></table>", "html.parser")
        assert soup.td is not None
        return soup.td

    def test_hidden_markup_is_removed(self):
        for html in (
            '<style data-mw-deduplicate="TemplateStyles:r1">.x{width:5 kg}</style>SES-8',
            '<script>var a = "12 kg";</script>SES-8',
            '<span class="sr-only">hidden</span>SES-8',
            '<span class="sortkey">0042</span>SES-8',
            '<span style="DISPLAY : None">0042</span>SES-8',
            '<span style="color:red;display: none;">0042</span>SES-8',
            'SES-8<sup class="mw-ref reference"><a>[18]</a></sup>',
            '<span class="sortkey"><span style="display:none">1</span>2</span>SES-8',
        ):
            with self.subTest(html=html):
                self.assertEqual(_cell_text(self._cell(html)), "SES-8")

    def test_visible_styles_are_kept(self):
        self.assertEqual(
            _cell_text(self._cell('<span style="display:inline">SES-8</span>')),
            "SES-8",
        )

    def test_cell_is_not_modified(self):
        cell = self._cell('SES-8<sup class="reference">[1]</sup><br>Extra')
        before = str(cell)
        self.assertEqual(_cell_text(cell), "SES-8 Extra")
        self.assertEqual(_cell_text(cell, "; "), "SES-8; Extra")
        self.assertEqual(str(cell), before)

    def test_hidden_markup_in_date_cell_is_ignored(self):
        date = (
            "<style>.mw-parser-output .x{margin:1 May 2001 11:11}</style>"
            '<span class="sortkey">000000002025-01-03-0000 12:34</span>'
            '<span style="display:none">7 July 2007 07:07</span>'
            "3 January 2025<br>01:27"
            '<sup class="reference">[5 June 2020 10:10]</sup>'
        )
        html = _starship_table(_falcon_row(date, "F9", "Sat", "1 kg", "LEO", "Success"))
        (record,) = parse_launch_page("falcon", html)
        self.assertEqual(record.launch_datetime, datetime.datetime(2025, 1, 3, 1, 27))

    def test_hidden_markup_in_starship_date_cell_is_ignored(self):
        date = '<span class="sr-only">1 May 2001</span>May 27, 2025 23:36'
        html = _starship_table(
            _starship_row(date, "Block 2 S35", "X", "1 kg", "LEO", "Success")
        )
        (record,) = parse_launch_page("starship", html)
        self.assertEqual(record.launch_datetime, datetime.datetime(2025, 5, 27, 23, 36))


def _cells_row(*cells):
    """A row of td cells, each either text or a (text, attributes) pair."""
    html = ""
    for cell in cells:
        text, attrs = cell if isinstance(cell, tuple) else (cell, "")
        html += f"<td {attrs}>{text}</td>"
    return f"<tr>{html}</tr>"


class TestTableStructure(unittest.TestCase):
    def test_nested_table_cells_do_not_become_columns(self):
        nested = "<table><tr><td>Sat A</td><td>Sat B</td></tr></table>"
        html = _starship_table(
            _falcon_row("3 January 2025", "F9", nested, "1 kg", "LEO", "Success")
        )
        (record,) = parse_launch_page("falcon", html)
        self.assertEqual(record.payload_mass, 1)
        self.assertEqual(record.orbit, "LEO")

    def test_rows_of_nested_tables_are_not_launch_rows(self):
        inner = _falcon_row("4 January 2025", "F9", "Inner", "2 kg", "LEO", "Success")
        outer = _falcon_row(
            "3 January 2025", "F9", f"Outer<table>{inner}</table>", "1 kg", "LEO", "Ok"
        )
        records = parse_launch_page("falcon", _starship_table(outer))
        self.assertEqual([r.launch_datetime.day for r in records], [3])

    def test_rows_inside_tbody_and_thead_are_read(self):
        row = _falcon_row("3 January 2025", "F9", "Sat", "1 kg", "LEO", "Success")
        html = (
            '<table class="wikitable"><thead><tr><th>Date</th></tr></thead>'
            f"<tbody>{row}</tbody></table>"
        )
        self.assertEqual(len(parse_launch_page("falcon", html)), 1)

    def test_flight_number_header_cell_does_not_shift_columns(self):
        row = _falcon_row("3 January 2025", "F9", "Sat", "1 kg", "LEO", "Success")
        row = row.replace("<tr>", '<tr><th scope="row" rowspan="2">42</th>', 1)
        description = '<tr><td colspan="9">Launched on 9 May 2024 at 10:00.</td></tr>'
        records = parse_launch_page("falcon", _starship_table(row, description))
        self.assertEqual([r.payload for r in records], ["Sat"])

    def test_colspan_cell_keeps_later_columns_aligned(self):
        row = _cells_row(
            "3 January 2025",
            ("F9 B5, CCSFS", 'colspan="2"'),
            "Sat",
            "1 kg",
            "LEO",
            "SpaceX",
            "Success",
            "Success (ASOG)",
        )
        (record,) = parse_launch_page("falcon", _starship_table(row))
        self.assertEqual((record.payload, record.orbit), ("Sat", "LEO"))

    def test_eleven_column_falcon_rows(self):
        row = _cells_row(
            "4 June 2010 18:45",
            "F9 v1.0 B0003",
            "CCAFS, SLC-40",
            "Dragon Qualification Unit",
            "Unknown",
            "LEO",
            "SpaceX",
            "Success",
            "Failure (parachute)",
            "extra 1",
            "extra 2",
        )
        (record,) = parse_launch_page("falcon", _starship_table(row))
        self.assertEqual(record.launch_datetime, datetime.datetime(2010, 6, 4, 18, 45))
        self.assertEqual(record.payload, "Dragon Qualification Unit")
        self.assertIsNone(record.payload_mass)
        self.assertEqual(record.outcome, "Success")

    def test_ten_column_falcon_rows_are_skipped(self):
        row = _cells_row("4 June 2010", *["x"] * 9)
        self.assertEqual(parse_launch_page("falcon", _starship_table(row)), [])

    def test_unknown_layout_is_rejected(self):
        with self.assertRaises(AssertionError):
            parse_launch_page(cast(TableLayout, "atlas"), "")


class TestMultiPayloadLaunches(unittest.TestCase):
    """Launches listed as one row per payload, sharing cells through rowspan."""

    def _launch(self, payload_rows, *, rows=None):
        rows = rows or len(payload_rows)
        span = f'rowspan="{rows}"'
        (payload, mass, outcome), *more = payload_rows
        first = _cells_row(
            ("3 January 2025 01:27", span),
            ("F9 B5 B1086", span),
            ("CCSFS, SLC-40", span),
            payload,
            mass,
            ("GTO<sup class='reference'>[3]</sup>", span),
            "SpaceX",
            outcome,
            ("Success (ASOG)", span),
        )
        rest = []
        for payload, mass, outcome in more:
            cells = [payload, mass, "Customer"]
            if outcome is not None:
                cells.append(outcome)
            rest.append(_cells_row(*cells))
        return first.replace("<tr>", f"<tr><th {span}>7</th>", 1) + "".join(rest)

    def test_payloads_sharing_a_date_cell_are_one_launch(self):
        html = _starship_table(
            self._launch(
                [
                    (
                        "ViaSat-3 Americas",
                        "6,400 kg (14,100 lb)",
                        ("Success", 'rowspan="3"'),
                    ),
                    ("Aurora 4A", "300 kg", None),
                    ("GS-1", "22 kg", None),
                ]
            )
        )
        (record,) = parse_launch_page("falcon", html)
        self.assertEqual(record.payload, "ViaSat-3 Americas + Aurora 4A + GS-1")
        self.assertEqual(record.payload_mass, 6722)
        self.assertEqual(record.orbit, "GTO")
        self.assertEqual(record.outcome, "Success")
        self.assertEqual(record.launch_datetime, datetime.datetime(2025, 1, 3, 1, 27))

    def test_secondary_payload_outcome_is_kept_alongside_the_launchs(self):
        html = _starship_table(
            self._launch(
                [
                    ("SpaceX CRS-1", "4,700 kg", "Success"),
                    ("Orbcomm-OG2", "172 kg", "Partial failure"),
                ]
            )
        )
        (record,) = parse_launch_page("falcon", html)
        self.assertEqual(record.payload_mass, 4872)
        self.assertEqual(record.outcome, "Success; Partial failure")

    def test_unknown_secondary_mass_leaves_the_known_total(self):
        html = _starship_table(
            self._launch(
                [
                    ("Primary", "Unknown", "Success"),
                    ("Secondary", "28 kg", "Success"),
                    ("Tertiary", "Classified", "Success"),
                ]
            )
        )
        (record,) = parse_launch_page("falcon", html)
        self.assertEqual(record.payload_mass, 28)
        self.assertEqual(record.outcome, "Success")

    def test_no_reported_mass_is_none(self):
        html = _starship_table(
            self._launch([("A", "Unknown", "Success"), ("B", "—", "Success")])
        )
        (record,) = parse_launch_page("falcon", html)
        self.assertIsNone(record.payload_mass)

    def test_empty_secondary_payload_cells_do_not_add_separators(self):
        html = _starship_table(
            self._launch([("Sat A", "0 kg", "Success"), (" ", " ", " ")])
        )
        (record,) = parse_launch_page("falcon", html)
        self.assertEqual(
            (record.payload, record.payload_mass, record.outcome),
            ("Sat A", 0, "Success"),
        )

    def test_mass_cell_shared_by_payloads_counts_once(self):
        first = _cells_row(
            ("3 January 2025", 'rowspan="2"'),
            ("F9", 'rowspan="2"'),
            ("CCSFS", 'rowspan="2"'),
            "Sat A",
            ("1,000 kg", 'rowspan="2"'),
            ("LEO", 'rowspan="2"'),
            "SpaceX",
            ("Success", 'rowspan="2"'),
            ("Success", 'rowspan="2"'),
        )
        second = _cells_row("Sat B", "SpaceX")
        (record,) = parse_launch_page("falcon", _starship_table(first, second))
        self.assertEqual(record.payload, "Sat A + Sat B")
        self.assertEqual(record.payload_mass, 1000)

    def test_equal_masses_in_separate_payload_cells_are_both_counted(self):
        html = _starship_table(
            self._launch(
                [("Sat A", "500 kg", "Success"), ("Sat B", "500 kg", "Success")]
            )
        )
        (record,) = parse_launch_page("falcon", html)
        self.assertEqual(record.payload, "Sat A + Sat B")
        self.assertEqual(record.payload_mass, 1000)

    def test_description_row_after_payload_rows_is_not_a_launch(self):
        launch = self._launch(
            [("A", "1 kg", "Success"), ("B", "2 kg", "Success")], rows=2
        )
        description = (
            '<tr><td colspan="9">Rescheduled from 4 June 2024 12:00.</td></tr>'
        )
        records = parse_launch_page("falcon", _starship_table(launch, description))
        self.assertEqual([(r.payload, r.payload_mass) for r in records], [("A + B", 3)])

    def test_cell_spanning_two_launches_reads_the_same_for_both(self):
        first = _falcon_row("3 January 2025", "F9", "A", "1 kg", "x", "Success")
        second = _falcon_row("4 January 2025", "F9", "B", "2 kg", "x", "Success")
        orbit = '<td rowspan="2">GTO<sup class="reference">[3]</sup></td>'
        first = first.replace("<td>x</td>", orbit)
        second = second.replace("<td>x</td>", "")
        records = parse_launch_page("falcon", _starship_table(first, second))
        self.assertEqual([r.orbit for r in records], ["GTO", "GTO"])
        self.assertEqual([r.payload for r in records], ["A", "B"])

    def test_starship_payload_rows(self):
        first = _starship_row(
            "May 27, 2025 23:36",
            "Block 2 S35",
            "8 Starlink simulators",
            "16 t",
            "x",
            "Success",
        )
        first = first.replace("<td>May 27", '<td rowspan="2">May 27', 1)
        first = first.replace("<td>x</td>", '<td rowspan="2">Transatmospheric</td>')
        second = _cells_row("Banana", "1 kg", "SpaceX", "Success")
        # The second row needs the shared cells before and after its payload
        for column in ("Block 3 B21", "Block 2 S35", "Starbase, OLP-2"):
            first = first.replace(
                f"<td>{column}</td>", f'<td rowspan="2">{column}</td>'
            )
        for column in ("Success (OLP-2)", "Controlled (ocean)"):
            first = first.replace(
                f"<td>{column}</td>", f'<td rowspan="2">{column}</td>'
            )
        (record,) = parse_launch_page("starship", _starship_table(first, second))
        self.assertEqual(record.payload, "8 Starlink simulators + Banana")
        self.assertEqual(record.payload_mass, 16001)
        self.assertEqual(record.vehicle, "Block 2 Starship")


class TestTableGrid(unittest.TestCase):
    def _grid(self, html):
        table = BeautifulSoup(html, "html.parser").table
        assert table is not None
        return [[cell.get_text() for cell in row] for row in _table_grid(table)]

    def test_rowspan_and_colspan_fill_their_slots(self):
        html = (
            "<table>"
            '<tr><td rowspan="2" colspan="2">a</td><td>b</td></tr>'
            "<tr><td>c</td></tr>"
            "<tr><td>d</td><td>e</td><td>f</td></tr>"
            "</table>"
        )
        self.assertEqual(
            self._grid(html), [["a", "a", "b"], ["a", "a", "c"], ["d", "e", "f"]]
        )

    def test_spans_are_bounded_and_tolerant(self):
        html = (
            "<table>"
            '<tr><td rowspan="0" colspan="banana">a</td><td colspan="99999999">b</td></tr>'
            "</table>"
        )
        (row,) = self._grid(html)
        self.assertEqual(row[0], "a")
        self.assertEqual(len(row), 1001)

    def test_colspan_continues_past_a_rowspan_from_above(self):
        # A browser never lets a later cell displace one spanning down into
        # the row: the colspan cell's second column moves past it
        html = (
            "<table>"
            '<tr><td>a</td><td rowspan="2">b</td><td>c</td></tr>'
            '<tr><td colspan="2">d</td><td>e</td></tr>'
            "</table>"
        )
        self.assertEqual(self._grid(html), [["a", "b", "c"], ["d", "b", "d", "e"]])

    def test_short_row_keeps_cells_spanning_into_it_in_their_columns(self):
        html = (
            "<table>"
            '<tr><td rowspan="3">a</td><td>b</td><td>c</td><td rowspan="3">z</td></tr>'
            "<tr><td>d</td></tr>"
            "<tr></tr>"
            "<tr><td>f</td><td>g</td></tr>"
            "</table>"
        )
        self.assertEqual(
            self._grid(html),
            [["a", "b", "c", "z"], ["a", "d", "", "z"], ["a", "", "", "z"], ["f", "g"]],
        )

    def test_span_running_past_the_last_row_is_harmless(self):
        html = '<table><tr><td rowspan="9">a</td><td>b</td></tr></table>'
        self.assertEqual(self._grid(html), [["a", "b"]])


_FUZZ_WORDS = (
    "1 4 12 31 2025 0 999 1,500 6,000 .5 - , : + ( ) [ ] [12] ~ ; x e kg t T tonnes"
    " metric lb lbs kilograms to May Sept June December Maybe UTC EST Unknown"
    " \u2013 \u2014 \u2011 \u2212 \u00d7 \u00a0 \u202f \U0001f680"
)
_FUZZ_PIECES = (*_FUZZ_WORDS.split(" "), " ", "\n", "\u0000", "9" * 40)


class TestFuzz(unittest.TestCase):
    """Arbitrary cell text never raises, and gives a sane result or None."""

    def _texts(self, count):
        rng = random.Random(20261125)
        for _ in range(count):
            yield "".join(rng.choice(_FUZZ_PIECES) for _ in range(rng.randint(0, 14)))
            yield "".join(
                chr(rng.randint(0, 0x2FFF)) for _ in range(rng.randint(0, 30))
            )

    def test_parse_launch_datetime_never_raises(self):
        for text in self._texts(3000):
            result = parse_launch_datetime(text)
            if result is not None:
                self.assertIsInstance(result, datetime.datetime)
                self.assertIsNone(result.tzinfo)

    def test_parse_payload_mass_text_never_raises(self):
        for text in self._texts(3000):
            result = parse_payload_mass_text(text)
            if result is not None:
                self.assertIsInstance(result, int)
                self.assertGreaterEqual(result, 0)

    def test_parse_launch_page_never_raises(self):
        rng = random.Random(7)
        tags = (
            "<tr>",
            "</tr>",
            "<td>",
            "</td>",
            "<th>",
            "<table>",
            "</table>",
            "<tbody>",
            "<br>",
            "</sup>",
            '<td rowspan="3">',
            '<td colspan="2">',
            '<sup class="reference">',
            "1 May 2025",
            "5 kg",
            "Block 2",
        )
        for _ in range(300):
            body = "".join(rng.choice(tags) for _ in range(rng.randint(0, 60)))
            html = f'<table class="wikitable">{body}</table>'
            for layout in ("falcon", "starship"):
                for record in parse_launch_page(layout, html):
                    self.assertIsInstance(record.launch_datetime, datetime.datetime)


if __name__ == "__main__":
    unittest.main()
