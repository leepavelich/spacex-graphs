"""Tests for writing the SVG and CSV artifacts."""

import csv
import datetime
import io
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from xml.etree import ElementTree

import pandas as pd
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from spacex_graphs import output, plotting, transform
from spacex_graphs.errors import PublishedCsvError
from spacex_graphs.parsing import LaunchRecord
from spacex_graphs.transform import build_dataframe
from spacex_graphs.validation import PublishedLaunch

SVG = "http://www.w3.org/2000/svg"


def _figure(title="Payload Mass"):
    # Text, bars and a clipped line exercise every source of random SVG IDs
    fig = Figure()
    FigureCanvasAgg(fig)
    ax = fig.add_subplot()
    ax.bar(["2024", "2025"], [17000, 4000], label="mass")
    ax.plot([0, 1], [0, 20000])
    ax.set_title(title)
    ax.legend()
    return fig


def _parse(content):
    # Every SVG parsed here was just written by the test itself
    return ElementTree.parse(io.BytesIO(content)).getroot()  # noqa: S314


# Launches in every orbit category with a dark-mode color, over enough years
# that the cumulative chart uses all eight year colors, plus a grey older year
_CHART_RECORDS = [
    LaunchRecord(year, orbit, payload, mass, datetime.datetime(year, 6, 1), "F9")
    for year in range(2019, 2028)
    for orbit, payload, mass in (
        ("LEO", "Starlink", 15_000 * (year - 2018)),
        ("SSO", "Starlink polar", 2_500),
        ("GTO", "SES", 4_000),
        ("BLT", "Lander", 2_000),
        ("Suborbital", "Starship", 1_000),
        ("SSO", "Transporter", 3_000),
    )
]
_TODAY = datetime.date(2027, 10, 3)


def _render_charts(directory):
    """Saves both real charts and returns each SVG's bytes by file name."""
    df = build_dataframe(_CHART_RECORDS)
    caption = transform.chart_caption(df)
    by_year = transform.payload_mass_by_year_orbit(df)
    cumulative = transform.build_cumulative_frame(df, _TODAY)
    output.save_plots(
        {
            output.BY_YEAR_SVG: plotting.plot_payload_mass_to_orbit_by_year(
                by_year, current_year=_TODAY.year, caption=caption
            ),
            output.CUMULATIVE_SVG: plotting.plot_cumulative_payload_mass_to_orbit(
                cumulative, _TODAY, caption=caption
            ),
        },
        output_dir=directory,
        descriptions={
            output.BY_YEAR_SVG: transform.by_year_summary(by_year, _TODAY.year),
            output.CUMULATIVE_SVG: transform.cumulative_summary(cumulative, _TODAY),
        },
    )
    return {
        name: Path(directory, name).read_bytes()
        for name in (output.BY_YEAR_SVG, output.CUMULATIVE_SVG)
    }


_STEP = re.compile(
    r"^(?P<tag>[a-z]+)?(?:#(?P<id>[\w.-]+))?"
    r'(?:\[(?P<attr>\w+)(?P<op>[*^])="(?P<value>[^"]*)"\])?'
    r"(?P<first>:first-child)?$"
)


def _dark_mode_rules():
    """Each rule in the dark-mode stylesheet, as (selectors, declarations)."""
    css = output.dark_mode_css()
    assert css.startswith("@media (prefers-color-scheme: dark) {")
    body = css[css.index("{") + 1 : css.rindex("}")]
    return [
        ([selector.strip() for selector in match[1].split(",")], match[2].strip())
        for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", body)
    ]


def _select(root, selector):
    """The elements a selector matches, for the selector forms the
    stylesheet uses: tags, IDs, [attr^=…] and [attr*=…], :first-child, and
    the child combinator."""
    parents = {child: parent for parent in root.iter() for child in parent}
    steps = [_STEP.match(step.strip()) for step in selector.split(">")]
    assert all(steps), selector

    def matches(element, step):
        tag = element.tag.rpartition("}")[2]
        if step["tag"] and tag != step["tag"]:
            return False
        if step["id"] and element.get("id") != step["id"]:
            return False
        if step["attr"]:
            value = element.get(step["attr"], "")
            if step["op"] == "^" and not value.startswith(step["value"]):
                return False
            if step["op"] == "*" and step["value"] not in value:
                return False
        if step["first"]:
            parent = parents.get(element)
            if parent is None or next(iter(parent)) is not element:
                return False
        return True

    def matches_chain(element, index):
        if not matches(element, steps[index]):
            return False
        if index == 0:
            return True
        parent = parents.get(element)
        return parent is not None and matches_chain(parent, index - 1)

    return [e for e in root.iter() if matches_chain(e, len(steps) - 1)]


def _rule_matches(root, selectors):
    return [element for selector in selectors for element in _select(root, selector)]


def _render_svgs(directory):
    figs = (_figure(), _figure())
    output.save_plots(
        {output.BY_YEAR_SVG: figs[0], output.CUMULATIVE_SVG: figs[1]},
        output_dir=directory,
    )
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

    def test_failed_svg_render_keeps_the_original_and_leaves_no_tempfile(self):
        fig = _figure()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, output.BY_YEAR_SVG)
            path.write_bytes(b"original")

            def fail(f, **kwargs):
                f.write(b"partial SVG")
                self.assertEqual(path.read_bytes(), b"original")
                raise OSError("disk error")

            with (
                mock.patch.object(fig, "savefig", side_effect=fail),
                self.assertRaises(OSError),
            ):
                output.save_plots({path.name: fig}, output_dir=directory)
            self.assertEqual(path.read_bytes(), b"original")
            self.assertEqual(list(Path(directory).iterdir()), [path])


class TestAccessibleSvg(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.svgs = _render_charts(tmp.name)
        self.roots = {name: _parse(content) for name, content in self.svgs.items()}

    def test_charts_are_titled_and_described_for_screen_readers(self):
        expected_titles = {
            output.BY_YEAR_SVG: "SpaceX Payload Mass Launched by Year and Destination",
            output.CUMULATIVE_SVG: "SpaceX Cumulative Payload Mass Launched by Year",
        }
        for name, root in self.roots.items():
            with self.subTest(name=name):
                self.assertEqual(root.get("role"), "img")
                self.assertEqual(root.get("aria-labelledby"), "chart-title chart-desc")
                title, desc = root[0], root[1]
                self.assertEqual(title.tag, f"{{{SVG}}}title")
                self.assertEqual(title.get("id"), "chart-title")
                self.assertEqual(title.text, expected_titles[name])
                self.assertEqual(desc.tag, f"{{{SVG}}}desc")
                self.assertEqual(desc.get("id"), "chart-desc")
                assert desc.text is not None
                # The chart's summary, then its caption
                self.assertIn("2027", desc.text)
                self.assertTrue(
                    desc.text.endswith(
                        transform.chart_caption(build_dataframe(_CHART_RECORDS))
                    )
                )

    def test_title_and_description_are_escaped(self):
        title = 'Mass & "more" <launched>'
        description = "A < B & C > D"
        with tempfile.TemporaryDirectory() as directory:
            output.save_plots(
                {"chart.svg": _figure(title)},
                output_dir=directory,
                descriptions={"chart.svg": description},
            )
            root = _parse(Path(directory, "chart.svg").read_bytes())
        self.assertEqual(root[0].text, title)
        self.assertEqual(root[1].text, description)

    def test_a_figure_without_axes_has_an_empty_title(self):
        fig = Figure()
        FigureCanvasAgg(fig)
        with tempfile.TemporaryDirectory() as directory:
            output.save_plots({"chart.svg": fig}, output_dir=directory)
            root = _parse(Path(directory, "chart.svg").read_bytes())
        self.assertIsNone(root[0].text)
        self.assertEqual(root.get("aria-labelledby"), "chart-title")

    def test_without_a_description_the_title_labels_the_chart(self):
        with tempfile.TemporaryDirectory() as directory:
            output.save_plots({"chart.svg": _figure()}, output_dir=directory)
            root = _parse(Path(directory, "chart.svg").read_bytes())
        self.assertEqual(root.get("aria-labelledby"), "chart-title")
        self.assertIsNone(root.find(f"{{{SVG}}}desc"))

    def test_real_charts_are_byte_identical_across_runs(self):
        with tempfile.TemporaryDirectory() as directory:
            again = _render_charts(directory)
        self.assertEqual(again, self.svgs)

    def test_dark_mode_stylesheet_applies_only_when_dark_is_preferred(self):
        for name, root in self.roots.items():
            styles = root.findall(f"{{{SVG}}}style")
            with self.subTest(name=name):
                self.assertEqual(len(styles), 1)
                self.assertEqual(styles[0].text.strip(), output.dark_mode_css())
        self.assertEqual(output.dark_mode_css().count("@media"), 1)
        self.assertTrue(output.dark_mode_css().rstrip().endswith("}"))

    def test_backgrounds_and_legend_frame_are_the_elements_recolored(self):
        rules = dict(
            (tuple(selectors), declarations)
            for selectors, declarations in _dark_mode_rules()
        )
        backgrounds = next(
            s for s in rules if f"#{plotting.FIGURE_BACKGROUND_ID} > path" in s
        )
        self.assertIn(f"#{plotting.AXES_BACKGROUND_ID} > path", backgrounds)
        legend = (f"#{plotting.LEGEND_BACKGROUND_ID} > path",)
        for name, root in self.roots.items():
            with self.subTest(name=name):
                matched = _rule_matches(root, backgrounds)
                self.assertEqual(len(matched), 2)
                for element in matched:
                    self.assertIn(
                        f"fill: {plotting.BACKGROUND_COLOR}", element.get("style")
                    )
                matched = _rule_matches(root, legend)
                self.assertEqual(len(matched), 1)
                self.assertIn(
                    f"stroke: {plotting.LEGEND_EDGE_COLOR}", matched[0].get("style")
                )
        self.assertIn(plotting.DARK_BACKGROUND_COLOR, rules[backgrounds])

    def test_every_neutral_rule_matches_an_element(self):
        # Catches a matplotlib upgrade that changes how the SVG names or
        # styles the elements; the rules for replaced data colors are checked
        # below, since a chart only uses some of those colors
        for selectors, declarations in _dark_mode_rules():
            if any(
                light in selector
                for light in plotting.DARK_MODE_DATA_COLORS
                for selector in selectors
            ):
                continue
            matched = [
                element
                for root in self.roots.values()
                for element in _rule_matches(root, selectors)
            ]
            with self.subTest(selectors=selectors):
                self.assertTrue(matched, declarations)

    def test_text_in_the_default_color_is_recolored(self):
        (text_rule,) = [s for s, _ in _dark_mode_rules() if s == ['g[id^="text_"]']]
        root = self.roots[output.CUMULATIVE_SVG]
        groups = _rule_matches(root, text_rule)
        # Title, axis label, tick labels, legend title and entries, year
        # labels, and the caption
        self.assertGreater(len(groups), 20)
        uses = [use for group in groups for use in group.iter(f"{{{SVG}}}use")]
        self.assertTrue(uses)
        # Glyphs have no fill of their own, so they inherit the rule's
        self.assertFalse([use for use in uses if "fill" in use.get("style", "")])

    def test_data_series_keep_their_colors(self):
        # A rule that recolors fills or strokes may only touch neutrals, or a
        # data color that has a dark-mode replacement
        replaced = set(plotting.DARK_MODE_DATA_COLORS)
        kept = (
            set(plotting.ORBIT_COLORS.values())
            | set(plotting.YEAR_COLORS)
            | {plotting.OLDER_YEARS_COLOR}
        ) - replaced
        for name, root in self.roots.items():
            data_elements = [
                element
                for element in root.iter()
                if any(color in element.get("style", "") for color in kept)
            ]
            self.assertTrue(data_elements)
            for selectors, declarations in _dark_mode_rules():
                matched = set(_rule_matches(root, selectors))
                with self.subTest(name=name, selectors=selectors):
                    touched = [
                        e.get("style")
                        for e in data_elements
                        if e in matched
                        and any(
                            f"{prop}: {color}" in e.get("style", "")
                            for color in kept
                            for prop in ("fill", "stroke")
                            if prop in declarations
                        )
                    ]
                    self.assertEqual(touched, [])

    def test_dark_replacements_cover_every_use_of_a_replaced_color(self):
        rules = _dark_mode_rules()
        for light, dark in plotting.DARK_MODE_DATA_COLORS.items():
            for prop in ("fill", "stroke"):
                selector = f'[style*="{prop}: {light}"]'
                with self.subTest(light=light, prop=prop):
                    self.assertIn(([selector], f"{prop}: {dark} !important"), rules)
        # Each replaced color is drawn by the chart whose palette it is in, so
        # every replacement rule is exercised by a real chart
        orbit_colors = set(plotting.ORBIT_COLORS.values())
        year_colors = set(plotting.YEAR_COLORS)
        for light, dark in plotting.DARK_MODE_DATA_COLORS.items():
            self.assertIn(light, orbit_colors | year_colors)
            chart = (
                output.BY_YEAR_SVG if light in orbit_colors else output.CUMULATIVE_SVG
            )
            root = self.roots[chart]
            with self.subTest(light=light, chart=chart):
                self.assertTrue(
                    _select(root, f'[style*="fill: {light}"]')
                    or _select(root, f'[style*="stroke: {light}"]')
                )
                # The dark shade appears only through the stylesheet
                for content in self.svgs.values():
                    body = content[content.index(b"</style>") :]
                    self.assertNotIn(dark.encode(), body)

    def test_every_year_color_is_drawn_in_the_cumulative_chart(self):
        root = self.roots[output.CUMULATIVE_SVG]
        for slot, color in enumerate(plotting.YEAR_COLORS):
            with self.subTest(slot=slot, color=color):
                self.assertTrue(_select(root, f'[style*="stroke: {color}"]'))
        self.assertTrue(
            _select(root, f'[style*="stroke: {plotting.OLDER_YEARS_COLOR}"]')
        )


class TestEmptyChartSvg(unittest.TestCase):
    def test_dark_mode_rules_still_find_the_backgrounds_without_data(self):
        df = build_dataframe([])
        with tempfile.TemporaryDirectory() as directory:
            output.save_plots(
                {
                    output.BY_YEAR_SVG: plotting.plot_payload_mass_to_orbit_by_year(
                        transform.payload_mass_by_year_orbit(df)
                    ),
                    output.CUMULATIVE_SVG: plotting.plot_cumulative_payload_mass_to_orbit(
                        transform.build_cumulative_frame(df, _TODAY), _TODAY
                    ),
                },
                output_dir=directory,
            )
            roots = {
                name: _parse(Path(directory, name).read_bytes())
                for name in (output.BY_YEAR_SVG, output.CUMULATIVE_SVG)
            }
        for name, root in roots.items():
            with self.subTest(name=name):
                backgrounds = _rule_matches(
                    root,
                    [
                        f"#{plotting.FIGURE_BACKGROUND_ID} > path",
                        f"#{plotting.AXES_BACKGROUND_ID} > path",
                    ],
                )
                self.assertEqual(len(backgrounds), 2)
                # No data, so no legend to recolor
                self.assertEqual(
                    _select(root, f"#{plotting.LEGEND_BACKGROUND_ID} > path"), []
                )
                self.assertEqual(len(root.findall(f"{{{SVG}}}style")), 1)
                self.assertTrue(_select(root, 'g[id^="text_"]'))


class TestSaveLaunchesCsv(unittest.TestCase):
    def test_rows_are_chronological_with_raw_and_categorized_orbits(self):
        df = build_dataframe(
            [
                LaunchRecord(
                    2026,
                    "LEO",
                    "Starlink 9",
                    17000,
                    datetime.datetime(2026, 2, 1, 5, 30),
                    "Falcon 9",
                ),
                LaunchRecord(
                    2025,
                    "GTO[12]",
                    "SES",
                    4000,
                    datetime.datetime(2025, 7, 4),
                    "Falcon Heavy",
                ),
                LaunchRecord(
                    2026,
                    "LEO",
                    "NROL-97",
                    None,
                    datetime.datetime(2026, 9, 1),
                    "Falcon 9",
                    "Failure",
                ),
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            output.save_launches_csv(df, output_dir=directory)
            with open(os.path.join(directory, "spacex_launches.csv"), newline="") as f:
                rows = list(csv.DictReader(f))

        self.assertEqual(
            list(rows[0]),
            [
                "Date",
                "Time (UTC)",
                "Year",
                "Vehicle",
                "Payload",
                "Payload Mass (kg)",
                "Orbit",
                "Orbit Category",
                "Outcome",
                "Counted Mass (kg)",
            ],
        )
        self.assertEqual(
            [row["Date"] for row in rows], ["2025-07-04", "2026-02-01", "2026-09-01"]
        )
        self.assertEqual(rows[1]["Time (UTC)"], "05:30:00")
        self.assertEqual(rows[0]["Orbit"], "GTO[12]")
        self.assertEqual(rows[0]["Orbit Category"], "GTO/GEO")
        self.assertEqual(rows[1]["Orbit Category"], "LEO (Starlink)")
        self.assertEqual(rows[1]["Payload Mass (kg)"], "17000")
        self.assertEqual(rows[1]["Counted Mass (kg)"], "17000")
        # Unknown mass is blank rather than a misleading 0; failures count 0
        self.assertEqual(rows[2]["Payload Mass (kg)"], "")
        self.assertEqual(rows[2]["Outcome"], "Failure")
        self.assertEqual(rows[2]["Counted Mass (kg)"], "0")

    def test_same_time_rows_sort_by_vehicle_then_payload_with_utf8_lf(self):
        when = datetime.datetime(2026, 2, 1)
        records = [
            LaunchRecord(2026, "LEO", payload, 1, when, vehicle)
            for vehicle, payload in (("FH", "C"), ("F9", "Bé"), ("F9", "A"))
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, output.LAUNCHES_CSV)
            output.save_launches_csv(build_dataframe(records), output_dir=directory)
            baseline = path.read_bytes()
            output.save_launches_csv(
                build_dataframe(records[::-1]), output_dir=directory
            )
            self.assertEqual(path.read_bytes(), baseline)
            self.assertNotIn(b"\r", baseline)
            self.assertTrue(baseline.endswith(b"\n"))
            self.assertIn("Bé".encode(), baseline)
            self.assertEqual(
                [row.payload for row in output.published_launches(directory)],
                ["A", "Bé", "C"],
            )

    def test_failed_csv_write_keeps_the_original_and_leaves_no_tempfile(self):
        df = build_dataframe([])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, output.LAUNCHES_CSV)
            path.write_bytes(b"original")

            def fail(f, **kwargs):
                f.write(b"partial CSV")
                self.assertEqual(path.read_bytes(), b"original")
                raise OSError("disk error")

            with (
                mock.patch.object(pd.DataFrame, "to_csv", side_effect=fail),
                self.assertRaises(OSError),
            ):
                output.save_launches_csv(df, output_dir=directory)
            self.assertEqual(path.read_bytes(), b"original")
            self.assertEqual(list(Path(directory).iterdir()), [path])


class TestFormulaEscaping(unittest.TestCase):
    def test_formula_like_text_is_escaped_in_the_csv(self):
        df = build_dataframe(
            [
                LaunchRecord(
                    2025,
                    "=1+1",
                    '=HYPERLINK("http://example.com","x")',
                    1,
                    datetime.datetime(2025, 1, 1),
                    "Falcon 9",
                    "@SUM(A1)",
                ),
                LaunchRecord(
                    2025, "LEO", "Starlink", 1, datetime.datetime(2025, 2, 1), "F9"
                ),
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            output.save_launches_csv(df, output_dir=directory)
            with open(os.path.join(directory, "spacex_launches.csv"), newline="") as f:
                rows = list(csv.DictReader(f))
        self.assertEqual(rows[0]["Payload"], '\'=HYPERLINK("http://example.com","x")')
        self.assertEqual(rows[0]["Orbit"], "'=1+1")
        self.assertEqual(rows[0]["Outcome"], "'@SUM(A1)")
        self.assertEqual(rows[1]["Payload"], "Starlink")


class TestPublishedLaunches(unittest.TestCase):
    def test_reads_back_what_was_published(self):
        df = build_dataframe(
            [
                LaunchRecord(
                    2025, "LEO", "A", 900, datetime.datetime(2025, 1, 1), "F9"
                ),
                LaunchRecord(
                    2026, "LEO", "B", None, datetime.datetime(2026, 1, 1), "FH"
                ),
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(output.published_launches(directory), [])
            output.save_launches_csv(df, output_dir=directory)
            self.assertEqual(
                output.published_launches(directory),
                [
                    PublishedLaunch(datetime.date(2025, 1, 1), "F9", "A", 900),
                    PublishedLaunch(datetime.date(2026, 1, 1), "FH", "B", None),
                ],
            )

    def test_formula_escapes_round_trip_without_stripping_literal_apostrophes(self):
        payloads = ["=1+1", "'=1+1", "''=1+1", "'Voyager", "\rno", "\nno", "@SUM(A1)"]
        records = [
            LaunchRecord(
                2025, "LEO", payload, 1, datetime.datetime(2025, 1, day), "-vehicle"
            )
            for day, payload in enumerate(payloads, 1)
        ]
        with tempfile.TemporaryDirectory() as directory:
            output.save_launches_csv(build_dataframe(records), output_dir=directory)
            baseline = output.published_launches(directory)
        self.assertEqual([launch.payload for launch in baseline], payloads)
        self.assertEqual(
            [launch.vehicle for launch in baseline], ["-vehicle"] * len(payloads)
        )

    def test_malformed_baseline_raises_a_data_error(self):
        header = b"Date,Vehicle,Payload,Payload Mass (kg)\n"
        for contents in (
            b"",
            # A header with no launches would switch the regression checks off
            header,
            header + b"2025-01-01,F9,Sat,-100\n",
            b"Date,Vehicle\n2025-01-01,F9\n",
            header + b"never,F9,Sat,100\n",
            header + b"2025-01-01,F9,Sat,not a mass\n",
            header + b"2025-01-01,F9,Sat\n",
            header + b'2025-01-01,F9,"Sat,100\n',
        ):
            with (
                self.subTest(contents=contents),
                tempfile.TemporaryDirectory() as directory,
            ):
                Path(directory, output.LAUNCHES_CSV).write_bytes(contents)
                with self.assertRaisesRegex(
                    PublishedCsvError, "malformed published CSV"
                ):
                    output.published_launches(directory)


class TestFilePermissions(unittest.TestCase):
    def test_outputs_are_readable_by_everyone_whatever_the_umask(self):
        df = build_dataframe(
            [LaunchRecord(2025, "LEO", "A", 900, datetime.datetime(2025, 1, 1), "F9")]
        )
        previous = os.umask(0o077)
        try:
            with tempfile.TemporaryDirectory() as directory:
                # Replacing existing owner-only files, too
                for name in (output.BY_YEAR_SVG, output.LAUNCHES_CSV):
                    path = Path(directory, name)
                    path.write_bytes(b"old")
                    path.chmod(0o600)
                output.save_plots({output.BY_YEAR_SVG: _figure()}, output_dir=directory)
                output.save_launches_csv(df, output_dir=directory)
                output.save_data_hash([], _TODAY, cache_dir=directory)
                modes = {
                    path.name: path.stat().st_mode & 0o777
                    for path in Path(directory).iterdir()
                }
        finally:
            os.umask(previous)
        self.assertEqual(
            modes,
            {
                output.BY_YEAR_SVG: 0o644,
                output.LAUNCHES_CSV: 0o644,
                "data_hash.txt": 0o644,
            },
        )


class TestEscapeFormula(unittest.TestCase):
    def test_every_formula_prefix_is_escaped(self):
        for text in ("=1", "+1", "-1", "@A1", "\tx", "\rx"):
            with self.subTest(text=repr(text)):
                self.assertEqual(output._escape_formula(text), "'" + text)

    def test_ordinary_text_is_untouched(self):
        for text in ("Starlink", "SES-8", "1+1", "a=b"):
            with self.subTest(text=text):
                self.assertEqual(output._escape_formula(text), text)


class TestMissingOutputs(unittest.TestCase):
    def test_a_missing_csv_counts_as_a_missing_output(self):
        with tempfile.TemporaryDirectory() as directory:
            for name in output.OUTPUT_FILES:
                open(os.path.join(directory, name), "w").close()
            self.assertEqual(output.missing_outputs(directory), [])
            os.remove(os.path.join(directory, output.LAUNCHES_CSV))
            self.assertEqual(output.missing_outputs(directory), [output.LAUNCHES_CSV])


if __name__ == "__main__":
    unittest.main()
