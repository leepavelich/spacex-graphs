# Test fixtures

`falcon_launches.html` and `starship_launches.html` are trimmed excerpts of
these Wikipedia articles:

- [List of Falcon 9 and Falcon Heavy launches](https://en.wikipedia.org/wiki/List_of_Falcon_9_and_Falcon_Heavy_launches),
  with its year pages for [2010–2019](https://en.wikipedia.org/wiki/List_of_Falcon_9_and_Falcon_Heavy_launches_(2010%E2%80%932019))
  and [2023](https://en.wikipedia.org/wiki/List_of_Falcon_9_and_Falcon_Heavy_launches_(2023))
- [List of Starship launches](https://en.wikipedia.org/wiki/List_of_Starship_launches)

In each file, the first table keeps a few complete launch rows from the
current list as fetched on 2026-10-02, with their description and footnote
markup, and the second a few planned-launch rows, which must not be parsed as
launches.

The last table in each file was added from the pages as fetched on
2026-09-02, one launch per HTML comment naming its source page and date. It
covers markup the first table doesn't:

- Falcon: launches with several payloads, listed one row per payload and
  sharing the date cell through `rowspan` (CRS-1, whose secondary payload has
  its own "Partial failure" outcome; Falcon Heavy flight 6, whose three
  payloads share the outcome cell; and the 2026-07-05 Starlink launch with a
  rideshare), a failure (CRS-7), and a pre-flight failure (AMOS-6).
- Starship: Block 2 and Block 3 flights with reported payload masses,
  including a failure (Flight 7).

All rows are copied verbatim, so the parser tests exercise real Wikipedia
markup without network access.

The text is by Wikipedia contributors and licensed under
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/); it is not
covered by this repository's MIT license.
