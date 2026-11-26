# Outputs

The graphs and CSV in this directory are regenerated daily by the scheduled
GitHub Actions workflow from these Wikipedia articles:

- [List of Falcon 9 and Falcon Heavy launches](https://en.wikipedia.org/wiki/List_of_Falcon_9_and_Falcon_Heavy_launches), and its archive pages for earlier years
- [List of Starship launches](https://en.wikipedia.org/wiki/List_of_Starship_launches)

They are adapted from that content, written by Wikipedia contributors, and
are therefore licensed under
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/), not under this
repository's MIT license. If you reuse them, credit Wikipedia contributors and
share adaptations under the same license.

## Methodology

The CSV has one row per launch. It retains the payload names, reported mass,
raw orbit, categorized orbit, and outcomes from the launch tables. Both graphs
sum `Counted Mass (kg)`, not `Payload Mass (kg)`.

- **Unknown mass.** A launch with no reported mass has a blank `Payload Mass (kg)`
  and 0 kg counted. If only some payloads have known masses, the CSV sums
  those and leaves the others out. It does not estimate missing values.
- **Multi-payload launches.** Rows that share a date cell via HTML `rowspan`
  become one launch. The parser joins payload names and outcomes and uses the
  first payload's orbit. A shared mass cell is counted only once.
- **Secondary failures.** The first payload's outcome determines whether the
  launch counts. CRS-1 retains both Dragon's success and Orbcomm's partial
  failure. Because Dragon succeeded, the graphs count the full reported
  4,872 kg, including Orbcomm's reported mass. A partial failure in the
  primary outcome counts as 0 kg.
- **Suborbital flights.** A successful suborbital flight with reported mass
  counts under `Transatmospheric`. That is why the charts say mass
  “launched,” not mass delivered to orbit.
- **Starlink rideshares.** Where the payload field names Starlink, the entire
  launch is categorized as Starlink for LEO or SSO. For Paz and the
  Tintin Starlink prototypes, the table lists one shared 2,150 kg figure.
  The graphs count it once under `SSO (Starlink)` and do not split it among
  satellites. [Source launch table](https://en.wikipedia.org/wiki/List_of_Falcon_9_and_Falcon_Heavy_launches_(2010%E2%80%932019)#2018).
- **Shared calendar.** The cumulative chart uses a 366-day leap-year axis.
  Common years skip February 29 so March 1 through December 31 line up
  date-for-date across leap and common years.
- **SVG accessibility.** Both generated SVGs embed a `<title>` and `<desc>`
  for screen readers and automatically switch to dark styling when
  `prefers-color-scheme: dark` matches.
