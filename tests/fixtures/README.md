# Test fixtures

`falcon_launches.html` and `starship_launches.html` are trimmed excerpts of
these Wikipedia articles, as fetched on 2026-10-02:

- [List of Falcon 9 and Falcon Heavy launches](https://en.wikipedia.org/wiki/List_of_Falcon_9_and_Falcon_Heavy_launches)
- [List of Starship launches](https://en.wikipedia.org/wiki/List_of_Starship_launches)

Each keeps a few complete launch rows, with their description and footnote
markup, plus a few planned-launch rows, copied verbatim. They let the parser
tests exercise real Wikipedia markup without network access.

The text is by Wikipedia contributors and licensed under
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/); it is not
covered by this repository's MIT license.
